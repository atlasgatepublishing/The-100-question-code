#!/usr/bin/env python3
"""V13 best-rules run: Baltussen bond-return ensemble, TLT vehicle.
Construction EXACTLY as v12 (4 signals, 120m z-scores, clip [-1,1],
weight=(mean+1)/2). Chassis per BEST-RULES-SPEC.md: vehicle TLT (trend leg
on TLT), monthly, no floor, 0.10%/side on turnover, remainder BIL.
Data plumbing replicated from v12 engine_common/engine_run_taa (read-only
shared inputs): monthly panel + px_*.json from the slice4 agent dir,
FRED yields from the aronson v12 data folder.
"""
import sys, json, os, glob
import numpy as np, pandas as pd

SLICE4 = '/home/hatch/workspace/agents/526b6a1f-f20e-4d45-a8b9-3239338684f9/slice4'
FRED_DIR = '/home/hatch/workspace/stock-app/backtests/v12-completions/catalog-aronson-cn-extremes-debt/data'
OUT = os.path.expanduser('~/workspace/stock-app/backtests/v13-best-rules/catalog-taa-baltussen-predicting-bond-returns')
COST = 0.001
ROADS = {'LONG': ('2010-01-01', '2026-10-31'), 'DECADE': ('2016-01-01', '2026-10-31'),
         'CONT': ('2019-01-01', '2026-10-31'), 'VAL': ('2023-01-01', '2026-10-31')}

def monthly_prices():
    piv = pd.read_csv(f'{SLICE4}/monthly_parquet.csv', index_col=0, parse_dates=True)
    piv.index = piv.index.to_period('M').to_timestamp('M')
    out = {c: piv[c].dropna() for c in piv.columns}
    for f in glob.glob(f'{SLICE4}/px_*.json'):
        t = os.path.basename(f)[3:-5]
        bars = json.load(open(f))
        s = pd.Series({pd.Timestamp(d): v for d, v in bars})
        m = s.resample('M').last().dropna()
        m.index = m.index.to_period('M').to_timestamp('M')
        out[t] = m.combine_first(out[t]) if t in out else m
    return out

def fred_monthly(name):
    d = pd.read_csv(f'{FRED_DIR}/{name}.csv', parse_dates=[0]); d.columns = ['date', 'v']
    d = d.set_index('date')['v']; m = d.resample('M').last()
    m.index = m.index.to_period('M').to_timestamp('M'); return m

P = monthly_prices()
D10 = fred_monthly('DGS10'); D3 = fred_monthly('DGS3MO')

def cash_ret():
    r = P['BIL'].pct_change()
    y = fred_monthly('DGS3MO') / 100 / 12
    return r.combine_first(y)
CR = cash_ret()

def ret(t, tk, m):
    s = P[tk]
    if t not in s.index: return None
    idx = s.index.get_loc(t)
    if idx < m: return None
    return s.iloc[idx] / s.iloc[idx - m] - 1

def _z(series, t, minp=120):
    series = series.dropna()
    if t not in series.index: return None
    i = series.index.get_loc(t)
    if i < minp: return None
    h = series.iloc[i - minp:i]; sd = h.std()
    if sd == 0 or np.isnan(sd): return None
    return (series.iloc[i] - h.mean()) / sd

