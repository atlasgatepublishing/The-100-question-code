#!/usr/bin/env python3
"""
v12 v0-aggressive - PERIOD-BY-PERIOD record at the strategy's native tempo
(DAILY), computed from the saved equity curves in results.json
(Terry's reporting correction, 2026-11-22).

Per road: number of daily periods, share of periods that made money, MEDIAN
daily period return, best day, worst day, longest run of consecutive losing
days, longest stretch between new highs (trading days). Averages are
reported only as a secondary, labeled line.
"""
import json, os, statistics

HERE = os.path.dirname(os.path.abspath(__file__))
res = json.load(open(os.path.join(HERE, "results.json")))
out = {}
for road, r in res["roads"].items():
    curve = [[d, e] for d, e in r["equity_curve"]]
    # day-over-day returns, starting from the $100 start balance
    rets = []
    prev = 100.0
    for d, e in curve:
        rets.append((d, e / prev - 1.0))
        prev = e
    vals = [x[1] for x in rets]
    up = sum(1 for v in vals if v > 0)
    flat = sum(1 for v in vals if v == 0)
    # longest losing streak (consecutive strictly negative days)
    streak = longest_loss = 0
    for v in vals:
        streak = streak + 1 if v < 0 else 0
        longest_loss = max(longest_loss, streak)
    # longest stretch between new highs (trading days without a new peak)
    peak = 100.0
    since_high = longest_gap = 0
    for _, e in curve:
        if e > peak:
            peak = e
            longest_gap = max(longest_gap, since_high)
            since_high = 0
        else:
            since_high += 1
    longest_gap = max(longest_gap, since_high)
    best = max(rets, key=lambda x: x[1])
    worst = min(rets, key=lambda x: x[1])
    out[road] = {
        "periods_daily": len(vals),
        "pct_periods_profitable": round(up / len(vals) * 100, 1),
        "pct_periods_flat": round(flat / len(vals) * 100, 1),
        "median_period_pct": round(statistics.median(vals) * 100, 3),
        "best_period": {"date": best[0], "pct": round(best[1] * 100, 2)},
        "worst_period": {"date": worst[0], "pct": round(worst[1] * 100, 2)},
        "longest_losing_streak_days": longest_loss,
        "longest_stretch_between_new_highs_days": longest_gap,
        "average_period_pct_SECONDARY": round(statistics.mean(vals) * 100, 3),
    }
    print(road, json.dumps(out[road]))
with open(os.path.join(HERE, "period_stats.json"), "w") as f:
    json.dump(out, f, indent=1)
print("wrote period_stats.json")
