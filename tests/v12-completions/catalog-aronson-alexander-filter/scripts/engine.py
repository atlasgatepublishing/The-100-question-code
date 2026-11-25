#!/usr/bin/env python3
"""Slice-1 Aronson timer engine. Usage: engine.py <family-slug>
Frozen by each family's SPEC-FROZEN.md / CONSTRUCTION-SPEC.md before runs.
Native: long/short always-in S&P500 (SPY) timer, signal on input series,
position applied next day, cost 0.10% per unit position change.
House (v9): short->cash; -15% floor from road start, 90-day cash halt, one restart.
Placebos: 20 circular phase-shifts of the position series.
Representative cell = MEDIAN final across the frozen parameter grid (anti-cherry-pick).
Simulation only."""
import json, os, sys, math, random, csv, datetime
import numpy as np

SLUG = sys.argv[1]
BASE = os.path.expanduser('~/workspace/stock-app/backtests/v12-completions')
FAM = os.path.join(BASE, SLUG)
SPYJ = os.path.expanduser('~/workspace/stock-app/backtests/v6/rsi2-mean-reversion/px_SPY_long.json')

# ---------- SPY daily ----------
d = json.load(open(SPYJ))['chart']['result'][0]
ts = d['timestamp']; q = d['indicators']['quote'][0]
dates, O, H, L, C, V = [], [], [], [], [], []
for i, t in enumerate(ts):
    if q['close'][i] is None: continue
    dates.append(datetime.datetime.utcfromtimestamp(t).date())
    O.append(q['open'][i]); H.append(q['high'][i]); L.append(q['low'][i]); C.append(q['close'][i]); V.append(q['volume'][i] or 0)
C = np.array(C); H = np.array(H); L = np.array(L); V = np.array(V, dtype=float)
N = len(C)
didx = {dt: i for i, dt in enumerate(dates)}

def load_yield(name):
    p = os.path.join(FAM, 'data', name + '.csv')
    out = {}
    for row in csv.DictReader(open(p)):
        try: out[datetime.date.fromisoformat(row['observation_date'])] = float(row[name])
        except Exception: pass
    s = np.full(N, np.nan)
    last = np.nan
    for i, dt in enumerate(dates):
        if dt in out: last = out[dt]
        s[i] = last
    return s

def sma(x, n):
    out = np.full(len(x), np.nan); cs = np.nancumsum(np.where(np.isnan(x), 0, x))
    cnt = np.cumsum(~np.isnan(x))
    for i in range(len(x)):
        j = i - n
        s = cs[i] - (cs[j] if j >= 0 else 0); c = cnt[i] - (cnt[j] if j >= 0 else 0)
        if c >= n: out[i] = s / n
    return out

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

def e_positions(series, span, hi, lo, mode):
    """E-type: CN(span), 4-day LMA smoothing, stateful extremes."""
    s = lma4(cn(series, span))
    pos = np.zeros(N); cur = 0.0
    for i in range(N):
        v = s[i]
        if not np.isnan(v):
            if v >= hi: cur = -1.0 if mode == 'rev' else 1.0
            elif v <= lo: cur = 1.0 if mode == 'rev' else -1.0
        pos[i] = cur
    return pos

def alex_positions(price, pct):
    pos = np.zeros(N); cur = 0.0; extreme = price[0]; 
    for i in range(N):
        p = price[i]
        if cur >= 0:
            extreme = max(extreme, p)
            if p <= extreme * (1 - pct / 100.0): cur = -1.0; extreme = p
        if cur <= 0:
            extreme = min(extreme, p) if cur < 0 else extreme
            if cur < 0 and p >= extreme * (1 + pct / 100.0): cur = 1.0; extreme = p
            elif cur == 0 and p >= extreme * (1 + pct / 100.0): cur = 1.0; extreme = p
        pos[i] = cur
    return pos

def maband_positions(price, span, width):
    m = sma(price, span); pos = np.zeros(N); cur = 0.0
    for i in range(N):
        if not np.isnan(m[i]):
            if price[i] > m[i] * (1 + width / 100.0): cur = 1.0
            elif price[i] < m[i] * (1 - width / 100.0): cur = -1.0
        pos[i] = cur
    return pos

def heiby_positions(companion, span, thr, inverse):
    a = lma4(cn(C, span)); b = lma4(cn(companion, span))
    div = a - b; pos = np.zeros(N); cur = 0.0
    for i in range(N):
        if not np.isnan(div[i]):
            if div[i] >= thr: cur = -1.0 if inverse else 1.0
            elif div[i] <= -thr: cur = 1.0 if inverse else -1.0
        pos[i] = cur
    return pos

# ---------- input series ----------
def obv_series():
    obv = np.cumsum(np.sign(np.diff(C, prepend=C[0])) * V); return obv
