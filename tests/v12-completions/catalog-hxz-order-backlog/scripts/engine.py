#!/usr/bin/env python3
"""Generic v12 catalog engine (Slice 13) — frozen grid per SPEC.
Reads signals.json in family folder: {family, signals:{name:{direction,pools:{F:{cik:val}}}}}
W04 broad price stack (read-only). June formations, 12-month holds, tiered
program costs, vanished->ZERO, v9 house floor variant, full pre-registered
grid (signal x universe{broad,large} x rulebook{native,house} x cadence
{annual,quarterly,monthly} x counts{1,2,3,5,8,10,15,20,30,ALL,QUINTILE}),
20-seed placebos per cell, folds for confirmation. Simulation only."""
import json, os, math, random
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
FAM = os.path.join(HERE, '..')
W04 = os.path.join(FAM, '..', '..', 'v11-native-rules', '_w04_broad_data')
def loadj(p): return json.load(open(p)) if os.path.exists(p) else {}
SIG = loadj(os.path.join(FAM, 'signals.json'))
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
FORMATIONS = sorted(int(f) for f in next(iter(SIG['signals'].values()))['pools'].keys())
POOLS = {}; MATS = {}
for sname, sdef in SIG['signals'].items():
    for F in FORMATIONS:
        raw = {int(k): v for k, v in sdef['pools'].get(str(F), {}).items()}
        for uni in ('broad', 'large'):
            pool = {}
            for cik, val in raw.items():
                if cik not in px: continue
                e = px[cik].get(ym(F, 6))
                if not e or not e[0]: continue
                cap = cap_of(cik, F)
                if uni == 'large' and (cap is None or cap < 1e9): continue
                pool[cik] = {'sig': val, 'cap': cap, 'rate': cost_rate(cap)}
            POOLS[(sname, F, uni)] = pool
            cols = [ym(F, m) for m in range(6, 13)] + [ym(F + 1, m) for m in range(1, 7)]
            ciks = sorted(pool)
            M = np.full((len(ciks), len(cols)), np.nan)
            for i, cik in enumerate(ciks):
                s = px[cik]; last = None; lastbar = max(s) if s else None
                for j, mm in enumerate(cols):
                    if mm in s: last = s[mm][0]
                    if lastbar is not None and mm > lastbar: M[i, j] = 0.0
                    elif last is not None: M[i, j] = last
            MATS[(sname, F, uni)] = (ciks, M)
def picks_for(sname, F, uni, count):
    pool = POOLS[(sname, F, uni)]
    direction = SIG['signals'][sname]['direction']
    items = sorted(pool.items(), key=lambda kv: -kv[1]['sig'] if direction > 0 else kv[1]['sig'])
    if count == 'ALL': return [c for c, _ in items]
    if count == 'QUINTILE': n = max(1, math.ceil(len(items) * 0.20)); return [c for c, _ in items[:n]]
    return [c for c, _ in items[:min(count, len(items))]]
