#!/usr/bin/env python3
"""Build this folder's signals.json from the v12 published record
(read-only): identical Tbi values, with the BEST-RULES-SPEC measurability
band applied as universe eligibility — keep a firm-year only if
0 <= Tbi <= 2. Values themselves are never altered."""
import json, os
HERE = os.path.dirname(os.path.abspath(__file__)); FAM = os.path.join(HERE, '..')
SRC = os.path.join(FAM, '..', '..', 'v12-completions', 'catalog-hxz-taxable-income', 'signals.json')
src = json.load(open(SRC))
out = {'family': src['family'], 'signals': {}}
for name, s in src['signals'].items():
    pools = {}
    for F, pool in s['pools'].items():
        kept = {cik: v for cik, v in pool.items() if 0.0 <= v <= 2.0}
        pools[F] = kept
        print(name, F, 'published', len(pool), '-> band-eligible', len(kept))
    out['signals'][name] = {'direction': s['direction'], 'pools': pools}
with open(os.path.join(FAM, 'signals.json'), 'w') as fh:
    json.dump(out, fh, indent=1)
print('saved signals.json')
