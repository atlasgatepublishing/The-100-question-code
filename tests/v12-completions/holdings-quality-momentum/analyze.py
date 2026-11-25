#!/usr/bin/env python3
"""Per-period distributions (Terry's reporting standard) from the saved
equity curves in results.json: periods at the run's own cadence tempo,
sampled at cadence dates (first trading day of each period, v10 cadence
definition) plus the road end. Stores results.json['distributions'] and
prints markdown tables."""
import json, os, statistics, sys
from datetime import date
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_sweep as rs

HERE = os.path.dirname(os.path.abspath(__file__))

def dist(curve, period_dates):
    pts = []
    cv = dict(curve)
    days = [d for d, _ in curve]
    for pd_ in period_dates:
        # curve value on the cadence date itself (it is a trading day)
        if pd_ in cv:
            pts.append((pd_, cv[pd_]))
    last_d, last_v = curve[-1]
    if pts and pts[-1][0] != last_d:
        pts.append((last_d, last_v))
    rets = []
    for (d0, v0), (d1, v1) in zip(pts, pts[1:]):
        if v0 > 0:
            rets.append((d1, v1 / v0 - 1.0))
    if not rets:
        return None
    vals = [r for _, r in rets]
    n = len(vals)
    prof = sum(1 for r in vals if r > 0)
    # longest losing run
    best_run = run = 0
    for r in vals:
        run = run + 1 if r <= 0 else 0
        best_run = max(best_run, run)
    # longest stretch between new highs (in periods)
    peak = -1e18
    since_high = 0
    longest_gap = 0
    for _, v in pts:
        if v >= peak:
            peak = v
            longest_gap = max(longest_gap, since_high)
            since_high = 0
        else:
            since_high += 1
    longest_gap = max(longest_gap, since_high)
    return {
        "periods": n,
        "pct_profitable": round(100.0 * prof / n, 1),
        "median_period_pct": round(statistics.median(vals) * 100, 2),
        "best_period_pct": round(max(vals) * 100, 2),
        "worst_period_pct": round(min(vals) * 100, 2),
        "longest_losing_run_periods": best_run,
        "longest_stretch_between_new_highs_periods": longest_gap,
        "average_period_pct_secondary": round(statistics.mean(vals) * 100, 2),
    }

def main():
    with open(os.path.join(HERE, "results.json")) as f:
        results = json.load(f)
    quality = rs.load_quality()
    bars = {t: rs.load_bars_full(t) for t in rs.UNIVERSE + ["SPY"]}
    pb = rs.PriceBook(bars)
    targets = [("house-weekly", "weekly", "1"),
               ("house-weekly", "weekly", "5"),
               ("house-quarterly", "quarterly", "5"),
               ("house-quarterly", "quarterly", "ALL")]
    out = {}
    for grid, cadence, count in targets:
        for road, (ws, we) in rs.ROADS.items():
            cell = results["grids"][grid][road][count]
            curve = [(d, v) for d, v in cell["equity_curve"]]
            pdates = rs.cadence_dates(pb, cadence, ws, we)
            dd = dist(curve, pdates)
            out[f"{grid}|{road}|n={count}"] = dd
            print(f"{grid} {road} n={count}: {dd}", flush=True)
    results["distributions"] = out
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
