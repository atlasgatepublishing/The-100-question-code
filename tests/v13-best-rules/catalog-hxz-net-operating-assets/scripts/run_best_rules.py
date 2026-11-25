#!/usr/bin/env python3
"""V13 best-rules run — catalog-hxz-net-operating-assets. Frozen by
BEST-RULES-SPEC.md. Signal: Noa exactly as the catalog/v12 defines it,
universe minus SIC first-digit 6, lowest quintile, equal weight, annual
June formations, NO floor, tiered program costs, vanished->ZERO,
20-seed placebos sharing the chassis. Mechanics replicate the v12
engine exactly (read-only inputs). Also recomputes the v12 published
cell (all-SIC quintile) as an integrity check / verdict comparator."""
import json, os, math, random, statistics, time
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); FAM = os.path.join(HERE, '..')
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
def frame(concept, unit):
    out = {}
    for y in range(2014, 2026):
        out[y] = {int(k): v for k, v in loadj(os.path.join(W04, 'frames', f'{concept}_{y}{unit}.json')).items()}
    return out
FR = {c: frame(c, u) for c, u in [('Assets', 'I'), ('CashAndCashEquivalentsAtCarryingValue', 'I'),
        ('Liabilities', 'I'), ('DebtCurrent', 'I'), ('LongTermDebt', 'I'),
        ('LongTermDebtNoncurrent', 'I'), ('Shares', 'I')]}
def g(concept, y, cik): return FR[concept].get(y, {}).get(cik)
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
    sh = g('Shares', F - 1, cik) or g('Shares', F - 2, cik)
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
def total_debt(y, cik):
    dc = g('DebtCurrent', y, cik); ltn = g('LongTermDebtNoncurrent', y, cik); lt = g('LongTermDebt', y, cik)
    if dc is not None and ltn is not None: return dc + ltn
    if lt is not None: return lt
    if dc is not None: return dc
    return ltn
def ym(y, m): return f'{y:04d}-{m:02d}'
def sig_noa(F):
    out = {}
    def num(y, cik):
        a, c, l = g('Assets', y, cik), g('CashAndCashEquivalentsAtCarryingValue', y, cik), g('Liabilities', y, cik)
        d = total_debt(y, cik)
        if None in (a, c, l, d): return None
        return (a - c) - (l - d)
    for cik in cand:
        n1, a0 = num(F - 1, cik), g('Assets', F - 2, cik)
        if n1 is None or not a0: continue
        out[cik] = n1 / a0
    return out

def build_pools(exclude_sic6):
    pools, mats = {}, {}
    for F in range(2016, 2026):
        vals = sig_noa(F)
        pool = {}
        for cik, v in vals.items():
            if cik not in px: continue
            e = px[cik].get(ym(F, 6))
            if not e or not e[0]: continue
            if exclude_sic6 and str(cand[cik].get('sic') or '')[:1] == '6': continue
            cap = cap_of(cik, F)
            pool[cik] = {'sig': v, 'cap': cap, 'rate': cost_rate(cap)}
        pools[F] = pool
        cols = [ym(F, m) for m in range(6, 13)] + [ym(F + 1, m) for m in range(1, 7)]
        ciks = sorted(pool)
        M = np.full((len(ciks), len(cols)), np.nan)
        for i, cik in enumerate(ciks):
            s = px[cik]; last = None; lastbar = max(s) if s else None
            for j, mm in enumerate(cols):
                if mm in s: last = s[mm][0]
                if lastbar is not None and mm > lastbar: M[i, j] = 0.0
                elif last is not None: M[i, j] = last
        mats[F] = (ciks, M)
    return pools, mats

POOLS, MATS = build_pools(True)          # my rules: SIC-6 excluded
POOLS_PUB, MATS_PUB = build_pools(False) # published form: all-SIC

def picks_for(pool, seed=None):
    n = max(1, math.ceil(len(pool) * 0.20))
    if seed is None:
        items = sorted(pool.items(), key=lambda kv: kv[1]['sig'])  # dir=low
        return [c for c, _ in items[:n]]
    rng = random.Random(seed * 100003 + id(pool) % 997)
    keys = list(pool.keys()); rng.shuffle(keys)
    return keys[:n]

def run_road(formations, pools, mats, seed=None):
    cash = 100.0; curve = []; total_costs = 0.0
    for F in formations:
        ciks_all, M = mats[F]; idx = {c: i for i, c in enumerate(ciks_all)}
        pool = pools[F]
        if seed is None:
            picks = picks_for(pool)
        else:
            rng = random.Random(seed * 100003 + F)
            keys = list(pool.keys()); rng.shuffle(keys)
            picks = keys[:max(1, math.ceil(len(keys) * 0.20))]
        cols = [ym(F, m) for m in range(6, 13)] + [ym(F + 1, m) for m in range(1, 7)]
        if not picks:
            for mm in cols[1:]: curve.append([mm, round(cash, 2)])
            continue
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
    return round(cash, 2), curve, round(total_costs, 2), round(maxdd, 4)

def spy_final(formations):
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

