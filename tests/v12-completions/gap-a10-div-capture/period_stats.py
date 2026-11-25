#!/usr/bin/env python3
"""Period-by-period record at the strategy's native tempo (one overnight
capture cycle per curve step), computed from the saved equity curves in
results.json. Merges a `period_record` block into each run in results.json.
Averages are reported only as a labeled secondary line."""
import json, os, statistics
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(HERE, "results.json")
r = json.load(open(P))

def period_record(curve):
    # curve: [[date, value], ...]; a period = one step between consecutive points
    rets = []
    for (d0, v0), (d1, v1) in zip(curve, curve[1:]):
        if v0 > 0:
            rets.append((d1, (v1 / v0 - 1) * 100))
    n = len(rets)
    pos = sum(1 for _, x in rets if x > 0)
    flat = sum(1 for _, x in rets if x == 0)
    # longest consecutive losing run
    worst_run = cur = 0
    for _, x in rets:
        cur = cur + 1 if x < 0 else 0
        worst_run = max(worst_run, cur)
    # longest stretch between new highs (in periods and calendar days)
    peak, peak_date, longest_p, longest_days = -1e18, None, 0, 0
    for d, v in curve:
        if v >= peak:
            if peak_date is not None:
                longest_days = max(longest_days,
                                   (datetime.strptime(d, "%Y-%m-%d") - datetime.strptime(peak_date, "%Y-%m-%d")).days)
            peak, peak_date = v, d
            cur_p = 0
        else:
            cur_p += 1
            longest_p = max(longest_p, cur_p)
    if peak_date is not None and curve:
        longest_days = max(longest_days,
                           (datetime.strptime(curve[-1][0], "%Y-%m-%d") - datetime.strptime(peak_date, "%Y-%m-%d")).days
                           if curve[-1][1] < peak else longest_days)
    vals = [x for _, x in rets]
    return {
        "tempo": "per curve step (one overnight capture cycle)",
        "n_periods": n,
        "pct_periods_positive": round(pos / n * 100, 1) if n else None,
        "pct_periods_flat_sitout_or_no_trade": round(flat / n * 100, 1) if n else None,
        "median_period_pct": round(statistics.median(vals), 4) if vals else None,
        "best_period_pct": round(max(vals), 2) if vals else None,
        "worst_period_pct": round(min(vals), 2) if vals else None,
        "longest_consecutive_losing_periods": worst_run,
        "longest_stretch_between_new_highs_periods": longest_p,
        "longest_stretch_between_new_highs_days": longest_days,
        "secondary_average_period_pct_labeled_average": round(statistics.mean(vals), 4) if vals else None,
    }

for w, run in r["runs"].items():
    run["period_record"] = period_record(run["curve"])
    print(w, run["period_record"])

json.dump(r, open(P, "w"), indent=1)
print("merged period_record into results.json")
