#!/usr/bin/env python3
"""Supplementary placebo: program-standard random top-2 twins (v10/v12 definition).

The spec's same-count placebo is degenerate for this design: the real pot
holds ALL eligible names, so a random subset of the same size IS the full
eligible set — all 20 twins reproduced the real final to the cent (kept in
results.json as placebo_*). The informative test of 'hold all eligible' is
against the family's standard twin: 2 random eligible names, equal weight,
same exits/costs/no floor, 20 seeds per road.
"""
import json, os, statistics, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_best_rules import get_ds, run_placebo, ROADS

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "results.json")) as f:
    out = json.load(f)
for name, (s, e, dd_) in ROADS.items():
    ds = get_ds(dd_)
    n_months = 1000
    twins = []
    for seed in range(1, 21):
        pr = run_placebo(ds, s, e, [2] * n_months, seed)
        twins.append({"seed": seed, "final": pr["final"], "max_dd_pct": pr["max_dd_pct"]})
    real = out["roads"][name]["final"]
    beaten = sum(1 for t in twins if real > t["final"])
    out["roads"][name]["placebo_top2"] = {
        "beaten": beaten,
        "median": round(statistics.median([t["final"] for t in twins]), 2),
        "max": max(t["final"] for t in twins),
        "min": min(t["final"] for t in twins),
        "finals": twins}
    print(name, "real", real, "top2 twins beaten", beaten, "/20",
          "median", out["roads"][name]["placebo_top2"]["median"],
          "max", out["roads"][name]["placebo_top2"]["max"], flush=True)
with open(os.path.join(HERE, "results.json"), "w") as f:
    json.dump(out, f, indent=1)
print("patched results.json")
