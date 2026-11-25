#!/usr/bin/env python3
"""Period-by-period record at the strategy's native tempo (DAILY — the
Wyckoff school works daily/weekly bar charts and judges readiness day by
day). The daily statistics stored in results.json were computed in-process
from the full daily equity curves during the run (see results.json
curve_note for why the stored curve is weekly-sampled). This script prints
the stored daily distribution and, for checking, the same distribution
computed from the stored weekly-sampled curve. Averages appear only as a
labeled secondary line, per Terry's reporting correction (2026-11-22)."""
import json, os, statistics

HERE = os.path.dirname(os.path.abspath(__file__))

def stats(curve):
    vals = [100.0] + [v for _, v in curve]
    rets = [(vals[i] / vals[i - 1] - 1) * 100 for i in range(1, len(vals))
            if vals[i - 1] > 0]
    pos = sum(1 for r in rets if r > 0)
    run = worst_run = 0
    for r in rets:
        run = run + 1 if r < 0 else 0
        worst_run = max(worst_run, run)
    peak = vals[0]
    since = 0
    longest = 0
    for v in vals[1:]:
        if v > peak:
            peak = v
            longest = max(longest, since)
            since = 0
        else:
            since += 1
    longest = max(longest, since)
    return {
        "periods": len(rets),
        "pct_periods_profitable": round(100 * pos / len(rets), 1) if rets else None,
        "median_period_pct": round(statistics.median(rets), 3) if rets else None,
        "best_period_pct": round(max(rets), 2) if rets else None,
        "worst_period_pct": round(min(rets), 2) if rets else None,
        "longest_losing_run_periods": worst_run,
        "longest_stretch_between_new_highs_periods": longest,
        "average_period_pct_SECONDARY_LABELED_AVERAGE":
            round(statistics.mean(rets), 3) if rets else None,
    }

def main():
    with open(os.path.join(HERE, "results.json")) as f:
        res = json.load(f)
    for road, r in res["roads"].items():
        print(road, "stored daily stats:", r["period_stats_daily"])
        print(road, "weekly-curve check:", stats(r["curve_weekly"]))

if __name__ == "__main__":
    main()
