#!/usr/bin/env python3
"""Probe: largest Feb->Feb adjusted-price returns in the placebo pool,
to check whether bimodal placebo finals are real names or data artifacts."""
import importlib.util, sys, os
spec = importlib.util.spec_from_file_location('eng', os.path.join(os.path.dirname(__file__), 'engine.py'))
e = importlib.util.module_from_spec(spec); sys.modules['eng'] = e
spec.loader.exec_module(e)
for F in range(2019, 2027):
    end = '2026-11' if F == 2026 else f'{F + 1:04d}-02'
    rets = []
    for cik in e.FORM[F]['all']:
        a = e.price_series(cik, [f'{F:04d}-02'])[0]
        b = e.price_series(cik, [end])[0]
        if a and a == a and a > 0 and b == b:
            rets.append((b / a - 1, e.cand[cik]['ticker'], e.IND[cik], cik in set(e.FORM[F]['eligible'])))
    rets.sort(reverse=True)
    print(F, [(t, round(r * 100), ind, 'ELIG' if el else '') for r, t, ind, el in rets[:4]])
