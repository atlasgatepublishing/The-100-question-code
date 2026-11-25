#!/usr/bin/env python3
"""Period-by-period record at native tempo (monthly) from results.json curves.
Used for the RESULTS.md table (Terry's reporting rule, 2026-11-22)."""
import json, pathlib, statistics

d = json.loads((pathlib.Path(__file__).parent / "results.json").read_text())

def stats(curve):
    vals = [100.0] + [v for _, v in curve]
    rets = [vals[i] / vals[i - 1] - 1 for i in range(1, len(vals))]
    run = mx = 0
    for r in rets:
        run = run + 1 if r < 0 else 0
        mx = max(mx, run)
    peak, last_high, maxgap = vals[0], 0, 0
    for i, v in enumerate(vals):
        if v >= peak:
            peak = v; maxgap = max(maxgap, i - last_high); last_high = i
    maxgap = max(maxgap, len(vals) - 1 - last_high)
    return {"months": len(rets), "pos_months": sum(1 for r in rets if r > 0),
            "flat_months": sum(1 for r in rets if abs(r) < 1e-9),
            "median_pct": round(100 * statistics.median(rets), 2),
            "best_pct": round(100 * max(rets), 2), "worst_pct": round(100 * min(rets), 2),
            "longest_losing_streak_months": mx,
            "longest_stretch_between_new_highs_months": maxgap,
            "average_pct_labeled_average": round(100 * sum(rets) / len(rets), 2)}

for f in "AB":
    for w in ["FULL", "LONG", "DECADE", "CONT", "VAL", "PRE2010"]:
        print(f, w, stats(d["forms_results"][f][w]["curve"]))
