#!/usr/bin/env python3
"""Per-period distribution per Terry's REPORTING STANDARD, computed from a
saved monthly equity curve resampled to the strategy's tempo.
Usage: period_stats(curve_monthly, period) where period in
{'annual','quarterly'} and curve_monthly = [[date, value], ...] dates as
'YYYY-MM' (SY) or 'YYYY-MM-DD' month-ends (DG). Returns dict with period
count, % profitable, median, best, worst, longest losing run, longest
stretch between new highs (in periods, from the period-end series), and
the average as a labeled secondary."""
import statistics

def _period_key(date, period):
    y, m = int(date[:4]), int(date[5:7])
    if period == 'annual':
        return f'{y:04d}'
    return f'{y:04d}Q{(m - 1) // 3 + 1}'

def period_stats(curve, period, start_value=100.0):
    ends = {}
    for d, v in curve:
        ends[_period_key(d, period)] = v  # last mark in period wins
    keys = sorted(ends)
    vals = [ends[k] for k in keys]
    rets = []
    prev = start_value
    for v in vals:
        rets.append(v / prev - 1 if prev else 0.0)
        prev = v
    if not rets:
        return {'period': period, 'n_periods': 0}
    prof = sum(1 for r in rets if r > 0)
    longest_loss = 0; run = 0
    for r in rets:
        run = run + 1 if r <= 0 else 0
        longest_loss = max(longest_loss, run)
    # longest stretch between new highs, in periods (period-end series)
    peak = start_value; since_high = 0; longest_gap = 0
    for v in vals:
        if v > peak:
            peak = v; longest_gap = max(longest_gap, since_high); since_high = 0
        else:
            since_high += 1
    longest_gap = max(longest_gap, since_high)
    return {
        'period': period,
        'n_periods': len(rets),
        'pct_profitable': round(100.0 * prof / len(rets), 1),
        'median_period_pct': round(100.0 * statistics.median(rets), 2),
        'best_period_pct': round(100.0 * max(rets), 2),
        'worst_period_pct': round(100.0 * min(rets), 2),
        'longest_losing_run_periods': longest_loss,
        'longest_stretch_between_new_highs_periods': longest_gap,
        'average_period_pct_SECONDARY': round(100.0 * statistics.mean(rets), 2),
        'period_returns_pct': [round(100.0 * r, 2) for r in rets],
        'period_keys': keys,
    }
