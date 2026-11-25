#!/usr/bin/env python3
"""20-seed random-allocation placebos per cadence cell for blend-ladder.
Twin design: identical cadence machinery, costs, Millennium ladder and v9
floor; Sleeve A targets are a random subset (p=0.5 per asset, equal weight)
at each evaluation and Sleeve B picks are a random sample of its eligible
names at each selection. Seeds 1-20."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_sweep as RS

HERE = os.path.dirname(os.path.abspath(__file__))
START, END = "2016-11-21", "2026-11-20"
ORDER = ["monthly", "annual", "semiannual", "quarterly", "biweekly",
         "weekly", "daily"]

def main():
    for cad in ORDER:
        path = os.path.join(HERE, "cells", cad + ".json")
        cell = json.load(open(path))
        twins = []
        for seed in range(1, 21):
            r = RS.run_pot_v10(START, END, 100.0, cad, True,
                               placebo_seed=seed)
            twins.append({"seed": seed, "final": round(r["final"], 2)})
            print(f"{cad} seed {seed}: ${r['final']:.2f}", flush=True)
        beaten = sum(1 for t in twins if t["final"] < cell["final"])
        cell["placebo_twins"] = twins
        cell["placebo_beaten"] = beaten
        cell["placebo_note"] = (
            "20-seed random-allocation twins (seeds 1-20): same cadence "
            "dates, costs, Millennium ladder and v9 floor; Sleeve A holds "
            "a random equal-weight subset of its 7 assets (p=0.5 each) at "
            "every evaluation, Sleeve B holds a random sample of its "
            "eligible names at every selection.")
        with open(path, "w") as f:
            json.dump(cell, f, indent=1)
        print(f"{cad}: placebo_beaten {beaten}/20", flush=True)

if __name__ == "__main__":
    main()
