#!/usr/bin/env python3
"""Slice-12 generic HXZ engine — frozen by each family's SPEC-FROZEN.md.
Usage: slice12_engine.py <family-slug>
Reads W04 broad stack (read-only) + family-local frames in
/tmp/slice12_frames + W04 frames. June formations, 12m holds, tiered
costs, vanished->ZERO, v9 house floor variant, pre-registered grid,
20-seed placebos. Writes results.json in the family folder only."""
import json, os, math, random, sys
import numpy as np

SLUG = sys.argv[1]
BASE = '/home/hatch/workspace/stock-app/backtests/v12-completions'
FAM = os.path.join(BASE, SLUG)
W04 = os.path.join(BASE, '..', 'v11-native-rules', '_w04_broad_data')
EXTRA = '/tmp/slice12_frames'

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
months_all = sorted(spy); midx = {m: i for i, m in enumerate(months_all)}

def frame(concept, unit):
    """unit 'I' instant Q4 or 'D' duration annual. W04 first, then extra."""
    out = {}
    for y in range(2014, 2026):
        d = loadj(os.path.join(W04, 'frames', f'{concept}_{y}{unit}.json'))
        if not d:
            d = loadj(os.path.join(EXTRA, f'{concept}_{y}{unit}.json'))
        out[y] = {int(k): v for k, v in d.items()}
    return out

FR = {}
for c, u in [('Assets','I'),('AssetsCurrent','I'),('CashAndCashEquivalentsAtCarryingValue','I'),
             ('Liabilities','I'),('LiabilitiesCurrent','I'),('DebtCurrent','I'),
             ('LongTermDebt','I'),('LongTermDebtCurrent','I'),('LongTermDebtNoncurrent','I'),
             ('StockholdersEquity','I'),('PropertyPlantAndEquipmentNet','I'),
             ('Shares','I'),('InventoryNet','I'),
             ('NetCashProvidedByUsedInOperatingActivities','D'),
             ('PaymentsToAcquirePropertyPlantAndEquipment','D'),
             ('SellingGeneralAndAdministrativeExpense','D'),
             ('CostOfRevenue','D'),('CostOfGoodsAndServicesSold','D'),('CostOfGoodsSold','D')]:
    FR[c] = frame(c, u)

def g(concept, y, cik):
    return FR[concept].get(y, {}).get(cik)

# split factors + market cap (brand chassis convention)
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

def total_debt(y, cik):
    dc = g('DebtCurrent', y, cik); ltn = g('LongTermDebtNoncurrent', y, cik)
    lt = g('LongTermDebt', y, cik)
    if dc is not None and ltn is not None: return dc + ltn
    if lt is not None: return lt
    if dc is not None: return dc
    if ltn is not None: return ltn
    return None

def ym(y, m): return f'{y:04d}-{m:02d}'

# ---------- signal builders: each returns {signal_name: (pool_dict, direction)}
# pool value = signal value; direction 'low' or 'high' = long leg end.
def sig_inventory(F):
    out = {}
    for cik in cand:
        inv1, inv0 = g('InventoryNet', F-1, cik), g('InventoryNet', F-2, cik)
        a1, a0 = g('Assets', F-1, cik), g('Assets', F-2, cik)
        if None in (inv1, inv0, a1) or a1 == 0: continue
        out[cik] = (inv1 - inv0) / a1
    var = {}
    for cik, v in out.items():
        a1, a0 = g('Assets', F-1, cik), g('Assets', F-2, cik)
        if a0: var[cik] = v * g('Assets', F-1, cik) / ((a1 + a0) / 2)
    return {'Ivg': (out, 'low'), 'Ivc': (var, 'low')}

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
    return {'IA': (ia, 'low'), 'dPia': (dp, 'low'), 'COMP': (comp, 'low')}

def _rets(cik):
    s = px.get(cik, {})
    ms = sorted(s)
    r = {}
    for a, b in zip(ms, ms[1:]):
        if s[a][0] and s[b][0]: r[b] = s[b][0] / s[a][0] - 1
    return r
SPYRET = {}
_ms = sorted(spy)
for a, b in zip(_ms, _ms[1:]):
    if spy[a]: SPYRET[b] = spy[b] / spy[a] - 1

