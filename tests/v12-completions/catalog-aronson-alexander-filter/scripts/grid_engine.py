#!/usr/bin/env python3
"""Second-Chance grid for slice-1 Aronson timers: cadence cells (daily native /
weekly / monthly rebalance sampling of the representative cell) + crypto
cross-run where mechanically applicable. Reads results.json representative."""
import json, os, sys, csv, datetime
import numpy as np
SLUG = sys.argv[1]
BASE = os.path.expanduser('~/workspace/stock-app/backtests/v12-completions')
FAM = os.path.join(BASE, SLUG)
res = json.load(open(os.path.join(FAM, 'results.json')))
rep = res['representative_cell_median']
curve = res['cells'][rep]['LONGEST_2015_2026']['curve']
# rebuild daily returns of SPY from curve dates via shared engine data
SPYJ = os.path.expanduser('~/workspace/stock-app/backtests/v6/rsi2-mean-reversion/px_SPY_long.json')
d = json.load(open(SPYJ))['chart']['result'][0]
ts = d['timestamp']; q = d['indicators']['quote'][0]
dates, C = [], []
for i, t in enumerate(ts):
    if q['close'][i] is None: continue
    dates.append(datetime.datetime.utcfromtimestamp(t).date()); C.append(q['close'][i])
C = np.array(C); N = len(C)
ret = np.zeros(N); ret[1:] = C[1:] / C[:-1] - 1

# recover representative daily positions by re-running the timer engine module
sys.path.insert(0, '/tmp/slice1')
import importlib.util
ENG = os.path.join(FAM, 'scripts', 'engine.py')
# timer_engine runs main only under __main__; import safely by exec of defs up to FAMILIES
src = open(ENG).read().split('ret = np.zeros')[0]
g = {'__name__': 'te_defs', 'sys': sys}
sys.argv = ['engine.py', SLUG]
exec(src, g)
pos = g['FAMILIES'][rep]

def run_cadence(pos, step_days):
    eq = 100.0; prev = 0.0; held = 0.0
    for i in range(1, N):
        if (i - 1) % step_days == 0: held = pos[i - 1]
        chg = abs(held - prev)
        if chg: eq -= eq * chg * 0.001
        eq *= (1 + held * ret[i]); prev = held
    return round(eq, 2)

def sma(x, n):
    out = np.full(len(x), np.nan)
    for i in range(len(x)):
        if i >= n - 1: out[i] = np.mean(x[i - n + 1:i + 1])
    return out
def cn(x, n):
    out = np.full(len(x), np.nan)
    for i in range(len(x)):
        if i < n - 1: continue
        w = x[i - n + 1:i + 1]; lo, hi = w.min(), w.max()
        out[i] = 100 * (x[i] - lo) / (hi - lo) if hi > lo else 50.0
    return out
def lma4(x):
    out = np.full(len(x), np.nan); w = np.array([1., 2., 3., 4.])
    for i in range(3, len(x)):
        seg = x[i - 3:i + 1]
        if not np.isnan(seg).any(): out[i] = float(np.dot(w, seg) / 10)
    return out

def coin_positions(close, kind, repname):
    n = len(close)
    if kind == 'alex':
        pct = float(repname.split('alex')[1]); pos = np.zeros(n); cur = 0.0; ex = close[0]
        for i in range(n):
            p = close[i]
            if cur >= 0:
                ex = max(ex, p)
                if p <= ex * (1 - pct / 100): cur = -1.0; ex = p
            if cur <= 0:
                if cur < 0:
                    ex = min(ex, p)
                    if p >= ex * (1 + pct / 100): cur = 1.0; ex = p
                elif p >= ex * (1 + pct / 100): cur = 1.0; ex = p
            pos[i] = cur
        return pos
    if kind == 'maband':
        sp = int(repname.split('ma')[1].split('b')[0]); w = float(repname.split('b')[-1])
        m = sma(close, sp); pos = np.zeros(n); cur = 0.0
        for i in range(n):
            if not np.isnan(m[i]):
                if close[i] > m[i] * (1 + w / 100): cur = 1.0
                elif close[i] < m[i] * (1 - w / 100): cur = -1.0
            pos[i] = cur
        return pos
    if kind == 'cn':
        parts = repname.split('|'); sp = int(parts[1][2:]); mode = parts[2]; hi = int(parts[3])
        s = lma4(cn(close, sp)); pos = np.zeros(n); cur = 0.0
        for i in range(n):
            v = s[i]
            if not np.isnan(v):
                if v >= hi: cur = -1.0 if mode == 'rev' else 1.0
                elif v <= 100 - hi: cur = 1.0 if mode == 'rev' else -1.0
            pos[i] = cur
        return pos
    return None

