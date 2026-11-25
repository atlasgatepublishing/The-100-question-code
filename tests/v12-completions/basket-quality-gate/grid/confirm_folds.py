#!/usr/bin/env python3
"""
CONFIRMATION (Terry's rule) for the holdings-grid cells that beat a
champion: gated basket at N=1 and N=2 (N=5 native shown for reference).
Standalone calendar-year folds 2017-2025, fresh $100 each year, same
engine/costs/protections as the grid slice. SPY buy-and-hold per fold
for reference. A variant counts only if the beat is broad across
different years, not one lucky stretch.
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(HERE)
sys.path.insert(0, PARENT)
sys.path.insert(0, HERE)
import run_gate_constructed as R
from run_grid import simulate_n

YEARS = list(range(2017, 2026))


def spy_fold(mkt, y):
    sd, ed = f"{y}-01-01", f"{y}-12-31"
    idx = [i for i, d in enumerate(mkt.cal) if sd <= d <= ed]
    a = mkt.close_px("SPY", idx[0] - 1)
    b = mkt.close_px("SPY", idx[-1])
    return round(100.0 * b / a, 2)


def main():
    gate_obs, financial, info = R.load_gate_obs()
    mkt = R.Market(R.UNIVERSE)
    out = {"slice": "confirmation calendar-year folds",
           "construction": "CONSTRUCTED", "folds": {}}
    for y in YEARS:
        sd, ed = f"{y}-01-01", f"{y}-12-31"
        row = {"SPY": spy_fold(mkt, y)}
        for n in (1, 2, 5):
            g = simulate_n(mkt, sd, ed, gate_obs, set(financial), n)
            row[f"n{n}"] = {"final": round(g["final"], 2),
                            "max_dd_pct": round(g["max_dd"] * 100, 2),
                            "halts": len(g["halts"])}
        out["folds"][str(y)] = row
        print(y, row, flush=True)
    for n in (1, 2, 5):
        wins = sum(1 for y in YEARS
                   if out["folds"][str(y)][f"n{n}"]["final"] >
                   out["folds"][str(y)]["SPY"])
        med = sorted(out["folds"][str(y)][f"n{n}"]["final"]
                     for y in YEARS)[len(YEARS) // 2]
        out[f"n{n}_folds_beat_spy"] = f"{wins}/{len(YEARS)}"
        out[f"n{n}_fold_median_final"] = med
        print(f"n={n}: folds beating SPY {wins}/{len(YEARS)}, "
              f"median fold final {med}", flush=True)
    path = os.path.join(HERE, "confirmation_folds.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=1)
    print("saved", path, flush=True)


if __name__ == "__main__":
    main()
