#!/usr/bin/env python3
"""V13 best-rules run — catalog-hlz-ticker-fluency. BEST-RULES-SPEC.md.
Broad universe, below-median-cap habitat, top-quintile fluency (v12 frozen
scores, read-only), annual June formation, 12m hold, EW, NO floor, tiered
program costs, vanished->ZERO, AMCCF (CIK 1748790) excluded as documented
corrupt series. 20-seed placebos from the same small-cap pool."""
import json, os, math, random, statistics
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); FAM = os.path.join(HERE, '..')
V12 = os.path.join(FAM, '..', '..', 'v12-completions', 'catalog-hlz-ticker-fluency')
W04 = os.path.join(FAM, '..', '..', 'v11-native-rules', '_w04_broad_data')
def loadj(p): return json.load(open(p)) if os.path.exists(p) else {}
cand = {int(k): v for k, v in loadj(os.path.join(W04, 'candidates.json')).items()}
px = {}
for cik, info in cand.items():
    t = info['ticker'].replace('/', '-'); p = os.path.join(W04, f'px_{t}.json')
    if os.path.exists(p):
        try: px[cik] = {r[0]: (r[1], r[2]) for r in loadj(p)}
        except Exception: pass
spy = {r[0]: r[1] for r in loadj(os.path.join(W04, 'px_SPY.json'))}
SIG = loadj(os.path.join(V12, 'signals.json'))['signals']['TickerFluency']
EXCLUDE = {1748790}  # AMCCF corrupt series, spec-disclosed
shares_f = {}
for y in range(2009, 2026):
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
FORMS = sorted({int(f) for f in SIG['values']})
POOLS = {}; MATS = {}
for F in FORMS:
    vals = {int(k): v for k, v in SIG['values'].get(str(F), {}).items()}
    pool = {}
    for cik, score in vals.items():
        if cik in EXCLUDE or cik not in px: continue
        e = px[cik].get(ym(F, 6))
        if not e or not e[0]: continue
        cap = cap_of(cik, F)
        if cap is None: continue
        pool[cik] = {'score': score, 'cap': cap, 'rate': cost_rate(cap)}
    med = statistics.median(v['cap'] for v in pool.values())
    small = {c: v for c, v in pool.items() if v['cap'] < med}
    POOLS[F] = {'pool': pool, 'small': small, 'median_cap': med}
    cols = [ym(F, m) for m in range(6, 13)] + [ym(F + 1, m) for m in range(1, 7)]
    allciks = sorted(pool)
    M = np.full((len(allciks), 13), np.nan); idx = {c: i for i, c in enumerate(allciks)}
    for i, cik in enumerate(allciks):
        s = px[cik]; last = None; lastbar = max(s) if s else None
        for j, mm in enumerate(cols):
            if mm in s: last = s[mm][0]
            if lastbar is not None and mm > lastbar: M[i, j] = 0.0
            elif last is not None: M[i, j] = last
    MATS[F] = (idx, M)
def picks_for(F):
    small = POOLS[F]['small']
    items = sorted(small.items(), key=lambda kv: kv[1]['score'], reverse=True)
    n = max(1, math.ceil(len(items) * 0.20))
    return [c for c, _ in items[:n]], n
