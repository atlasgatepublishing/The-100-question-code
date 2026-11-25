#!/usr/bin/env python3
"""V13 best-rules run: catalog-hxz-investment-growth.
Frozen config (BEST-RULES-SPEC.md): signal COMP (rank blend of IA & dPia,
long LOW), QUINTILE breadth, annual June formation, 12m hold, NO floor,
program tiered costs, vanished->ZERO. Comparator: published IA quintile,
same chassis. 20-seed placebos per road. Writes results.json in this folder only.
Inputs (read-only): W04 broad stack + v12 family-local frames."""
import json, os, math, random, sys
import numpy as np

HOME = os.path.expanduser('~')
OUT = os.path.join(HOME, 'workspace/stock-app/backtests/v13-best-rules/catalog-hxz-investment-growth')
W04 = os.path.join(HOME, 'workspace/stock-app/backtests/v11-native-rules/_w04_broad_data')
EXTRA = os.path.join(HOME, 'workspace/stock-app/backtests/v12-completions/catalog-hxz-investment-growth/data/frames')

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
        if not d:
            d = loadj(os.path.join(EXTRA, f'{concept}_{y}{unit}.json'))
        out[y] = {int(k): v for k, v in d.items()}
    return out

FR = {c: frame(c, u) for c, u in [('Assets', 'I'), ('Shares', 'I'),
        ('PropertyPlantAndEquipmentNet', 'I'),
        ('PaymentsToAcquirePropertyPlantAndEquipment', 'D')]}

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

def sig_investment(F):
    ia, dp = {}, {}
    for cik in cand:
        cx, a1 = g('PaymentsToAcquirePropertyPlantAndEquipment', F-1, cik), g('Assets', F-1, cik)
        if cx is not None and a1: ia[cik] = cx / a1
        p1, p0 = g('PropertyPlantAndEquipmentNet', F-1, cik), g('PropertyPlantAndEquipmentNet', F-2, cik)
        if None not in (p1, p0) and a1: dp[cik] = (p1 - p0) / a1
    comp = {}
    both = [c for c in ia if c in dp]
    if len(both) >= 10:
        def rank(d):
            s = sorted(d, key=lambda c: d[c]); return {c: i / (len(s) - 1) for i, c in enumerate(s)}
        ra, rd = rank({c: ia[c] for c in both}), rank({c: dp[c] for c in both})
        comp = {c: (ra[c] + rd[c]) / 2 for c in both}
    return {'IA': ia, 'COMP': comp}

POOLS = {}; MATS = {}
for F in range(2016, 2026):
    sigs = sig_investment(F)
    cols = [ym(F, m) for m in range(6, 13)] + [ym(F+1, m) for m in range(1, 7)]
    for sname, vals in sigs.items():
        pool = {}
        for cik, v in vals.items():
            if cik not in px: continue
            e = px[cik].get(ym(F, 6))
            if not e or not e[0]: continue
            cap = cap_of(cik, F)
            pool[cik] = {'sig': v, 'cap': cap, 'rate': cost_rate(cap)}
        POOLS[(F, sname)] = pool
        ciks = sorted(pool)
        M = np.full((len(ciks), len(cols)), np.nan)
        for i, cik in enumerate(ciks):
            s = px[cik]; last = None; lastbar = max(s) if s else None
            for j, mm in enumerate(cols):
                if mm in s: last = s[mm][0]
                if lastbar is not None and mm > lastbar: M[i, j] = 0.0
                elif last is not None: M[i, j] = last
        MATS[(F, sname)] = (ciks, M)

def picks_for(F, sname):
    pool = POOLS[(F, sname)]
    items = sorted(pool.items(), key=lambda kv: kv[1]['sig'])  # long LOW
    n = max(1, math.ceil(len(items) * 0.20))
    return [c for c, _ in items[:n]]

