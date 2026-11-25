#!/usr/bin/env python3
"""Slice-2 AAII screens v12 engine v2 — frozen specs in SPEC-FROZEN.md.
Usage: engine.py <screen>
Data layer: W04 broad stack + shareholder-yield frames (read-only) +
this family's data/frames, precomputed into matrices (fast features).
PIT by formation lag (fy = year-1 if month>=Jun else year-2). Market cap
and per-share figures on the FORMATION-date split basis. Tiered program
costs, vanished->ZERO, v9 house floor variant, full Second-Chance grid,
20-seed placebos per cell. Simulation only. Writes results.json here."""
import json, os, sys, math, random
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FAM = os.path.join(HERE, '..')
W04 = os.path.join(FAM, '..', '..', 'v11-native-rules', '_w04_broad_data')
SYF = '/home/hatch/workspace/stock-app/backtests/v12-completions/shareholder-yield/data/frames'
FR = '/home/hatch/workspace/stock-app/backtests/v12-completions/catalog-aaii-dual-cash-flow/data/frames'
YEARS = list(range(2009, 2026)); YIDX = {y: i for i, y in enumerate(YEARS)}

def loadj(p):
    return json.load(open(p)) if os.path.exists(p) else {}

cand = {int(k): v for k, v in loadj(os.path.join(W04, 'candidates.json')).items()}
CIKS = sorted(c for c in cand)
CIDX = {c: i for i, c in enumerate(CIKS)}
NC = len(CIKS)
spy = {r[0]: r[1] for r in loadj(os.path.join(W04, 'px_SPY.json'))}
MONTHS = sorted(spy); MIDX = {m: i for i, m in enumerate(MONTHS)}; NM = len(MONTHS)
PXA = np.full((NC, NM), np.nan); PXR = np.full((NC, NM), np.nan)
for c in CIKS:
    t = cand[c]['ticker'].replace('/', '-')
    p = os.path.join(W04, f'px_{t}.json')
    if not os.path.exists(p): continue
    for r in loadj(p):
        j = MIDX.get(r[0])
        if j is not None: PXA[CIDX[c], j] = r[1]; PXR[CIDX[c], j] = r[2]
SPY = np.array([spy[m] for m in MONTHS], dtype=float)

def tag_matrix(tag, suf, base):
    M = np.full((len(YEARS), NC), np.nan)
    for y in YEARS:
        d = loadj(os.path.join(base, f'{tag}_{y}{suf}.json'))
        for k, v in d.items():
            i = CIDX.get(int(k))
            if i is not None: M[YIDX[y], i] = v
    return M

W04F = os.path.join(W04, 'frames')
MAT = {}
def mat(name):
    if name in MAT: return MAT[name]
    if name == 'rev':
        M = np.full((len(YEARS), NC), np.nan)
        for t in ('RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues', 'SalesRevenueNet'):
            T = tag_matrix(t, 'D', W04F)
            M = np.where(np.isnan(M), T, M)
        MAT[name] = M; return M
    spec = {'ni': ('NetIncomeLoss', 'D', W04F), 'oi': ('OperatingIncomeLoss', 'D', W04F),
            'ocf': ('NetCashProvidedByUsedInOperatingActivities', 'D', W04F),
            'eq': ('StockholdersEquity', 'I', W04F), 'at': ('Assets', 'I', W04F),
            'liab': ('Liabilities', 'I', W04F), 'ppe': ('PropertyPlantAndEquipmentNet', 'I', W04F),
            'cash': ('CashAndCashEquivalentsAtCarryingValue', 'I', W04F),
            'sh': ('Shares', 'I', W04F),
            'div': ('PaymentsOfDividendsCommonStock', 'D', SYF),
            'divall': ('PaymentsOfDividends', 'D', SYF),
            'dep': ('DepreciationDepletionAndAmortization', 'D', SYF),
            'capex': ('PaymentsToAcquirePropertyPlantAndEquipment', 'D', FR),
            'inv': ('InventoryNet', 'I', FR), 'recv': ('ReceivablesNetCurrent', 'I', FR)}[name]
    MAT[name] = tag_matrix(*spec)
    return MAT[name]

