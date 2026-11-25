#!/usr/bin/env python3
"""Period-by-period record at the strategy's native tempo (MONTHLY --
Daniel & Moskowitz evaluate and re-weight monthly), computed from the
saved equity curves in results.json. Coordinator requirement 2026-11-22:
period count, share of periods that made money, MEDIAN period, best,
worst, longest run of consecutive losing periods, longest stretch
between new highs. Averages only as a labeled secondary line."""
import json
import os
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))


def monthly_stats(curve):
    # month-end values from the daily curve
    month_end = {}
    for d, v in curve:
        month_end[d[:7]] = v
    months = sorted(month_end)
    rets = []
    for i in range(1, len(months)):
        prev, cur = month_end[months[i - 1]], month_end[months[i]]
        rets.append((months[i], cur / prev - 1.0))
    vals = [r for _, r in rets]
    pos = sum(1 for r in vals if r > 0)
    # longest losing streak
    streak = longest = 0
    for r in vals:
        streak = streak + 1 if r < 0 else 0
        longest = max(longest, streak)
    # longest stretch between new highs (months from a peak until the
    # curve first exceeds it again; if never, to the end of the window)
    peak = -1.0
    peak_i = 0
    longest_gap = 0
    gap_open = None
    series = [month_end[m] for m in months]
    for i, v in enumerate(series):
        if v > peak:
            if gap_open is not None:
                longest_gap = max(longest_gap, i - gap_open)
                gap_open = None
            peak, peak_i = v, i
        elif gap_open is None:
            gap_open = peak_i
    if gap_open is not None:
        longest_gap = max(longest_gap, len(series) - 1 - gap_open)
    return {
        "periods_monthly": len(vals),
        "periods_made_money": pos,
        "share_made_money_pct": round(100.0 * pos / len(vals), 1),
        "median_period_pct": round(statistics.median(vals) * 100, 2),
        "best_period": {"month": max(rets, key=lambda kv: kv[1])[0],
                        "pct": round(max(vals) * 100, 2)},
        "worst_period": {"month": min(rets, key=lambda kv: kv[1])[0],
                         "pct": round(min(vals) * 100, 2)},
        "longest_losing_streak_periods": longest,
        "longest_stretch_between_new_highs_periods": longest_gap,
        "average_period_pct_SECONDARY": round(sum(vals) / len(vals) * 100, 2),
    }


def main():
    with open(os.path.join(HERE, "results.json")) as f:
        res = json.load(f)
    out = {}
    for road in ("CONT", "VAL", "CONFIRM"):
        blk = res[road]
        entry = {}
        for arm in ("ranked_gated", "ranked_ungated"):
            if arm in blk:
                entry[arm] = monthly_stats(blk[arm]["curve"])
        out[road] = entry
        print(road, json.dumps(entry, indent=1))
    with open(os.path.join(HERE, "period-record.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("saved period-record.json")


if __name__ == "__main__":
    main()
