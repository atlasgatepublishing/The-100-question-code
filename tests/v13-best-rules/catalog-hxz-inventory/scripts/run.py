#!/usr/bin/env python3
"""V13 best-rules run for catalog-hxz-inventory.
Chassis frozen in BEST-RULES-SPEC.md: Ivg exactly as catalogued, VETO form
(hold eligible pool, exclude highest-Ivg quintile), annual June formation,
equal weight, buy-and-hold drift, NO floor, tiered program costs,
vanished->ZERO, 20-seed same-chassis placebos.
Inputs (read-only): W04 broad stack + v12 family InventoryNet frames."""
import json, os, math, random, statistics
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); FAM = os.path.join(HERE, '..')
V12 = os.path.join(FAM, '..', '..', 'v12-completions', 'catalog-hxz-inventory')
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
def frame(concept, unit, src):
    out = {}
    for y in range(2014, 2026):
        base = W04 if src == 'w04' else V12
        sub = os.path.join('frames', f'{concept}_{y}{unit}.json') if src == 'w04' else os.path.join('data', 'frames', f'{concept}_{y}{unit}.json')
        out[y] = {int(k): v for k, v in loadj(os.path.join(base, sub)).items()}
    return out
ASSETS = frame('Assets', 'I', 'w04'); INV = frame('InventoryNet', 'I', 'fam')
SHARES = frame('Shares', 'I', 'w04')
def g(fr, y, cik): return fr.get(y, {}).get(cik)
sf = {}
for cik in cand:
    avail = [(y, SHARES[y][cik]) for y in range(2014, 2026) if cik in SHARES.get(y, {})]
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
    sh = g(SHARES, F-1, cik) or g(SHARES, F-2, cik); s = px.get(cik)
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
    vals = {}
    for cik in cand:
        inv1, inv0 = g(INV, F-1, cik), g(INV, F-2, cik); a1 = g(ASSETS, F-1, cik)
        if None in (inv1, inv0, a1) or a1 == 0: continue
        vals[cik] = (inv1 - inv0) / a1
    pool = {}
    for cik, v in vals.items():
        if cik not in px: continue
        e = px[cik].get(ym(F, 6))
        if not e or not e[0]: continue
        cap = cap_of(cik, F)
        pool[cik] = {'sig': v, 'cap': cap, 'rate': cost_rate(cap)}
    POOLS[F] = pool
    cols = [ym(F, m) for m in range(6, 13)] + [ym(F+1, m) for m in range(1, 7)]
    ciks = sorted(pool); M = np.full((len(ciks), len(cols)), np.nan)
    for i, cik in enumerate(ciks):
        s = px[cik]; last = None; lastbar = max(s) if s else None
        for j, mm in enumerate(cols):
            if mm in s: last = s[mm][0]
            if lastbar is not None and mm > lastbar: M[i, j] = 0.0
            elif last is not None: M[i, j] = last
    MATS[F] = (ciks, M)
def veto_picks(F, seed=None):
    pool = POOLS[F]
    items = sorted(pool.items(), key=lambda kv: kv[1]['sig'])  # low -> high
    n_excl = max(1, math.ceil(len(items) * 0.20))
    if seed is None:
        return [c for c, _ in items[:-n_excl]] if n_excl < len(items) else [c for c, _ in items]
    rng = random.Random(seed * 100003 + F); keys = list(pool.keys()); rng.shuffle(keys)
    return keys[:len(items) - n_excl]
def run_road(formations, seed=None):
    cash = 100.0; curve = []; total_costs = 0.0; period_rets = []
    for F in formations:
        start_cash = cash
        ciks_all, M = MATS[F]; idx = {c: i for i, c in enumerate(ciks_all)}; pool = POOLS[F]
        picks = veto_picks(F, seed=seed)
        cols = [ym(F, m) for m in range(6, 13)] + [ym(F+1, m) for m in range(1, 7)]
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
            else:
                cash = val
            curve.append([cols[j], round(cash, 2)])
        period_rets.append(cash / start_cash - 1 if start_cash else 0.0)
    peak = 100.0; maxdd = 0.0
    for _, v in curve:
        peak = max(peak, v); maxdd = max(maxdd, 1 - v / peak) if peak else 0.0
    return round(cash, 2), curve, round(total_costs, 2), round(maxdd, 4), period_rets
