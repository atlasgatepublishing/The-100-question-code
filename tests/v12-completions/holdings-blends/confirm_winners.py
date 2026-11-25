#!/usr/bin/env python3
"""
CONFIRMATION — winners-blend count 2 (Terry's rule: a non-native
count that wins across roads is re-run on DIFFERENT YEARS before
its verdict counts).

Grid result being confirmed (house form): N=2 had the highest
3-road sum ($1,911 vs native N=5's $1,104) and beat N=5 on all
three roads — DECADE $901 vs $500, CONT $640 vs $369, VAL $370 vs
$235. (It also had the highest native-form sum.)

Confirmation: fresh-$100 calendar-year folds 2017..2026, house
form (quarterly, v9, the sweep's plumbing), N=2 vs N=5 head-to-head,
plus DECADE half-windows H1 2016-11-21->2021-12-31 and
H2 2022-01-01->2026-11-20.
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import engine_winners as W  # noqa: E402

END = "2026-11-20"


def _safe_dump(obj, path):
    last = None
    for _i in range(40):
        try:
            with open(path, "w") as _f:
                json.dump(obj, _f, indent=1)
            return
        except PermissionError as _e:
            last = _e
            time.sleep(10)
    raise last


def main():
    t0 = time.time()
    mkt = W.mb.Market(W.mb.UNIVERSE)
    pb, eq_rows, sh_rows = W.build_vm_book_orig()
    eq_struct = {t: W.make_pit_struct(eq_rows[t]) for t in W.UNIVERSE}
    sh_struct = {t: W.make_pit_struct(sh_rows[t]) for t in W.UNIVERSE}
    fb_decade = W.build_decade_book()
    ctx = {"mkt": mkt, "fb_decade": fb_decade, "eq_struct": eq_struct,
           "sh_struct": sh_struct}
    out = {"candidate_count": 2, "native_count": 5, "folds": {},
           "halves": {}}
    wins = 0
    for yr in range(2017, 2027):
        s = f"{yr}-01-01"
        e = END if yr == 2026 else f"{yr}-12-31"
        W.HOLD_N = 2
        r2 = W.run_cell_win(ctx, "quarterly", s, e)
        W.HOLD_N = 5
        r5 = W.run_cell_win(ctx, "quarterly", s, e)
        w = r2["final"] > r5["final"]
        wins += 1 if w else 0
        out["folds"][str(yr)] = {"candidate_final": r2["final"],
                                 "native5_final": r5["final"],
                                 "candidate_wins": w}
        print(f"FOLD {yr}: N=2 ${r2['final']:,.2f} vs N=5 "
              f"${r5['final']:,.2f} win={w} ({time.time()-t0:.0f}s)",
              flush=True)
    hwins = 0
    for hn, (s, e) in {"H1_2016-2021": ("2016-11-21", "2021-12-31"),
                       "H2_2022-2026": ("2022-01-01", END)}.items():
        W.HOLD_N = 2
        r2 = W.run_cell_win(ctx, "quarterly", s, e)
        W.HOLD_N = 5
        r5 = W.run_cell_win(ctx, "quarterly", s, e)
        w = r2["final"] > r5["final"]
        hwins += 1 if w else 0
        out["halves"][hn] = {"candidate_final": r2["final"],
                             "native5_final": r5["final"],
                             "candidate_wins": w}
        print(f"HALF {hn}: N=2 ${r2['final']:,.2f} vs N=5 "
              f"${r5['final']:,.2f} win={w}", flush=True)
    out["fold_wins"] = f"{wins}/10"
    out["half_wins"] = f"{hwins}/2"
    out["confirmed"] = wins >= 6 and hwins >= 1
    _safe_dump(out, os.path.join(HERE, "confirm_winners.json"))
    print(f"CONFIRMATION DONE folds {wins}/10 halves {hwins}/2 "
          f"confirmed={out['confirmed']} ({time.time()-t0:.0f}s)",
          flush=True)


if __name__ == "__main__":
    main()
