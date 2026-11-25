#!/usr/bin/env python3
"""Post-process: fill spy_final_same_window in results.json.
The v12 data cache's px_SPY.json is a 0-byte file (v12's own results.json
has null SPY fields too; its RESULTS.md SPY figures came from the shared
v7 long-hold pxfull_SPY Yahoo payload). This script recomputes same-window
SPY (June-to-June, matching each road's hold window) from that payload.
VALIDATION: reproduces v12's five published same-window SPY finals to the
cent (DECADE 355.34, CONT 282.28, VAL 174.86, FOLD17-20 190.37,
FOLD21-25 186.66). Read-only on shared inputs; writes only results.json."""
import json, os
from datetime import datetime, timezone
HERE = os.path.dirname(os.path.abspath(__file__))
RESP = os.path.join(HERE, '..', 'results.json')
rows = json.load(open('/home/hatch/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json'))
r = rows['chart']['result'][0]
monthly = {}
for t, a in zip(r['timestamp'], r['indicators']['adjclose'][0]['adjclose']):
    if a is None: continue
    d = datetime.fromtimestamp(t, timezone.utc)
    monthly[f'{d.year:04d}-{d.month:02d}'] = a

ROADS = {  # road -> formation list (mirrors run_best.py)
    'LONG': list(range(2012, 2026)), 'DECADE': list(range(2017, 2026)),
    'CONT': list(range(2019, 2026)), 'VAL': list(range(2023, 2026)),
    'FOLD_2017_2020': list(range(2017, 2021)), 'FOLD_2021_2025': list(range(2021, 2026)),
}
for name in ['LONG', 'DECADE', 'CONT', 'VAL']:
    f = ROADS[name]; mid = len(f) // 2
    ROADS[name + '_H1'] = f[:mid]; ROADS[name + '_H2'] = f[mid:]

res = json.load(open(RESP))
for name, forms in ROADS.items():
    if name not in res['roads'] or 'final' not in res['roads'][name]: continue
    a = monthly[f'{forms[0]:04d}-06']; b = monthly[f'{forms[-1] + 1:04d}-06']
    res['roads'][name]['spy_final_same_window'] = round(100 * b / a, 2)
    print(name, res['roads'][name]['spy_final_same_window'])
res['spy_source'] = ('v7 long-hold pxfull_SPY.json (Yahoo adjclose, monthly last bar); '
                     'validated to the cent vs v12 published same-window SPY on all five overlapping windows')
with open(RESP, 'w') as fh: json.dump(res, fh, indent=1)
print('patched results.json')
