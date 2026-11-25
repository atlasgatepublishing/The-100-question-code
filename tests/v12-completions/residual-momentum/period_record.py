#!/usr/bin/env python3
"""Period-by-period record at the strategy's NATIVE tempo (monthly), computed
from the saved equity curves in cells/. Periods = calendar months (value at
last trading day of month vs previous month-end). Reports: number of periods,
share of periods that made money, MEDIAN period return, best, worst, longest
run of consecutive losing periods, longest stretch between new highs
(months, peak month-end to next month-end above it). The mean is printed only
as a secondary, labelled average. Output: period_record.json + stdout."""
import json, os, statistics

HERE = os.path.dirname(os.path.abspath(__file__))
CELLS = os.path.join(HERE, "cells")

def month_ends(curve):
    me = {}
    for d, v in curve:
        me[d[:7]] = v  # last day in month wins (curve is date-ordered)
    return [me[k] for k in sorted(me)], sorted(me)

def record(road):
    cell = json.load(open(os.path.join(CELLS, f"{road}-monthly.json")))
    vals, months = month_ends(cell["equity_curve"])
    rets = []
    for a, b in zip(vals, vals[1:]):
        if a > 0:
            rets.append(b / a - 1.0)
    n = len(rets)
    pos = sum(1 for r in rets if r > 0)
    # longest losing streak
    streak = best_streak = 0
    for r in rets:
        streak = streak + 1 if r < 0 else 0
        best_streak = max(best_streak, streak)
    # longest stretch between new highs (in months, month-end series incl start)
    peak = -1e18; peak_i = 0; longest = 0
    for i, v in enumerate(vals):
        if v > peak:
            peak = v; peak_i = i
        longest = max(longest, i - peak_i)
    out = {"road": road, "period": "calendar month (native tempo)",
           "n_periods": n, "pct_periods_profitable": round(100.0 * pos / n, 1) if n else None,
           "median_period_pct": round(100.0 * statistics.median(rets), 2) if n else None,
           "best_period_pct": round(100.0 * max(rets), 2) if n else None,
           "best_period_month": months[1 + rets.index(max(rets))] if n else None,
           "worst_period_pct": round(100.0 * min(rets), 2) if n else None,
           "worst_period_month": months[1 + rets.index(min(rets))] if n else None,
           "longest_losing_streak_periods": best_streak,
           "longest_stretch_between_new_highs_months": longest,
           "average_period_pct_SECONDARY_LABELLED_AVERAGE": round(100.0 * statistics.mean(rets), 2) if n else None}
    return out

res = {road: record(road) for road in ("LONG", "DECADE", "CONT", "VAL")}
import time as _t
for _a in range(120):
    try:
        with open(os.path.join(HERE, "period_record.json"), "w") as f:
            json.dump(res, f, indent=1)
        break
    except PermissionError:
        _t.sleep(20)
for road, r in res.items():
    print(road, r)