# cumulative split factor per cik: CUM[i, yi] = prod of split ratios for years <= YEARS[yi]
SH = mat('sh')
CUM = np.ones((NC, len(YEARS)))
for yi in range(1, len(YEARS)):
    a, b = SH[yi - 1], SH[yi]
    with np.errstate(invalid='ignore', divide='ignore'):
        r = np.where((a > 0) & (b > 0), b / a, 1.0)
    r = np.where((r >= 1.6) | (r <= 0.625), r, 1.0)
    CUM[:, yi] = CUM[:, yi - 1] * r

def cost_rate(cap):
    if cap is None or np.isnan(cap): return 0.0075
    if cap >= 5e9: return 0.0010
    if cap >= 1e9: return 0.0025
    return 0.0075

def ym_add(ym, k):
    y, m = int(ym[:4]), int(ym[5:7]) + k
    return f'{y + (m - 1) // 12:04d}-{(m - 1) % 12 + 1:02d}'

def pct_rank(vals):
    v = np.asarray(vals, dtype=float); out = np.full(len(v), np.nan)
    ok = ~np.isnan(v)
    if ok.sum() < 2: return out
    order = np.argsort(v[ok], kind='stable'); ranks = np.empty(ok.sum()); ranks[order] = np.arange(ok.sum())
    sv = v[ok][order]; i = 0
    while i < len(sv):
        j = i
        while j + 1 < len(sv) and sv[j + 1] == sv[i]: j += 1
        ranks[order[i:j + 1]] = ranks[order[i:j + 1]].mean(); i = j + 1
    out[ok] = ranks / (ok.sum() - 1) * 100.0
    return out

def ind_median(vals, groups):
    v = np.asarray(vals, dtype=float); out = np.full(len(v), np.nan)
    gd = {}
    for i, g in enumerate(groups): gd.setdefault(g, []).append(i)
    for g, idx in gd.items():
        vv = v[idx]; vv = vv[~np.isnan(vv)]
        if len(vv):
            for i in idx: out[i] = np.median(vv)
    return out

SIC2 = np.array([str(cand[c].get('sic') or '00')[:2] for c in CIKS])
OTC = np.array([1.0 if str(cand[c].get('exchange') or '').upper() == 'OTC' else 0.0 for c in CIKS])

