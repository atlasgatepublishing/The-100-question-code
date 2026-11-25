#!/usr/bin/env python3
"""V13 best-rules run: Ocp (catalog-exact), top-10, annual, no floor.
Reuses v12 chassis logic (W04 broad stack, June formations, tiered costs,
vanished->ZERO, 20-seed placebos). Writes results.json in this folder only."""
import json, os, math, random
import numpy as np

FAM = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W04 = '/home/hatch/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data'

def loadj(p):
    return json.load(open(p)) if os.path.exists(p) else {}

cand = {int(k): v for k, v in loadj(os.path.join(W04, 'candidates.json')).items()}
px = {}
for cik, info in cand.items():
    t = info['ticker'].replace('/', '-')
    p = os.path.join(W04, f'px_{t}.json')
    if os.path.exists(p):
        try: px[cik] = {r[0]: (r[1], r[2]) for r in loadj(p)}
        except Exception: pass
spy = {r[0]: r[1] for r in loadj(os.path.join(W04, 'px_SPY.json'))}

def frame(concept, unit):
    out = {}
    for y in range(2014, 2026):
        d = loadj(os.path.join(W04, 'frames', f'{concept}_{y}{unit}.json'))
        out[y] = {int(k): v for k, v in d.items()}
    return out

FR = {'Shares': frame('Shares', 'I'),
      'OCF': frame('NetCashProvidedByUsedInOperatingActivities', 'D')}

def g(concept, y, cik):
    return FR[concept].get(y, {}).get(cik)

sf = {}
for cik in cand:
    avail = [(y, FR['Shares'][y][cik]) for y in range(2014, 2026) if cik in FR['Shares'].get(y, {})]
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
    sh = g('Shares', F-1, cik) or g('Shares', F-2, cik)
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

POOLS = {}; MATS = {}
for F in range(2016, 2026):
    pool = {}
    for cik in cand:
        ocf, mc = g('OCF', F-1, cik), cap_of(cik, F)
        if ocf is None or not mc or cik not in px: continue
        e = px[cik].get(ym(F, 6))
        if not e or not e[0]: continue
        cap = cap_of(cik, F)
        pool[cik] = {'sig': ocf / mc, 'cap': cap, 'rate': cost_rate(cap)}
    POOLS[F] = pool
    cols = [ym(F, m) for m in range(6, 13)] + [ym(F+1, m) for m in range(1, 7)]
    ciks = sorted(pool)
    M = np.full((len(ciks), len(cols)), np.nan)
    for i, cik in enumerate(ciks):
        s = px[cik]; last = None; lastbar = max(s) if s else None
        for j, mm in enumerate(cols):
            if mm in s: last = s[mm][0]
            if lastbar is not None and mm > lastbar: M[i, j] = 0.0
            elif last is not None: M[i, j] = last
    MATS[F] = (ciks, M)

COUNT = 10

