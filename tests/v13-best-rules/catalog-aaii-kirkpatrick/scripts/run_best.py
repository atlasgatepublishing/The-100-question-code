#!/usr/bin/env python3
"""V13 best-rules run for catalog-aaii-kirkpatrick.
Spec: ../BEST-RULES-SPEC.md (frozen before this run).
One cell: Kirkpatrick Bargain, native universe, native rulebook (NO floor),
quarterly formation, top-3 by published RS-ratio ranking, equal weight.
Comparator: the published form (native, monthly, ALL passing) same engine.
Reuses the v12 engine read-only. Simulation only."""
import json, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FAM = os.path.join(HERE, '..')
sys.path.insert(0, os.path.join(FAM, '..', '..', 'v12-completions',
                                'catalog-aaii-kirkpatrick', 'scripts'))
import engine as E

# extra roads: folds already in E.ROADS; add half-windows
E.ROADS.update({
    'DECADE_H1': ('2017-06', '2021-09'), 'DECADE_H2': ('2021-09', '2026-06'),
    'CONT_H1': ('2019-06', '2022-09'), 'CONT_H2': ('2022-09', '2026-06'),
    'VAL_H1': ('2023-06', '2024-12'), 'VAL_H2': ('2024-12', '2026-06'),
})

fn, native_count = E.SCREENS['kirkpatrick-bargain']

def dist_stats(curve, step):
    """Per-period distribution from a monthly equity curve (list of [ym, v])."""
    vals = [100.0] + [v for _, v in curve]
    per = [vals[i] / vals[i - step] - 1 for i in range(step, len(vals), step)]
    if not per:
        return None
    los = 0; worst_run = 0
    for r in per:
        los = los + 1 if r <= 0 else 0
        worst_run = max(worst_run, los)
    peak = vals[0]; since_high = 0; longest = 0
    for v in vals[1:]:
        if v >= peak:
            peak = v; since_high = 0
        else:
            since_high += 1; longest = max(longest, since_high)
    return {'n_periods': len(per),
            'share_positive': round(float(np.mean([r > 0 for r in per])), 3),
            'median': round(float(np.median(per)), 4),
            'best': round(float(max(per)), 4), 'worst': round(float(min(per)), 4),
            'longest_losing_streak': int(worst_run),
            'longest_months_between_new_highs': int(longest),
            'mean_secondary': round(float(np.mean(per)), 4)}

def run(uni, rb, cad, count, roads):
    out = {}
    for road in roads:
        c = E.run_cell(fn, uni, rb, cad, count, road, native_count)
        if c is None:
            out[road] = None; continue
        c = dict(c)
        c['dist_quarterly'] = dist_stats(c['curve'], 3)
        c['dist_monthly'] = dist_stats(c['curve'], 1)
        c['dist_annual'] = dist_stats(c['curve'], 12)
        out[road] = c
        print(f'{uni}|{rb}|{cad}|{count} {road}: final={c["final"]} '
              f'spy={c["spy_same_window"]} pb={c["placebos_beaten"]}/20 '
              f'maxdd={c["max_dd"]} costs={c["costs"]}', flush=True)
    return out

MAIN = ['LONGEST', 'DECADE', 'CONT', 'VAL']
res = {'family': 'catalog-aaii-kirkpatrick', 'screen': 'kirkpatrick-bargain',
       'spec': 'BEST-RULES-SPEC.md (frozen before run)',
       'my_rules': {'universe': 'native', 'rulebook': 'native (no floor)',
                    'cadence': 'quarterly', 'count': 3},
       'roads_note': 'Stack prices begin 2016-01; LONG 2010 not supportable. '
                     'LONGEST=Jun2016->Jun2026 formations, DECADE=2017->, '
                     'CONT=2019->, VAL=2023-> (v12 road definitions).',
       'my_rules_results': run('native', 'native', 'quarterly', 3,
                               MAIN + ['FOLD1', 'FOLD2', 'DECADE_H1', 'DECADE_H2',
                                       'CONT_H1', 'CONT_H2', 'VAL_H1', 'VAL_H2']),
       'published_form_results': run('native', 'native', 'monthly', 'ALL', MAIN)}
pools = {}
for y in range(2016, 2026):
    F = E.features(f'{y:04d}-06')
    mask, _ = fn(F, 'native')
    pools[str(y)] = int(mask.sum())
res['pool_sizes_june_native'] = pools
json.dump(res, open(os.path.join(FAM, 'results.json'), 'w'), indent=1)
print('saved results.json; pools:', pools)
