#!/usr/bin/env python3
"""Per-period distribution stats from results.json daily curves.
Period = calendar month (primary) + calendar-year folds. Terry's rule:
median period, share positive, best/worst, longest losing streak,
longest stretch between new highs; averages demoted."""
import json, os, statistics
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
d = json.load(open(os.path.join(HERE, "results.json")))

def month_end(curve):
    m = OrderedDict()
    for date, v in curve:
        m[date[:7]] = v
    return m

def analyze(tag):
    r = d[tag]
    curve = r["curve"]
    m = month_end(curve)
    keys = list(m.keys())
    rets = []
    for i in range(1, len(keys)):
        rets.append((keys[i], m[keys[i]] / m[keys[i - 1]] - 1))
    vals = [x[1] for x in rets]
    pos = sum(1 for x in vals if x > 0)
    # longest losing streak (consecutive negative months)
    streak = cur = 0
    for x in vals:
        cur = cur + 1 if x < 0 else 0
        streak = max(streak, cur)
    # longest stretch between new highs (in trading days, from daily curve)
    peak = -1; peak_i = 0; longest = 0
    for i, (date, v) in enumerate(curve):
        if v >= peak:
            peak = v; peak_i = i
        longest = max(longest, i - peak_i)
    # year folds
    y = OrderedDict()
    for date, v in curve:
        y[date[:4]] = v
    ykeys = list(y.keys())
    folds = {}
    prev = 100.0
    # first year fold is partial-window: measure from window start value
    start_v = curve[0][1]
    for i, k in enumerate(ykeys):
        base = start_v if i == 0 else y[ykeys[i - 1]]
        folds[k] = round((y[k] / base - 1) * 100, 1)
    return {
        "months": len(rets),
        "median_month_pct": round(statistics.median(vals) * 100, 2),
        "share_months_positive_pct": round(100 * pos / len(vals), 1),
        "best_month": [max(rets, key=lambda x: x[1])[0], round(max(vals) * 100, 2)],
        "worst_month": [min(rets, key=lambda x: x[1])[0], round(min(vals) * 100, 2)],
        "longest_losing_month_streak": streak,
        "longest_days_between_new_highs": longest,
        "year_folds_pct": folds,
        "secondary_mean_month_pct": round(statistics.mean(vals) * 100, 2),
    }

out = {}
for tag in ("full", "validation", "decade"):
    out[tag] = analyze(tag)
    print(tag, json.dumps(out[tag]))
d["period_distribution"] = out
with open(os.path.join(HERE, "results.json"), "w") as f:
    json.dump(d, f, indent=1, default=str)
print("written into results.json")