def ad_series():
    rng = np.where((H - L) == 0, 1e-9, H - L)
    mfm = ((C - L) - (H - C)) / rng
    return np.cumsum(mfm * V)
def mf_series():
    tp = (H + L + C) / 3.0
    return np.cumsum(np.sign(np.diff(tp, prepend=tp[0])) * tp * V)
def nvi_pvi():
    nvi = np.full(N, 1000.0); pvi = np.full(N, 1000.0)
    for i in range(1, N):
        r = C[i] / C[i - 1] - 1
        if V[i] < V[i - 1]: nvi[i] = nvi[i - 1] * (1 + r)
        else: nvi[i] = nvi[i - 1]
        if V[i] > V[i - 1]: pvi[i] = pvi[i - 1] * (1 + r)
        else: pvi[i] = pvi[i - 1]
    return nvi, pvi

FAMILIES = {}
if SLUG == 'catalog-aronson-alexander-filter':
    FAMILIES = {f'SPYclose|alex{pct}': alex_positions(C, pct) for pct in (1, 2, 3, 5, 10)}
elif SLUG == 'catalog-aronson-ma-bands':
    FAMILIES = {f'SPYclose|ma{sp}b{w}': maband_positions(C, sp, w) for sp in (41, 91, 205) for w in (1, 3, 5)}
elif SLUG == 'catalog-aronson-cn-extremes-index':
    FAMILIES = {f'SPYclose|cn{sp}|{m}|{hi}': e_positions(C, sp, hi, 100 - hi, m)
                for sp in (41, 91, 205) for m in ('rev', 'mom') for hi in (75, 90)}
elif SLUG == 'catalog-aronson-cn-extremes-price-volume':
    obv = obv_series(); nvi, pvi = nvi_pvi()
    series = {'OBV': obv, 'OBV10': sma(obv, 10), 'OBV30': sma(obv, 30), 'AD': ad_series(),
              'MF': mf_series(), 'NVI': nvi, 'PVI': pvi}
    series['MF10'] = sma(series['MF'], 10); series['MF30'] = sma(series['MF'], 30)
    series['NV10'] = sma(nvi, 10); series['NV30'] = sma(nvi, 30)
    series['PV10'] = sma(pvi, 10); series['PV30'] = sma(pvi, 30)
    FAMILIES = {f'{nm}|cn{sp}|{m}|{hi}': e_positions(sv, sp, hi, 100 - hi, m)
                for nm, sv in series.items() for sp in (91,) for m in ('rev', 'mom') for hi in (75, 90)}
elif SLUG == 'catalog-aronson-cn-extremes-debt':
    ser = {'TB3': 100.0 / load_yield('DGS3MO'), 'TN10': 100.0 / load_yield('DGS10'),
           'AAA': 100.0 / load_yield('DAAA'), 'BAA': 100.0 / load_yield('DBAA')}
    FAMILIES = {f'{nm}|cn{sp}|{m}|{hi}': e_positions(sv, sp, hi, 100 - hi, m)
                for nm, sv in ser.items() for sp in (41, 91, 205) for m in ('rev', 'mom') for hi in (75, 90)}
elif SLUG == 'catalog-aronson-cn-extremes-spreads':
    ser = {'DUR': load_yield('DGS10') - load_yield('DGS3MO'), 'QUAL': load_yield('DBAA') - load_yield('DAAA')}
    FAMILIES = {f'{nm}|cn{sp}|{m}|{hi}': e_positions(sv, sp, hi, 100 - hi, m)
                for nm, sv in ser.items() for sp in (41, 91, 205) for m in ('rev', 'mom') for hi in (75, 90)}
elif SLUG == 'catalog-aronson-heiby-divergence':
    obv = obv_series()
    ser = {'OBV': obv, 'TN10price': 100.0 / load_yield('DGS10'), 'DUR': load_yield('DGS10') - load_yield('DGS3MO')}
    FAMILIES = {f'{nm}|cn{sp}|t{thr}|{"inv" if inv else "std"}': heiby_positions(sv, sp, thr, inv)
                for nm, sv in ser.items() for sp in (41, 91, 205) for thr in (25, 50) for inv in (False, True)}
else:
    raise SystemExit('unknown slug ' + SLUG)

ret = np.zeros(N); ret[1:] = C[1:] / C[:-1] - 1
ROADS = {'LONGEST_2015_2026': ('2015-06-01', '2026-11-20'), 'DECADE_2016_2026': ('2016-01-01', '2026-11-20'),
         'CONT_2019_2026': ('2019-01-01', '2026-11-20'), 'VAL_2023_2026': ('2023-01-01', '2026-11-20'),
         'FOLD_2015_2020': ('2015-06-01', '2020-12-31'), 'FOLD_2021_2026': ('2021-01-01', '2026-11-20')}