def run_road(formations, seed=None):
    cash = 100.0; curve = []; total_costs = 0.0; counts = {}
    for F in formations:
        idx, M = MATS[F]; small = POOLS[F]['small']
        if seed is None:
            picks, n = picks_for(F)
        else:
            rng = random.Random(seed * 100003 + F); keys = list(small.keys()); rng.shuffle(keys)
            _, n = picks_for(F); picks = keys[:n]
        counts[F] = len(picks)
        cols = [ym(F, m) for m in range(6, 13)] + [ym(F + 1, m) for m in range(1, 7)]
        rows = np.array([idx[c] for c in picks]); P = M[rows, :]
        rates = np.array([small[c]['rate'] for c in picks])
        px0 = P[:, 0].copy(); px0[px0 <= 0] = np.nan
        w = cash / len(picks)
        shares = np.where(np.isnan(px0), 0.0, (w * (1 - rates)) / np.where(np.isnan(px0), 1.0, px0))
        total_costs += float(np.sum(w * rates))
        for j in range(1, 13):
            pj = P[:, j]; val = float(np.sum(shares * np.where(np.isnan(pj), 0.0, pj)))
            if j == 12:
                sell = float(np.sum(shares * np.where(np.isnan(pj), 0.0, pj) * rates))
                total_costs += sell; cash = val - sell
            else:
                cash = val
            curve.append([cols[j], round(cash, 2)])
    peak = 100.0; maxdd = 0.0; last_high_i = 0; max_gap = 0
    for i, (_, v) in enumerate(curve):
        if v >= peak: peak = v; last_high_i = i
        maxdd = max(maxdd, 1 - v / peak) if peak else 0.0
        max_gap = max(max_gap, i - last_high_i)
    return round(cash, 2), curve, round(total_costs, 2), round(maxdd, 4), max_gap, counts
def spy_final(formations):
    a = spy.get(ym(formations[0], 6)); b = spy.get(ym(formations[-1] + 1, 6))
    return round(100 * b / a, 2) if a and b else None
def period_stats(curve):
    # annual periods: value at each June (formation boundaries)
    junes = [(i, v) for i, (d, v) in enumerate(curve) if d.endswith('-06')]
    rets = []
    prev = 100.0
    for _, v in junes:
        rets.append(v / prev - 1); prev = v
    pos = sum(1 for r in rets if r > 0)
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; streak = max(streak, cur)
    return {'periods': len(rets), 'median_pct': round(statistics.median(rets) * 100, 1) if rets else None,
            'share_positive': f"{pos}/{len(rets)}" if rets else None,
            'best_pct': round(max(rets) * 100, 1) if rets else None,
            'worst_pct': round(min(rets) * 100, 1) if rets else None,
            'mean_pct_secondary': round(statistics.mean(rets) * 100, 1) if rets else None,
            'longest_losing_streak_periods': streak, 'period_returns_pct': [round(r * 100, 1) for r in rets]}
ROADS = {'LONG': FORMS, 'DECADE': [f for f in FORMS if f >= 2017],
         'CONT': [f for f in FORMS if f >= 2019], 'VAL': [f for f in FORMS if f >= 2023]}
def main():
    out = {'family': 'catalog-hlz-ticker-fluency', 'spec': 'BEST-RULES-SPEC.md',
           'roads_windows': {k: [f'{v[0]}-06', f'{v[-1] + 1}-06'] for k, v in ROADS.items()},
           'pool_sizes': {str(F): {'broad_with_cap': len(POOLS[F]['pool']), 'small_half': len(POOLS[F]['small']),
                                   'median_cap': round(POOLS[F]['median_cap'])} for F in FORMS},
           'roads': {}}
    for rname, forms in ROADS.items():
        fin, curve, costs, maxdd, gap, counts = run_road(forms)
        twins = []
        for sd in range(1, 21):
            tf, _, _, _, _, _ = run_road(forms, seed=sd); twins.append(tf)
        out['roads'][rname] = {'final': fin, 'costs': costs, 'max_dd': maxdd,
                               'spy_same_window': spy_final(forms),
                               'placebo_finals': twins, 'placebos_beaten': sum(1 for t in twins if fin > t),
                               'months_between_new_highs_max': gap, 'holdings_per_formation': counts,
                               'period_stats': period_stats(curve), 'curve': curve}
        print(rname, fin, 'dd', maxdd, 'pb', out['roads'][rname]['placebos_beaten'], 'spy', out['roads'][rname]['spy_same_window'], flush=True)
    with open(os.path.join(FAM, 'results.json'), 'w') as fh: json.dump(out, fh, indent=1)
    print('saved results.json')
if __name__ == '__main__': main()