def run_road(formations, sname, seed=None):
    cash = 100.0; curve = []; total_costs = 0.0; annual = []
    for F in formations:
        start_val = cash
        ciks_all, M = MATS[(F, sname)]
        idx = {c: i for i, c in enumerate(ciks_all)}
        pool = POOLS[(F, sname)]
        if seed is None:
            picks = picks_for(F, sname)
        else:
            rng = random.Random(seed * 100003 + F)
            keys = list(pool.keys()); rng.shuffle(keys)
            n = max(1, math.ceil(len(keys) * 0.20))
            picks = keys[:n]
        cols = [ym(F, m) for m in range(6, 13)] + [ym(F+1, m) for m in range(1, 7)]
        if not picks:
            for mm in cols[1:]: curve.append([mm, round(cash, 2)])
            annual.append(0.0); continue
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
        annual.append(round(cash / start_val - 1, 4) if start_val else 0.0)
    peak2 = 100.0; maxdd = 0.0; peak_at = None; last_high_t = 0; longest_gap = 0
    run_peak = 100.0
    for i, (_, v) in enumerate(curve):
        if v >= run_peak:
            run_peak = v; longest_gap = max(longest_gap, i - last_high_t); last_high_t = i
        peak2 = max(peak2, v); maxdd = max(maxdd, 1 - v / peak2) if peak2 else 0.0
    longest_gap = max(longest_gap, len(curve) - 1 - last_high_t)
    return {'final': round(cash, 2), 'curve': curve, 'costs': round(total_costs, 2),
            'max_dd': round(maxdd, 4), 'annual_rets': annual,
            'months_between_highs_max': longest_gap}

def spy_final(formations):
    a = spy.get(ym(formations[0], 6)); b = spy.get(ym(formations[-1] + 1, 6))
    return round(100 * b / a, 2) if a and b else None

def distribution(res):
    a = res['annual_rets']
    if not a: return {}
    srt = sorted(a); n = len(a)
    med = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2
    streak = cur = 0
    for r in a:
        cur = cur + 1 if r < 0 else 0; streak = max(streak, cur)
    return {'periods': n, 'median_period': round(med, 4),
            'share_positive': round(sum(1 for r in a if r > 0) / n, 3),
            'best_period': round(max(a), 4), 'worst_period': round(min(a), 4),
            'longest_losing_streak': streak,
            'longest_months_between_new_highs': res['months_between_highs_max'],
            'mean_period_secondary': round(sum(a) / n, 4),
            'annual_rets': a}

ROADS = {'LONGEST_2016_2025': list(range(2016, 2026)), 'DECADE_2017_2025': list(range(2017, 2026)),
         'CONT_2019_2025': list(range(2019, 2026)), 'VAL_2023_2025': list(range(2023, 2026)),
         'FOLD_2016_2020': list(range(2016, 2021)), 'FOLD_2021_2025': list(range(2021, 2026)),
         'CONT_HALF1_2019_2022': list(range(2019, 2023)), 'CONT_HALF2_2023_2025': list(range(2023, 2026))}

def main():
    log = []
    fences = {f'{F}|{s}': len(POOLS[(F, s)]) for (F, s) in sorted(POOLS.keys())}
    log.append(f'pools {fences}')
    out = {'family': 'catalog-hxz-investment-growth', 'program': 'v13-best-rules',
           'spec': 'BEST-RULES-SPEC.md', 'pool_sizes_eligible': fences, 'configs': {}}
    for sname, label in [('COMP', 'my_rules'), ('IA', 'published_form')]:
        cfg = {}
        for rname, forms in ROADS.items():
            res = run_road(forms, sname)
            twins = []
            for sd in range(1, 21):
                t = run_road(forms, sname, seed=sd)
                twins.append(t['final'])
            entry = {'final': res['final'], 'costs': res['costs'], 'max_dd': res['max_dd'],
                     'spy_same_window': spy_final(forms), 'curve': res['curve'],
                     'placebo_finals': twins,
                     'placebos_beaten': sum(1 for t in twins if res['final'] > t),
                     'distribution_annual': distribution(res)}
            cfg[rname] = entry
            log.append(f"{label} {rname} final {res['final']} dd {res['max_dd']} spy {entry['spy_same_window']} pb {entry['placebos_beaten']}/20")
        out['configs'][label] = cfg
    with open(os.path.join(OUT, 'results.json'), 'w') as fh:
        json.dump(out, fh, indent=1)
    with open(os.path.join(OUT, 'run.log'), 'w') as fh:
        fh.write('\n'.join(log) + '\n')
    print('\n'.join(log)); print('saved results.json')

if __name__ == '__main__':
    main()
