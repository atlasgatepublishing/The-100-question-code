#!/usr/bin/env python3
"""Period-by-period record at the strategy's native tempo (DAILY — Minervini
SEPA is a daily system: daily VCP/breakout scans, daily stop checks).
Computed from the saved equity curves in results.json. Period = one trading
day; period return = equity change vs the prior curve point (first period
measured vs the $100 start). Averages are reported only as a labeled
secondary line, per Terry's reporting correction (2026-11-22)."""
import json, os, statistics

HERE = os.path.dirname(os.path.abspath(__file__))

def stats(curve):
    vals = [100.0] + [v for _, v in curve]
    rets = [(vals[i] / vals[i - 1] - 1) * 100 for i in range(1, len(vals))
            if vals[i - 1] > 0]
    pos = sum(1 for r in rets if r > 0)
    # longest run of consecutive losing periods
    run = worst_run = 0
    for r in rets:
        run = run + 1 if r < 0 else 0
        worst_run = max(worst_run, run)
    # longest stretch between new highs (in periods, peak to next new high)
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
    out = {}
    for road, r in res["roads"].items():
        out[road] = stats(r["curve"])
        print(road, out[road])
    res["period_stats_daily_native_tempo"] = out
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(res, f, indent=1)
    print("written into results.json")

if __name__ == "__main__":
    main()
