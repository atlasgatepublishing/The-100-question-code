#!/usr/bin/env python3
"""Per-period (annual, native tempo) distribution from results.json curves.
Prints stats for the native cell and any cell named on argv."""
import json, os, sys, statistics
FAM = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
res = json.load(open(os.path.join(FAM, 'results.json')))

def stats(curve):
    # curve: monthly marks starting after first formation June; annual periods = Jun->Jun steps of 12
    vals = [100.0] + [v for _, v in curve]
    rets = []
    for i in range(12, len(vals), 12):
        rets.append(vals[i] / vals[i - 12] - 1)
    if not rets: return None
    pos = sum(1 for r in rets if r > 0)
    worst_run = 0; run = 0
    for r in rets:
        run = run + 1 if r <= 0 else 0; worst_run = max(worst_run, run)
    peak = vals[0]; longest_no_high = 0; cur = 0
    for v in vals:
        if v >= peak: peak = v; cur = 0
        else: cur += 1; longest_no_high = max(longest_no_high, cur)
    return {'periods': len(rets), 'positive': pos,
            'median_pct': round(statistics.median(rets) * 100, 1),
            'mean_pct_secondary': round(statistics.mean(rets) * 100, 1),
            'best_pct': round(max(rets) * 100, 1), 'worst_pct': round(min(rets) * 100, 1),
            'yearly_pct': [round(r * 100, 1) for r in rets],
            'longest_losing_run': worst_run, 'longest_months_between_highs': longest_no_high}

keys = sys.argv[1:] or ['BrandInvest|native|native|annual|QUINTILE']
for k in keys:
    cell = res['grid'].get(k)
    if not cell: print(k, 'MISSING'); continue
    for road in ('LONGEST_2016_2025', 'DECADE_2017_2025', 'CONT_2019_2025', 'VAL_2023_2025'):
        print(k, road, cell[road]['final'], 'pb', cell[road]['placebos_beaten'], stats(cell[road]['curve']))