def run_road(formations, seed=None):
    cash = 100.0; curve = [[ym(formations[0], 6), 100.0]]; total_costs = 0.0
    period_rets = []
    for F in formations:
        start_val = cash
        ciks_all, M = MATS[F]
        idx = {c: i for i, c in enumerate(ciks_all)}
        pool = POOLS[F]
        if seed is None:
            picks = [c for c, _ in sorted(pool.items(), key=lambda kv: kv[1]['sig'], reverse=True)[:COUNT]]
        else:
            rng = random.Random(seed * 100003 + F)
            keys = list(pool.keys()); rng.shuffle(keys)
            picks = keys[:min(COUNT, len(keys))]
        cols = [ym(F, m) for m in range(6, 13)] + [ym(F+1, m) for m in range(1, 7)]
        if not picks:
            for mm in cols[1:]: curve.append([mm, round(cash, 2)])
            period_rets.append(0.0); continue
        rows = np.array([idx[c] for c in picks])
        P = M[rows, :]
        rates = np.array([pool[c]['rate'] for c in picks])
        px0 = P[:, 0].copy(); px0[px0 <= 0] = np.nan
        w = cash / len(picks)
        shares = np.where(np.isnan(px0), 0.0, (w * (1 - rates)) / np.where(np.isnan(px0), 1.0, px0))
        total_costs += float(np.sum(w * rates))
        for j in range(1, 13):
            pj = P[:, j]
            vals = shares * np.where(np.isnan(pj), 0.0, pj)
            val = float(np.sum(vals))
            if j == 12:
                sell = float(np.sum(vals * rates)); total_costs += sell; cash = val - sell
            else:
                cash = val
            curve.append([cols[j], round(cash, 2)])
        period_rets.append(cash / start_val - 1 if start_val else 0.0)
    peak = 100.0; maxdd = 0.0; last_high_i = 0; longest_gap = 0
    for i, (_, v) in enumerate(curve):
        if v >= peak: peak = v; last_high_i = i
        else: longest_gap = max(longest_gap, i - last_high_i)
        if peak: maxdd = max(maxdd, 1 - v / peak)
    # longest stretch between new highs in months (curve is monthly)
    return {'final': round(cash, 2), 'curve': curve, 'costs': round(total_costs, 2),
            'max_dd': round(maxdd, 4), 'period_rets': [round(r, 4) for r in period_rets],
            'longest_months_between_highs': longest_gap}

def spy_final(formations):
    a = spy.get(ym(formations[0], 6)); b = spy.get(ym(formations[-1]+1, 6))
    return round(100 * b / a, 2) if a and b else None

def dist(period_rets):
    if not period_rets: return {}
    pos = sum(1 for r in period_rets if r > 0)
    streak = cur = 0
    for r in period_rets:
        cur = cur + 1 if r <= 0 else 0; streak = max(streak, cur)
    s = sorted(period_rets)
    med = s[len(s)//2] if len(s) % 2 else (s[len(s)//2-1] + s[len(s)//2]) / 2
    return {'n_periods': len(period_rets), 'median_period': round(med, 4),
            'share_positive': f"{pos}/{len(period_rets)}", 'best': round(max(period_rets), 4),
            'worst': round(min(period_rets), 4), 'longest_losing_streak': streak,
            'mean_period_secondary': round(float(np.mean(period_rets)), 4)}

ROADS = {'LONGEST': list(range(2016, 2026)), 'DECADE': list(range(2017, 2026)),
         'CONT': list(range(2019, 2026)), 'VAL': list(range(2023, 2026)),
         'FOLD_2016_2020': list(range(2016, 2021)), 'FOLD_2021_2025': list(range(2021, 2026))}

def main():
    print('pools', {F: len(POOLS[F]) for F in sorted(POOLS)}, flush=True)
    out = {'family': 'catalog-hxz-operating-cashflow-to-price', 'spec': 'BEST-RULES-SPEC.md',
           'config': 'Ocp catalog-exact | top-10 equal-weight | annual June formation, 12m hold | no floor | tiered program costs | long-only translation',
           'pool_sizes': {str(F): len(POOLS[F]) for F in sorted(POOLS)}, 'roads': {}}
    for rname, forms in ROADS.items():
        r = run_road(forms)
        twins = [run_road(forms, seed=sd)['final'] for sd in range(1, 21)]
        r['placebo_finals'] = twins
        r['placebos_beaten'] = sum(1 for t in twins if r['final'] > t)
        r['spy_same_window'] = spy_final(forms)
        r['distribution'] = dist(r['period_rets'])
        out['roads'][rname] = r
        print(rname, r['final'], 'dd', r['max_dd'], 'spy', r['spy_same_window'], 'pb', r['placebos_beaten'], flush=True)
    with open(os.path.join(FAM, 'results.json'), 'w') as fh:
        json.dump(out, fh, indent=1)
    print('saved results.json')

if __name__ == '__main__':
    main()
