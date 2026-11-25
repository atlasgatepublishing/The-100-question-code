#!/usr/bin/env python3
"""V13 best-rules run — catalog-aronson-heiby-divergence.
Frozen spec: BEST-RULES-SPEC.md (2026-11-22, before this run).
Design: divergence as VETO. Default long SPY; exit to cash when
div = CN91(SPY) - CN91(cumOBV) <= -50 (Heiby documented 75/25 gap);
re-enter when div > -50. Long/cash only, no short, no floor.
CN = channel-normalized position in 91d range, 4-day LMA smoothing
(published construction, inherited from v12 engine).
Position decided day i-1 applies to ret[i]; cost 0.10% per unit change.
Placebos: 20 circular phase-shifts of position series (v12 chassis seeds).
Data: program cache pxfull_SPY.json (2008->2026, OHLCV). Simulation only."""
import json, os, random, datetime
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FAM = os.path.dirname(HERE)
SPYJ = os.path.expanduser('~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json')

d = json.load(open(SPYJ))['chart']['result'][0]
ts = d['timestamp']; q = d['indicators']['quote'][0]
dates, C, V = [], [], []
for i, t in enumerate(ts):
    if q['close'][i] is None: continue
    dates.append(datetime.datetime.utcfromtimestamp(t).date())
    C.append(q['close'][i]); V.append(q['volume'][i] or 0)
C = np.array(C, dtype=float); V = np.array(V, dtype=float)
N = len(C)

def cn(x, n):
    out = np.full(len(x), np.nan)
    for i in range(len(x)):
        if i < n - 1: continue
        w = x[i - n + 1:i + 1]; w = w[~np.isnan(w)]
        if len(w) < n // 2: continue
        lo, hi = w.min(), w.max()
        out[i] = 100.0 * (x[i] - lo) / (hi - lo) if hi > lo else 50.0
    return out

def lma4(x):
    out = np.full(len(x), np.nan); w = np.array([1., 2., 3., 4.])
    for i in range(3, len(x)):
        seg = x[i - 3:i + 1]
        if np.isnan(seg).any(): continue
        out[i] = float(np.dot(w, seg) / 10.0)
    return out

obv = np.cumsum(np.sign(np.diff(C, prepend=C[0])) * V)
div = lma4(cn(C, 91)) - lma4(cn(obv, 91))

# veto gate: long unless div <= -50 (stateful only via current div value)
pos = np.ones(N)
for i in range(N):
    if not np.isnan(div[i]) and div[i] <= -50.0:
        pos[i] = 0.0

ret = np.zeros(N); ret[1:] = C[1:] / C[:-1] - 1

def road_idx(a, b):
    i0 = next(i for i, dt in enumerate(dates) if dt >= datetime.date.fromisoformat(a))
    i1 = max(i for i, dt in enumerate(dates) if dt <= datetime.date.fromisoformat(b))
    return i0, i1

def run(p, i0, i1):
    pp = p[i0:i1]; r = ret[i0 + 1:i1 + 1]
    chg = np.abs(np.diff(np.concatenate(([0.0], pp))))
    factors = (1 - 0.001 * chg) * (1 + pp * r)
    eqv = 100.0 * np.cumprod(factors)
    curve = [[str(dates[i0]), 100.0]] + [[str(dates[i0 + 1 + k]), round(float(v), 2)] for k, v in enumerate(eqv)]
    costs = 0.0; eq = 100.0
    for f, c in zip(factors, chg):
        costs += eq * 0.001 * c; eq *= f
    peak = 100.0; mdd = 0.0
    for v in eqv:
        peak = max(peak, float(v)); mdd = max(mdd, 1 - float(v) / peak)
    n_trades = int(sum(1 for c in chg if c > 0))
    return {'final': round(float(eqv[-1]), 2), 'costs': round(costs, 2), 'max_dd': round(mdd, 4),
            'n_position_changes': n_trades, 'long_share': round(float(np.mean(pp)), 3), 'curve': curve}

def spy_final(i0, i1): return round(100 * C[i1] / C[i0], 2)

