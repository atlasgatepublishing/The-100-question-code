#!/usr/bin/env python3
"""Per-period distribution (Terry's reporting standard) from saved equity
curves at the strategy's tempo (monthly), plus the confirmation runner.
Usage:
  analyze.py dist <cell.json> [...]   -> prints distribution JSON per cell
  (confirmation runs live in confirm.py)"""
import json, sys
import numpy as np

def monthly_points(curve):
    pts, seen = [], {}
    for d, v in curve:
        seen[d[:7]] = (d, v)
    for k in sorted(seen):
        pts.append(seen[k])
    return pts

def distribution(curve):
    pts = monthly_points(curve)
    rets = []
    for (d0, v0), (d1, v1) in zip(pts, pts[1:]):
        if v0 > 0:
            rets.append(v1 / v0 - 1.0)
    if not rets:
        return {"periods": 0}
    arr = np.array(rets)
    # longest losing run
    run = best_run = 0
    for r in rets:
        run = run + 1 if r < 0 else 0
        best_run = max(best_run, run)
    # longest stretch between new highs (in monthly periods, on month-end values)
    peak = -1e18; since = 0; longest = 0
    for _, v in pts:
        if v > peak:
            peak = v; since = 0
        else:
            since += 1; longest = max(longest, since)
    return {"period_tempo": "monthly", "periods": len(rets),
            "pct_periods_profitable": round(float((arr > 0).mean() * 100), 1),
            "median_period_pct": round(float(np.median(arr) * 100), 2),
            "best_period_pct": round(float(arr.max() * 100), 2),
            "worst_period_pct": round(float(arr.min() * 100), 2),
            "longest_losing_run_periods": best_run,
            "longest_stretch_between_new_highs_periods": longest,
            "average_period_pct_SECONDARY": round(float(arr.mean() * 100), 2)}

if __name__ == "__main__":
    out = {}
    for path in sys.argv[2:]:
        cell = json.load(open(path))
        key = f"{cell['rules']}-{cell['road']}-{cell['count']}"
        out[key] = distribution(cell["equity_curve"])
    print(json.dumps(out, indent=1))