FEAT_CACHE = {}
def features(ym):
    if ym in FEAT_CACHE: return FEAT_CACHE[ym]
    Y, M = int(ym[:4]), int(ym[5:7])
    fy = Y - 1 if M >= 6 else Y - 2
    mj = MIDX[ym]
    adj = PXA[:, mj]; raw = PXR[:, mj]
    yi = YIDX[fy]
    poolmask = (~np.isnan(adj)) & (adj > 0) & (~np.isnan(mat('ni')[yi])) & \
               (~np.isnan(mat('rev')[yi])) & (~np.isnan(mat('eq')[yi])) & \
               (~np.isnan(mat('at')[yi])) & (~np.isnan(mat('sh')[yi]))
    idx = np.where(poolmask)[0]
    F = {'idx': idx, 'fy': fy, 'ym': ym}
    def A(name, yoff=0):
        return mat(name)[YIDX[fy - yoff], idx]
    fac = CUM[idx, YIDX[min(Y, 2025)]] / CUM[idx, yi]          # split factor fy -> formation year
    sh_fy = A('sh') * fac                            # shares on formation basis
    F['shares'] = sh_fy
    F['adj'] = adj[idx]; F['raw'] = raw[idx]
    F['cap'] = sh_fy * raw[idx]
    for nm in ('ni', 'rev', 'eq', 'at', 'liab', 'oi', 'ocf', 'ppe', 'inv', 'recv', 'capex', 'dep'):
        F[nm] = A(nm)
    div = A('div'); diva = A('divall')
    F['div'] = np.where(np.isnan(div), np.where(np.isnan(diva), 0.0, diva), div)
    F['eps'] = F['ni'] / np.where(sh_fy > 0, sh_fy, np.nan)
    for k in (1, 2, 3, 4, 5):
        shk = mat("sh")[YIDX[fy - k], idx] * (CUM[idx, YIDX[min(Y, 2025)]] / CUM[idx, YIDX[fy - k]])
        F[f'eps_{k}'] = mat('ni')[YIDX[fy - k], idx] / np.where(shk > 0, shk, np.nan)
        F[f'rev_{k}'] = A('rev', k); F[f'ni_{k}'] = A('ni', k); F[f'eq_{k}'] = A('eq', k)
    def growth(cur, prev):
        return np.where((prev > 0) & (cur > 0), cur / prev - 1, np.nan)
    F['eps_g1'] = growth(F['eps'], F['eps_1']); F['eps_g2'] = growth(F['eps_1'], F['eps_2'])
    F['eps_g3'] = growth(F['eps_2'], F['eps_3']); F['eps_g4'] = growth(F['eps_3'], F['eps_4'])
    with np.errstate(invalid='ignore', divide='ignore'):
        F['eps_cagr5'] = np.where((F['eps'] > 0) & (F['eps_5'] > 0), (F['eps'] / F['eps_5']) ** 0.2 - 1, np.nan)
        F['rev_cagr5'] = np.where((F['rev'] > 0) & (F['rev_5'] > 0), (F['rev'] / F['rev_5']) ** 0.2 - 1, np.nan)
        F['rev_cagr3'] = np.where((F['rev'] > 0) & (F['rev_3'] > 0), (F['rev'] / F['rev_3']) ** (1 / 3) - 1, np.nan)
        F['pe'] = np.where(F['ni'] > 0, F['cap'] / F['ni'], np.nan)
        F['pb'] = np.where(F['eq'] > 0, F['cap'] / F['eq'], np.nan)
        F['ps'] = np.where(F['rev'] > 0, F['cap'] / F['rev'], np.nan)
    cf = F['ni'] + np.where(np.isnan(F['dep']), 0.0, F['dep'])
    F['cf'] = cf
    with np.errstate(invalid='ignore', divide='ignore'):
        F['pcf'] = np.where(cf > 0, F['cap'] / cf, np.nan)
        F['fcf'] = F['ocf'] - F['capex']
        F['pfcf'] = np.where(F['fcf'] > 0, F['cap'] / F['fcf'], np.nan)
        F['dy'] = np.where(F['cap'] > 0, F['div'] / F['cap'], np.nan)
        F['roe'] = np.where(F['eq'] > 0, F['ni'] / F['eq'], np.nan)
        F['netm'] = np.where(F['rev'] > 0, F['ni'] / F['rev'], np.nan)
        F['opm'] = np.where(F['rev'] > 0, F['oi'] / F['rev'], np.nan)
        F['lia_at'] = np.where(F['at'] > 0, F['liab'] / F['at'], np.nan)
    roe_yrs = []
    for k in range(5):
        e = A('eq', k); nn = A('ni', k)
        roe_yrs.append(np.where(e > 0, nn / e, np.nan))
    with np.errstate(invalid='ignore'):
        F['roe5'] = np.nanmean(np.vstack(roe_yrs), axis=0)
    F['frot'] = np.where(F['ni'] > 0, F['ni'] / F['cap'], 0.0) + \
                np.where(F['eq'] > 0, (F['ni'] - F['div']) / F['eq'], np.nan) + \
                np.where(F['cap'] > 0, F['div'] / F['cap'], 0.0)
    for k, nm in ((1, 'r1m'), (3, 'r3m'), (6, 'r6m'), (12, 'r12m')):
        past = PXA[idx, mj - k] if mj - k >= 0 else np.full(len(idx), np.nan)
        F[nm] = np.where(past > 0, F['adj'] / past - 1, np.nan)
    for k, nm in ((3, 'spy3'), (6, 'spy6'), (12, 'spy12')):
        F[nm] = SPY[mj] / SPY[mj - k] - 1 if mj - k >= 0 else np.nan
    F['rs26'] = F['r6m'] - F['spy6']; F['rs13'] = F['r3m'] - F['spy3']
    seg = PXA[idx, mj - 5:mj + 1] if mj >= 5 else np.full((len(idx), 6), np.nan)
    with np.errstate(invalid='ignore'):
        F['ksr'] = np.where(np.sum(~np.isnan(seg), axis=1) == 6, F['adj'] / np.nanmean(seg, axis=1), np.nan)
    F['sic2'] = SIC2[idx]; F['otc'] = OTC[idx]
    F['rate'] = np.array([cost_rate(c) for c in F['cap']])
    FEAT_CACHE[ym] = F
    return F

