#!/usr/bin/env python3
"""
CONFIRMATION — combo-vm-nf3 count 3 (Terry's rule: a non-native
count that wins across roads is re-run on DIFFERENT YEARS before
its verdict counts).

Grid result being confirmed (house form): N=3 beat N=5 on all three
roads — DECADE $875 vs $716, CONT $668 vs $532, VAL $386 vs $290.

Confirmation runs (all house form, spliced book throughout):
- fresh-$100 calendar-year folds 2017..2026, N=3 vs N=5 head-to-head
- DECADE half-windows H1 2016-11-21->2021-12-31, H2 2022-01-01->END
- the champion parent standalone in THIS plumbing (spliced book,
  quarterly, plain floor and v9) for the standing parent fence.
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import engine_nf3 as E  # noqa: E402

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
    facts, eq, sh = E.load_facts()
    bars_spliced, _factors = E.spliced_bars()
    pb = E.FastPriceBook(bars_spliced)
    sc = E.Scorer(pb, eq, sh, facts)

    out = {"candidate_count": 3, "native_count": 5, "folds": {},
           "halves": {}, "parent_champion_in_plumbing": {}}
    wins = 0
    for yr in range(2017, 2027):
        s = f"{yr}-01-01"
        e = END if yr == 2026 else f"{yr}-12-31"
        q = E.champ.quarter_selection_dates(pb, s, e)
        r3 = E.run_combo_v9(pb, sc, s, e, q, 100.0, n=3)
        r5 = E.run_combo_v9(pb, sc, s, e, q, 100.0, n=5)
        w = r3["final"] > r5["final"]
        wins += 1 if w else 0
        out["folds"][str(yr)] = {"candidate_final": round(r3["final"], 2),
                                 "native5_final": round(r5["final"], 2),
                                 "candidate_wins": w}
        print(f"FOLD {yr}: N=3 ${r3['final']:,.2f} vs N=5 "
              f"${r5['final']:,.2f} win={w} ({time.time()-t0:.0f}s)",
              flush=True)
    hwins = 0
    for hn, (s, e) in {"H1_2016-2021": ("2016-11-21", "2021-12-31"),
                       "H2_2022-2026": ("2022-01-01", END)}.items():
        q = E.champ.quarter_selection_dates(pb, s, e)
        r3 = E.run_combo_v9(pb, sc, s, e, q, 100.0, n=3)
        r5 = E.run_combo_v9(pb, sc, s, e, q, 100.0, n=5)
        w = r3["final"] > r5["final"]
        hwins += 1 if w else 0
        out["halves"][hn] = {"candidate_final": round(r3["final"], 2),
                             "native5_final": round(r5["final"], 2),
                             "candidate_wins": w}
        print(f"HALF {hn}: N=3 ${r3['final']:,.2f} vs N=5 "
              f"${r5['final']:,.2f} win={w}", flush=True)
    out["fold_wins"] = f"{wins}/10"
    out["half_wins"] = f"{hwins}/2"
    out["confirmed"] = wins >= 6 and hwins >= 1
    # champion parent standalone in this plumbing (for the fence)
    for road, s in (("DECADE", "2016-11-21"), ("CONT", "2019-01-02"),
                    ("VAL", "2023-01-03")):
        q = E.champ.quarter_selection_dates(pb, s, END)
        rp = E.champ.run_pot(pb, eq, sh, s, END, 100.0, 85.0, [],
                             label=f"parent {road}", quiet=True)
        out["parent_champion_in_plumbing"][road] = round(rp["final"], 2)
        print(f"PARENT champion {road} (spliced book, plain floor): "
              f"${rp['final']:,.2f}", flush=True)
    _safe_dump(out, os.path.join(HERE, "confirm_nf3.json"))
    print(f"CONFIRMATION DONE folds {wins}/10 halves {hwins}/2 "
          f"confirmed={out['confirmed']} ({time.time()-t0:.0f}s)",
          flush=True)


if __name__ == "__main__":
    main()
