#!/usr/bin/env python3
"""V13 best-rules engine (delta-roll continuous chassis; pools identical to v12). Original: AAII catalog slice-3 engine — SCREEN = value-on-the-move. Frozen by SPEC-FROZEN.md.
W04 broad stack (read-only) + EDGAR frames fetched in catalog-aaii-pe-relative
(sibling slice folder). June formations, 12-month holds, tiered program costs,
vanished->ZERO, v9 house floor variant, pre-registered grid, 20-seed placebos.
Simulation only. Writes only results.json in this family folder."""
import json, os, math, random
import numpy as np

SCREEN = "value-on-the-move"
HERE = os.path.dirname(os.path.abspath(__file__))
FAM = os.path.join(HERE, '..')
W04 = os.path.join(FAM, '..', '..', 'v11-native-rules', '_w04_broad_data')
XFR = os.path.join(FAM, '..', 'catalog-aaii-pe-relative', 'data', 'frames')

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
    return e[1] if e and e[1] else None  # raw close

def eps(cik, y):
    ni = g(cik, 'NetIncomeLoss', y); sh = g(cik, 'Shares', y)
    if ni is None or not sh: return None
    return ni / sh

def cagr(vals):
    if len(vals) < 2 or vals[0] is None or vals[-1] is None or vals[0] <= 0 or vals[-1] <= 0: return None
    return (vals[-1] / vals[0]) ** (1.0 / (len(vals) - 1)) - 1

def pe_hist(cik, Fy):
    out = []
    for y in range(Fy - 5, Fy):
        e = eps(cik, y); p = june_px(cik, y + 1)
        if e is None or e <= 0 or not p: return None
        out.append(p / e)
    return out

def rs_pct(cik, Fy, months=6):
    s = px.get(cik, {})
    a = s.get(ym(Fy, 6)); 
    idx = months_all.index(ym(Fy, 6)) if ym(Fy, 6) in months_all else None
    if not a or idx is None or idx - months < 0: return None
    b = s.get(months_all[idx - months])
    if not b or not b[0]: return None
    return a[0] / b[0] - 1

