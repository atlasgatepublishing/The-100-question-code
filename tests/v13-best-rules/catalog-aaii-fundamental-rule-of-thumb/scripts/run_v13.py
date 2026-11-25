#!/usr/bin/env python3
"""V13 best-rules run — catalog-aaii-fundamental-rule-of-thumb.
Frozen cell (BEST-RULES-SPEC.md): native universe, native rulebook (no
floor), ANNUAL June formation, top-10 by published score, equal weight,
program tiered costs, vanished->ZERO, 20-seed placebos sharing the chassis.
Reuses the v12 chassis engine (engine_base.py, copied read-only logic);
the only path correction is SYF -> the v12 shareholder-yield frames tree
(dividend data), identical data to the v12 run. Simulation only."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine_base as E

# dividend frames live in the v12 tree (v13 sibling folder has no data/)
E.SYF = os.path.expanduser(
    '~/workspace/stock-app/backtests/v12-completions/shareholder-yield/data/frames')
E.MAT.clear()

E.ROADS.update({
    'LONG_H1': ('2016-06', '2021-06'), 'LONG_H2': ('2021-06', '2026-06'),
    'DECADE_H1': ('2017-06', '2022-06'), 'DECADE_H2': ('2022-06', '2026-06'),
    'CONT_H1': ('2019-06', '2023-06'), 'CONT_H2': ('2023-06', '2026-06'),
    'VAL_H1': ('2023-06', '2025-06'), 'VAL_H2': ('2025-06', '2026-06'),
})

fn, native_count = E.SCREENS['fundamental-rule-of-thumb']
ROADS = ['LONGEST', 'DECADE', 'CONT', 'VAL', 'FOLD1', 'FOLD2',
         'LONG_H1', 'LONG_H2', 'DECADE_H1', 'DECADE_H2',
         'CONT_H1', 'CONT_H2', 'VAL_H1', 'VAL_H2']
# engine road keys: LONGEST is the chassis LONG analog (Jun 2016->2026)
out = {}
for road in ROADS:
    r = E.run_cell(fn, 'native', 'native', 'annual', 10, road, native_count)
    out[road] = r
    print(road, r['final'], 'spy', r['spy_same_window'], 'pb',
          r['placebos_beaten'], 'dd', r['max_dd'], 'costs', r['costs'], flush=True)

pools = {}
for y in range(2016, 2026):
    F = E.features(f'{y:04d}-06')
    mask, _ = fn(F, 'native')
    pools[str(y)] = int(mask.sum())

res = {'family': 'catalog-aaii-fundamental-rule-of-thumb',
       'spec': 'native universe | no floor | annual June | top-10 by published score',
       'pool_sizes_june_native': pools, 'roads': out}
dest = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'results.json')
json.dump(res, open(dest, 'w'), indent=1)
print('saved', dest)
