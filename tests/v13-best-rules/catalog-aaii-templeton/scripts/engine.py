#!/usr/bin/env python3
"""AAII catalog slice-3 engine — SCREEN = templeton. Frozen by SPEC-FROZEN.md.
W04 broad stack (read-only) + EDGAR frames fetched in catalog-aaii-pe-relative
(sibling slice folder). June formations, 12-month holds, tiered program costs,
vanished->ZERO, v9 house floor variant, pre-registered grid, 20-seed placebos.
Simulation only. Writes only results.json in this family folder."""
import json, os, math, random
import numpy as np

SCREEN = "templeton"
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
ELIGIBLE = {}
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
    ELIGIBLE[Fy] = sorted(ms.keys())
    print(SCREEN, Fy, 'passed', len(passed), 'of', len(ms), flush=True)


# ================= V13 BEST-RULES SIMULATION (sticky holdings) =================
# Spec: BEST-RULES-SPEC.md (frozen before this run). Annual June re-screen;
# sell if no longer passing or held 5 full years; buy all new passers;
# re-equalize at formation only; NO floor; program tiered costs; vanished->ZERO.

def price_at(cik, month):
    """Adjusted price at month with carry-forward; 0.0 after last bar (vanished)."""
    s = px.get(cik, {})
    if not s: return 0.0
    if month in s: return s[month][0]
    if month > max(s): return 0.0
    # carry last available <= month
    prev = [m for m in s if m <= month]
    return s[max(prev)][0] if prev else 0.0

def rate_of(cik, Fy):
    p = POOLS.get(Fy, {}).get(cik)
    if p: return p['rate']
    return cost_rate(cap_of(cik, Fy))

def month_range(y0, y1):
    """Months from June y0 to June y1 inclusive."""
    out = []
    y, m = y0, 6
    while (y, m) <= (y1, 6):
        out.append(ym(y, m))
        m += 1
        if m > 12: y, m = y + 1, 1
    return out

def simulate(formations, placebo_seed=None, turnover_plan=None):
    """Returns dict(final, curve, costs, maxdd_pct, turnover_plan, trades).
    If placebo_seed is not None, turnover_plan (per-Fy (n_sold, n_bought) from
    the main run) drives random selection from ELIGIBLE pools."""
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    months = month_range(formations[0], formations[-1] + 1)
    form_months = {ym(f, 6): f for f in formations}
    cash = 100.0
    shares = {}       # cik -> shares
    since = {}        # cik -> formation year bought
    curve = []
    total_costs = 0.0
    plan = {}
    n_trades = 0
    for month in months:
        if month in form_months:
            Fy = form_months[month]
            pool = POOLS[Fy]
            # value portfolio at this month's prices
            vals = {c: shares[c] * price_at(c, month) for c in shares}
            V = cash + sum(vals.values())
            if placebo_seed is None:
                sells = [c for c in shares if c not in pool or Fy - since[c] >= 5]
                capped = {c for c in sells if Fy - since[c] >= 5 and c in pool}
                keep = [c for c in shares if c not in sells]
                buys = [c for c in pool if c not in shares and c not in capped]
                plan[Fy] = (len(sells), len(buys))
            else:
                n_sold, n_bought = turnover_plan[Fy]
                held = list(shares.keys())
                rng.shuffle(held)
                sells = held[:min(n_sold, len(held))]
                keep = [c for c in shares if c not in sells]
                elig = [c for c in ELIGIBLE[Fy] if c not in keep and c not in sells]
                rng.shuffle(elig)
                buys = elig[:n_bought]
            target = keep + buys
            if not target:
                # liquidate everything to cash
                cst = sum(vals[c] * rate_of(c, Fy) for c in shares)
                total_costs += cst; n_trades += len(shares)
                cash = V - cst; shares = {}; since = {}
            else:
                tgt_val = V / len(target)
                cst = 0.0
                for c in target:
                    cur = vals.get(c, 0.0)
                    cst += abs(tgt_val - cur) * rate_of(c, Fy)
                    if abs(tgt_val - cur) > 1e-9: n_trades += 1
                for c in sells:
                    cst += 0.0  # full-sale cost already counted via |tgt-cur| for non-target? no:
                # sells are not in target; their trade cost must be added:
                cst += sum(vals[c] * rate_of(c, Fy) for c in sells)
                n_trades += len(sells)
                total_costs += cst
                V2 = V - cst
                tgt2 = V2 / len(target)
                new_shares = {}
                for c in target:
                    p = price_at(c, month)
                    new_shares[c] = (tgt2 / p) if p and p > 0 else 0.0
                    if c not in since: since[c] = Fy
                for c in sells: since.pop(c, None)
                shares = new_shares
                cash = 0.0
            V = cash + sum(shares[c] * price_at(c, month) for c in shares)
            curve.append([month, round(V, 2)])
        else:
            V = cash + sum(shares[c] * price_at(c, month) for c in shares)
            curve.append([month, round(V, 2)])
    # road-end liquidation (last month is June of formations[-1]+1)
    end_month = months[-1]
    Fy_end = formations[-1] + 1
    vals = {c: shares[c] * price_at(c, end_month) for c in shares}
    sell_cost = sum(vals[c] * rate_of(c, Fy_end) for c in shares)
    total_costs += sell_cost
    final = cash + sum(vals.values()) - sell_cost
    if curve: curve[-1] = [end_month, round(final, 2)]
    allv = [100.0] + [v for _, v in curve]
    pk = 100.0; maxdd = 0.0
    for v in allv:
        pk = max(pk, v); maxdd = min(maxdd, v / pk - 1) if pk else 0.0
    return {'final': round(final, 2), 'curve': curve, 'costs': round(total_costs, 2),
            'maxdd_pct': round(maxdd * 100, 1), 'turnover_plan': {str(k): list(v) for k, v in plan.items()},
            'trades': n_trades}