def spy_final(formations):
    a = spy.get(ym(formations[0], 6)); b = spy.get(ym(formations[-1] + 1, 6))
    return round(100 * b / a, 2) if a and b else None
def dist(curve, period_rets):
    med = statistics.median(period_rets) if period_rets else 0.0
    pos = sum(1 for r in period_rets if r > 0)
    best = max(period_rets) if period_rets else 0.0; worst = min(period_rets) if period_rets else 0.0
    streak = cur = 0
    for r in period_rets:
        cur = cur + 1 if r <= 0 else 0; streak = max(streak, cur)
    peak = 100.0; since = 0; longest = 0; last_date = None
    for d, v in curve:
        if v >= peak: peak = v; since = 0
        else: since += 1; longest = max(longest, since)
    return {'n_periods': len(period_rets), 'median_period_pct': round(med * 100, 1),
            'share_positive': f'{pos}/{len(period_rets)}', 'best_period_pct': round(best * 100, 1),
            'worst_period_pct': round(worst * 100, 1), 'longest_losing_streak_periods': streak,
            'longest_stretch_between_new_highs_months': longest,
            'period_rets_pct': [round(r * 100, 1) for r in period_rets],
            'mean_period_pct_secondary': round(statistics.mean(period_rets) * 100, 1) if period_rets else 0.0}
ROADS = {'LONG_2016_2025': list(range(2016, 2026)), 'DECADE_2017_2025': list(range(2017, 2026)),
         'CONT_2019_2025': list(range(2019, 2026)), 'VAL_2023_2025': list(range(2023, 2026)),
         'FOLD_2016_2020': list(range(2016, 2021)), 'FOLD_2021_2025': list(range(2021, 2026))}
CHAMP = {'LONG_2016_2025': 1415.62, 'DECADE_2017_2025': 667.35, 'CONT_2019_2025': 544.47, 'VAL_2023_2025': 288.05}
out = {'family': 'catalog-hxz-inventory', 'spec': 'BEST-RULES-SPEC.md', 'chassis': 'Ivg veto: hold eligible pool excl top-Ivg quintile, annual June, EW, no floor',
       'pool_sizes_eligible': {str(F): len(POOLS[F]) for F in sorted(POOLS)}, 'roads': {}}
for rname, forms in ROADS.items():
    fin, curve, costs, maxdd, prets = run_road(forms)
    twins = [run_road(forms, seed=sd)[0] for sd in range(1, 21)]
    entry = {'final': fin, 'costs': costs, 'max_dd': maxdd, 'spy_same_window': spy_final(forms),
             'placebo_finals': twins, 'placebos_beaten': sum(1 for t in twins if fin > t),
             'curve': curve, 'distribution': dist(curve, prets)}
    if rname in CHAMP:
        entry['champion_vm_reference'] = CHAMP[rname]; entry['beats_champion'] = fin > CHAMP[rname]
        half = len(forms) // 2
        entry['half_windows'] = {}
        for hn, hf in (('H1', forms[:half]), ('H2', forms[half:])):
            hf_fin = run_road(hf)[0]
            entry['half_windows'][hn] = {'formations': hf, 'final': hf_fin, 'spy_same_window': spy_final(hf)}
    out['roads'][rname] = entry
    print(rname, fin, 'dd', maxdd, 'spy', entry['spy_same_window'], 'pb', entry['placebos_beaten'], flush=True)
with open(os.path.join(FAM, 'results.json'), 'w') as fh: json.dump(out, fh, indent=1)
print('saved results.json')
