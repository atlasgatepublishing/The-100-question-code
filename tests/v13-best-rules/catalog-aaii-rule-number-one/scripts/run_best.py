#!/usr/bin/env python3
"""V13 best-rules run for catalog-aaii-rule-number-one.
Spec: ../BEST-RULES-SPEC.md (frozen before this run).
One cell: screen criteria as published/constructed (v12), native rulebook
(NO floor), ANNUAL June formation, TOP-5 by published PEG rank, equal
weight, no intra-year re-equalization.
Comparator: the published form (native, annual, ALL passing) same engine.
Reuses the v12 engine code (copied to engine_base.py, paths repointed to
the read-only shared stacks). Simulation only."""
import json, os, sys, statistics
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FAM = os.path.join(HERE, '..')
sys.path.insert(0, HERE)
import engine_base as E

ROADS = {
    'LONGEST': list(range(2016, 2026)),
    'DECADE': list(range(2017, 2026)),
    'CONT': list(range(2019, 2026)),
    'VAL': list(range(2023, 2026)),
    'FOLD1': list(range(2016, 2021)),
    'FOLD2': list(range(2021, 2026)),
    'LONGEST_H1': list(range(2016, 2021)), 'LONGEST_H2': list(range(2021, 2026)),
    'DECADE_H1': list(range(2017, 2021)), 'DECADE_H2': list(range(2021, 2026)),
    'CONT_H1': list(range(2019, 2023)), 'CONT_H2': list(range(2023, 2026)),
    'VAL_H1': list(range(2023, 2025)), 'VAL_H2': list(range(2025, 2026)),
}
MAIN = ['LONGEST', 'DECADE', 'CONT', 'VAL']

def dist_stats(curve, step):
    vals = [100.0] + [v for _, v in curve]
    per = [vals[i] / vals[i - step] - 1 for i in range(step, len(vals), step)]
    if not per:
        return None
    los = 0; worst_run = 0
    for r in per:
        los = los + 1 if r <= 0 else 0
        worst_run = max(worst_run, los)
    peak = vals[0]; since = 0; longest = 0
    for v in vals[1:]:
        if v >= peak:
            peak = v; since = 0
        else:
            since += 1; longest = max(longest, since)
    return {'n_periods': len(per),
            'share_positive': round(float(np.mean([r > 0 for r in per])), 3),
            'median_pct': round(float(np.median(per)) * 100, 1),
            'best_pct': round(float(max(per)) * 100, 1),
            'worst_pct': round(float(min(per)) * 100, 1),
            'longest_losing_streak': int(worst_run),
            'longest_months_between_new_highs': int(longest),
            'mean_pct_secondary': round(float(np.mean(per)) * 100, 1),
            'period_pct': [round(r * 100, 1) for r in per]}

def run_cell(count, roads, placebos=False):
    out = {}
    for road in roads:
        forms = ROADS[road]
        r = E.run_road(forms, count, 'annual', False)
        cell = dict(r)
        cell['spy_same_window'] = E.spy_final(forms)
        cell['dist_annual'] = dist_stats(r['curve'], 12)
        cell['dist_monthly'] = dist_stats(r['curve'], 1)
        if placebos:
            beaten = 0
            finals = []
            for s in range(20):
                pr = E.run_road(forms, count, 'annual', False, seed=s + 1)
                finals.append(pr['final'])
                if r['final'] > pr['final']:
                    beaten += 1
            cell['placebos_beaten'] = beaten
            cell['placebo_finals'] = finals
        out[road] = cell
        print(f"count={count} {road}: final={cell['final']} spy={cell['spy_same_window']} "
              f"maxdd={cell['maxdd_pct']} costs={cell['costs']}"
              + (f" pb={cell['placebos_beaten']}/20" if placebos else ""), flush=True)
    return out

res = {'family': 'catalog-aaii-rule-number-one',
       'spec': 'BEST-RULES-SPEC.md (frozen before run)',
       'my_rules': {'rulebook': 'native (no floor)', 'cadence': 'annual June formation, no intra-year re-equalization',
                    'count': 5, 'rank': 'PEG ascending (published)'},
       'roads_note': 'Stack prices begin 2016-01; LONG 2010 not supportable. LONGEST=formations 2016-2025, DECADE=2017-2025, CONT=2019-2025, VAL=2023-2025 (v12 road definitions). First non-empty pool 2019.',
       'pool_sizes': {str(k): len(v) for k, v in E.POOLS.items()},
       'my_rules_results': run_cell(5, MAIN + ['FOLD1', 'FOLD2', 'LONGEST_H1', 'LONGEST_H2',
                                               'DECADE_H1', 'DECADE_H2', 'CONT_H1', 'CONT_H2',
                                               'VAL_H1', 'VAL_H2'], placebos=True),
       'published_form_results': run_cell('ALL', MAIN)}
json.dump(res, open(os.path.join(FAM, 'results.json'), 'w'), indent=1)
print('saved results.json; pools:', res['pool_sizes'])