def road_idx(a, b):
    i0 = next(i for i, dt in enumerate(dates) if dt >= datetime.date.fromisoformat(a))
    i1 = max(i for i, dt in enumerate(dates) if dt <= datetime.date.fromisoformat(b))
    return i0, i1

def run(pos, i0, i1, house=False):
    if house:
        return run_loop(pos, i0, i1, house=True)
    p = pos[i0:i1]                      # position decided at i-1 applies to ret[i]; slice aligns: for day i in (i0+1..i1), p = pos[i-1]
    r = ret[i0 + 1:i1 + 1]
    chg = np.abs(np.diff(np.concatenate(([0.0], p))))
    factors = (1 - 0.001 * chg) * (1 + p * r)
    eqv = 100.0 * np.cumprod(factors)
    curve = [[str(dates[i0]), 100.0]] + [[str(dates[i0 + 1 + k]), round(float(v), 2)] for k, v in enumerate(eqv)]
    costs = 0.0; eq = 100.0
    for f, c in zip(factors, chg):
        costs += eq * 0.001 * c; eq *= f
    peak = 100.0; mdd = 0.0
    for v in eqv:
        peak = max(peak, float(v)); mdd = max(mdd, 1 - float(v) / peak)
    return round(float(eqv[-1]), 2), curve, round(costs, 2), round(mdd, 4)

def run_loop(pos, i0, i1, house=False):
    eq = 100.0; curve = [[str(dates[i0]), 100.0]]; costs = 0.0; prev = 0.0
    halted_until = -1; halts = 0
    for i in range(i0 + 1, i1 + 1):
        p = pos[i - 1]
        if house:
            p = max(p, 0.0)
            if i <= halted_until: p = 0.0
        chg = abs(p - prev)
        if chg > 0:
            c = eq * chg * 0.001; eq -= c; costs += c
        eq *= (1 + p * ret[i]); prev = p
        if house and eq <= 85.0 and i > halted_until and halts < 1:
            halts += 1; halted_until = i + 63; prev = 0.0  # ~90 calendar days cash, one restart
        curve.append([str(dates[i]), round(eq, 2)])
    peak = 100.0; mdd = 0.0
    for _, v in curve: peak = max(peak, v); mdd = max(mdd, 1 - v / peak)
    return round(eq, 2), curve, round(costs, 2), round(mdd, 4)

def spy_final(i0, i1): return round(100 * C[i1] / C[i0], 2)

def period_stats(curve):
    months = {}
    for ds, v in curve: months[ds[:7]] = v
    ks = sorted(months); vals = [months[k] for k in ks]
    rets = [vals[i] / vals[i - 1] - 1 for i in range(1, len(vals)) if vals[i - 1] > 0]
    if not rets: return {}
    los = cur = 0; 
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

def main():
    cells = {}
    for name, pos in FAMILIES.items():
        cell = {}
        for rname, (a, b) in ROADS.items():
            i0, i1 = road_idx(a, b)
            fin, curve, costs, mdd = run(pos, i0, i1)
            twins = []
            for s in range(1, 21):
                rng = random.Random(777 + s)
                off = rng.randint(60, N - 60)
                shifted = np.roll(pos, off)
                tf, _, _, _ = run(shifted, i0, i1)
                twins.append(tf)
            cell[rname] = {'final': fin, 'costs': costs, 'max_dd': mdd, 'spy_same_window': spy_final(i0, i1),
                           'placebos_beaten': sum(1 for t in twins if fin > t), 'placebo_finals': twins,
                           'curve': curve if rname == 'LONGEST_2015_2026' else None}
        cells[name] = cell
        print(name, 'LONGEST', cell['LONGEST_2015_2026']['final'], 'pb', cell['LONGEST_2015_2026']['placebos_beaten'], flush=True)
    # representative = median LONGEST final
    order = sorted(cells, key=lambda k: cells[k]['LONGEST_2015_2026']['final'])
    rep = order[len(order) // 2]; best = order[-1]
    rep_house = {}
    pos = FAMILIES[rep]
    for rname, (a, b) in ROADS.items():
        i0, i1 = road_idx(a, b)
        fin, curve, costs, mdd = run(pos, i0, i1, house=True)
        rep_house[rname] = {'final': fin, 'costs': costs, 'max_dd': mdd}
    out = {'family': SLUG, 'n_cells': len(cells), 'representative_cell_median': rep, 'best_cell_fenced': best,
           'cells': cells, 'representative_house': rep_house,
           'representative_period_stats_monthly': period_stats(cells[rep]['LONGEST_2015_2026']['curve']),
           'best_period_stats_monthly': period_stats(cells[best]['LONGEST_2015_2026']['curve'])}
    json.dump(out, open(os.path.join(FAM, 'results.json'), 'w'), indent=1)
    print('REP', rep, 'BEST', best)

if __name__ == '__main__': main()