PMAT = {}
def price_matrix(idx, ym, hold):
    key = (ym, hold)
    mj = MIDX[ym]
    M = PXA[idx, mj:mj + hold + 1].astype(float).copy()
    lastbar = np.full(len(idx), -1)
    for i in range(len(idx)):
        row = PXA[idx[i]]
        nz = np.where(~np.isnan(row))[0]
        lastbar[i] = nz[-1] if len(nz) else -1
    last = np.full(len(idx), np.nan)
    for j in range(hold + 1):
        col = M[:, j]
        upd = ~np.isnan(col)
        last[upd] = col[upd]
        dead = (mj + j) > lastbar
        M[dead, j] = 0.0
        alive = ~dead
        M[alive, j] = np.where(np.isnan(M[alive, j]), last[alive], M[alive, j])
    return M

# ---------------- screens: fn(F, uni) -> (mask, rankkey) ----------------
def base_pool(F, uni):
    m = np.ones(len(F['idx']), dtype=bool)
    if uni == 'native': m &= F['otc'] == 0
    return m

def S_driehaus(F, uni):
    m = base_pool(F, uni)
    m &= (F['cap'] >= 50e6) & (F['cap'] <= 3e9)
    m &= (F['eps_g1'] > F['eps_g2']) & (F['eps_g2'] > F['eps_g3']) & (F['eps_g1'] > 0)
    m &= F['r1m'] > 0
    med = ind_median(F['r6m'], F['sic2'])
    m &= F['r6m'] >= med
    return m, F['r6m']

def _dcf(F, yoff):
    idx = F['idx']; fy = F['fy'] - yoff
    def g(name, y):
        return mat(name)[YIDX[y], idx]
    with np.errstate(invalid='ignore', divide='ignore'):
        op = ((g('eq', fy) - g('eq', fy - 1)) - (g('ppe', fy) - g('ppe', fy - 1)) -
              (g('inv', fy) - g('inv', fy - 1))) / g('rev', fy)
        bs = ((g('liab', fy) - g('liab', fy - 1)) - (g('recv', fy) - g('recv', fy - 1))) / g('rev', fy)
    return op, bs

def S_dualcf(F, uni):
    m = base_pool(F, uni)
    op1, bs1 = _dcf(F, 0); op2, bs2 = _dcf(F, 1)
    m &= (op1 > 0) & (op2 > 0) & (bs1 < 0) & (bs2 < 0) & (op1 > op2)
    return m, op1

def S_fisher(F, uni):
    m = base_pool(F, uni)
    for k in range(5):
        nn = F['ni'] if k == 0 else F[f'ni_{k}']
        rv = F['rev'] if k == 0 else F[f'rev_{k}']
        nm = np.where(rv > 0, nn / rv, np.nan)
        med = ind_median(nm, F['sic2'])
        m &= nm > med
    m &= (F['rev'] > F['rev_1']) & (F['rev_1'] > F['rev_2']) & (F['rev_2'] > F['rev_3'])
    med3 = ind_median(F['rev_cagr3'], F['sic2'])
    m &= F['rev_cagr3'] >= med3
    m &= F['div'] <= 0
    peg = np.where((F['pe'] > 0) & (F['eps_cagr5'] > 0), F['pe'] / (F['eps_cagr5'] * 100), np.nan)
    m &= (peg > 0.1) & (peg <= 0.5)
    return m, -peg

def S_frot(F, uni):
    m = base_pool(F, uni)
    med = ind_median(F['lia_at'], F['sic2'])
    m &= F['frot'] >= 0.25
    m &= F['lia_at'] <= med
    return m, F['frot']

def _kirk_common(F, uni):
    m = base_pool(F, uni)
    F['_ksr_pct'] = pct_rank(F['ksr'])
    eg = np.where(F['eps_1'] > 0, F['eps'] / F['eps_1'], np.nan)
    F['_eg_pct'] = pct_rank(eg)
    F['_ps_pct'] = pct_rank(F['ps'])
    return m

def S_kirk_growth(F, uni):
    m = _kirk_common(F, uni)
    m &= (F['raw'] >= 10) & (F['cap'] >= 1e9)
    m &= (F['_ksr_pct'] >= 90) & (F['_eg_pct'] >= 90)
    return m, F['ksr']

def S_kirk_value(F, uni):
    m = _kirk_common(F, uni)
    m &= (F['raw'] >= 10) & (F['cap'] >= 500e6)
    m &= (F['_ksr_pct'] >= 90) & (F['_eg_pct'] >= 90) & (F['_ps_pct'] <= 30)
    return m, F['ksr']

