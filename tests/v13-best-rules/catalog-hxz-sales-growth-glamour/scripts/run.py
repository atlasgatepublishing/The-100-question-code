#!/usr/bin/env python3
"""V13 best-rules run — catalog-hxz-sales-growth-glamour.
Spec: BEST-RULES-SPEC.md (frozen before this run).
Sr (5y sales-growth CAGR), long LOW DECILE, broad W04 stack, annual June
formation, 12-month hold, no re-equalization, NO floor, program tiered
costs, vanished->ZERO, 20-seed placebos sharing the chassis.
Reads v12 signals.json + W04 stack read-only. Simulation only."""
import json, os, math, random, statistics
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
FAM = os.path.join(HERE, '..')
V12 = os.path.join(FAM, '..', '..', 'v12-completions', 'catalog-hxz-sales-growth-glamour')
W04 = os.path.join(FAM, '..', '..', 'v11-native-rules', '_w04_broad_data')
def loadj(p): return json.load(open(p)) if os.path.exists(p) else {}
SIG = loadj(os.path.join(V12, 'signals.json'))['signals']['Sr']
cand = {int(k): v for k, v in loadj(os.path.join(W04, 'candidates.json')).items()}
px = {}
for cik, info in cand.items():
    t = info['ticker'].replace('/', '-')
    p = os.path.join(W04, f'px_{t}.json')
    if os.path.exists(p):
        try: px[cik] = {r[0]: (r[1], r[2]) for r in loadj(p)}
        except Exception: pass
spy = {r[0]: r[1] for r in loadj(os.path.join(W04, 'px_SPY.json'))}
assets = {}; shares_f = {}
for y in range(2009, 2026):
    assets[y] = {int(k): v for k, v in loadj(os.path.join(W04, 'frames', f'Assets_{y}I.json')).items()}
    shares_f[y] = {int(k): v for k, v in loadj(os.path.join(W04, 'frames', f'Shares_{y}I.json')).items()}
sf = {}
for cik in cand:
    avail = [(y, shares_f[y][cik]) for y in range(2009, 2026) if cik in shares_f[y]]
    d = {}
    for F in range(2016, 2027):
        f = 1.0
        for (y0, a), (y1, b) in zip(avail, avail[1:]):
            if y1 >= F and a:
                r = b / a
                if r >= 1.6 or r <= 0.625: f *= r
        d[F] = f
    sf[cik] = d
def cap_of(cik, F):
    sh = shares_f.get(F - 1, {}).get(cik) or shares_f.get(F - 2, {}).get(cik)
    s = px.get(cik)
    if not sh or not s: return None
    e = s.get(f'{F:04d}-06')
    if not e or not e[1]: return None
    return sh * e[1] * sf.get(cik, {}).get(F, 1.0)
def cost_rate(cap):
    if cap is None: return 0.0075
    if cap >= 5e9: return 0.0010
    if cap >= 1e9: return 0.0025
    return 0.0075
def ym(y, m): return f'{y:04d}-{m:02d}'
FORMATIONS = sorted(int(f) for f in SIG['pools'].keys())
POOLS = {}; MATS = {}
for F in FORMATIONS:
    raw = {int(k): v for k, v in SIG['pools'].get(str(F), {}).items()}
    pool = {}
    for cik, val in raw.items():
        if cik not in px: continue
        e = px[cik].get(ym(F, 6))
        if not e or not e[0]: continue
        cap = cap_of(cik, F)
        pool[cik] = {'sig': val, 'cap': cap, 'rate': cost_rate(cap)}
    POOLS[F] = pool
    cols = [ym(F, m) for m in range(6, 13)] + [ym(F + 1, m) for m in range(1, 7)]
    ciks = sorted(pool)
    M = np.full((len(ciks), len(cols)), np.nan)
    for i, cik in enumerate(ciks):
        s = px[cik]; last = None; lastbar = max(s) if s else None
        for j, mm in enumerate(cols):
            if mm in s: last = s[mm][0]
            if lastbar is not None and mm > lastbar: M[i, j] = 0.0
            elif last is not None: M[i, j] = last
    MATS[F] = (ciks, M)
def decile_n(F): return max(1, math.ceil(len(POOLS[F]) * 0.10))
def picks_for(F, seed=None):
    pool = POOLS[F]
    if seed is None:
        items = sorted(pool.items(), key=lambda kv: kv[1]['sig'])  # long LOW growth
        return [c for c, _ in items[:decile_n(F)]]
    rng = random.Random(seed * 100003 + F)
    keys = list(pool.keys()); rng.shuffle(keys)
    return keys[:decile_n(F)]
