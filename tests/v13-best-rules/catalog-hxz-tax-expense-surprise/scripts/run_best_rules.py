#!/usr/bin/env python3
"""V13 best-rules run — catalog-hxz-tax-expense-surprise. Frozen by BEST-RULES-SPEC.md.
Tes (catalog Q1 construction, v12 signals reused read-only), broad universe,
HIGH quintile equal weight, annual June formation, SIX-MONTH hold (Jul-Dec)
then cash to next formation, 2018 formation SKIPPED (TCJA straddle),
NO floor, tiered program costs, vanished->ZERO, 20-seed placebos same chassis."""
import json, os, math, random, statistics, time
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); FAM = os.path.join(HERE, '..')
V12 = os.path.join(FAM, '..', '..', 'v12-completions', 'catalog-hxz-tax-expense-surprise')
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
SIG = loadj(os.path.join(V12, 'signals.json'))['signals']['Tes']
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
ALL_FORMS = sorted(int(f) for f in SIG['pools'])
SKIP = {2018}  # TCJA straddle, frozen in spec
POOLS = {}; MATS = {}
for F in ALL_FORMS:
    raw = {int(k): v for k, v in SIG['pools'].get(str(F), {}).items()}
    pool = {}
    for cik, val in raw.items():
        if cik not in px: continue
        e = px[cik].get(ym(F, 6))
        if not e or not e[0]: continue
        cap = cap_of(cik, F)
        pool[cik] = {'sig': val, 'cap': cap, 'rate': cost_rate(cap)}
    POOLS[F] = pool
    # months Jul F .. Jun F+1 (12 marks); invested only first 6 (Jul..Dec)
    cols = [ym(F, m) for m in range(7, 13)] + [ym(F + 1, m) for m in range(1, 7)]
    base = [ym(F, 6)] + cols
    allciks = sorted(pool)
    M = np.full((len(allciks), len(base)), np.nan)
    for i, cik in enumerate(allciks):
        s = px[cik]; last = None; lastbar = max(s) if s else None
        for j, mm in enumerate(base):
            if mm in s: last = s[mm][0]
            if lastbar is not None and mm > lastbar: M[i, j] = 0.0
            elif last is not None: M[i, j] = last
    MATS[F] = ({c: i for i, c in enumerate(allciks)}, M, cols)
def picks_for(F, seed=None):
    pool = POOLS[F]
    n = max(1, math.ceil(len(pool) * 0.20))
    if seed is None:
        items = sorted(pool.items(), key=lambda kv: -kv[1]['sig'])  # long HIGH
        return [c for c, _ in items[:n]]
    rng = random.Random(seed * 100003 + F); keys = list(pool.keys()); rng.shuffle(keys)
    return keys[:n]
def run_road(formations, seed=None):
    cash = 100.0; curve = []; total_costs = 0.0
    for F in formations:
        idx, M, cols = MATS[F]; pool = POOLS[F]
        if F in SKIP:
            for mm in cols: curve.append([mm, round(cash, 2)])
            continue
        picks = picks_for(F, seed)
        if not picks:
            for mm in cols: curve.append([mm, round(cash, 2)])
            continue
        rows = np.array([idx[c] for c in picks]); P = M[rows, :]
        rates = np.array([pool[c]['rate'] for c in picks])
        px0 = P[:, 0].copy(); px0[px0 <= 0] = np.nan
        w = cash / len(picks)
        shares = np.where(np.isnan(px0), 0.0, (w * (1 - rates)) / np.where(np.isnan(px0), 1.0, px0))
        total_costs += float(np.sum(w * rates))
        for j in range(1, 13):
            if j <= 6:  # Jul..Dec invested
                pj = P[:, j]; vals = shares * np.where(np.isnan(pj), 0.0, pj); val = float(np.sum(vals))
                if j == 6:
                    sell = float(np.sum(vals * rates)); total_costs += sell; cash = val - sell
                else: cash = val
            # j>6: cash, flat
            curve.append([cols[j - 1], round(cash, 2)])
    peak2 = 100.0; maxdd = 0.0
    for _, v in curve:
        peak2 = max(peak2, v); maxdd = max(maxdd, 1 - v / peak2) if peak2 else 0.0
    return round(cash, 2), curve, round(total_costs, 2), round(maxdd, 4)
def spy_curve_final(formations):
    a = spy.get(ym(formations[0], 6)); b = spy.get(ym(formations[-1] + 1, 6))
    return round(100 * b / a, 2) if a and b else None
