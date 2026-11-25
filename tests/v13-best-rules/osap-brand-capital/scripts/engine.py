#!/usr/bin/env python3
"""osap-brand-capital v13 best-rules engine — frozen by BEST-RULES-SPEC.md.
BrandInvest low, native (SIC-filtered) universe, >=3 consecutive xad years,
10 names EW, annual June formation, 12m hold, no floor/gates, tiered program
costs, vanished->ZERO, 20-seed placebos sharing the chassis.
Data: v12 EDGAR AdvertisingExpense frames + W04 broad stack (both read-only).
Simulation only. Writes results.json in this family folder."""
import json, os, math, random, statistics
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FAM = os.path.join(HERE, '..')
V12 = os.path.join(FAM, '..', '..', 'v12-completions', 'osap-brand-capital')
W04 = os.path.join(FAM, '..', '..', 'v11-native-rules', '_w04_broad_data')
FR = os.path.join(V12, 'data', 'frames')
COUNT = 10

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

xad = {}
for y in range(2009, 2026):
    xad[y] = {int(k): v for k, v in loadj(os.path.join(FR, f'AdvertisingExpense_{y}D.json')).items()}
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

BC = {}
for cik in cand:
    bc = {}; prev = None; prev_y = None
    for y in range(2009, 2026):
        v = xad[y].get(cik)
        if v is None:
            prev = None; prev_y = None; continue
        cur = v / 0.6 if (prev is None or prev_y != y - 1) else 0.5 * prev + v
        bc[y] = cur; prev = cur; prev_y = y
    if bc: BC[cik] = bc

def ym(y, m): return f'{y:04d}-{m:02d}'

# pools: native universe + >=3 consecutive xad years ending F-1
POOLS = {}
for F in range(2016, 2026):
    pool = {}
    for cik, bc in BC.items():
        # history: xad present F-1, F-2, F-3 consecutively (BC chain unbroken)
        if any((F - k) not in bc for k in (1, 2, 3)): continue
        if xad[F - 1].get(cik, 0) <= 0: continue
        if cik not in px: continue
        e = px[cik].get(ym(F, 6))
        if not e or not e[0]: continue
        at = assets.get(F - 1, {}).get(cik)
        if not at: continue
        sic = str(cand[cik].get('sic') or '')
        if sic[:1] in ('4', '6'): continue
        cap = cap_of(cik, F)
        pool[cik] = {'bi': xad[F - 1][cik] / bc[F - 1], 'cap': cap,
                     'rate': cost_rate(cap), 'px0': e[0]}
    POOLS[F] = pool

MATS = {}
for F in range(2016, 2026):
    cols = [ym(F, m) for m in range(6, 13)] + [ym(F + 1, m) for m in range(1, 7)]
    pool = POOLS[F]; ciks = sorted(pool)
    M = np.full((len(ciks), len(cols)), np.nan)
    for i, cik in enumerate(ciks):
        s = px[cik]; last = None; lastbar = max(s) if s else None
        for j, mm in enumerate(cols):
            if mm in s: last = s[mm][0]
            if lastbar is not None and mm > lastbar: M[i, j] = 0.0
            elif last is not None: M[i, j] = last
    MATS[F] = (ciks, M)

def picks_for(F):
    items = sorted(POOLS[F].items(), key=lambda kv: kv[1]['bi'])  # long LOW
    return [c for c, _ in items[:min(COUNT, len(items))]]

