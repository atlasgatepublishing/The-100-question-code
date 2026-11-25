#!/usr/bin/env python3
"""Period-by-period record at the strategy's lived tempo (MONTHLY — classical
charting formations take weeks-to-months to build and the positions they
produce are held for weeks; a practitioner's statement arrives monthly).
Computed from the saved equity curves in results.json. Period = one calendar
month; period return = month-end equity vs prior month-end (first period
measured vs the $100 start). Averages appear only as a labeled secondary
line, per Terry's reporting correction (2026-11-22)."""
import json, os, statistics

HERE = os.path.dirname(os.path.abspath(__file__))

def monthly(curve):
    ends = {}
    for d, v in curve:
        ends[d[:7]] = v
    months = sorted(ends)
    return [100.0] + [ends[m] for m in months]

def stats(curve):
    vals = monthly(curve)
    rets = [(vals[i] / vals[i - 1] - 1) * 100 for i in range(1, len(vals)) if vals[i - 1] > 0]
    pos = sum(1 for r in rets if r > 0)
    run = worst_run = 0
    for r in rets:
        run = run + 1 if r < 0 else 0
        worst_run = max(worst_run, run)
    peak = vals[0]; since = 0; longest = 0
    for v in vals[1:]:
        if v > peak:
            peak = v; longest = max(longest, since); since = 0
        else:
            since += 1
    longest = max(longest, since)
    return {"periods_months": len(rets),
            "pct_periods_profitable": round(100 * pos / len(rets), 1) if rets else None,
            "median_period_pct": round(statistics.median(rets), 3) if rets else None,
            "best_period_pct": round(max(rets), 2) if rets else None,
            "worst_period_pct": round(min(rets), 2) if rets else None,
            "longest_losing_run_months": worst_run,
            "longest_stretch_between_new_highs_months": longest,
            "average_period_pct_SECONDARY_LABELED_AVERAGE": round(statistics.mean(rets), 3) if rets else None}

def main():
    # Prints the monthly period stats for the saved curves. The same stats are
    # embedded in results.json by run_judgment.py itself (key
    # "period_stats_monthly"); this script recomputes them standalone as a
    # cross-check. (Standalone print only: this session's sandbox blocks
    # python file writes — see run_judgment.py note.)
    with open(os.path.join(HERE, "results.json")) as f:
        res = json.load(f)
    for road, r in res["roads"].items():
        print(road, stats(r["equity_curve"]))

if __name__ == "__main__":
    main()
