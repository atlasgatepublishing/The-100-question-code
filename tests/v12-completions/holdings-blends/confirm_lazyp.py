#!/usr/bin/env python3
"""
CONFIRMATION — combo-vm-lazyp count 3 (Terry's rule: a non-native
count that wins is re-run on DIFFERENT YEARS before its verdict
counts).

Grid result being confirmed (house form): N=3 had the highest
3-road sum ($1,524 vs native N=5's $1,368) and beat N=5 on CONT
($662 vs $541) and VAL ($429 vs $313) but LOST DECADE ($433 vs
$514). Confirmation: fresh-$100 calendar-year folds 2017..2026
(house form) N=3 vs N=5, plus half-windows on the family's book
(H1 2017-01-01->2021-12-31, H2 2022-01-01->2026-11-20; the book's
first bar is 2017-06-01, the documented effective-road artifact,
identical for both counts).
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_lazyp as L  # noqa: E402

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
    pb_vm, eq, sh = L.B.build_vm_book()
    pb_lz, signals, _census = L.B.build_lz_book()
    L._fast_book_methods(pb_vm)
    L._fast_book_methods(pb_lz)
    L.vm.pit_value = L.pit_value_fast
    ctx = {"pb_vm": pb_vm, "eq": eq, "sh": sh, "pb_lz": pb_lz,
           "signals": signals}
    out = {"candidate_count": 3, "native_count": 5, "folds": {},
           "halves": {}}
    wins = 0
    for yr in range(2017, 2027):
        s = f"{yr}-01-01"
        e = END if yr == 2026 else f"{yr}-12-31"
        r3 = L.run_house(ctx, s, e, 3)
        r5 = L.run_house(ctx, s, e, 5)
        w = r3["final"] > r5["final"]
        wins += 1 if w else 0
        out["folds"][str(yr)] = {"candidate_final": round(r3["final"], 2),
                                 "native5_final": round(r5["final"], 2),
                                 "candidate_wins": w}
        print(f"FOLD {yr}: N=3 ${r3['final']:,.2f} vs N=5 "
              f"${r5['final']:,.2f} win={w} ({time.time()-t0:.0f}s)",
              flush=True)
    hwins = 0
    for hn, (s, e) in {"H1_2017-2021": ("2017-01-01", "2021-12-31"),
                       "H2_2022-2026": ("2022-01-01", END)}.items():
        r3 = L.run_house(ctx, s, e, 3)
        r5 = L.run_house(ctx, s, e, 5)
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
    _safe_dump(out, os.path.join(HERE, "confirm_lazyp.json"))
    print(f"CONFIRMATION DONE folds {wins}/10 halves {hwins}/2 "
          f"confirmed={out['confirmed']} ({time.time()-t0:.0f}s)",
          flush=True)


if __name__ == "__main__":
    main()
