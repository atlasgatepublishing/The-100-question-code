#!/usr/bin/env python3
"""Monthly per-period distribution from results.json curves (Terry's reporting standard)."""
import json, os, statistics
HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "results.json")) as f:
    R = json.load(f)
out = {}
for road, r in R["roads"].items():
    curve = r["curve"]
    months = {}
    for d, v in curve:
        months[d[:7]] = v  # last value in month
    keys = sorted(months)
    rets = []
    prev = 100.0
    for k in keys:
        rets.append(months[k] / prev - 1)
        prev = months[k]
    pos = sum(1 for x in rets if x > 0)
    # longest losing streak + longest stretch between new highs (on daily curve)
    streak = mx = 0
    for x in rets:
        streak = streak + 1 if x <= 0 else 0
        mx = max(mx, streak)
    peak = -1; since = mxstretch = 0
    for _d, v in curve:
        if v >= peak:
            peak = v; since = 0
        else:
            since += 1; mxstretch = max(mxstretch, since)
    out[road] = {"n_months": len(rets), "pct_positive": round(100 * pos / len(rets), 1) if rets else 0,
                 "median_month_pct": round(100 * statistics.median(rets), 2) if rets else 0,
                 "mean_month_pct": round(100 * statistics.mean(rets), 2) if rets else 0,
                 "best_month_pct": round(100 * max(rets), 2) if rets else 0,
                 "worst_month_pct": round(100 * min(rets), 2) if rets else 0,
                 "longest_losing_streak_months": mx,
                 "longest_days_between_highs": mxstretch}
    print(road, out[road])
with open(os.path.join(HERE, "period_stats.json"), "w") as f:
    json.dump(out, f, indent=1)