def baltussen(t, vehicle):
    spread = (D10 - D3)
    z1 = _z(spread, t)
    if z1 is None: return {}
    z1 = float(np.clip(z1, -1, 1))
    e12 = ret(t, vehicle, 12); b12 = ret(t, 'BIL', 12)
    if e12 is None or b12 is None: return {}
    s2 = 1.0 if e12 - b12 > 0 else -1.0
    spy = P['SPY']; bil = P['BIL']
    common = spy.index.intersection(bil.index)
    ex = (spy.reindex(common) / spy.reindex(common).shift(12) - 1) - (bil.reindex(common) / bil.reindex(common).shift(12) - 1)
    z3 = _z(ex, t)
    z4 = _z(P['DBC'].pct_change(12), t)
    if z3 is None or z4 is None: return {}
    avg = np.mean([z1, s2, float(np.clip(-z3, -1, 1)), float(np.clip(-z4, -1, 1))])
    w = float((avg + 1) / 2)
    return {vehicle: w} if w > 0.01 else {}

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
    start, end = ROADS[road]; start = pd.Timestamp(start); end = pd.Timestamp(end)
    idx = P['SPY'].index; idx = idx[(idx >= start) & (idx <= end)]
    rng = np.random.default_rng(placebo_seed) if placebo_seed is not None else None
    eq = 100.0; curve = {}; weights = {}; total_cost = 0.0
    months = list(idx)
    for i, t in enumerate(months):
        curve[t] = eq
        if i == len(months) - 1: break
        t1 = months[i + 1]
        if rng is not None:
            new_w = {'TLT': float(rng.uniform(0, 1))}
        else:
            new_w = signal_fn(t)
            new_w = {k: float(v) for k, v in new_w.items() if abs(v) > 1e-9}
        allk = set(weights) | set(new_w)
        turn = sum(abs(new_w.get(k, 0) - weights.get(k, 0)) for k in allk)
        c = eq * turn * COST; total_cost += c; eq -= c
        crv = CR.get(t1, 0.0) if t1 in CR.index else 0.0
        if crv is None or pd.isna(crv): crv = 0.0
        r = (1 - sum(new_w.values())) * crv
        for k, w in new_w.items():
            s = P[k]
            if t in s.index and t1 in s.index: r += w * (s[t1] / s[t] - 1)
            else: r += w * crv
        eq *= (1 + r); weights = new_w
    return pd.Series(curve), total_cost

def buyhold(tk, road):
    start, end = ROADS[road]
    s = P[tk]; s = s[(s.index >= start) & (s.index <= end)]
    eq = 100 * s / s.iloc[0]
    return eq

def main():
    out = {'roads': {}, 'benchmarks': {}, 'placebos': {}, 'published_v12': {'LONG': 125.18, 'DECADE': 125.67, 'CONT': 120.98, 'VAL': 113.05}}
    fn = lambda t: baltussen(t, 'TLT')
    fn_ief = lambda t: baltussen(t, 'IEF')
    for road in ROADS:
        eq, cost = simulate(fn, road)
        out['roads'][road] = {'final': round(float(eq.iloc[-1]), 2), 'cost': round(cost, 2),
                              'stats': period_stats(eq),
                              'curve': {str(k.date()): round(float(v), 4) for k, v in eq.items()}}
        eqi, _ = simulate(fn_ief, road)
        out['roads'][road + '_ief_replication'] = {'final': round(float(eqi.iloc[-1]), 2), 'stats': period_stats(eqi)}
        bh = {}
        for tk in ('IEF', 'TLT', 'SPY'):
            e = buyhold(tk, road)
            bh[tk] = {'final': round(float(e.iloc[-1]), 2), 'stats': period_stats(e)}
        out['benchmarks'][road] = bh
        print(road, 'TLT-dial', out['roads'][road]['final'], 'IEF-repl', out['roads'][road + '_ief_replication']['final'],
              'BH-TLT', bh['TLT']['final'], 'BH-IEF', bh['IEF']['final'], 'BH-SPY', bh['SPY']['final'], flush=True)
    for road in ('LONG', 'CONT'):
        beats = 0; finals = []
        for seed in range(20):
            eqp, _ = simulate(fn, road, placebo_seed=seed)
            finals.append(float(eqp.iloc[-1]))
            if out['roads'][road]['final'] > finals[-1]: beats += 1
        out['placebos'][road] = {'beats': beats, 'median_placebo': round(float(np.median(finals)), 2),
                                 'finals': [round(x, 2) for x in finals]}
        print('placebo', road, beats, '/20 median', out['placebos'][road]['median_placebo'], flush=True)
    json.dump(out, open(f'{OUT}/results.json', 'w'), indent=1)
    print('DONE')

if __name__ == '__main__':
    main()
