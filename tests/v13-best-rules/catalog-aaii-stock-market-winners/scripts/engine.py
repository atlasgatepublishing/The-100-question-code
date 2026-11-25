#!/usr/bin/env python3
"""V13 BEST-RULES engine — AAII Stock Market Winners (Reinganum).
Frozen by BEST-RULES-SPEC.md in this folder. Chassis: SEMIANNUAL formations
(June + December), ALL passing names equal-weight, 6-month holds, NO floor,
program tiered costs, vanished->ZERO, 20-seed placebos drawn from the
formation's full computable universe. Screen criteria identical to the
frozen v12 construction (read-only record). W04 broad stack is read-only.
Simulation only. Writes only inside this family folder."""
import json, os, random
import numpy as np
from collections import defaultdict

SCREEN = "stock-market-winners"
HERE = os.path.dirname(os.path.abspath(__file__))
FAM = os.path.join(HERE, '..')
W04 = os.path.join(FAM, '..', '..', 'v11-native-rules', '_w04_broad_data')
XFR = os.path.join(FAM, '..', '..', 'v12-completions', 'catalog-aaii-pe-relative', 'data', 'frames')

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
months_all = sorted(spy)
midx = {m: i for i, m in enumerate(months_all)}

def frame(name, y, kind):
    d = loadj(os.path.join(W04, 'frames', f'{name}_{y}{kind}.json'))
    return {int(k): v for k, v in d.items()}
def xframe(name, y):
    d = loadj(os.path.join(XFR, f'{name}_{y}D.json'))
    return {int(k): v for k, v in d.items()}

YEARS = range(2009, 2026)
F = {}
for name, kind in [('Assets','I'),('StockholdersEquity','I'),('Liabilities','I'),
                   ('CashAndCashEquivalentsAtCarryingValue','I'),('Shares','I'),
                   ('LongTermDebt','I'),('LongTermDebtNoncurrent','I'),('DebtCurrent','I'),
                   ('NetIncomeLoss','D'),('OperatingIncomeLoss','D'),
                   ('NetCashProvidedByUsedInOperatingActivities','D'),
                   ('GrossProfit','D')]:
    F[name] = {y: frame(name, y, kind) for y in YEARS}
REV = {}
for y in YEARS:
    d = {}
    for nm in ('Revenues','SalesRevenueNet','RevenueFromContractWithCustomerExcludingAssessedTax'):
        for k, v in frame(nm, y, 'D').items(): d.setdefault(k, v)
    REV[y] = d
CAPEX = {y: xframe('PaymentsToAcquirePropertyPlantAndEquipment', y) for y in YEARS}

# split factors by formation year (same construction as v12)
sf = {}
for cik in cand:
    avail = [(y, F['Shares'][y][cik]) for y in YEARS if cik in F['Shares'][y]]
    d = {}
    for Fy in range(2016, 2027):
        f = 1.0
        for (y0, a), (y1, b) in zip(avail, avail[1:]):
            if y1 >= Fy and a:
                r = b / a
                if r >= 1.6 or r <= 0.625: f *= r
        d[Fy] = f
    sf[cik] = d

def ym(y, m): return f'{y:04d}-{m:02d}'

def add_months(y, m, k):
    t = (y * 12 + (m - 1)) + k
    return t // 12, t % 12 + 1

def g(cik, name, y):
    src = REV if name == 'REV' else (CAPEX if name == 'CAPEX' else F[name])
    return src.get(y, {}).get(cik)

def eps(cik, y):
    ni = g(cik, 'NetIncomeLoss', y); sh = g(cik, 'Shares', y)
    if ni is None or not sh: return None
    return ni / sh

def cagr(vals):
    if len(vals) < 2 or vals[0] is None or vals[-1] is None or vals[0] <= 0 or vals[-1] <= 0: return None
    return (vals[-1] / vals[0]) ** (1.0 / (len(vals) - 1)) - 1

def form_px(cik, Fy, fm):
    e = px.get(cik, {}).get(ym(Fy, fm))
    return e  # (adj, raw) or None