def period_stats(curve):
    vals = [100.0] + [v for _, v in curve]
    rets = [vals[i] / vals[i - 12] - 1 for i in range(12, len(vals), 12)]
    if not rets: return None
    run = worst = 0
    for r in rets:
        run = run + 1 if r <= 0 else 0; worst = max(worst, run)
    peak = vals[0]; cur = longest = 0
    for v in vals:
        if v >= peak: peak = v; cur = 0
        else: cur += 1; longest = max(longest, cur)
    return {'periods': len(rets), 'positive': sum(1 for r in rets if r > 0),
            'median_pct': round(statistics.median(rets) * 100, 1),
            'mean_pct_secondary': round(statistics.mean(rets) * 100, 1),
            'best_pct': round(max(rets) * 100, 1), 'worst_pct': round(min(rets) * 100, 1),
            'yearly_pct': [round(r * 100, 1) for r in rets],
            'longest_losing_streak_periods': worst,
            'longest_months_between_highs': longest}
ROADS = {'LONG': ALL_FORMS, 'DECADE': [f for f in ALL_FORMS if f >= 2017],
         'CONT': [f for f in ALL_FORMS if f >= 2019], 'VAL': [f for f in ALL_FORMS if f >= 2023]}
CHAMP = {'LONG': 1415.62, 'DECADE': 667.35, 'CONT': 544.47, 'VAL': 288.05}
SPYREF = {'LONG': 822.94, 'DECADE': 367.80, 'CONT': 313.62, 'VAL': 187.77}
PUBLISHED = {'LONG': 585.66, 'DECADE': 488.52, 'CONT': 388.10, 'VAL': 218.57}  # v12 Tes12 quintile, its own (LONGEST) window naming
PUBLISHED_BEST = {'LONG': 874.56, 'DECADE': 705.19, 'CONT': 573.88, 'VAL': 318.93}  # v12 confirming variant count-30
def main():
    t0 = time.time(); roads = {}
    for rname, forms in ROADS.items():
        fin, curve, costs, maxdd = run_road(forms)
        twins = []
        for sd in range(1, 21):
            tf, _, _, _ = run_road(forms, seed=sd); twins.append(tf)
        roads[rname] = {'formations': forms, 'final': fin, 'costs': costs, 'max_dd': maxdd,
                        'spy_same_window_habitat': spy_curve_final(forms), 'spy_program_reference': SPYREF[rname],
                        'champion_vm': CHAMP[rname], 'published_tes12_quintile': PUBLISHED[rname],
                        'published_best_variant_count30': PUBLISHED_BEST[rname],
                        'placebo_finals': twins, 'placebos_beaten': sum(1 for t in twins if fin > t),
                        'placebo_median': round(statistics.median(twins), 2),
                        'period_stats': period_stats(curve), 'curve': curve}
        print(rname, fin, 'dd', maxdd, 'pb', roads[rname]['placebos_beaten'], '/20', flush=True)
    # confirmation diagnostics (always computed, used only if a road beats champion)
    conf = {}
    for rname, forms in ROADS.items():
        half = len(forms) // 2
        fa, fb = forms[:half], forms[half:]
        out = {}
        for nm, fs in (('fold_first_half', fa), ('fold_second_half', fb)):
            fin, _, _, dd = run_road(fs)
            out[nm] = {'formations': fs, 'final': fin, 'max_dd': dd, 'spy_habitat': spy_curve_final(fs), 'beats_spy': fin > (spy_curve_final(fs) or 1e18)}
        # half-windows by calendar months of the road curve
        curve = roads[rname]['curve']; mid = len(curve) // 2
        start = 100.0
        h1 = curve[mid - 1][1] if mid else start
        # half-window finals measured as standalone $100 pots over each half's formations
        out['half_windows_formations'] = {'first': fa, 'second': fb}
        conf[rname] = out
    res = {'program': 'v13-best-rules', 'family': 'catalog-hxz-tax-expense-surprise',
           'spec': 'BEST-RULES-SPEC.md (frozen before run)',
           'my_rules': {'signal': 'Tes Q1 seasonal difference (catalog construction), long HIGH',
                        'universe': 'broad W04 stack, PIT June-after-filing formation',
                        'holdings': 'high quintile, equal weight', 'cadence': 'annual June, 6-month hold (Tes6) then cash',
                        'tcja': '2018 formation skipped (seasonal difference straddles TCJA)',
                        'protections': 'none (no floor)', 'costs': 'tiered program costs, vanished->ZERO', 'start_cash': 100.0},
           'pool_sizes': {str(F): len(POOLS[F]) for F in ALL_FORMS},
           'roads': roads, 'confirmation_diagnostics': conf, 'elapsed_sec': round(time.time() - t0, 1)}
    with open(os.path.join(FAM, 'results.json'), 'w') as fh: json.dump(res, fh, indent=1)
    print('saved results.json')
if __name__ == '__main__': main()