def period_stats(curve):
    months = {}
    for ds, v in curve: months[ds[:7]] = v
    ks = sorted(months); vals = [months[k] for k in ks]
    rets = [vals[i] / vals[i - 1] - 1 for i in range(1, len(vals)) if vals[i - 1] > 0]
    if not rets: return {}
    los = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0; los = max(los, cur)
    peak = -1; since = 0; longest = 0
    for v in vals:
        if v >= peak: peak = v; since = 0
        else: since += 1; longest = max(longest, since)
    return {'n_months': len(rets), 'share_positive': round(sum(1 for r in rets if r > 0) / len(rets), 3),
            'median_month_pct': round(100 * float(np.median(rets)), 2),
            'best_month_pct': round(100 * max(rets), 2), 'worst_month_pct': round(100 * min(rets), 2),
            'longest_losing_streak_months': los, 'longest_between_highs_months': longest,
            'avg_month_pct_secondary': round(100 * float(np.mean(rets)), 2)}

def halves(a, b):
    i0, i1 = road_idx(a, b); mid = dates[i0] + (dates[i1] - dates[i0]) / 2
    return (a, str(mid)), (str(mid + datetime.timedelta(days=1)), b)

ROADS = {
    'LONG':   ('2010-01-04', '2026-11-20'),
    'DECADE': ('2016-11-21', '2026-11-20'),
    'CONT':   ('2019-01-02', '2026-11-20'),
    'VAL':    ('2023-01-03', '2026-11-20'),
    # v12 windows for published-form comparison
    'V12_LONGEST': ('2015-06-01', '2026-11-20'),
    'V12_DECADE':  ('2016-01-01', '2026-11-20'),
    'V12_CONT':    ('2019-01-01', '2026-11-20'),
    'V12_VAL':     ('2023-01-01', '2026-11-20'),
}

out = {'family': 'catalog-aronson-heiby-divergence', 'spec': 'BEST-RULES-SPEC.md (frozen 2026-11-22)',
       'cell': 'SPY long/cash veto | companion cumOBV | CN91 + LMA4 | exit div<=-50, re-enter div>-50 | no short | no floor | daily | cost 0.10%/unit change',
       'roads': {}}

for name, (a, b) in ROADS.items():
    i0, i1 = road_idx(a, b)
    res = run(pos, i0, i1)
    twins = []
    for s in range(1, 21):
        rng = random.Random(777 + s)
        off = rng.randint(60, N - 60)
        tf = run(np.roll(pos, off), i0, i1)['final']
        twins.append(tf)
    # folds (split by calendar years at midpoint year boundary) + half-windows
    yrs = list(range(dates[i0].year, dates[i1].year + 1))
    midyr = yrs[len(yrs) // 2]
    fold1 = run(pos, *road_idx(a, f'{midyr - 1}-12-31')) if midyr - 1 >= dates[i0].year else None
    fold2 = run(pos, *road_idx(f'{midyr}-01-01', b))
    (h1a, h1b), (h2a, h2b) = halves(a, b)
    hf1 = run(pos, *road_idx(h1a, h1b)); hf2 = run(pos, *road_idx(h2a, h2b))
    def slim(r, aa, bb):
        if r is None: return None
        j0, j1 = road_idx(aa, bb)
        return {'final': r['final'], 'max_dd': r['max_dd'], 'spy_same_window': spy_final(j0, j1)}
    entry = {'final': res['final'], 'costs': res['costs'], 'max_dd': res['max_dd'],
             'n_position_changes': res['n_position_changes'], 'long_share': res['long_share'],
             'spy_same_window': spy_final(i0, i1),
             'placebo_finals': twins, 'placebos_beaten': sum(1 for t in twins if res['final'] > t),
             'distribution_monthly': period_stats(res['curve']),
             'fold_first_years': slim(fold1, a, f'{midyr - 1}-12-31'),
             'fold_second_years': slim(fold2, f'{midyr}-01-01', b),
             'half1': slim(hf1, h1a, h1b), 'half2': slim(hf2, h2a, h2b),
             'curve': res['curve']}
    out['roads'][name] = entry
    print(name, res['final'], 'dd', res['max_dd'], 'pb', entry['placebos_beaten'], 'longshare', res['long_share'], 'changes', res['n_position_changes'], flush=True)

json.dump(out, open(os.path.join(FAM, 'results.json'), 'w'), indent=1)
print('DONE')