def spy_final(formations):
    a = spy.get(ym(formations[0], 6)); b = spy.get(ym(formations[-1] + 1, 6))
    return round(100.0 * b / a, 2) if a and b else None

def spy_effective(formations):
    first = next((f for f in formations if POOLS.get(f)), formations[0])
    a = spy.get(ym(first, 6)); b = spy.get(ym(formations[-1] + 1, 6))
    return round(100.0 * b / a, 2) if a and b else None

ROADS = {'LONGEST_2016_2025': list(range(2016, 2026)), 'DECADE_2017_2025': list(range(2017, 2026)),
         'CONT_2019_2025': list(range(2019, 2026)), 'VAL_2023_2025': list(range(2023, 2026)),
         'FOLD_2016_2020': list(range(2016, 2021)), 'FOLD_2021_2025': list(range(2021, 2026))}

results = {}
for road, forms in ROADS.items():
    main = simulate(forms)
    plan = {int(k): tuple(v) for k, v in main['turnover_plan'].items()}
    beaten = 0; pb_finals = []
    for s in range(1, 21):
        pb = simulate(forms, placebo_seed=s * 7919 + len(forms), turnover_plan=plan)
        pb_finals.append(pb['final'])
        if main['final'] > pb['final']: beaten += 1
    results[road] = {**main, 'placebos_beaten': beaten,
                     'placebo_finals': pb_finals,
                     'placebo_median': round(float(np.median(pb_finals)), 2) if pb_finals else None,
                     'spy_full': spy_final(forms), 'spy_effective': spy_effective(forms)}
    print('road', road, 'final', main['final'], 'maxdd', main['maxdd_pct'], 'pb', beaten, '/20', flush=True)

out = {'family': 'catalog-aaii-templeton', 'program': 'v13-best-rules',
       'chassis': 'ALL passers EW, annual June re-screen, sticky holds (exit on fail or 5y cap), no floor, program costs',
       'roads': results,
       'pool_sizes': {str(k): len(v) for k, v in POOLS.items()},
       'eligible_sizes': {str(k): len(v) for k, v in ELIGIBLE.items()}}
json.dump(out, open(os.path.join(FAM, 'results.json'), 'w'))
print('WROTE results.json')