ROADS = {'LONG': list(range(2016, 2026)), 'DECADE': list(range(2017, 2026)),
         'CONT': list(range(2019, 2026)), 'VAL': list(range(2023, 2026))}
CHAMP = {'LONG': 1415.62, 'DECADE': 667.35, 'CONT': 544.47, 'VAL': 288.05}
SPYREF = {'LONG': 822.94, 'DECADE': 367.80, 'CONT': 313.62, 'VAL': 187.77}
PUBLISHED_V12 = {'LONG': 361.07, 'DECADE': 279.30, 'CONT': 239.26, 'VAL': 183.15}

def main():
    t0 = time.time(); roads = {}; pub = {}
    for rname, forms in ROADS.items():
        fin, curve, costs, maxdd = run_road(forms, POOLS, MATS)
        twins = []
        for sd in range(1, 21):
            tf, _, _, _ = run_road(forms, POOLS, MATS, seed=sd); twins.append(tf)
        pfin, pcurve, pcosts, pmaxdd = run_road(forms, POOLS_PUB, MATS_PUB)
        pub[rname] = {'final': pfin, 'costs': pcosts, 'max_dd': pmaxdd,
                      'v12_recorded': PUBLISHED_V12[rname],
                      'reproduces_v12': abs(pfin - PUBLISHED_V12[rname]) < 0.02}
        roads[rname] = {'formations': forms, 'final': fin, 'costs': costs, 'max_dd': maxdd,
                        'spy_same_window_habitat': spy_final(forms), 'spy_program_reference': SPYREF[rname],
                        'champion_vm': CHAMP[rname], 'published_noa_quintile_v12': PUBLISHED_V12[rname],
                        'published_noa_quintile_recomputed': pfin,
                        'placebo_finals': twins, 'placebos_beaten': sum(1 for t in twins if fin > t),
                        'placebo_median': round(statistics.median(twins), 2),
                        'period_stats': period_stats(curve), 'curve': curve}
        print(rname, 'mine', fin, 'dd', maxdd, 'pb', roads[rname]['placebos_beaten'], '/20',
              '| published recomputed', pfin, 'v12', PUBLISHED_V12[rname], flush=True)
    # Confirmation trigger check (frozen bars in spec)
    triggered = [r for r in ROADS if roads[r]['final'] > CHAMP[r]]
    confirmation = {'triggered_roads': triggered, 'run': False}
    if triggered:
        confirmation['run'] = True; confirmation['detail'] = {}
        for rname in triggered:
            forms = ROADS[rname]
            yrs_mine = {}; yrs_pub = {}
            for F in forms:
                yrs_mine[F], _, _, _ = run_road([F], POOLS, MATS)
                yrs_pub[F], _, _, _ = run_road([F], POOLS_PUB, MATS_PUB)
            half = len(forms) // 2
            h1m, _, _, _ = run_road(forms[:half], POOLS, MATS); h1p, _, _, _ = run_road(forms[:half], POOLS_PUB, MATS_PUB)
            h2m, _, _, _ = run_road(forms[half:], POOLS, MATS); h2p, _, _, _ = run_road(forms[half:], POOLS_PUB, MATS_PUB)
            wins = sum(1 for F in forms if yrs_mine[F] > yrs_pub[F])
            confirmation['detail'][rname] = {
                'yearly_mine': yrs_mine, 'yearly_published': yrs_pub,
                'yearly_win_share': round(wins / len(forms), 3), 'yearly_bar_0.60': wins / len(forms) >= 0.60,
                'half1': {'mine': h1m, 'published': h1p}, 'half2': {'mine': h2m, 'published': h2p},
                'halves_won': int(h1m > h1p) + int(h2m > h2p), 'halves_bar_ge1': (h1m > h1p) or (h2m > h2p)}
            c = confirmation['detail'][rname]
            c['confirmed'] = bool(c['yearly_bar_0.60'] and c['halves_bar_ge1'])
    res = {'program': 'v13-best-rules', 'family': 'catalog-hxz-net-operating-assets',
           'spec': 'BEST-RULES-SPEC.md (frozen before run)',
           'my_rules': {'signal': 'Noa = [(Assets-Cash)-(Liabilities-Debt)]_{F-1}/Assets_{F-2} (catalog construction), low=good',
                        'universe': 'W04 stack minus SIC first-digit 6 (financials), PIT June lag',
                        'holdings': 'lowest quintile, equal weight', 'cadence': 'annual June, 12m hold',
                        'protections': 'none (no floor)', 'costs': 'tiered program costs, vanished->ZERO',
                        'start_cash': 100.0},
           'pool_sizes': {str(F): len(POOLS[F]) for F in range(2016, 2026)},
           'pool_sizes_published_all_sic': {str(F): len(POOLS_PUB[F]) for F in range(2016, 2026)},
           'integrity_published_replication': pub,
           'roads': roads, 'confirmation': confirmation,
           'elapsed_sec': round(time.time() - t0, 1)}
    with open(os.path.join(FAM, 'results.json'), 'w') as fh: json.dump(res, fh, indent=1)
    print('confirmation triggered:', triggered)
    print('saved results.json')
if __name__ == '__main__': main()
