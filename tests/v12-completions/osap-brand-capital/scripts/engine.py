#!/usr/bin/env python3
"""osap-brand-capital v12 engine — frozen by SPEC-FROZEN.md.
BrandInvest = xad/BC, BrandCapital = BC/at; BC perpetual inventory
(first year xad/0.6, then BC=0.5*BC_prev+xad; a missing-xad year breaks
the chain and the next present year restarts as a first year).
W04 broad price stack (read-only) + EDGAR frames AdvertisingExpense
(this folder) + W04 Assets/Shares frames (read-only). June formations,
12-month holds, tiered program costs, vanished->ZERO, v9 house floor
variant, full pre-registered grid, 20-seed placebos per cell.
Simulation only. Writes only results.json in this family folder."""
import json, os, math, random
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FAM = os.path.join(HERE, '..')
W04 = os.path.join(FAM, '..', '..', 'v11-native-rules', '_w04_broad_data')
FR = os.path.join(FAM, 'data', 'frames')

def loadj(p):
    return json.load(open(p)) if os.path.exists(p) else {}

# ---------- data ----------
cand = {int(k): v for k, v in loadj(os.path.join(W04, 'candidates.json')).items()}
px = {}   # cik -> {ym:(adj,raw)}
for cik, info in cand.items():
    t = info['ticker'].replace('/', '-')
    p = os.path.join(W04, f'px_{t}.json')
    if os.path.exists(p):
        try: px[cik] = {r[0]: (r[1], r[2]) for r in loadj(p)}
        except Exception: pass
spy = {r[0]: r[1] for r in loadj(os.path.join(W04, 'px_SPY.json'))}
months_all = sorted(spy)
midx = {m: i for i, m in enumerate(months_all)}

xad = {}  # year -> {cik:val}
for y in range(2009, 2026):
    xad[y] = {int(k): v for k, v in loadj(os.path.join(FR, f'AdvertisingExpense_{y}D.json')).items()}
assets = {}; shares_f = {}
for y in range(2009, 2026):
    assets[y] = {int(k): v for k, v in loadj(os.path.join(W04, 'frames', f'Assets_{y}I.json')).items()}
    shares_f[y] = {int(k): v for k, v in loadj(os.path.join(W04, 'frames', f'Shares_{y}I.json')).items()}

# split factors (W04 chassis convention)
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

# brand capital per cik per year (year = fiscal year of xad)
BC = {}   # cik -> {year: bc}
for cik in cand:
    bc = {}; prev = None; prev_y = None
    for y in range(2009, 2026):
        v = xad[y].get(cik)
        if v is None:
            prev = None; prev_y = None; continue
        if prev is None or prev_y != y - 1:
            cur = v / 0.6
        else:
            cur = 0.5 * prev + v
        bc[y] = cur; prev = cur; prev_y = y
    if bc: BC[cik] = bc

def ym(y, m): return f'{y:04d}-{m:02d}'

# pools per formation per universe
POOLS = {}
for F in range(2016, 2026):
    for uni in ('native', 'broad'):
        pool = {}
        for cik, bc in BC.items():
            if (F - 1) not in bc or bc[F - 1] <= 0 or xad[F - 1].get(cik, 0) <= 0: continue
            if cik not in px: continue
            e = px[cik].get(ym(F, 6))
            if not e or not e[0]: continue
            at = assets.get(F - 1, {}).get(cik)
            if not at: continue
            if uni == 'native':
                sic = str(cand[cik].get('sic') or '')
                if sic[:1] in ('4', '6'): continue
            cap = cap_of(cik, F)
            pool[cik] = {'bi': xad[F - 1][cik] / bc[F - 1], 'bc_at': bc[F - 1] / at,
                         'cap': cap, 'rate': cost_rate(cap), 'px0': e[0]}
        POOLS[(F, uni)] = pool

# price-path matrices per formation: rows = pool ciks (fixed order), cols = months Jun F .. Jun F+1 (13)
MATS = {}
for F in range(2016, 2026):
    cols = [ym(F, m) for m in range(6, 13)] + [ym(F + 1, m) for m in range(1, 7)]
    for uni in ('native', 'broad'):
        pool = POOLS[(F, uni)]
        ciks = sorted(pool)
        M = np.full((len(ciks), len(cols)), np.nan)
        for i, cik in enumerate(ciks):
            s = px[cik]; last = None; lastbar = max(s) if s else None
            for j, mm in enumerate(cols):
                if mm in s: last = s[mm][0]
                if lastbar is not None and mm > lastbar:
                    M[i, j] = 0.0          # vanished -> ZERO
                elif last is not None:
                    M[i, j] = last         # gap months carried at last price
        MATS[(F, uni)] = (ciks, M)

def picks_for(F, uni, signal, count):
    pool = POOLS[(F, uni)]
    items = list(pool.items())
    if signal == 'BrandInvest':
        items.sort(key=lambda kv: kv[1]['bi'])          # long LOW
    else:
        items.sort(key=lambda kv: -kv[1]['bc_at'])      # long HIGH (imposed)
    if count == 'ALL':
        return [c for c, _ in items]
    if count == 'QUINTILE':
        n = max(1, math.ceil(len(items) * 0.20))
        return [c for c, _ in items[:n]]
    return [c for c, _ in items[:min(count, len(items))]]

REBAL = {'annual': {0}, 'quarterly': {0, 3, 6, 9}, 'monthly': set(range(12))}