def S_kirk_bargain(F, uni):
    m = _kirk_common(F, uni)
    m &= (F['raw'] >= 10) & (F['cap'] >= 1e9)
    mb = m & (F['_ksr_pct'] >= 97) & (F['_ps_pct'] >= 17) & (F['_ps_pct'] <= 42)
    if mb.sum() < 20:
        mb = m & (F['_ksr_pct'] >= 90) & (F['_ps_pct'] >= 17) & (F['_ps_pct'] <= 42)
    return mb, F['ksr']

def S_lakonishok(F, uni):
    m = base_pool(F, uni)
    m &= F['cap'] >= 500e6
    any_low = np.zeros(len(F['idx']), dtype=bool)
    for key in ('pb', 'pcf', 'pe', 'ps'):
        med = ind_median(F[key], F['sic2'])
        any_low |= (F[key] < med)
    m &= any_low
    m &= F['rs26'] > 0
    m &= F['rs13'] >= F['rs26']
    return m, F['rs13']

def S_muhlenkamp(F, uni):
    m = base_pool(F, uni)
    m &= (F['roe'] > 0.12) & (F['roe5'] > 0.12)
    m &= (F['pe'] > 0) & (F['pe'] < 17)
    med = ind_median(F['eps_cagr5'], F['sic2'])
    m &= (F['eps_cagr5'] > 0) & (F['eps_cagr5'] >= med)
    m &= F['rev_cagr5'] >= F['eps_cagr5']
    mednm = ind_median(F['netm'], F['sic2'])
    m &= F['netm'] > mednm
    medla = ind_median(F['lia_at'], F['sic2'])
    m &= F['lia_at'] < medla
    m &= F['fcf'] - F['div'] > 0
    return m, F['roe']

def S_neff(F, uni):
    m = base_pool(F, uni)
    g = F['eps_cagr5'] * 100
    dpeg = np.where((F['pe'] > 0) & (F['eps_cagr5'] > 0), F['pe'] / (g + F['dy'] * 100), np.nan)
    med = np.nanmedian(dpeg) if np.any(~np.isnan(dpeg)) else np.nan
    m &= dpeg <= 0.5 * med
    m &= (F['eps_cagr5'] >= 0.07) & (F['eps_cagr5'] <= 0.20)
    m &= (F['rev_cagr5'] >= 0.07) & (F['rev_cagr5'] <= 0.20)
    m &= F['fcf'] > 0
    medom = ind_median(F['opm'], F['sic2'])
    m &= F['opm'] > medom
    return m, -dpeg

def _market_leaders(F, uni):
    m = base_pool(F, uni)
    idx = np.where(m)[0]
    if len(idx) == 0: return m
    capm = np.nanmean(F['cap'][idx]); shm = np.nanmean(F['shares'][idx])
    cfps = F['cf'] / np.where(F['shares'] > 0, F['shares'], np.nan)
    cfm = np.nanmean(cfps[idx]); rvm = np.nanmean(F['rev'][idx])
    m &= (F['cap'] > capm) & (F['shares'] > shm) & (cfps > cfm) & (F['rev'] >= 1.5 * rvm)
    return m

def S_osh_value(F, uni):
    return _market_leaders(F, uni), F['dy']

def S_osh_growth2(F, uni):
    m = base_pool(F, uni)
    m &= F['cap'] >= 150e6
    m &= (F['ps'] > 0) & (F['ps'] < 1.5)
    m &= F['eps_g1'] > 0
    return m, F['r12m']

def S_osh_scgv(F, uni):
    m = base_pool(F, uni)
    esc = 1.03 ** (F['fy'] + 1 - 2005)
    m &= (F['cap'] >= 200e6 * esc) & (F['cap'] <= 2e9 * esc)
    m &= (F['ps'] > 0) & (F['ps'] < 1.5)
    m &= F['eps_g1'] > 0
    return m, F['r12m']

def S_osh_gml(F, uni):
    m = _market_leaders(F, uni)
    m &= (F['eps_g1'] > 0) & (F['eps_g2'] > 0) & (F['eps_g3'] > 0) & (F['eps_g4'] > 0)
    return m, F['r12m']