REBAL = {'annual': {0}, 'quarterly': {0, 3, 6, 9}, 'monthly': set(range(12))}
def run_road(formations, sname, uni, count, cadence, house, seed=None):
    cash = 100.0; peak = 100.0; curve = []; total_costs = 0.0
    for F in formations:
        ciks_all, M = MATS[(sname, F, uni)]
        idx = {c: i for i, c in enumerate(ciks_all)}
        pool = POOLS[(sname, F, uni)]
        if seed is None: picks = picks_for(sname, F, uni, count)
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
        rows = np.array([idx[c] for c in picks]); P = M[rows, :]
        rates = np.array([pool[c]['rate'] for c in picks])
        px0 = P[:, 0].copy(); px0[px0 <= 0] = np.nan
        w = cash / len(picks)
        shares = np.where(np.isnan(px0), 0.0, (w * (1 - rates)) / np.where(np.isnan(px0), 1.0, px0))
        total_costs += float(np.sum(w * rates)); in_cash = False
        for j in range(1, 13):
            if in_cash: curve.append([cols[j], round(cash, 2)]); continue
            pj = P[:, j]; vals = shares * np.where(np.isnan(pj), 0.0, pj); val = float(np.sum(vals))
            if j in REBAL[cadence] and j < 12:
                tgt = val / len(picks); trade = np.abs(tgt - vals)
                cst = float(np.sum(trade * rates)); total_costs += cst
                scale = (val - cst) / val if val > 0 else 0.0; vals = vals * scale
                tgt = float(np.sum(vals)) / len(picks)
                shares = np.where(np.isnan(pj) | (pj <= 0), 0.0, tgt / np.where(np.isnan(pj) | (pj <= 0), 1.0, pj))
                val = float(np.sum(vals))
            if j == 12:
                sell = float(np.sum(vals * rates)); total_costs += sell; cash = val - sell
            else: cash = val
            curve.append([cols[j], round(cash, 2)]); peak = max(peak, cash)
            if house and cash <= 0.85 * peak and j < 12:
                sell = float(np.sum((shares * np.where(np.isnan(P[:, j]), 0.0, P[:, j])) * rates))
                total_costs += sell; cash = cash - sell; in_cash = True
                curve[-1] = [cols[j], round(cash, 2)]
        peak = max(peak, cash)
    peak2 = 100.0; maxdd = 0.0
    for _, v in curve:
        peak2 = max(peak2, v); maxdd = max(maxdd, 1 - v / peak2) if peak2 else 0.0
    return round(cash, 2), curve, round(total_costs, 2), round(maxdd, 4)
def roads():
    f0 = FORMATIONS[0]
    r = {'LONGEST': FORMATIONS,
         'DECADE': [f for f in FORMATIONS if f >= max(2017, f0)],
         'CONT': [f for f in FORMATIONS if f >= max(2019, f0)],
         'VAL': [f for f in FORMATIONS if f >= 2023]}
    half = len(FORMATIONS) // 2
    r['FOLD_A'] = FORMATIONS[:half]; r['FOLD_B'] = FORMATIONS[half:]
    return {k: v for k, v in r.items() if v}
def spy_final(formations):
    a = spy.get(ym(formations[0], 6)); b = spy.get(ym(formations[-1] + 1, 6))
    return round(100 * b / a, 2) if a and b else None
def main():
    counts = [1, 2, 3, 5, 8, 10, 15, 20, 30, 'ALL', 'QUINTILE']
    grid = {}; fences = {}
    for sname in SIG['signals']:
        for F in FORMATIONS:
            for uni in ('broad', 'large'):
                fences[f'{sname}|{F}|{uni}'] = len(POOLS[(sname, F, uni)])
    print('pools', fences, flush=True)
    R = roads()
    for sname in SIG['signals']:
        for uni in ('broad', 'large'):
            for rb in ('native', 'house'):
                house = rb == 'house'
                for cad in ('annual', 'quarterly', 'monthly'):
                    for count in counts:
                        key = f'{sname}|{uni}|{rb}|{cad}|{count}'
                        cell = {}
                        for rname, forms in R.items():
                            fin, curve, costs, maxdd = run_road(forms, sname, uni, count, cad, house)
                            entry = {'final': fin, 'costs': costs, 'max_dd': maxdd, 'spy_same_window': spy_final(forms)}
                            if rname in ('LONGEST', 'DECADE', 'CONT', 'VAL'):
                                twins = []
                                for s in range(1, 21):
                                    tf, _, _, _ = run_road(forms, sname, uni, count, cad, house, seed=s)
                                    twins.append(tf)
                                entry['placebo_finals'] = twins
                                entry['placebos_beaten'] = sum(1 for t in twins if fin > t)
                                entry['curve'] = curve
                            cell[rname] = entry
                        grid[key] = cell
                        print(key, 'LONGEST', cell['LONGEST']['final'], 'pb', cell['LONGEST'].get('placebos_beaten'), flush=True)
    res = {'family': SIG['family'], 'spec': 'SPEC-FROZEN.md', 'formations': FORMATIONS,
           'pool_sizes_eligible': fences, 'grid': grid}
    with open(os.path.join(FAM, 'results.json'), 'w') as fh: json.dump(res, fh, indent=1)
    print('saved results.json')
if __name__ == '__main__': main()