# ---- per-formation raw metrics ----
def metrics(cik, Fy):
    y = Fy - 1
    m = {}
    m['rev'] = g(cik, 'REV', y); m['ni'] = g(cik, 'NetIncomeLoss', y)
    m['oi'] = g(cik, 'OperatingIncomeLoss', y); m['at'] = g(cik, 'Assets', y)
    m['eq'] = g(cik, 'StockholdersEquity', y); m['ocf'] = g(cik, 'NetCashProvidedByUsedInOperatingActivities', y)
    m['capex'] = g(cik, 'CAPEX', y); m['div'] = g(cik, 'DIV', y) or 0.0
    m['sh'] = g(cik, 'Shares', y); m['px'] = june_px(cik, Fy)
    m['cap'] = cap_of(cik, Fy)
    if not m['px'] or not m['sh']: return None
    m['eps'] = eps(cik, y)
    m['fcf'] = (m['ocf'] - m['capex']) if (m['ocf'] is not None and m['capex'] is not None) else None
    m['pe'] = (m['px'] / m['eps']) if (m['eps'] and m['eps'] > 0) else None
    m['ps'] = (m['cap'] / m['rev']) if (m['cap'] and m['rev']) else None
    m['pfcf'] = (m['cap'] / m['fcf']) if (m['cap'] and m['fcf']) else None
    m['pb'] = (m['cap'] / m['eq']) if (m['cap'] and m['eq']) else None
    m['roe'] = (m['ni'] / m['eq']) if (m['ni'] is not None and m['eq']) else None
    m['roa'] = (m['ni'] / m['at']) if (m['ni'] is not None and m['at']) else None
    m['margin'] = (m['ni'] / m['rev']) if (m['ni'] is not None and m['rev']) else None
    m['omargin'] = (m['oi'] / m['rev']) if (m['oi'] is not None and m['rev']) else None
    m['turn'] = (m['rev'] / m['at']) if (m['rev'] and m['at']) else None
    m['peh'] = pe_hist(cik, Fy)
    m['eps5'] = [eps(cik, yy) for yy in range(Fy - 5, Fy)]
    m['eps_cagr5'] = cagr([e for e in m['eps5']]) if all(e is not None and e > 0 for e in m['eps5']) else None
    m['eps_cagr3'] = cagr([eps(cik, yy) for yy in range(Fy - 3, Fy)]) if all((eps(cik, yy) or 0) > 0 for yy in range(Fy - 3, Fy)) else None
    m['rev_cagr5'] = cagr([g(cik, 'REV', yy) for yy in range(Fy - 5, Fy)])
    m['eq_cagr5'] = cagr([g(cik, 'StockholdersEquity', yy) for yy in range(Fy - 5, Fy)])
    m['roe5'] = []
    for yy in range(Fy - 5, Fy):
        ni = g(cik, 'NetIncomeLoss', yy); eq = g(cik, 'StockholdersEquity', yy)
        m['roe5'].append(ni / eq if (ni is not None and eq) else None)
    m['rs6'] = rs_pct(cik, Fy, 6); m['rs12'] = rs_pct(cik, Fy, 12)
    # trailing 12m low / 24m high from monthly adj prices
    s = px.get(cik, {})
    idx = months_all.index(ym(Fy, 6)) if ym(Fy, 6) in months_all else None
    if idx is not None:
        lo = [s[mm][0] for mm in months_all[max(0, idx-11):idx+1] if mm in s]
        hi = [s[mm][0] for mm in months_all[max(0, idx-23):idx+1] if mm in s]
        cur = s.get(ym(Fy, 6), (None, None))[0]
        m['near_low'] = (cur / min(lo)) if lo and cur else None
        m['pct_high'] = (cur / max(hi)) if hi and cur else None
    ltd = g(cik, 'LongTermDebt', y); dc = g(cik, 'DebtCurrent', y) or 0.0
    m['debt'] = (ltd + dc) if ltd is not None else None
    m['payout'] = (m['div'] / m['ni']) if (m['ni'] and m['ni'] > 0) else None
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
    # cross-sectional helpers
    rs6s = {c: m['rs6'] for c, m in ms.items() if m['rs6'] is not None}
    rs_sorted = sorted(rs6s.values())
    def pct_rank(v):
        if v is None or not rs_sorted: return None
        return sum(1 for x in rs_sorted if x <= v) / len(rs_sorted)
    sicmed = {}
    from collections import defaultdict
    bysic = defaultdict(list)
    for c, m in ms.items():
        sic2 = str(cand[c].get('sic') or '')[:2]
        bysic[sic2].append(m)
    for s2, lst in bysic.items():
        sicmed[s2] = {'roa': med([m['roa'] for m in lst]), 'margin': med([m['margin'] for m in lst]),
                      'omargin': med([m['omargin'] for m in lst]), 'ps': med([m['ps'] for m in lst])}
    pool_med = {'roe': med([m['roe'] for m in ms.values()]), 'pfcf': med([m['pfcf'] for m in ms.values() if m['pfcf'] and m['pfcf'] > 0]),
                'eps_cagr3': med([m['eps_cagr3'] for m in ms.values()])}
    passed = {}
    for cik, m in ms.items():
        sic2 = str(cand[cik].get('sic') or '')[:2]
        sm = sicmed.get(sic2, {})
        ok = False; rank = None
        if SCREEN == 'pe-relative':
            if m['peh'] and m['pe']:
                avg = sum(m['peh']) / len(m['peh'])
                if m['pe'] < avg and all(e is not None and e > 0 for e in m['eps5']):
                    ok = True; rank = m['pe'] / avg
        elif SCREEN == 'price-to-fcf':
            if m['fcf'] and m['fcf'] > 0 and m['pfcf'] and pool_med['pfcf']:
                hist = []
                good = True
                for yy in range(Fy - 5, Fy):
                    ocf = g(cik, 'NetCashProvidedByUsedInOperatingActivities', yy); cx = g(cik, 'CAPEX', yy)
                    sh = g(cik, 'Shares', yy); pp = june_px(cik, yy + 1)
                    if ocf is None or cx is None or not sh or not pp: good = False; break
                    f = ocf - cx
                    if f <= 0: good = False; break
                    hist.append(pp * sh * sf.get(cik, {}).get(yy + 1, 1.0) / f)
                if good and hist and m['pfcf'] < sum(hist)/len(hist) and m['pfcf'] < pool_med['pfcf']:
                    ok = True; rank = m['pfcf']
        elif SCREEN == 'price-to-sales':
            if m['ps'] and m['ps'] > 0 and sm.get('ps') and m['rev_cagr5'] is not None:
                if m['ps'] < sm['ps'] and m['rev_cagr5'] > 0:
                    ok = True; rank = m['ps']
        elif SCREEN == 'roe':
            if m['roe'] and pool_med['roe'] and m['roe'] > 1.5 * pool_med['roe']:
                if all(r is not None and r > 0 for r in m['roe5'][-3:]) and m['eps_cagr5'] and m['eps_cagr5'] > 0 and m['rev_cagr5'] and m['rev_cagr5'] > 0:
                    ok = True; rank = -m['roe']
        elif SCREEN == 'rule-number-one':
            if all(r is not None and r >= 0.10 for r in m['roe5']):
                if m['rev_cagr5'] and m['rev_cagr5'] >= 0.10 and m['eps_cagr5'] and m['eps_cagr5'] >= 0.10 and m['eq_cagr5'] and m['eq_cagr5'] >= 0.0:
                    if m['pe'] and m['pe'] / (m['eps_cagr5'] * 100) < 1.5:
                        ok = True; rank = m['pe'] / (m['eps_cagr5'] * 100)
        elif SCREEN == 'schloss':
            if m['pb'] and 0 < m['pb'] < 1.0 and m['near_low'] and m['near_low'] <= 1.10:
                if m['debt'] is not None and m['eq'] and m['debt'] < m['eq']:
                    ok = True; rank = m['pb']
        elif SCREEN == 'stock-market-winners':
            r = pct_rank(m['rs6'])
            if m['pb'] and 0 < m['pb'] < 1.5 and m['eps_cagr5'] and m['eps_cagr5'] > 0 and m['omargin'] and m['omargin'] > 0:
                if r and r >= 0.70 and m['pct_high'] and m['pct_high'] >= 0.85:
                    ok = True; rank = -m['rs6']
        elif SCREEN == 'templeton':
            if m['peh'] and m['pe'] and all(p < 75 for p in m['peh']):
                avg = sum(m['peh']) / len(m['peh'])
                epss = m['eps5']
                if m['pe'] < avg and all(e is not None and e > 0 for e in epss) and all(epss[i] > epss[i-1] for i in range(1, 5)):
                    if m['omargin'] and m['omargin'] > 0 and sm.get('omargin') is not None and m['omargin'] >= sm['omargin']:
                        ok = True; rank = m['pe'] / avg
        elif SCREEN == 'trowe-price':
            e3 = sorted([mm['eps_cagr3'] for mm in ms.values() if mm['eps_cagr3'] is not None])
            e5 = sorted([mm['eps_cagr5'] for mm in ms.values() if mm['eps_cagr5'] is not None])
            def q(v, arr, frac):
                return v is not None and arr and v >= arr[int(len(arr) * frac)]
            if m['peh'] and m['pe'] and sum(m['peh'])/len(m['peh']) < 40 and m['pe'] < sum(m['peh'])/len(m['peh']):
                if q(m['eps_cagr3'], e3, 0.75) and q(m['eps_cagr5'], e5, 0.50):
                    if m['payout'] is not None and m['payout'] < 1.0 and m['ocf'] and m['ocf'] > 0:
                        if m['roa'] and sm.get('roa') is not None and m['roa'] > sm['roa'] and m['margin'] and sm.get('margin') is not None and m['margin'] > sm['margin']:
                            ok = True; rank = -m['eps_cagr3']
        elif SCREEN == 'value-on-the-move':
            if m['pe'] and m['eps_cagr5'] and m['eps_cagr5'] > 0:
                peg = m['pe'] / (m['eps_cagr5'] * 100)
                r = pct_rank(m['rs6'])
                if 0.2 <= peg <= 1.0 and all(e is not None and e > 0 for e in m['eps5']) and r and r >= 0.70:
                    ok = True; rank = peg
        if ok:
            mm2 = dict(m); mm2['rank'] = rank; mm2['rate'] = cost_rate(m['cap'])
            passed[cik] = mm2
    POOLS[Fy] = passed
    print(SCREEN, Fy, 'passed', len(passed), 'of', len(ms), flush=True)


