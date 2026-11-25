#!/usr/bin/env python3
"""
V13 BEST-RULES — Accelerating Dual Momentum. Spec: BEST-RULES-SPEC.md (frozen before this run).
Monthly chassis identical in semantics to the v12 engine (engine_common.simulate):
month-end total-return (adjclose) prices, signal at month-end t applied to t->t+1,
cost 0.10% of turnover, $100 pots, cash residue earns BIL monthly return.
MY RULES: published ADM construction EXACTLY (SPY/SCZ score = avg of 1/3/6m returns;
winner 100% if score>0) EXCEPT the defensive leg holds TLT/TIP 50/50 instead of the
published 1-month-return winner-pick. NO floor.
COMPARATORS in-engine: published form, buy-hold SPY, static 60/40 (SPY/TLT monthly rebal).
Placebos: 20 seeds, random monthly allocations over {SPY,SCZ,TLT,TIP}, LONG & CONT.
Data: shared read-only Yahoo cache (SPY/TLT/TIP/BIL) from
v12-completions/catalog-taa-keller-faa/data_etf_cache/ + SCZ.json fetched fresh
from Yahoo into this folder (same chart format, adjclose = total return).
"""
import json, os
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/catalog-taa-keller-faa/data_etf_cache")
COST = 0.001
START = 100.0
ROADS = {'LONG': ('2010-01-01', '2026-10-31'), 'DECADE': ('2016-01-01', '2026-10-31'),
         'CONT': ('2019-01-01', '2026-10-31'), 'VAL': ('2023-01-01', '2026-10-31')}
ASSETS = ['SPY', 'SCZ', 'TLT', 'TIP']

def load_monthly(t):
    path = os.path.join(HERE, f'{t}.json') if t == 'SCZ' else os.path.join(CACHE, f'{t}.json')
    with open(path) as f:
        data = json.load(f)
    res = data['chart']['result'][0]
    ts = res['timestamp']
    adj = res['indicators']['adjclose'][0]['adjclose']
    s = pd.Series({pd.Timestamp.utcfromtimestamp(x).normalize(): v for x, v in zip(ts, adj) if v})
    m = s.resample('M').last().dropna()
    m.index = m.index.to_period('M').to_timestamp('M')
    return m

P = {t: load_monthly(t) for t in ASSETS + ['BIL']}
CR = P['BIL'].pct_change()  # cash residue return

def ret(t, tk, m):
    s = P[tk]
    if t not in s.index: return None
    i = s.index.get_loc(t)
    if i < m: return None
    return float(s.iloc[i] / s.iloc[i - m] - 1)

def avg_ret(t, tk, months):
    vals = [ret(t, tk, m) for m in months]
    if any(v is None for v in vals): return None
    return float(np.mean(vals))

def adm_published(t):
    a, b = avg_ret(t, 'SPY', [1, 3, 6]), avg_ret(t, 'SCZ', [1, 3, 6])
    if a is None or b is None: return {}
    if max(a, b) <= 0:
        r1 = {k: ret(t, k, 1) for k in ('TLT', 'TIP')}
        if any(v is None for v in r1.values()): return {'TLT': 1.0}
        return {max(r1, key=r1.get): 1.0}
    return {'SPY': 1.0} if a >= b else {'SCZ': 1.0}

def adm_mine(t):
    a, b = avg_ret(t, 'SPY', [1, 3, 6]), avg_ret(t, 'SCZ', [1, 3, 6])
    if a is None or b is None: return {}
    if max(a, b) <= 0:
        return {'TLT': 0.5, 'TIP': 0.5}
    return {'SPY': 1.0} if a >= b else {'SCZ': 1.0}

def hold_spy(t): return {'SPY': 1.0}
def mix_6040(t): return {'SPY': 0.6, 'TLT': 0.4}

def period_stats(eq):
    r = eq.pct_change().dropna()
    if len(r) == 0: return {}
    ls = cur = 0
    for x in r:
        cur = cur + 1 if x <= 0 else 0; ls = max(ls, cur)
    run_max = eq.cummax(); below = (eq < run_max - 1e-9)
    lb = cur = 0
    for x in below:
        cur = cur + 1 if x else 0; lb = max(lb, cur)
    dd = (eq / run_max - 1).min()
    return {'n_periods': int(len(r)), 'share_positive': round(float((r > 0).mean()), 3),
            'median_period': round(float(r.median()), 4), 'mean_period_secondary': round(float(r.mean()), 4),
            'best': round(float(r.max()), 4), 'worst': round(float(r.min()), 4),
            'longest_losing_streak': int(ls), 'longest_below_high_months': int(lb),
            'max_dd': round(float(dd), 4)}

def simulate(signal_fn, road, placebo_seed=None):
    start, end = ROADS[road]
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    idx = P['SPY'].index
    months = list(idx[(idx >= start) & (idx <= end)])
    rng = np.random.default_rng(placebo_seed) if placebo_seed is not None else None
    eq, curve, weights, total_cost = START, {}, {}, 0.0
    for i, t in enumerate(months):
        curve[t] = eq
        if i == len(months) - 1: break
        t1 = months[i + 1]
        if rng is not None:
            k = int(rng.integers(1, len(ASSETS) + 1))
            pick = rng.choice(ASSETS, size=k, replace=False)
            w = rng.dirichlet(np.ones(k))
            new_w = {a: float(x) for a, x in zip(pick, w)}
        else:
            new_w = {k: float(v) for k, v in signal_fn(t).items() if abs(v) > 1e-9}
        allk = set(weights) | set(new_w)
        turn = sum(abs(new_w.get(k, 0) - weights.get(k, 0)) for k in allk)
        c = eq * turn * COST; total_cost += c; eq -= c
        crv = CR.get(t1, 0.0)
        if crv is None or pd.isna(crv): crv = 0.0
        r = (1 - sum(new_w.values())) * crv
        for k, w in new_w.items():
            s = P[k]
            r += w * (s[t1] / s[t] - 1) if (t in s.index and t1 in s.index) else w * crv
        eq *= (1 + r); weights = new_w
    return pd.Series(curve), total_cost

def pack(eq, cost):
    return {'final': round(float(eq.iloc[-1]), 2), 'cost': round(float(cost), 2),
            'stats': period_stats(eq),
            'curve': {str(k.date()): round(float(v), 4) for k, v in eq.items()}}

def main():
    out = {'roads': {}, 'placebos': {}, 'comparators': {}}
    fns = {'mine': adm_mine, 'published': adm_published, 'spy_hold': hold_spy, 'mix_6040': mix_6040}
    for road in ROADS:
        out['roads'][road] = {}
        for name, fn in fns.items():
            eq, cost = simulate(fn, road)
            out['roads'][road][name] = pack(eq, cost)
        print(road, {n: out['roads'][road][n]['final'] for n in fns},
              'mine DD', out['roads'][road]['mine']['stats']['max_dd'],
              'pub DD', out['roads'][road]['published']['stats']['max_dd'], flush=True)
    for road in ('LONG', 'CONT'):
        finals, beats = [], 0
        for seed in range(20):
            eqp, _ = simulate(None, road, placebo_seed=seed)
            finals.append(round(float(eqp.iloc[-1]), 2))
            if out['roads'][road]['mine']['final'] > finals[-1]: beats += 1
        out['placebos'][road] = {'beats_mine': beats, 'median_placebo': round(float(np.median(finals)), 2),
                                 'finals': finals}
        print('placebos', road, out['placebos'][road], flush=True)
    json.dump(out, open(os.path.join(HERE, 'results.json'), 'w'), indent=1)
    print('DONE')

if __name__ == '__main__':
    main()
