#!/usr/bin/env python3
"""Confirmation + diagnostics for champion-beating cells (frozen rule):
both DECADE folds (fresh $100, formations 2016-2020 and 2021-2025) must
beat SPY on their own windows, with the road placebo score >= 15/20
(already in results.json). Also prints the recurring picks of the top
cells (diagnostic only — no tuning). Appends to results.json."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_grid as G
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
R = json.load(open(os.path.join(HERE, '..', 'results.json')))
CH = {'LONGEST': 1415.62, 'DECADE': 667.35, 'CONT': 544.47, 'VAL': 288.05}
FOLDS = {'FOLD16_20': ('2016-01', '2020-12'), 'FOLD21_25': ('2021-01', '2025-12')}

winners = []
for sig, cells in R['signals'].items():
    for key, roads in cells.items():
        for road, r in roads.items():
            if r['final'] > CH[road]:
                winners.append((sig, key, road, r['final'], r['placebo_beaten']))
print('champion-beating cells:', len(winners))

def parse(key):
    parts = key.split('_')
    cad = int(parts[0][3:]); cnt = parts[1][1:]; book = parts[2]
    return cad, ('ALL' if cnt == 'ALL' else int(cnt)), book

conf = {}
for sig, key, road, fin, pb in winners:
    cad, cnt, book = parse(key)
    ck = f'{sig}|{key}'
    if ck not in conf:
        fc = {}
        for fold, (s, e) in FOLDS.items():
            r = G.run_cell(sig, cad, cnt, book, fold, s, e)
            if r: fc[fold] = {k: r[k] for k in ('final', 'placebo_beaten', 'spy_final_same_window', 'max_dd', 'costs')}
        conf[ck] = fc
    f1 = conf[ck].get('FOLD16_20', {}); f2 = conf[ck].get('FOLD21_25', {})
    ok = (f1.get('final', 0) > (f1.get('spy_final_same_window') or 1e9) and
          f2.get('final', 0) > (f2.get('spy_final_same_window') or 1e9) and pb >= 15)
    print(sig, key, road, fin, 'placebo', pb, '| folds:', f1.get('final'), 'vs spy', f1.get('spy_final_same_window'),
          '/', f2.get('final'), 'vs spy', f2.get('spy_final_same_window'), '| CONFIRMED' if ok else '| NOT confirmed')

R['confirmation'] = conf
R['confirmation_winners'] = [list(w) for w in winners]
json.dump(R, open(os.path.join(HERE, '..', 'results.json'), 'w'))
print('saved')

# diagnostics: recurring picks for the biggest cells
P = G.P
tick = P['tickers']
for sig, key in (('IntanSP', 'cad3_n5_native'), ('IntanCFP', 'cad3_n5_native'), ('IntanBM', 'cad1_n3_native')):
    cad, cnt, book = parse(key)
    from collections import Counter
    c = Counter()
    j = G.MIDX['2016-01']
    while j <= G.MIDX['2025-12']:
        picks, _ = G.picks_for(sig, G.MONTHS[j], cnt)
        if picks is not None:
            for f in picks: c[tick[f]] += 1
        j += cad
    print('PICKS', sig, key, c.most_common(12))