# ================= V13 BEST-RULES CHASSIS (frozen in BEST-RULES-SPEC.md) =================
# ALL passing, equal weight, annual June, NO floor, CONTINUOUS delta-only roll.
UNIV = {}
_orig_pools_loop_marker = None
# UNIV is rebuilt here from the same metrics() the pool loop used (identical values).
for Fy in range(2016, 2026):
    ms = {}
    for cik in cand:
        if cik not in px: continue
        mm = metrics(cik, Fy)
        if mm: ms[cik] = mm
    UNIV[Fy] = ms

def build_mat(ciks, Fy):
    cols = [ym(Fy, m) for m in range(6, 13)] + [ym(Fy + 1, m) for m in range(1, 7)]
    M = {}
    for cik in ciks:
        s = px[cik]; last = None; lastbar = max(s) if s else None
        row = []
        for mm in cols:
            if mm in s: last = s[mm][0]
            if lastbar is not None and mm > lastbar: row.append(0.0)
            elif last is not None: row.append(last)
            else: row.append(float('nan'))
        M[cik] = row
    return cols, M

def run_road(formations, seed=None):
    """Continuous portfolio. seed=None -> screen picks (ALL passing).
    seed=int -> placebo: same count drawn at random from UNIV[Fy]."""
    cash = 100.0; shares = {}; total_costs = 0.0; curve = []
    mats = {}
    for Fy in formations:
        pool = POOLS[Fy]
        if seed is None:
            picks = sorted(pool.keys())
            rates = {c: pool[c]['rate'] for c in picks}
        else:
            rng = random.Random(seed * 100003 + Fy)
            keys = sorted(UNIV[Fy].keys()); rng.shuffle(keys)
            picks = keys[:min(len(pool), len(keys))]
            rates = {c: cost_rate(UNIV[Fy][c]['cap']) for c in picks}
        allc = sorted(set(picks) | set(shares.keys()))
        cols, M = build_mat(allc, Fy)
        mats[Fy] = (cols, M)
        # --- formation rebalance at cols[0] prices, delta-only ---
        px0 = {c: M[c][0] for c in allc}
        def val0(c):
            p = px0.get(c)
            return shares.get(c, 0.0) * p if (p and not math.isnan(p)) else 0.0
        equity = cash + sum(val0(c) for c in shares)
        target_set = set(picks)
        # sell non-passing holdings entirely
        for c in list(shares.keys()):
            if c not in target_set:
                v = val0(c); r = rates.get(c, cost_rate(UNIV[Fy].get(c, {}).get('cap') if c in UNIV[Fy] else (pool.get(c, {}) or {}).get('cap')))
                cst = v * r; total_costs += cst; cash += v - cst; del shares[c]
        equity = cash + sum(val0(c) for c in shares)
        if picks:
            tgt = equity / len(picks)
            for c in picks:
                p = px0.get(c)
                if not p or math.isnan(p) or p <= 0: continue
                cur = shares.get(c, 0.0) * p
                delta = tgt - cur
                r = rates[c]
                if delta > 0:
                    spend = min(delta, cash)
                    sh = spend * (1 - r) / p; total_costs += spend * r
                    shares[c] = shares.get(c, 0.0) + sh; cash -= spend
                elif delta < 0:
                    sellv = -delta; sh = sellv / p
                    shares[c] = shares.get(c, 0.0) - sh
                    proceeds = sellv * (1 - r); total_costs += sellv * r; cash += proceeds
                    if shares[c] <= 1e-12: del shares[c]
        # --- monthly marks cols[1..12] ---
        for j in range(1, 13):
            v = cash
            for c, sh in shares.items():
                p = M[c][j]
                if p and not math.isnan(p): v += sh * p
            curve.append([cols[j], round(v, 2)])
        # cash is unchanged during the hold (no intra-year trades); only
        # formation trades above move it. Holdings carry into next formation.
    final = curve[-1][1] if curve else 100.0
    vals = [100.0] + [v for _, v in curve]
    pk = 100.0; maxdd = 0.0
    for v in vals:
        pk = max(pk, v); maxdd = min(maxdd, v / pk - 1) if pk else 0.0
    return {'final': round(final, 2), 'curve': curve, 'costs': round(total_costs, 2),
            'maxdd_pct': round(maxdd * 100, 1)}

