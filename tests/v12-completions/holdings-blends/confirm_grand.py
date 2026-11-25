#!/usr/bin/env python3
"""
CONFIRMATION — grand-combination count 2 (Terry's rule: a
non-native count that wins across roads is re-run on DIFFERENT
YEARS before its verdict counts).

Grid result being confirmed (house form): N=2 beat N=5 on all
three roads — DECADE $485 vs $320, CONT $437 vs $288, VAL $269 vs
$192 — and also won the native form on all three roads.

Confirmation: fresh-$100 calendar-year folds 2017..2026, house
form, N=2 vs N=5 head-to-head, plus half-windows H1
2017-01-01->2021-12-31 and H2 2022-01-01->2026-11-20 on the
family's book (first bar 2017-06-01 — the documented effective-road
artifact, identical for both counts).
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_grand as RG  # noqa: E402

END = "2026-11-20"
G, mb = RG.G, RG.mb


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
    mkt = mb.Market(mb.UNIVERSE)
    pb, eq_rows, sh_rows, bars = G.build_vm_book()
    ctx = {"mkt": mkt, "book": RG.VMBookN(bars, eq_rows, sh_rows),
           "pre": RG.MBPreN(mkt), "etfbook": G.ETFBook()}
    out = {"candidate_count": 2, "native_count": 5, "folds": {},
           "halves": {}}
    wins = 0
    for yr in range(2017, 2027):
        s = f"{yr}-01-01"
        e = END if yr == 2026 else f"{yr}-12-31"
        r2 = RG.run_house(ctx, s, e, 2)
        r5 = RG.run_house(ctx, s, e, 5)
        w = r2["final"] > r5["final"]
        wins += 1 if w else 0
        out["folds"][str(yr)] = {"candidate_final": round(r2["final"], 2),
                                 "native5_final": round(r5["final"], 2),
                                 "candidate_wins": w}
        print(f"FOLD {yr}: N=2 ${r2['final']:,.2f} vs N=5 "
              f"${r5['final']:,.2f} win={w} ({time.time()-t0:.0f}s)",
              flush=True)
    hwins = 0
    for hn, (s, e) in {"H1_2017-2021": ("2017-01-01", "2021-12-31"),
                       "H2_2022-2026": ("2022-01-01", END)}.items():
        r2 = RG.run_house(ctx, s, e, 2)
        r5 = RG.run_house(ctx, s, e, 5)
        w = r2["final"] > r5["final"]
        hwins += 1 if w else 0
        out["halves"][hn] = {"candidate_final": round(r2["final"], 2),
                             "native5_final": round(r5["final"], 2),
                             "candidate_wins": w}
        print(f"HALF {hn}: N=2 ${r2['final']:,.2f} vs N=5 "
              f"${r5['final']:,.2f} win={w}", flush=True)
    out["fold_wins"] = f"{wins}/10"
    out["half_wins"] = f"{hwins}/2"
    out["confirmed"] = wins >= 6 and hwins >= 1
    _safe_dump(out, os.path.join(HERE, "confirm_grand.json"))
    print(f"CONFIRMATION DONE folds {wins}/10 halves {hwins}/2 "
          f"confirmed={out['confirmed']} ({time.time()-t0:.0f}s)",
          flush=True)


if __name__ == "__main__":
    main()