def run_road(formations, uni, signal, count, cadence, house, seed=None):
    """Returns (final, curve list of [ym,val], costs). Curve monthly marks Jun..Jun."""
    cash = 100.0; peak = 100.0; curve = []; total_costs = 0.0; floored = False
    for F in formations:
        ciks_all, M = MATS[(F, uni)]
        idx = {c: i for i, c in enumerate(ciks_all)}
        pool = POOLS[(F, uni)]
        if seed is None:
            picks = picks_for(F, uni, signal, count)
        else:
            rng = random.Random(seed * 100003 + F)
            keys = list(pool.keys()); rng.shuffle(keys)
            if count == 'ALL': n = len(keys)
            elif count == 'QUINTILE': n = max(1, math.ceil(len(keys) * 0.20))
            else: n = min(count, len(keys))
            picks = keys[:n]
        cols = [ym(F, m) for m in range(6, 13)] + [ym(F + 1, m) for m in range(1, 7)]
        if not picks:
            for mm in cols[1:]: curve.append([mm, round(cash, 2)])
            continue
        rows = np.array([idx[c] for c in picks])
        P = M[rows, :]                       # n x 13 prices (col0 = formation)
        rates = np.array([pool[c]['rate'] for c in picks])
        px0 = P[:, 0].copy(); px0[px0 <= 0] = np.nan
        # initial buy: equal weight, buy costs per name
        w = cash / len(picks)
        shares = np.where(np.isnan(px0), 0.0, (w * (1 - rates)) / np.where(np.isnan(px0), 1.0, px0))
        total_costs += float(np.sum(w * rates)); n_orders = len(picks)
        in_cash = False
        for j in range(1, 13):
            if in_cash:
                curve.append([cols[j], round(cash, 2)]); continue
            pj = P[:, j]
            vals = shares * np.where(np.isnan(pj), 0.0, pj)
            val = float(np.sum(vals))
            if j in REBAL[cadence] and j < 12:
                # re-equalize: trade to equal weights, costs on traded value
                tgt = val / len(picks)
                trade = np.abs(tgt - vals)
                cst = float(np.sum(trade * rates))
                total_costs += cst
                scale = (val - cst) / val if val > 0 else 0.0
                vals = vals * scale
                tgt = float(np.sum(vals)) / len(picks)
                shares = np.where(np.isnan(pj) | (pj <= 0), 0.0, tgt / np.where(np.isnan(pj) | (pj <= 0), 1.0, pj))
                val = float(np.sum(vals))
            if j == 12:
                sell = float(np.sum(vals * rates)); total_costs += sell
                cash = val - sell
            else:
                cash = val
            curve.append([cols[j], round(cash, 2)])
            peak = max(peak, cash)
            if house and cash <= 0.85 * peak and j < 12:
                sell = float(np.sum((shares * np.where(np.isnan(P[:, j]), 0.0, P[:, j])) * rates))
                total_costs += sell; cash = cash - sell; in_cash = True
                curve[-1] = [cols[j], round(cash, 2)]
        peak = max(peak, cash)
    peak2 = 100.0; maxdd = 0.0
    for _, v in curve:
        peak2 = max(peak2, v); maxdd = max(maxdd, 1 - v / peak2) if peak2 else 0.0
    return round(cash, 2), curve, round(total_costs, 2), round(maxdd, 4)

ROADS = {'LONGEST_2016_2025': list(range(2016, 2026)),
         'DECADE_2017_2025': list(range(2017, 2026)),
         'CONT_2019_2025': list(range(2019, 2026)),
         'VAL_2023_2025': list(range(2023, 2026)),
         'FOLD_2016_2020': list(range(2016, 2021)),
         'FOLD_2021_2025': list(range(2021, 2026))}

def spy_final(formations):
    a = spy.get(ym(formations[0], 6)); b = spy.get(ym(formations[-1] + 1, 6))
    return round(100 * b / a, 2) if a and b else None

def main():
    counts = [1, 2, 3, 5, 8, 10, 15, 20, 30, 'ALL', 'QUINTILE']
    grid = {}
    fences = {f'{F}|{u}': len(POOLS[(F, u)]) for F in range(2016, 2026) for u in ('native', 'broad')}
    print('pool sizes', fences, flush=True)
    for signal in ('BrandInvest', 'BrandCapital'):
        for uni in ('native', 'broad'):
            for rb in ('native', 'house'):
                house = rb == 'house'
                for cad in ('annual', 'quarterly', 'monthly'):
                    for count in counts:
                        key = f'{signal}|{uni}|{rb}|{cad}|{count}'
                        cell = {}
                        for rname, forms in ROADS.items():
                            fin, curve, costs, maxdd = run_road(forms, uni, signal, count, cad, house)
                            twins = []
                            for s in range(1, 21):
                                tf, _, _, _ = run_road(forms, uni, signal, count, cad, house, seed=s)
                                twins.append(tf)
                            cell[rname] = {'final': fin, 'costs': costs, 'max_dd': maxdd,
                                           'spy_same_window': spy_final(forms),
                                           'placebo_finals': twins,
                                           'placebos_beaten': sum(1 for t in twins if fin > t),
                                           'curve': curve}
                        grid[key] = cell
                        print(key, 'LONGEST', cell['LONGEST_2016_2025']['final'],
                              'pb', cell['LONGEST_2016_2025']['placebos_beaten'], flush=True)
    res = {'family': 'osap-brand-capital', 'spec': 'SPEC-FROZEN.md',
           'pool_sizes_eligible': fences, 'grid': grid}
    with open(os.path.join(FAM, 'results.json'), 'w') as fh:
        json.dump(res, fh, indent=1)
    print('saved results.json')

if __name__ == '__main__':
    main()