def S_osh_allcap(F, uni):
    m = base_pool(F, uni)
    esc = 1.03 ** (F['fy'] + 1 - 2006)
    m &= F['cap'] >= 200e6 * esc
    psp = pct_rank(F['ps']); pcfp = pct_rank(F['pcf']); dyp = pct_rank(F['dy'])
    m &= (psp <= 30) & (pcfp <= 30) & (dyp >= 70)
    return m, F['r12m']

def S_tiny_titans(F, uni):
    m = base_pool(F, uni)
    m &= (F['cap'] >= 25e6) & (F['cap'] <= 250e6)
    m &= (F['ps'] > 0) & (F['ps'] < 1.0)
    return m, F['r12m']

SCREENS = {
 'driehaus': (S_driehaus, 'ALL'), 'dual-cash-flow': (S_dualcf, 'ALL'),
 'fisher': (S_fisher, 'ALL'), 'fundamental-rule-of-thumb': (S_frot, 'ALL'),
 'kirkpatrick-growth': (S_kirk_growth, 'ALL'), 'kirkpatrick-value': (S_kirk_value, 'ALL'),
 'kirkpatrick-bargain': (S_kirk_bargain, 'ALL'),
 'lakonishok': (S_lakonishok, 'ALL'), 'muhlenkamp': (S_muhlenkamp, 'ALL'),
 'neff': (S_neff, 'ALL'),
 'oshaughnessy-value': (S_osh_value, 50), 'oshaughnessy-growth2': (S_osh_growth2, 50),
 'oshaughnessy-scgv': (S_osh_scgv, 25), 'oshaughnessy-gml': (S_osh_gml, 10),
 'oshaughnessy-allcap': (S_osh_allcap, 25), 'tiny-titans': (S_tiny_titans, 25),
}

CAD = {'monthly': 1, 'quarterly': 3, 'semiannual': 6, 'annual': 12}
def formation_months(cad, start, end):
    out = []; ym = start
    while ym < end:
        y, m = int(ym[:4]), int(ym[5:7])
        if cad == 'monthly': ok = True
        elif cad == 'quarterly': ok = m in (3, 6, 9, 12)
        elif cad == 'semiannual': ok = m in (6, 12)
        else: ok = m == 6
        if ok and ym_add(ym, CAD[cad]) <= '2026-11': out.append(ym)
        ym = ym_add(ym, 1)
    return out

ROADS = {'LONGEST': ('2016-06', '2026-06'), 'DECADE': ('2017-06', '2026-06'),
         'CONT': ('2019-06', '2026-06'), 'VAL': ('2023-06', '2026-06'),
         'FOLD1': ('2016-06', '2021-06'), 'FOLD2': ('2021-06', '2026-06')}