def _beta(cik, F, dimson=False):
    r = _rets(cik)
    end = ym(F, 5)
    xs, ys = [], []
    keys = [m for m in sorted(r) if m <= end][-60:]
    for m in keys:
        if m in SPYRET:
            if dimson:
                prev = months_all[midx[m] - 1] if midx[m] > 0 else None
                if prev in SPYRET: xs.append((SPYRET[m], SPYRET[prev])); ys.append(r[m])
            else:
                xs.append((SPYRET[m],)); ys.append(r[m])
    if len(ys) < 24: return None
    X = np.array(xs); yv = np.array(ys)
    Xd = np.column_stack([np.ones(len(yv)), X])
    try: coef, *_ = np.linalg.lstsq(Xd, yv, rcond=None)
    except Exception: return None
    return float(np.sum(coef[1:]))

def sig_beta(F):
    low, high, dim = {}, {}, {}
    for cik in cand:
        if cik not in px: continue
        b = _beta(cik, F)
        if b is None: continue
        low[cik] = b; high[cik] = b
        d = _beta(cik, F, dimson=True)
        if d is not None: dim[cik] = d
    return {'BetaLow': (low, 'low'), 'BetaHigh': (high, 'high'), 'BetaDimson': (dim, 'low')}

def sig_ndp(F):
    out, pos = {}, {}
    for cik in cand:
        debt, cash = total_debt(F-1, cik), g('CashAndCashEquivalentsAtCarryingValue', F-1, cik)
        mc = cap_of(cik, F)
        if debt is None or cash is None or not mc: continue
        v = (debt - cash) / mc
        out[cik] = v
        if debt - cash > 0: pos[cik] = v
    return {'Ndp': (out, 'high'), 'NdpPos': (pos, 'high')}

def sig_noa(F):
    out, dout = {}, {}
    def num(y, cik):
        a, c, l = g('Assets', y, cik), g('CashAndCashEquivalentsAtCarryingValue', y, cik), g('Liabilities', y, cik)
        d = total_debt(y, cik)
        if None in (a, c, l, d): return None
        return (a - c) - (l - d)
    for cik in cand:
        n1, a0 = num(F-1, cik), g('Assets', F-2, cik)
        if n1 is None or not a0: continue
        out[cik] = n1 / a0
        n0, am1 = num(F-2, cik), g('Assets', F-3, cik) if F-3 >= 2014 else None
        if n0 is not None and am1: dout[cik] = n1 / a0 - n0 / am1
    return {'Noa': (out, 'low'), 'dNoa': (dout, 'low')}

def sig_ocp(F):
    out, va = {}, {}
    for cik in cand:
        ocf, mc, a1 = g('NetCashProvidedByUsedInOperatingActivities', F-1, cik), cap_of(cik, F), g('Assets', F-1, cik)
        if ocf is None: continue
        if mc: out[cik] = ocf / mc
        if a1: va[cik] = ocf / a1
    return {'Ocp': (out, 'high'), 'OcpA': (va, 'high')}

def _cogs(y, cik):
    for c in ('CostOfRevenue', 'CostOfGoodsAndServicesSold', 'CostOfGoodsSold'):
        v = g(c, y, cik)
        if v is not None: return v
    return None

def sig_ol(F):
    out, vc = {}, {}
    for cik in cand:
        a1 = g('Assets', F-1, cik)
        if not a1: continue
        cg, sg = _cogs(F-1, cik), g('SellingGeneralAndAdministrativeExpense', F-1, cik)
        if cg is None and sg is None: continue
        out[cik] = ((cg or 0) + (sg or 0)) / a1
        if cg is not None: vc[cik] = cg / a1
    return {'Ol': (out, 'high'), 'OlCogs': (vc, 'high')}

# constructed intermediary leverage factor: annual log-change of SIC62x Assets/Equity
LEV = {}
for y in range(2014, 2026):
    ta = te = 0.0; n = 0
    for cik, info in cand.items():
        sic = str(info.get('sic') or '')
        if sic[:3] in ('621', '622', '628'):
            a, e = g('Assets', y, cik), g('StockholdersEquity', y, cik)
            if a and e and e > 0: ta += a; te += e; n += 1
    if te: LEV[y] = math.log(ta / te)
