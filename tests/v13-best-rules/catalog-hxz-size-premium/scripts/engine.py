#!/usr/bin/env python3
"""V13 best-rules engine — catalog-hxz-size-premium.
Spec: BEST-RULES-SPEC.md (frozen before this run).
Signal exactly as v12 catalog: Me (shares FY F-1, split-adj x raw June close),
long LOW. Chassis: broad W04 PIT stack, smallest DECILE equal-weight,
annual June formation, 12-month hold, no rebalancing, NO floor,
habitat cost load (<$1B 1.50% / $1-5B 0.50% / >=$5B 0.10% per side),
vanished -> ZERO. 20-seed placebos share the chassis (same decile count,
random draw from same year's eligible broad pool). Simulation only."""
import json, os, math, random, statistics
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
FAM = os.path.join(HERE, '..')
V12 = os.path.join(FAM, '..', '..', 'v12-completions', 'catalog-hxz-size-premium')
W04 = os.path.join(FAM, '..', '..', 'v11-native-rules', '_w04_broad_data')
def loadj(p): return json.load(open(p)) if os.path.exists(p) else {}
SIG = loadj(os.path.join(V12, 'signals.json'))
cand = {int(k): v for k, v in loadj(os.path.join(W04, 'candidates.json')).items()}
px = {}
for cik, info in cand.items():
    t = info['ticker'].replace('/', '-')
    p = os.path.join(W04, f'px_{t}.json')
    if os.path.exists(p):
        try: px[cik] = {r[0]: (r[1], r[2]) for r in loadj(p)}
        except Exception: pass
spy = {r[0]: r[1] for r in loadj(os.path.join(W04, 'px_SPY.json'))}
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
    # habitat-realistic load frozen in spec choice 5
    if cap is None: return 0.0150
    if cap >= 5e9: return 0.0010
    if cap >= 1e9: return 0.0050
    return 0.0150
def ym(y, m): return f'{y:04d}-{m:02d}'
FORMATIONS = sorted(int(f) for f in SIG['signals']['Me']['pools'].keys())
POOLS = {}; MATS = {}
for F in FORMATIONS:
    raw = {int(k): v for k, v in SIG['signals']['Me']['pools'].get(str(F), {}).items()}
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
def picks_for(F):
    items = sorted(POOLS[F].items(), key=lambda kv: kv[1]['sig'])  # long LOW Me
    return [c for c, _ in items[:decile_n(F)]]
def run_road(formations, seed=None):
    cash = 100.0; curve = []; total_costs = 0.0; picks_log = {}
    for F in formations:
        ciks_all, M = MATS[F]
        idx = {c: i for i, c in enumerate(ciks_all)}
        pool = POOLS[F]
        if seed is None:
            picks = picks_for(F)
        else:
            rng = random.Random(seed * 100003 + F)
            keys = list(pool.keys()); rng.shuffle(keys)
            picks = keys[:decile_n(F)]
        if seed is None:
            picks_log[F] = [{'cik': c, 'ticker': cand.get(c, {}).get('ticker'),
                             'cap': pool[c]['cap']} for c in picks]
        cols = [ym(F, m) for m in range(6, 13)] + [ym(F + 1, m) for m in range(1, 7)]
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
    peak2 = 100.0; maxdd = 0.0
    for _, v in curve:
        peak2 = max(peak2, v); maxdd = max(maxdd, 1 - v / peak2) if peak2 else 0.0
    return round(cash, 2), curve, round(total_costs, 2), round(maxdd, 4), picks_log
def spy_final(formations):
    a = spy.get(ym(formations[0], 6)); b = spy.get(ym(formations[-1] + 1, 6))
    return round(100 * b / a, 2) if a and b else None
def period_stats(curve):
    vals = [100.0] + [v for _, v in curve]
    rets = [(vals[i] / vals[i-1] - 1) * 100 if vals[i-1] else 0.0 for i in range(1, len(vals))]
    med = statistics.median(rets); pos = sum(1 for r in rets if r > 0)
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0; streak = max(streak, cur)
    peak = vals[0]; since = 0; longest = 0
    for v in vals:
        if v >= peak: peak = v; longest = max(longest, since); since = 0
        else: since += 1
    longest = max(longest, since)
    annual = []
    for i in range(12, len(vals), 12):
        annual.append((vals[i] / vals[i-12] - 1) * 100)
    return {'months': len(rets), 'median_month_pct': round(med, 2),
            'share_positive_pct': round(100 * pos / len(rets), 1) if rets else None,
            'best_month_pct': round(max(rets), 2), 'worst_month_pct': round(min(rets), 2),
            'longest_losing_streak_mo': streak, 'longest_between_highs_mo': longest,
            'avg_month_pct_secondary': round(statistics.mean(rets), 2),
            'annual_periods_pct': [round(a, 1) for a in annual],
            'annual_median_pct': round(statistics.median(annual), 1) if annual else None,
            'annual_share_positive': f'{sum(1 for a in annual if a > 0)}/{len(annual)}' if annual else None}
def main():
    R = {'LONG': FORMATIONS,
         'DECADE': [f for f in FORMATIONS if f >= 2017],
         'CONT': [f for f in FORMATIONS if f >= 2019],
         'VAL': [f for f in FORMATIONS if f >= 2023]}
    out = {'family': 'catalog-hxz-size-premium', 'spec': 'BEST-RULES-SPEC.md',
           'chassis': 'broad|native(no floor)|annual|DECILE|habitat costs <1B 1.50% / 1-5B 0.50% / >=5B 0.10%',
           'formations': FORMATIONS,
           'pool_sizes': {F: len(POOLS[F]) for F in FORMATIONS},
           'decile_counts': {F: decile_n(F) for F in FORMATIONS}, 'roads': {}}
    for rname, forms in R.items():
        fin, curve, costs, maxdd, picks_log = run_road(forms)
        twins = []
        for s in range(1, 21):
            tf, _, _, _, _ = run_road(forms, seed=s); twins.append(tf)
        out['roads'][rname] = {'formations': forms, 'final': fin, 'costs': costs,
                               'max_dd': maxdd, 'spy_same_window': spy_final(forms),
                               'placebo_finals': twins,
                               'placebos_beaten': sum(1 for t in twins if fin > t),
                               'placebo_median': round(statistics.median(twins), 2),
                               'period_stats': period_stats(curve), 'curve': curve,
                               'picks': picks_log}
        print(rname, fin, 'dd', maxdd, 'costs', costs, 'spy', spy_final(forms),
              'pb', out['roads'][rname]['placebos_beaten'], '/20', flush=True)
    with open(os.path.join(FAM, 'results.json'), 'w') as fh: json.dump(out, fh, indent=1)
    print('saved results.json')
if __name__ == '__main__': main()