PICK_CACHE = {}
SCREEN_CACHE = {}
def run_cell(screen_fn, uni, rb, cad, count, road, native_count):
    hold = CAD[cad]
    forms = formation_months(cad, *ROADS[road])
    if not forms: return None
    house = rb == 'house'
    NS = 21
    cash = np.full(NS, 100.0); peak = np.full(NS, 100.0)
    costs = 0.0; curve = []
    for fi, ym in enumerate(forms):
        F = features(ym)
        sck = (id(screen_fn), uni, ym)
        if sck in SCREEN_CACHE: mask, rank = SCREEN_CACHE[sck]
        else:
            mask, rank = screen_fn(F, uni); SCREEN_CACHE[sck] = (mask, rank)
        pool_pos = np.where(mask)[0]
        npool = len(pool_pos)
        if count == 'ALL': n = npool
        elif count == 'NATIVE': n = npool if native_count == 'ALL' else min(native_count, npool)
        else: n = min(count, npool)
        if n == 0:
            for j in range(1, hold + 1): curve.append([ym_add(ym, j), round(float(cash[0]), 2)])
            continue
        ck = (id(screen_fn), uni, ym, n)
        if ck in PICK_CACHE:
            picks = PICK_CACHE[ck]
        else:
            rk = np.where(np.isnan(rank[pool_pos]), -1e18, rank[pool_pos])
            actual_pos = pool_pos[np.argsort(-rk)[:n]]
            picks = [actual_pos]
            for s in range(1, NS):
                rng = random.Random(s * 100003 + fi * 131 + MIDX[ym])
                picks.append(np.array(rng.sample(list(pool_pos), n)) if npool > n else pool_pos.copy())
            PICK_CACHE[ck] = picks
        M = price_matrix(F['idx'], ym, hold)
        rates = F['rate']
        maxn = n
        P3 = np.zeros((NS, maxn, hold + 1)); R3 = np.zeros((NS, maxn)); SH = np.zeros((NS, maxn))
        for s in range(NS):
            pk = picks[s]
            P = M[pk, :]; r = rates[pk]
            P3[s] = P; R3[s] = r
            p0 = P[:, 0].copy(); p0[p0 <= 0] = np.nan
            w = cash[s] / len(pk)
            SH[s] = np.where(np.isnan(p0), 0.0, w * (1 - r) / np.where(np.isnan(p0), 1.0, p0))
            if s == 0: costs += float(np.sum(w * r))
        vals = np.zeros((NS, hold + 1)); vals[:, 0] = cash
        incash = np.zeros(NS, dtype=bool)
        live = SH[:, :, None] * np.where(np.isnan(P3), 0.0, P3)
        for j in range(1, hold + 1):
            v = live[:, :, j].sum(axis=1)
            if j == hold:
                sell = (live[:, :, j] * R3).sum(axis=1)
                v = v - sell
                costs += float(sell[0])
            vals[:, j] = np.where(incash, cash, v)
            cash = vals[:, j].copy()
            peak = np.maximum(peak, cash)
            if house:
                trig = ((cash <= 0.85 * peak) & (~incash)) if j < hold else np.zeros(NS, dtype=bool)
                if trig.any():
                    sell = (live[:, :, j] * R3).sum(axis=1)
                    cash = np.where(trig, cash - sell, cash)
                    vals[:, j] = cash
                    costs += float(sell[0]) if trig[0] else 0.0
                    incash = incash | trig
        cash = vals[:, hold].copy(); peak = np.maximum(peak, cash)
        for j in range(1, hold + 1): curve.append([ym_add(ym, j), round(float(vals[0, j]), 2)])
    peak2 = 100.0; maxdd = 0.0
    for _, v in curve:
        peak2 = max(peak2, v); maxdd = max(maxdd, 1 - v / peak2) if peak2 else 0.0
    a = spy.get(forms[0]); b = spy.get(ym_add(forms[-1], hold))
    spyfin = round(100 * b / a, 2) if a and b else None
    twins = [round(float(x), 2) for x in cash[1:]]
    return {'final': round(float(cash[0]), 2), 'costs': round(costs, 2),
            'max_dd': round(maxdd, 4), 'spy_same_window': spyfin,
            'placebo_finals': twins,
            'placebos_beaten': int(sum(1 for t in twins if cash[0] > t)),
            'curve': curve, 'n_formations': len(forms)}

def main():
    screen = sys.argv[1]
    fn, native_count = SCREENS[screen]
    counts = [1, 2, 3, 5, 8, 10, 15, 20, 30, 'ALL']
    if native_count != 'ALL' and native_count not in counts: counts.append('NATIVE')
    grid = {}
    for uni in ('native', 'broad'):
        for rb in ('native', 'house'):
            for cad in ('monthly', 'quarterly', 'semiannual', 'annual'):
                for count in counts:
                    key = f'{uni}|{rb}|{cad}|{count}'
                    cell = {}
                    for road in ('LONGEST', 'DECADE', 'CONT', 'VAL'):
                        cell[road] = run_cell(fn, uni, rb, cad, count, road, native_count)
                    if cad in ('annual', 'quarterly'):
                        for road in ('FOLD1', 'FOLD2'):
                            cell[road] = run_cell(fn, uni, rb, cad, count, road, native_count)
                    grid[key] = cell
                    c0 = cell['LONGEST']
                    print(key, 'LONGEST', c0['final'] if c0 else None,
                          'pb', c0['placebos_beaten'] if c0 else None, flush=True)
    pools = {}
    for y in range(2016, 2026):
        F = features(f'{y:04d}-06')
        mask, _ = fn(F, 'native')
        pools[str(y)] = int(mask.sum())
    res = {'screen': screen, 'native_count': native_count, 'pool_sizes_june_native': pools, 'grid': grid}
    out = os.path.join(FAM, 'results.json')
    data = json.load(open(out)) if os.path.exists(out) else {'screens': {}}
    data.setdefault('screens', {})[screen] = res
    json.dump(data, open(out, 'w'), indent=1)
    print('saved', screen)

if __name__ == '__main__':
    main()
