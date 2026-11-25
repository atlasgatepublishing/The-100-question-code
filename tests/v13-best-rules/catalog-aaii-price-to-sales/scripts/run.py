#!/usr/bin/env python3
"""V13 BEST-RULES run for catalog-aaii-price-to-sales.
Chassis frozen in BEST-RULES-SPEC.md: published screen unchanged
(P/S>0, below SIC-2 median, 5y rev CAGR>0; rank P/S asc),
TOP 20 equal-weight, ANNUAL June formation, NO floor.
Pool construction copied verbatim from the v12 engine (same stack,
same PIT lag, same costs, vanished->ZERO) so the published-form
comparison is same-stack. Also runs the published native form
(ALL passing, annual, no floor) as the baseline, 20-seed placebos,
folds and half-windows for the frozen confirmation bars.
Writes ONLY results.json + run.log in this v13 folder. Simulation only."""
import json, os, math, random, statistics, sys
import numpy as np

SCREEN = "price-to-sales"
HERE = os.path.dirname(os.path.abspath(__file__))
FAM = os.path.join(HERE, '..')
V12 = os.path.join(FAM, '..', '..', 'v12-completions', 'catalog-aaii-price-to-sales')
W04 = os.path.join(FAM, '..', '..', 'v11-native-rules', '_w04_broad_data')
XFR = os.path.join(FAM, '..', '..', 'v12-completions', 'catalog-aaii-pe-relative', 'data', 'frames')
LOG = open(os.path.join(FAM, 'run.log'), 'w')
def log(*a):
    print(*a, flush=True); print(*a, file=LOG, flush=True)

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
DIV = {}
for y in YEARS:
    d = dict(xframe('PaymentsOfDividends', y))
    for k, v in xframe('PaymentsOfDividendsCommonStock', y).items(): d.setdefault(k, v)
    DIV[y] = d

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

def cap_of(cik, Fy):
    sh = F['Shares'].get(Fy-1, {}).get(cik) or F['Shares'].get(Fy-2, {}).get(cik)
    s = px.get(cik)
    if not sh or not s: return None
    e = s.get(f'{Fy:04d}-06')
    if not e or not e[1]: return None
    return sh * e[1] * sf.get(cik, {}).get(Fy, 1.0)

def cost_rate(cap):
    if cap is None: return 0.0075
    if cap >= 5e9: return 0.0010
    if cap >= 1e9: return 0.0025
    return 0.0075

def g(cik, name, y):
    src = REV if name == 'REV' else (CAPEX if name == 'CAPEX' else (DIV if name == 'DIV' else F[name]))
    return src.get(y, {}).get(cik)

def ym(y, m): return f'{y:04d}-{m:02d}'

def june_px(cik, y):
    e = px.get(cik, {}).get(ym(y, 6))
    return e[1] if e and e[1] else None

def eps(cik, y):
    ni = g(cik, 'NetIncomeLoss', y); sh = g(cik, 'Shares', y)
    if ni is None or not sh: return None
    return ni / sh

def cagr(vals):
    if len(vals) < 2 or vals[0] is None or vals[-1] is None or vals[0] <= 0 or vals[-1] <= 0: return None
    return (vals[-1] / vals[0]) ** (1.0 / (len(vals) - 1)) - 1

def metrics(cik, Fy):
    y = Fy - 1
    m = {}
    m['rev'] = g(cik, 'REV', y)
    m['sh'] = g(cik, 'Shares', y); m['px'] = june_px(cik, Fy)
    m['cap'] = cap_of(cik, Fy)
    if not m['px'] or not m['sh']: return None
    m['ps'] = (m['cap'] / m['rev']) if (m['cap'] and m['rev']) else None
    m['rev_cagr5'] = cagr([g(cik, 'REV', yy) for yy in range(Fy - 5, Fy)])
    return m