out = {'family': SLUG, 'representative': rep,
       'cadence_cells': {'daily_native': res['cells'][rep]['LONGEST_2015_2026']['final'],
                         'weekly_rebalance': run_cadence(pos, 5),
                         'monthly_rebalance': run_cadence(pos, 21)},
       'holdings_grid': 'NOT-APPLICABLE — single-asset index timer, no security selection',
       'universe_grid': 'NOT-APPLICABLE — native universe is the S&P 500 index itself'}
CRYPTO_OK = {'catalog-aronson-alexander-filter': 'alex', 'catalog-aronson-ma-bands': 'maband',
             'catalog-aronson-cn-extremes-index': 'cn'}
if SLUG in CRYPTO_OK:
    coins = {}
    for sym in ('BTC', 'ETH'):
        rows = list(csv.DictReader(open(os.path.expanduser(f'~/workspace/stock-app/backtests/v4/crypto-trend-data/{sym}-USD.csv'))))
        cl = np.array([float(r['close']) for r in rows]); ds = [r['date'] for r in rows]
        p = coin_positions(cl, CRYPTO_OK[SLUG], rep)
        r = np.zeros(len(cl)); r[1:] = cl[1:] / cl[:-1] - 1
        eq = 100.0; prev = 0.0
        for i in range(1, len(cl)):
            chg = abs(p[i - 1] - prev)
            if chg: eq -= eq * chg * 0.004
            eq *= (1 + p[i - 1] * r[i]); prev = p[i - 1]
        coins[sym] = {'final': round(eq, 2), 'buy_hold_final': round(100 * cl[-1] / cl[0], 2),
                      'window': f'{ds[0]}..{ds[-1]}', 'cost_note': '0.40%/unit position change (v4 retail range)'}
    out['crypto_cross_run'] = coins
else:
    reasons = {
        'catalog-aronson-cn-extremes-breadth': 'NOT-APPLICABLE — no NYSE advance/decline, up/down-volume or new-high/low series exists for a coin market.',
        'catalog-aronson-cn-extremes-debt': 'NOT-APPLICABLE — no debt-instrument yield series exists in crypto as published.',
        'catalog-aronson-cn-extremes-spreads': 'NOT-APPLICABLE — no Treasury/corporate yield spreads exist in crypto as published.',
        'catalog-aronson-cn-extremes-price-volume': 'NOT-APPLICABLE on program data — the program crypto cache (v4 BTC/ETH csv) carries no volume column, so OBV-class indicators cannot be computed honestly; wash-trading caveat would apply regardless.',
        'catalog-aronson-heiby-divergence': 'NOT-APPLICABLE on program data — companions used here are OBV (needs volume, absent from program crypto cache) and Treasury series (no coin analogue).'}
    out['crypto_cross_run'] = reasons.get(SLUG, 'NOT-APPLICABLE')
os.makedirs(os.path.join(FAM, 'grid'), exist_ok=True)
json.dump(out, open(os.path.join(FAM, 'grid', 'grid_results.json'), 'w'), indent=1)
print(json.dumps(out, indent=1)[:1200])