def cap_of(cik, Fy, fm):
    sh = F['Shares'].get(Fy-1, {}).get(cik) or F['Shares'].get(Fy-2, {}).get(cik)
    s = px.get(cik)
    if not sh or not s: return None
    e = s.get(ym(Fy, fm))
    if not e or not e[1]: return None
    return sh * e[1] * sf.get(cik, {}).get(Fy, 1.0)

def cost_rate(cap):
    if cap is None: return 0.0075
    if cap >= 5e9: return 0.0010
    if cap >= 1e9: return 0.0025
    return 0.0075

def metrics(cik, Fy, fm):
    """Fundamentals: fiscal years <= Fy-1 (PIT lag, same for Jun and Dec of
    year Fy). Price legs computed at the formation month (Fy, fm)."""
    y = Fy - 1
    m = {}
    m['rev'] = g(cik, 'REV', y); m['ni'] = g(cik, 'NetIncomeLoss', y)
    m['oi'] = g(cik, 'OperatingIncomeLoss', y); m['at'] = g(cik, 'Assets', y)
    m['eq'] = g(cik, 'StockholdersEquity', y)
    m['sh'] = g(cik, 'Shares', y)
    e = form_px(cik, Fy, fm)
    if not e or not e[1] or not m['sh']: return None
    m['px'] = e[1]  # raw close at formation
    m['cap'] = cap_of(cik, Fy, fm)
    m['eps'] = eps(cik, y)
    m['pb'] = (m['cap'] / m['eq']) if (m['cap'] and m['eq']) else None
    m['omargin'] = (m['oi'] / m['rev']) if (m['oi'] is not None and m['rev']) else None
    eps5 = [eps(cik, yy) for yy in range(Fy - 5, Fy)]
    m['eps_cagr5'] = cagr(eps5) if all(v is not None and v > 0 for v in eps5) else None
    # price legs at formation month
    s = px.get(cik, {})
    fmkey = ym(Fy, fm)
    idx = midx.get(fmkey)
    if idx is None or idx - 6 < 0: return None
    a = s.get(fmkey); b = s.get(months_all[idx - 6])
    if not a or not b or not b[0]: return None
    m['rs6'] = a[0] / b[0] - 1
    hi = [s[mm][0] for mm in months_all[max(0, idx-23):idx+1] if mm in s]
    m['pct_high'] = (a[0] / max(hi)) if hi and a[0] else None
    return m

# ---- formations: June + December, 2016..2025 ----
FORMATIONS = [(Fy, fm) for Fy in range(2016, 2026) for fm in (6, 12)]
POOLS = {}       # fkey -> {cik: metrics+rate}
UNIVERSE = {}    # fkey -> [cik with computable metrics]
for (Fy, fm) in FORMATIONS:
    fkey = ym(Fy, fm)
    ms = {}
    for cik in cand:
        if cik not in px: continue
        mm = metrics(cik, Fy, fm)
        if mm: ms[cik] = mm
    rs_sorted = sorted(v['rs6'] for v in ms.values() if v['rs6'] is not None)
    def pct_rank(v):
        if v is None or not rs_sorted: return None
        return sum(1 for x in rs_sorted if x <= v) / len(rs_sorted)
    passed = {}
    for cik, m in ms.items():
        r = pct_rank(m['rs6'])
        if m['pb'] and 0 < m['pb'] < 1.5 and m['eps_cagr5'] and m['eps_cagr5'] > 0 \
           and m['omargin'] and m['omargin'] > 0 \
           and r and r >= 0.70 and m['pct_high'] and m['pct_high'] >= 0.85:
            mm2 = dict(m); mm2['rate'] = cost_rate(m['cap'])
            passed[cik] = mm2
    POOLS[fkey] = passed
    UNIVERSE[fkey] = sorted(ms.keys())
    print(SCREEN, fkey, 'passed', len(passed), 'of', len(ms), flush=True)

# ---- hold matrices: 6 monthly steps after formation month ----
MATS = {}
for (Fy, fm) in FORMATIONS:
    fkey = ym(Fy, fm)
    cols = [ym(*add_months(Fy, fm, k)) for k in range(0, 7)]
    ciks = sorted(set(POOLS[fkey]) | set(UNIVERSE[fkey]))
    idx = {c: i for i, c in enumerate(ciks)}
    M = np.full((len(ciks), len(cols)), np.nan)
    for i, cik in enumerate(ciks):
        s = px[cik]; last = None; lastbar = max(s) if s else None
        for j, mm in enumerate(cols):
            if mm in s: last = s[mm][0]
            if lastbar is not None and mm > lastbar: M[i, j] = 0.0
            elif last is not None: M[i, j] = last
    MATS[fkey] = (idx, M, cols)

