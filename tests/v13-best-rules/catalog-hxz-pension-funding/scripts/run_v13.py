#!/usr/bin/env python3
"""V13 best-rules run for catalog-hxz-pension-funding — BEST-RULES-SPEC.md (frozen).
Cell: Fra | broad sponsor pond | no floor | annual June | TOP HALF EW (exclusion form).
Reuses the v12 engine chassis verbatim (copied alongside; only change = HALF count).
Simulation only. Public data + published signals only."""
import json, os, sys, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E

HERE = os.path.dirname(os.path.abspath(__file__))
FAM = os.path.join(HERE, '..')

ROADS = {'LONG': list(range(2016, 2026)), 'DECADE': list(range(2017, 2026)),
         'CONT': list(range(2019, 2026)), 'VAL': list(range(2023, 2026))}
FOLDS = {'FOLD_2016_2020': list(range(2016, 2021)), 'FOLD_2021_2025': list(range(2021, 2026))}
HALVES = {}  # filled per beating road only if confirmation triggers

def dist_stats(curve):
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
    return E.run_road(forms, 'Fra', 'broad', 'HALF', 'annual', False, seed=seed)

# Integrity gate: v12 published cell must reproduce exactly on this chassis.
chk, _, _, _ = E.run_road(ROADS['LONG'], 'Fra', 'broad', 'QUINTILE', 'annual', False)
print('INTEGRITY v12 Fra|broad|native|annual|QUINTILE LONG:', chk, '(expect 357.08)', flush=True)
assert chk == 357.08, 'chassis does not reproduce v12 published cell'

out = {'family': 'catalog-hxz-pension-funding', 'program': 'v13-best-rules',
       'spec': 'BEST-RULES-SPEC.md',
       'cell': 'Fra|broad|nofloor|annual|HALF',
       'integrity_check_v12_quintile_long': chk,
       'pool_sizes': {str(F): len(E.POOLS[('Fra', F, 'broad')]) for F in range(2016, 2026)},
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
            'distribution': dist_stats(curve),
            'curve': curve}
    (out['roads'] if name in ROADS else out['folds'])[name] = cell
    print(name, fin, 'maxdd', maxdd, 'spy', cell['spy_same_window'],
          'pb', cell['placebos_beaten'], '/20', flush=True)

with open(os.path.join(FAM, 'results.json'), 'w') as fh:
    json.dump(out, fh, indent=1)
print('saved results.json')
