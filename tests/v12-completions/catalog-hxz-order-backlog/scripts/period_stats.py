#!/usr/bin/env python3
"""Per-period (annual, native tempo) distribution from results.json curves."""
import json, os, sys, statistics
FAM = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
res = json.load(open(os.path.join(FAM, 'results.json')))
def stats(curve):
    vals = [100.0] + [v for _, v in curve]
    rets = [vals[i] / vals[i - 12] - 1 for i in range(12, len(vals), 12)]
    if not rets: return None
    pos = sum(1 for r in rets if r > 0); worst_run = 0; run = 0
    for r in rets:
        run = run + 1 if r <= 0 else 0; worst_run = max(worst_run, run)
    peak = vals[0]; longest = 0; cur = 0
    for v in vals:
        if v >= peak: peak = v; cur = 0
        else: cur += 1; longest = max(longest, cur)
    return {'periods': len(rets), 'positive': pos, 'median_pct': round(statistics.median(rets) * 100, 1),
            'mean_pct_secondary': round(statistics.mean(rets) * 100, 1),
            'best_pct': round(max(rets) * 100, 1), 'worst_pct': round(min(rets) * 100, 1),
            'yearly_pct': [round(r * 100, 1) for r in rets],
            'longest_losing_run': worst_run, 'longest_months_between_highs': longest}
for k in sys.argv[1:]:
    cell = res['grid'].get(k)
    if not cell: print(k, 'MISSING'); continue
    for road in ('LONGEST', 'DECADE', 'CONT', 'VAL'):
        if road in cell and 'curve' in cell[road]:
            print(k, road, cell[road]['final'], 'pb', cell[road].get('placebos_beaten'), stats(cell[road]['curve']))