def run_road(formations, seed=None):
    cash = 100.0; curve = []; total_costs = 0.0; period_rets = []
    for F in formations:
        start = cash
        ciks_all, M = MATS[F]
        idx = {c: i for i, c in enumerate(ciks_all)}
        pool = POOLS[F]
        picks = picks_for(F, seed)
        cols = [ym(F, m) for m in range(6, 13)] + [ym(F + 1, m) for m in range(1, 7)]
        if not picks:
            for mm in cols[1:]: curve.append([mm, round(cash, 2)])
            period_rets.append(0.0); continue
        rows = np.array([idx[c] for c in picks]); P = M[rows, :]
        rates = np.array([pool[c]['rate'] for c in picks])
        px0 = P[:, 0].copy(); px0[px0 <= 0] = np.nan
        w = cash / len(picks)
        shares = np.where(np.isnan(px0), 0.0, (w * (1 - rates)) / np.where(np.isnan(px0), 1.0, px0))
        total_costs += float(np.sum(w * rates))
        for j in range(1, 13):
            pj = P[:, j]; vals = shares * np.where(np.isnan(pj), 0.0, pj); val = float(np.sum(vals))
            if j == 12:
                sell = float(np.sum(vals * rates)); total_costs += sell; cash = val - sell
            else: cash = val
            curve.append([cols[j], round(cash, 2)])
        period_rets.append(cash / start - 1.0 if start else 0.0)
    peak = 100.0; maxdd = 0.0; last_high_i = 0; max_gap = 0
    for i, (_, v) in enumerate(curve):
        if v >= peak: peak = v; last_high_i = i
        maxdd = max(maxdd, 1 - v / peak) if peak else 0.0
        max_gap = max(max_gap, i - last_high_i)
    return {'final': round(cash, 2), 'curve': curve, 'costs': round(total_costs, 2),
            'max_dd': round(maxdd, 4), 'period_rets': [round(r, 4) for r in period_rets],
            'months_between_highs_max': max_gap}
def spy_final(formations):
    a = spy.get(ym(formations[0], 6)); b = spy.get(ym(formations[-1] + 1, 6))
    return round(100 * b / a, 2) if a and b else None
def dist(period_rets):
    if not period_rets: return {}
    pos = sum(1 for r in period_rets if r > 0)
    streak = mx = 0
    for r in period_rets:
        streak = streak + 1 if r <= 0 else 0; mx = max(mx, streak)
    return {'n_periods': len(period_rets), 'median_period': round(statistics.median(period_rets), 4),
            'share_positive': f'{pos}/{len(period_rets)}', 'best': round(max(period_rets), 4),
            'worst': round(min(period_rets), 4), 'longest_losing_streak': mx,
            'mean_period_secondary': round(statistics.mean(period_rets), 4)}
ROADS = {'LONGEST': FORMATIONS,
         'DECADE': [f for f in FORMATIONS if f >= 2017],
         'CONT': [f for f in FORMATIONS if f >= 2019],
         'VAL': [f for f in FORMATIONS if f >= 2023],
         'FOLD1': [f for f in FORMATIONS if f <= 2020],
         'FOLD2': [f for f in FORMATIONS if f >= 2021]}
def main():
    out = {'family': 'catalog-hxz-sales-growth-glamour', 'program': 'v13-best-rules',
           'spec': 'BEST-RULES-SPEC.md',
           'cell': 'Sr|broad|native(no floor)|annual|DECILE(lowest 10% Sr)',
           'formations': FORMATIONS,
           'pool_sizes': {str(F): len(POOLS[F]) for F in FORMATIONS},
           'decile_counts': {str(F): decile_n(F) for F in FORMATIONS},
           'roads': {}}
    for rname, forms in ROADS.items():
        r = run_road(forms)
        entry = dict(r); entry['formations'] = forms; entry['spy_same_window'] = spy_final(forms)
        entry['distribution'] = dist(r['period_rets'])
        if rname in ('LONGEST', 'DECADE', 'CONT', 'VAL'):
            twins = []
            for s in range(1, 21):
                twins.append(run_road(forms, seed=s)['final'])
            entry['placebo_finals'] = twins
            entry['placebos_beaten'] = sum(1 for t in twins if r['final'] > t)
            half = len(forms) // 2
            for hn, hf in (('HALF_A', forms[:half]), ('HALF_B', forms[half:])):
                hr = run_road(hf)
                entry[hn] = {'formations': hf, 'final': hr['final'], 'max_dd': hr['max_dd'],
                             'spy_same_window': spy_final(hf)}
        out['roads'][rname] = entry
        print(rname, entry['final'], 'dd', entry['max_dd'], 'spy', entry['spy_same_window'],
              'pb', entry.get('placebos_beaten'), flush=True)
    with open(os.path.join(FAM, 'results.json'), 'w') as fh: json.dump(out, fh, indent=1)
    print('saved results.json')
if __name__ == '__main__': main()