FAC = {y: LEV[y] - LEV[y-1] for y in range(2015, 2026) if y in LEV and y-1 in LEV}

def _ann_ret(cik, y):
    s = px.get(cik, {})
    a, b = s.get(ym(y-1, 6)), s.get(ym(y, 6))
    if a and b and a[0]: return b[0] / a[0] - 1
    return None

def sig_levbeta(F):
    out = {}
    for cik in cand:
        if cik not in px: continue
        xs, ys = [], []
        for y in range(max(2016, F-10), F):
            r, f = _ann_ret(cik, y), FAC.get(y)
            if r is not None and f is not None: xs.append(f); ys.append(r)
        if len(ys) < 5: continue
        X = np.array(xs); yv = np.array(ys)
        if np.var(X) == 0: continue
        out[cik] = float(np.cov(yv, X, ddof=0)[0, 1] / np.var(X))
    return {'BetaLev': (out, 'high')}

BUILDERS = {
 'catalog-hxz-inventory': sig_inventory,
 'catalog-hxz-investment-growth': sig_investment,
 'catalog-hxz-market-beta': sig_beta,
 'catalog-hxz-net-debt-to-price': sig_ndp,
 'catalog-hxz-net-operating-assets': sig_noa,
 'catalog-hxz-operating-cashflow-to-price': sig_ocp,
 'catalog-hxz-operating-leverage': sig_ol,
 'catalog-hxz-intermediary-leverage-beta': sig_levbeta,
}
PRIMARY = {
 'catalog-hxz-inventory': 'Ivg', 'catalog-hxz-investment-growth': 'IA',
 'catalog-hxz-market-beta': 'BetaLow', 'catalog-hxz-net-debt-to-price': 'Ndp',
 'catalog-hxz-net-operating-assets': 'Noa', 'catalog-hxz-operating-cashflow-to-price': 'Ocp',
 'catalog-hxz-operating-leverage': 'Ol', 'catalog-hxz-intermediary-leverage-beta': 'BetaLev',
}

# pools per formation per signal
POOLS = {}; MATS = {}
for F in range(2016, 2026):
    sigs = BUILDERS[SLUG](F)
    cols = [ym(F, m) for m in range(6, 13)] + [ym(F+1, m) for m in range(1, 7)]
    for sname, (vals, direction) in sigs.items():
        pool = {}
        for cik, v in vals.items():
            if cik not in px: continue
            e = px[cik].get(ym(F, 6))
            if not e or not e[0]: continue
            cap = cap_of(cik, F)
            pool[cik] = {'sig': v, 'dir': direction, 'cap': cap, 'rate': cost_rate(cap)}
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

def picks_for(F, sname, count):
    pool = POOLS[(F, sname)]
    items = sorted(pool.items(), key=lambda kv: kv[1]['sig'], reverse=(pool and next(iter(pool.values()))['dir'] == 'high'))
    if count == 'ALL': return [c for c, _ in items]
    if count == 'QUINTILE': n = max(1, math.ceil(len(items) * 0.20)); return [c for c, _ in items[:n]]
    return [c for c, _ in items[:min(count, len(items))]]

REBAL = {'annual': {0}, 'quarterly': {0, 3, 6, 9}, 'monthly': set(range(12))}