def run_road(formations, seed=None):
    cash = 100.0; curve = []; total_costs = 0.0; period_rets = []
    for F in formations:
        ciks_all, M = MATS[F]; idx = {c: i for i, c in enumerate(ciks_all)}
        pool = POOLS[F]; start_val = cash
        if seed is None:
            picks = picks_for(F)
        else:
            rng = random.Random(seed * 100003 + F)
            keys = list(pool.keys()); rng.shuffle(keys)
            picks = keys[:min(COUNT, len(keys))]
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
            pj = P[:, j]
            vals = shares * np.where(np.isnan(pj), 0.0, pj)
            val = float(np.sum(vals))
            if j == 12:
                sell = float(np.sum(vals * rates)); total_costs += sell
                cash = val - sell
            else:
                cash = val
            curve.append([cols[j], round(cash, 2)])
        period_rets.append(cash / start_val - 1.0 if start_val else 0.0)
    peak = 100.0; maxdd = 0.0; last_high_i = 0; longest_gap = 0
    vals = [100.0] + [v for _, v in curve]
    runmax = 100.0
    for i, v in enumerate(vals):
        if v >= runmax: runmax = v; last_high_i = i
        longest_gap = max(longest_gap, i - last_high_i)
        peak = max(peak, v); maxdd = max(maxdd, 1 - v / peak) if peak else 0.0
    # longest losing streak over annual periods
    streak = mx = 0
    for r in period_rets:
        streak = streak + 1 if r < 0 else 0; mx = max(mx, streak)
    dist = {'periods': len(period_rets),
            'median_period_pct': round(100 * statistics.median(period_rets), 1) if period_rets else None,
            'share_positive_pct': round(100 * sum(1 for r in period_rets if r > 0) / len(period_rets), 1) if period_rets else None,
            'best_period_pct': round(100 * max(period_rets), 1) if period_rets else None,
            'worst_period_pct': round(100 * min(period_rets), 1) if period_rets else None,
            'period_pcts': [round(100 * r, 1) for r in period_rets],
            'longest_losing_streak_periods': mx,
            'longest_stretch_between_new_highs_months': longest_gap,
            'secondary_average_period_pct': round(100 * statistics.mean(period_rets), 1) if period_rets else None}
    return round(cash, 2), curve, round(total_costs, 2), round(maxdd, 4), dist

ROADS = {'LONGEST_2016_2025': list(range(2016, 2026)),
         'DECADE_2017_2025': list(range(2017, 2026)),
         'CONT_2019_2025': list(range(2019, 2026)),
         'VAL_2023_2025': list(range(2023, 2026)),
         'FOLD_2016_2020': list(range(2016, 2021)),
         'FOLD_2021_2025': list(range(2021, 2026)),
         'HALF_2016_2018': list(range(2016, 2019)),
         'HALF_2019_2021': list(range(2019, 2022)),
         'HALF_2022_2025': list(range(2022, 2026))}

def spy_final(formations):
    a = spy.get(ym(formations[0], 6)); b = spy.get(ym(formations[-1] + 1, 6))
    return round(100 * b / a, 2) if a and b else None

def main():
    out = {'family': 'osap-brand-capital', 'program': 'v13-best-rules',
           'spec': 'BEST-RULES-SPEC.md',
           'pool_sizes_eligible_hist3_native': {str(F): len(POOLS[F]) for F in range(2016, 2026)},
           'roads': {}}
    print('pools', out['pool_sizes_eligible_hist3_native'], flush=True)
    for rname, forms in ROADS.items():
        fin, curve, costs, maxdd, dist = run_road(forms)
        twins = []
        for s in range(1, 21):
            tf, _, _, _, _ = run_road(forms, seed=s); twins.append(tf)
        out['roads'][rname] = {'final': fin, 'costs': costs, 'max_dd': maxdd,
                               'spy_same_window': spy_final(forms),
                               'placebo_finals': twins,
                               'placebos_beaten': sum(1 for t in twins if fin > t),
                               'distribution_annual': dist, 'curve': curve}
        print(rname, fin, 'dd', maxdd, 'spy', spy_final(forms),
              'pb', out['roads'][rname]['placebos_beaten'], flush=True)
    with open(os.path.join(FAM, 'results.json'), 'w') as fh:
        json.dump(out, fh, indent=1)
    print('saved results.json')

if __name__ == '__main__':
    main()