def run_road(formations, seed=None):
    cash = 100.0; curve = []; total_costs = 0.0
    for (Fy, fm) in formations:
        fkey = ym(Fy, fm)
        idx, M, cols = MATS[fkey]
        pool = POOLS[fkey]
        if seed is None:
            picks = sorted(pool.keys())
            rates = {c: pool[c]['rate'] for c in picks}
        else:
            rng = random.Random(seed * 100003 + Fy * 100 + fm)
            uni = list(UNIVERSE[fkey]); rng.shuffle(uni)
            picks = sorted(uni[:len(pool)])
            rates = {}
            for c in picks:
                mm = metrics(c, Fy, fm)
                rates[c] = cost_rate(mm['cap']) if mm else 0.0075
        if not picks:
            for mm in cols[1:]: curve.append([mm, round(cash, 2)])
            continue
        rows = np.array([idx[c] for c in picks])
        P = M[rows, :]
        rts = np.array([rates[c] for c in picks])
        px0 = P[:, 0].copy(); px0[px0 <= 0] = np.nan
        w = cash / len(picks)
        shares = np.where(np.isnan(px0), 0.0, (w * (1 - rts)) / np.where(np.isnan(px0), 1.0, px0))
        total_costs += float(np.sum(w * rts))
        for j in range(1, 7):
            pj = P[:, j]
            vals = shares * np.where(np.isnan(pj), 0.0, pj)
            val = float(np.sum(vals))
            if j == 6:
                sell = float(np.sum(vals * rts)); total_costs += sell
                cash = val - sell
            else:
                cash = val
            curve.append([cols[j], round(cash, 2)])
    vals = [100.0] + [v for _, v in curve]
    pk = 100.0; maxdd = 0.0
    for v in vals:
        pk = max(pk, v); maxdd = min(maxdd, v / pk - 1) if pk else 0.0
    return {'final': round(cash, 2), 'curve': curve, 'costs': round(total_costs, 2),
            'maxdd_pct': round(maxdd * 100, 1)}

def spy_final(formations):
    (y0, m0) = formations[0]
    a = spy.get(ym(y0, m0))
    (y1, m1) = add_months(*formations[-1], 6)
    b = spy.get(ym(y1, m1))
    return round(100.0 * b / a, 2) if a and b else None

def road_forms(y0, y1):
    return [(Fy, fm) for Fy in range(y0, y1 + 1) for fm in (6, 12)]

ROADS = {'LONGEST_2016_2025': road_forms(2016, 2025), 'DECADE_2017_2025': road_forms(2017, 2025),
         'CONT_2019_2025': road_forms(2019, 2025), 'VAL_2023_2025': road_forms(2023, 2025),
         'HALF_2016_2020': road_forms(2016, 2020), 'HALF_2021_2025': road_forms(2021, 2025)}

out = {'screen': SCREEN, 'chassis': 'v13-best-rules: semiannual Jun+Dec formations, ALL passing, no floor, program tiered costs',
       'roads': {}, 'spy': {}, 'pool_sizes': {k: len(v) for k, v in POOLS.items()},
       'universe_sizes': {k: len(v) for k, v in UNIVERSE.items()}}
for road, forms in ROADS.items():
    r = run_road(forms)
    beaten = 0; pb_finals = []
    for s in range(20):
        pr = run_road(forms, seed=s + 1)
        pb_finals.append(pr['final'])
        if r['final'] > pr['final']: beaten += 1
    out['roads'][road] = {**r, 'placebos_beaten': beaten, 'placebo_finals': pb_finals}
    out['spy'][road] = spy_final(forms)
    print('road', road, r['final'], 'maxdd', r['maxdd_pct'], 'costs', r['costs'], 'pb', beaten, '/20', flush=True)

json.dump(out, open(os.path.join(FAM, 'results.json'), 'w'))
print('WROTE results.json')
