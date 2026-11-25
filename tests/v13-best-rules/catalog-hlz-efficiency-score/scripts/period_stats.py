#!/usr/bin/env python3
"""Per-period (monthly) distribution stats from results.json curves."""
import json, os, statistics
HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(HERE, '..')
res = json.load(open(os.path.join(OUT, 'results.json')))
def stats(curve):
    vals = [100.0] + [v for _, v in curve]
    rets = [(vals[i] / vals[i - 1] - 1) * 100 for i in range(1, len(vals)) if vals[i - 1] > 0]
    pos = sum(1 for r in rets if r > 0)
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0; streak = max(streak, cur)
    peak = vals[0]; since = 0; longest = 0
    for v in vals:
        if v >= peak: peak = v; longest = max(longest, since); since = 0
        else: since += 1
    longest = max(longest, since)
    return {'months': len(rets), 'median_pct': round(statistics.median(rets), 2),
            'share_positive_pct': round(100 * pos / len(rets), 1) if rets else 0,
            'best_pct': round(max(rets), 2), 'worst_pct': round(min(rets), 2),
            'longest_losing_streak_mo': streak, 'longest_between_highs_mo': longest,
            'mean_pct_secondary': round(statistics.mean(rets), 2)}
out = {r: stats(d['curve']) for r, d in res['roads'].items()}
print(json.dumps(out, indent=1))
json.dump(out, open(os.path.join(OUT, 'period_stats.json'), 'w'), indent=1)
