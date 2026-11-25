#!/usr/bin/env python3
"""V13 best-rules run for catalog-hxz-taxable-income — BEST-RULES-SPEC.md (frozen).
Cell: Tbi (exact catalog construction) | broad + measurability band
0<=Tbi<=2 | no floor | annual June | QUINTILE EW.
Reuses the v12 engine chassis verbatim (copied alongside). Simulation only."""
import json, os, sys, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E

HERE = os.path.dirname(os.path.abspath(__file__))
FAM = os.path.join(HERE, '..')

ROADS = {'LONG': list(range(2016, 2026)), 'DECADE': list(range(2017, 2026)),
         'CONT': list(range(2019, 2026)), 'VAL': list(range(2023, 2026))}
FOLDS = {'FOLD_2016_2020': list(range(2016, 2021)), 'FOLD_2021_2025': list(range(2021, 2026))}

def dist_stats(curve, formations):
    vals = [v for _, v in curve]
    ends = [100.0] + [vals[i] for i in range(11, len(vals), 12)]
    rets = [(b / a - 1) * 100 for a, b in zip(ends, ends[1:]) if a]
    pos = sum(1 for r in rets if r > 0)
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0
        streak = max(streak, cur)
    peak = 100.0; since = 0; longest = 0
    for v in vals:
        if v >= peak: peak = v; longest = max(longest, since); since = 0
        else: since += 1
    longest = max(longest, since)
    return {'n_periods': len(rets), 'period_returns_pct': [round(r, 1) for r in rets],
            'median_period_pct': round(statistics.median(rets), 1) if rets else None,
            'share_positive': f'{pos}/{len(rets)}' if rets else None,
            'best_pct': round(max(rets), 1) if rets else None,
            'worst_pct': round(min(rets), 1) if rets else None,
            'mean_period_pct_secondary': round(statistics.mean(rets), 1) if rets else None,
            'longest_losing_streak_periods': streak,
            'longest_months_between_new_highs': longest}

def run(forms, seed=None):
    return E.run_road(forms, 'Tbi', 'broad', 'QUINTILE', 'annual', False, seed=seed)

out = {'family': 'catalog-hxz-taxable-income', 'program': 'v13-best-rules',
       'spec': 'BEST-RULES-SPEC.md',
       'cell': 'Tbi|broad+band[0,2]|nofloor|annual|QUINTILE',
       'pool_sizes': {f'{F}|broad': len(E.POOLS[("Tbi", F, "broad")]) for F in range(2016, 2026)},
       'roads': {}, 'folds': {}}

for name, forms in {**ROADS, **FOLDS}.items():
    fin, curve, costs, maxdd = run(forms)
    twins = []
    for s in range(1, 21):
        tf, _, _, _ = run(forms, seed=s)
        twins.append(tf)
    cell = {'final': fin, 'costs': costs, 'max_dd': maxdd,
            'spy_same_window': E.spy_final(forms),
            'placebo_finals': twins,
            'placebos_beaten': sum(1 for t in twins if fin > t),
            'placebo_median': round(statistics.median(twins), 2),
            'distribution': dist_stats(curve, forms),
            'curve': curve}
    (out['roads'] if name in ROADS else out['folds'])[name] = cell
    print(name, fin, 'maxdd', maxdd, 'spy', cell['spy_same_window'],
          'pb', cell['placebos_beaten'], '/20', flush=True)

with open(os.path.join(FAM, 'results.json'), 'w') as fh:
    json.dump(out, fh, indent=1)
print('saved results.json')