def run_road(formations, sname, count, cadence, house, seed=None):
    cash = 100.0; peak = 100.0; curve = []; total_costs = 0.0
    for F in formations:
        ciks_all, M = MATS[(F, sname)]
        idx = {c: i for i, c in enumerate(ciks_all)}
        pool = POOLS[(F, sname)]
        if seed is None:
            picks = picks_for(F, sname, count)
        else:
            rng = random.Random(seed * 100003 + F)
            keys = list(pool.keys()); rng.shuffle(keys)
            if count == 'ALL': n = len(keys)
            elif count == 'QUINTILE': n = max(1, math.ceil(len(keys) * 0.20))
            else: n = min(count, len(keys))
            picks = keys[:n]
        cols = [ym(F, m) for m in range(6, 13)] + [ym(F+1, m) for m in range(1, 7)]
        if not picks:
            for mm in cols[1:]: curve.append([mm, round(cash, 2)])
            continue
        rows = np.array([idx[c] for c in picks])
        P = M[rows, :]
        rates = np.array([pool[c]['rate'] for c in picks])
        px0 = P[:, 0].copy(); px0[px0 <= 0] = np.nan
        w = cash / len(picks)
        shares = np.where(np.isnan(px0), 0.0, (w * (1 - rates)) / np.where(np.isnan(px0), 1.0, px0))
        total_costs += float(np.sum(w * rates))
        in_cash = False
        for j in range(1, 13):
            if in_cash:
                curve.append([cols[j], round(cash, 2)]); continue
            pj = P[:, j]
            vals = shares * np.where(np.isnan(pj), 0.0, pj)
            val = float(np.sum(vals))
            if j in REBAL[cadence] and j < 12:
                tgt = val / len(picks)
                trade = np.abs(tgt - vals)
                cst = float(np.sum(trade * rates)); total_costs += cst
                scale = (val - cst) / val if val > 0 else 0.0
                vals = vals * scale
                tgt = float(np.sum(vals)) / len(picks)
                shares = np.where(np.isnan(pj) | (pj <= 0), 0.0, tgt / np.where(np.isnan(pj) | (pj <= 0), 1.0, pj))
                val = float(np.sum(vals))
            if j == 12:
                sell = float(np.sum(vals * rates)); total_costs += sell; cash = val - sell
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

ROADS = {'LONGEST_2016_2025': list(range(2016, 2026)), 'DECADE_2017_2025': list(range(2017, 2026)),
         'CONT_2019_2025': list(range(2019, 2026)), 'VAL_2023_2025': list(range(2023, 2026)),
         'FOLD_2016_2020': list(range(2016, 2021)), 'FOLD_2021_2025': list(range(2021, 2026))}

def spy_final(formations):
    a = spy.get(ym(formations[0], 6)); b = spy.get(ym(formations[-1]+1, 6))
    return round(100 * b / a, 2) if a and b else None

def main():
    signals = sorted({s for (F, s) in POOLS.keys()})
    counts = [1, 2, 3, 5, 8, 10, 15, 20, 30, 'ALL', 'QUINTILE']
    fences = {f'{F}|{s}': len(POOLS[(F, s)]) for (F, s) in sorted(POOLS.keys())}
    print('pools', fences, flush=True)
    grid = {}
    for sname in signals:
        for rb in ('native', 'house'):
            house = rb == 'house'
            for cad in ('annual', 'quarterly', 'monthly'):
                for count in counts:
                    key = f'{sname}|broad|{rb}|{cad}|{count}'
                    cell = {}
                    native_cell = (sname == PRIMARY[SLUG] and count == 'QUINTILE' and cad == 'annual' and rb == 'native')
                    for rname, forms in ROADS.items():
                        fin, curve, costs, maxdd = run_road(forms, sname, count, cad, house)
                        entry = {'final': fin, 'costs': costs, 'max_dd': maxdd, 'spy_same_window': spy_final(forms)}
                        if rname == 'LONGEST_2016_2025' or native_cell:
                            twins = []
                            for sd in range(1, 21):
                                tf, _, _, _ = run_road(forms, sname, count, cad, house, seed=sd)
                                twins.append(tf)
                            entry['placebo_finals'] = twins
                            entry['placebos_beaten'] = sum(1 for t in twins if fin > t)
                        if native_cell or rname == 'LONGEST_2016_2025':
                            entry['curve'] = curve
                        cell[rname] = entry
                    grid[key] = cell
                    print(key, 'LONGEST', cell['LONGEST_2016_2025']['final'], 'pb', cell['LONGEST_2016_2025'].get('placebos_beaten'), flush=True)
    res = {'family': SLUG, 'spec': 'SPEC-FROZEN.md', 'pool_sizes_eligible': fences, 'grid': grid}
    with open(os.path.join(FAM, 'results.json'), 'w') as fh:
        json.dump(res, fh, indent=1)
    # grid subfolder copy (Second-Chance grid deliverable)
    with open(os.path.join(FAM, 'grid', 'grid.json'), 'w') as fh:
        json.dump({'family': SLUG, 'grid': grid, 'pool_sizes_eligible': fences}, fh, indent=1)
    print('saved results.json + grid/grid.json')

if __name__ == '__main__':
    main()