def med(vals):
    v = sorted(x for x in vals if x is not None)
    return v[len(v)//2] if v else None

POOLS = {}
for Fy in range(2016, 2026):
    ms = {}
    for cik in cand:
        if cik not in px: continue
        mm = metrics(cik, Fy)
        if mm: ms[cik] = mm
    from collections import defaultdict
    bysic = defaultdict(list)
    for c, m in ms.items():
        bysic[str(cand[c].get('sic') or '')[:2]].append(m)
    sicmed = {s2: med([m['ps'] for m in lst]) for s2, lst in bysic.items()}
    passed = {}
    for cik, m in ms.items():
        sm = sicmed.get(str(cand[cik].get('sic') or '')[:2])
        if m['ps'] and m['ps'] > 0 and sm and m['rev_cagr5'] is not None:
            if m['ps'] < sm and m['rev_cagr5'] > 0:
                mm2 = dict(m); mm2['rank'] = m['ps']; mm2['rate'] = cost_rate(m['cap'])
                passed[cik] = mm2
    POOLS[Fy] = passed
    log(SCREEN, Fy, 'passed', len(passed), 'of', len(ms))

MATS = {}
for Fy in range(2016, 2026):
    cols = [ym(Fy, m) for m in range(6, 13)] + [ym(Fy + 1, m) for m in range(1, 7)]
    pool = POOLS[Fy]
    ciks = sorted(pool)
    M = np.full((len(ciks), len(cols)), np.nan)
    for i, cik in enumerate(ciks):
        s = px[cik]; last = None; lastbar = max(s) if s else None
        for j, mm in enumerate(cols):
            if mm in s: last = s[mm][0]
            if lastbar is not None and mm > lastbar: M[i, j] = 0.0
            elif last is not None: M[i, j] = last
    MATS[Fy] = (ciks, M)

def picks_for(Fy, count):
    items = sorted(POOLS[Fy].items(), key=lambda kv: kv[1]['rank'])
    if count == 'ALL': return [c for c, _ in items]
    return [c for c, _ in items[:min(count, len(items))]]

def run_road(formations, count, seed=None):
    """Annual cadence, no floor (both my-rules and published ALL form)."""
    cash = 100.0; curve = []; total_costs = 0.0
    for Fy in formations:
        ciks_all, M = MATS[Fy]
        idx = {c: i for i, c in enumerate(ciks_all)}
        pool = POOLS[Fy]
        if seed is None:
            picks = picks_for(Fy, count)
        else:
            rng = random.Random(seed * 100003 + Fy)
            keys = list(pool.keys()); rng.shuffle(keys)
            n = len(keys) if count == 'ALL' else min(count, len(keys))
            picks = keys[:n]
        cols = [ym(Fy, m) for m in range(6, 13)] + [ym(Fy + 1, m) for m in range(1, 7)]
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
    vals = [100.0] + [v for _, v in curve]
    pk = 100.0; maxdd = 0.0
    for v in vals:
        pk = max(pk, v); maxdd = min(maxdd, v / pk - 1) if pk else 0.0
    return {'final': round(cash, 2), 'curve': curve, 'costs': round(total_costs, 2),
            'maxdd_pct': round(maxdd * 100, 1)}

def spy_final(formations):
    a = spy.get(ym(formations[0], 6)); b = spy.get(ym(formations[-1] + 1, 6))
    return round(100.0 * b / a, 2) if a and b else None

def spy_effective(formations):
    """SPY from first non-empty formation June to road end."""
    eff = [f for f in formations if POOLS[f]]
    if not eff: return None
    return spy_final([eff[0], formations[-1]]) if False else (
        round(100.0 * spy[ym(formations[-1] + 1, 6)] / spy[ym(eff[0], 6)], 2))

def period_stats(curve):
    vals = [100.0] + [v for _, v in curve]
    rets = []
    for i in range(12, len(vals), 12):
        rets.append(vals[i] / vals[i - 12] - 1)
    if not rets: return None
    pos = sum(1 for r in rets if r > 0)
    worst_run = 0; run = 0
    for r in rets:
        run = run + 1 if r <= 0 else 0; worst_run = max(worst_run, run)
    peak = vals[0]; longest_no_high = 0; cur = 0
    for v in vals:
        if v >= peak: peak = v; cur = 0
        else: cur += 1; longest_no_high = max(longest_no_high, cur)
    return {'periods': len(rets), 'positive': pos,
            'median_pct': round(statistics.median(rets) * 100, 1),
            'mean_pct_secondary': round(statistics.mean(rets) * 100, 1),
            'best_pct': round(max(rets) * 100, 1), 'worst_pct': round(min(rets) * 100, 1),
            'yearly_pct': [round(r * 100, 1) for r in rets],
            'longest_losing_run': worst_run,
            'longest_months_between_highs': longest_no_high}

ROADS = {'LONGEST': list(range(2016, 2026)), 'DECADE': list(range(2017, 2026)),
         'CONT': list(range(2019, 2026)), 'VAL': list(range(2023, 2026))}
CHAMP = {'LONGEST': 1415.62, 'DECADE': 667.35, 'CONT': 544.47, 'VAL': 288.05}
SPY_PROG = {'LONGEST': 822.94, 'DECADE': 367.80, 'CONT': 313.62, 'VAL': 187.77}

out = {'family': 'catalog-aaii-price-to-sales', 'program': 'v13-best-rules',
       'chassis': 'top20 equal-weight, annual June, no floor, published screen unchanged',
       'pool_sizes': {str(k): len(v) for k, v in POOLS.items()}, 'roads': {}}

for name, forms in ROADS.items():
    mine = run_road(forms, 20)
    pub = run_road(forms, 'ALL')
    beaten = 0; pfinals = []
    for s in range(20):
        pr = run_road(forms, 20, seed=s + 1)
        pfinals.append(pr['final'])
        if mine['final'] > pr['final']: beaten += 1
    out['roads'][name] = {
        'formations': forms, 'my_rules': mine, 'published_all': pub,
        'placebos_beaten': beaten, 'placebo_finals': pfinals,
        'placebo_median': round(statistics.median(pfinals), 2),
        'spy_full_window': spy_final(forms), 'spy_effective_window': spy_effective(forms),
        'champion_vm_program_road': CHAMP[name], 'spy_program_road': SPY_PROG[name],
        'period_stats_my': period_stats(mine['curve']),
        'period_stats_published': period_stats(pub['curve'])}
    log(name, 'mine', mine['final'], 'dd', mine['maxdd_pct'], 'pub', pub['final'],
        'pb', beaten, 'spy_eff', spy_effective(forms))

# Confirmation machinery (frozen bars in spec) — evaluated for every road,
# claimed only where a road beats its champion figure.
out['confirmation'] = {}
for name, forms in ROADS.items():
    if out['roads'][name]['my_rules']['final'] <= CHAMP[name]:
        out['confirmation'][name] = {'needed': False}
        continue
    folds = {'FOLD_A': [f for f in forms if 2016 <= f <= 2020],
             'FOLD_B': [f for f in forms if 2021 <= f <= 2025]}
    halves = {'HALF_1': forms[:len(forms)//2], 'HALF_2': forms[len(forms)//2:]}
    conf = {'needed': True, 'folds': {}, 'halves': {}}
    ok = True
    for k, ff in folds.items():
        if not ff: conf['folds'][k] = None; ok = False; continue
        r = run_road(ff, 20); b = 0
        for s in range(20):
            if r['final'] > run_road(ff, 20, seed=s + 1)['final']: b += 1
        s_ = spy_final(ff)
        conf['folds'][k] = {'final': r['final'], 'spy': s_, 'placebos_beaten': b}
        if not (s_ and r['final'] > s_ and b >= 15): ok = False
    for k, ff in halves.items():
        if not ff: conf['halves'][k] = None; ok = False; continue
        r = run_road(ff, 20); s_ = spy_final(ff)
        conf['halves'][k] = {'final': r['final'], 'spy': s_}
        if not (s_ and r['final'] > s_): ok = False
    conf['confirmed'] = ok
    out['confirmation'][name] = conf
    log('CONFIRM', name, json.dumps(conf))

json.dump(out, open(os.path.join(FAM, 'results.json'), 'w'))
log('WROTE results.json')
LOG.close()
