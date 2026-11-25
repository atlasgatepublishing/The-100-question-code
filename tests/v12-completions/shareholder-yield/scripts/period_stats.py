#!/usr/bin/env python3
"""Period-by-period record at the strategy's NATIVE tempo (annual), per
Terry's 2026-11-22 reporting correction. Computed from the saved equity
curve / yearly records in results.json. Headline stats are per-period
(median, share positive, best/worst, losing streaks, time between highs);
the mean appears only as a labeled secondary average."""
import json, os, statistics
HERE = os.path.dirname(os.path.abspath(__file__))
res = json.load(open(os.path.join(HERE, '..', 'results.json')))

def stats_for(road):
    yrs = road['yearly']
    rets = [y['ret'] for y in yrs]
    n = len(rets)
    pos = sum(1 for r in rets if r > 0)
    # longest run of consecutive losing periods
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0
        streak = max(streak, cur)
    # longest stretch between new highs, from monthly curve (months)
    curve = road['curve']
    peak = -1.0; last_high_i = 0; longest = 0
    for i, (_, v) in enumerate(curve):
        if v >= peak:
            peak = v; longest = max(longest, i - last_high_i); last_high_i = i
    longest = max(longest, len(curve) - 1 - last_high_i)
    # same, in annual periods (period-end values)
    vals = [100.0]
    for r in rets: vals.append(vals[-1] * (1 + r))
    peak = -1.0; last_high_i = 0; longest_p = 0
    for i, v in enumerate(vals):
        if v >= peak:
            peak = v; longest_p = max(longest_p, i - last_high_i); last_high_i = i
    longest_p = max(longest_p, len(vals) - 1 - last_high_i)
    return {
        'periods': n,
        'share_positive': round(pos / n, 3) if n else None,
        'n_positive': pos,
        'median_period': round(statistics.median(rets), 4) if n else None,
        'best_period': round(max(rets), 4) if n else None,
        'worst_period': round(min(rets), 4) if n else None,
        'longest_losing_streak_periods': streak,
        'longest_between_highs_months': longest,
        'longest_between_highs_periods': longest_p,
        'average_period_secondary': round(sum(rets) / n, 4) if n else None,
        'period_rets': [round(r, 4) for r in rets],
    }

out = {}
for name, road in res['roads'].items():
    if 'dropped' in road: continue
    out[name] = stats_for(road)
    print(name, json.dumps(out[name]))
json.dump(out, open(os.path.join(HERE, '..', 'period_stats.json'), 'w'), indent=1)
print('saved period_stats.json')