def spy_final(formations):
    a = spy.get(ym(formations[0], 6)); b = spy.get(ym(formations[-1] + 1, 6))
    return round(100.0 * b / a, 2) if a and b else None

def spy_from(start_month):
    a = spy.get(start_month); b = spy.get('2026-06')
    return round(100.0 * b / a, 2) if a and b else None

import statistics
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
            'longest_losing_run': worst_run, 'longest_months_between_highs': longest_no_high}

ROADS = {'LONGEST': list(range(2016, 2026)), 'DECADE': list(range(2017, 2026)),
         'CONT': list(range(2019, 2026)), 'VAL': list(range(2023, 2026)),
         'FOLD_2016_2020': list(range(2016, 2021)), 'FOLD_2021_2025': list(range(2021, 2026))}
out = {'family': 'catalog-aaii-value-on-the-move', 'program': 'v13-best-rules',
       'pool_sizes': {str(k): len(v) for k, v in POOLS.items()}, 'roads': {}}
for road, forms in ROADS.items():
    r = run_road(forms)
    beaten = 0
    for s in range(20):
        pr = run_road(forms, seed=s + 1)
        if r['final'] > pr['final']: beaten += 1
    out['roads'][road] = {**r, 'placebos_beaten': beaten, 'period_stats': period_stats(r['curve']),
                          'spy_same_window': spy_final(forms)}
    print('road', road, r['final'], 'maxdd', r['maxdd_pct'], 'pb', beaten, 'spy', spy_final(forms), flush=True)
out['spy_effective'] = {k: spy_from(ym(f[0], 6)) for k, f in
                        [('LONGEST', ROADS['LONGEST']), ('DECADE', ROADS['DECADE']),
                         ('CONT', ROADS['CONT']), ('VAL', ROADS['VAL'])]}
# effective invested window starts at first non-empty formation (2019)
out['spy_effective_invested'] = spy_from('2019-06')
json.dump(out, open(os.path.join(FAM, 'results.json'), 'w'))
print('WROTE results.json')
