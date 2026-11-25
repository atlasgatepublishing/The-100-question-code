#!/usr/bin/env python3
"""Per-period (semiannual, my chassis's native tempo) distribution from
results.json curves. Periods = 6-month steps along the monthly curve."""
import json, os, statistics
FAM = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
res = json.load(open(os.path.join(FAM, 'results.json')))

def stats(curve):
    vals = [100.0] + [v for _, v in curve]
    rets = []
    for i in range(6, len(vals), 6):
        rets.append(vals[i] / vals[i - 6] - 1)
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
            'period_pct': [round(r * 100, 1) for r in rets],
            'longest_losing_run': worst_run, 'longest_months_between_highs': longest_no_high}

for road in ('LONGEST_2016_2025', 'DECADE_2017_2025', 'CONT_2019_2025', 'VAL_2023_2025'):
    r = res['roads'][road]
    print(road, 'final', r['final'], 'maxdd', r['maxdd_pct'], 'costs', r['costs'],
          'pb', r['placebos_beaten'], '/20  SPY same-window', res['spy'][road])
    print('  ', stats(r['curve']))
    print('   placebo finals:', r['placebo_finals'])
