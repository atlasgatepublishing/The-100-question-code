#!/usr/bin/env python3
"""V13 best-rules run — catalog-hlz-political-contributions.
Spec: ../BEST-RULES-SPEC.md (frozen before this run).
Data layer copied from the program W04 chassis (engine_base pattern):
monthly prices Jan 2016-Nov 2026, tiered costs, vanished->ZERO.
Signal: ../data/signal.json (FEC connected-PAC candidate counts by
completed election cycle). February formations, signal = most recent
completed cycle (usable Feb 1 after the Jan 31 filing deadline),
top 20 by distinct candidates supported, equal weight, 12-month hold,
NO floor. 20-seed placebos from the same eligible pond.
Writes ../results.json with equity curves. Simulation only."""
import json, os, sys, math, random
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FAM = os.path.join(HERE, '..')
W04 = '/home/hatch/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data'
SYF = '/home/hatch/workspace/stock-app/backtests/v12-completions/shareholder-yield/data/frames'
FR = '/home/hatch/workspace/stock-app/backtests/v12-completions/catalog-aaii-neff/data/frames'
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

OTC = np.array([1.0 if str(cand[c].get('exchange') or '').upper() == 'OTC' else 0.0 for c in CIKS])

FEAT_CACHE = {}
def features(ym):
    """Formation features: cap/cost/price validity on the program pool
    (PIT June-lag fundamentals rule inherited from the chassis)."""
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
    fac = CUM[idx, YIDX[min(Y, 2025)]] / CUM[idx, yi]
    sh_fy = mat('sh')[yi, idx] * fac
    F = {'idx': idx, 'fy': fy, 'ym': ym,
         'cap': sh_fy * raw[idx], 'adj': adj[idx],
         'otc': OTC[idx],
         'rate': np.array([cost_rate(c) for c in sh_fy * raw[idx]])}
    FEAT_CACHE[ym] = F
    return F

def price_matrix(idx, ym, hold):
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

# ---------------- signal ----------------
SIGNAL = json.load(open(os.path.join(FAM, 'data', 'signal.json')))
def cycle_for(feb_year):
    y = feb_year - 1
    return str(y if y % 2 == 0 else y - 1)

def pond_and_picks(ym):
    """Returns (pond_global_idx, signal_picks_global_idx, pond_size)."""
    F = features(ym)
    cyc = cycle_for(int(ym[:4]))
    sig = SIGNAL.get(cyc, {})
    pos = []
    for j, gidx in enumerate(F['idx']):
        cik = CIKS[gidx]
        if str(cik) in sig and F['otc'][j] == 0 and not np.isnan(F['cap'][j]):
            pos.append(j)
    pond = F['idx'][pos]
    ranked = sorted(pos, key=lambda j: (-sig[str(CIKS[F['idx'][j]])][0],
                                        -sig[str(CIKS[F['idx'][j]])][1],
                                        CIKS[F['idx'][j]]))
    picks = F['idx'][ranked[:20]]
    return F, pond, picks

HOLD = 12
def run_road(form_years, mode, seed=0):
    """mode: 'signal' or 'placebo'. Returns road result dict."""
    NS = 1
    cash = 100.0; costs = 0.0; curve = []; periods = []
    pond_sizes = []
    for fy_ in form_years:
        ym = f'{fy_:04d}-02'
        F, pond, picks = pond_and_picks(ym)
        pond_sizes.append(len(pond))
        if mode == 'placebo':
            rng = random.Random(seed * 100003 + fy_ * 131)
            pk = np.array(rng.sample(list(pond), min(20, len(pond)))) if len(pond) else pond
        else:
            pk = picks
        start_cash = cash
        if len(pk) == 0:
            for j in range(1, HOLD + 1): curve.append([ym_add(ym, j), round(cash, 2)])
            periods.append(0.0); continue
        posmap = {g: j for j, g in enumerate(F['idx'])}
        rates = np.array([F['rate'][posmap[g]] for g in pk])
        M = price_matrix(pk, ym, HOLD)
        p0 = M[:, 0].copy(); p0[p0 <= 0] = np.nan
        w = cash / len(pk)
        sh = np.where(np.isnan(p0), 0.0, w * (1 - rates) / np.where(np.isnan(p0), 1.0, p0))
        costs += float(np.sum(w * rates))
        live = sh[:, None] * np.where(np.isnan(M), 0.0, M)
        vals = np.zeros(HOLD + 1); vals[0] = cash
        for j in range(1, HOLD + 1):
            v = live[:, j].sum()
            if j == HOLD:
                sell = (live[:, j] * rates).sum()
                v -= sell; costs += float(sell)
            vals[j] = v
            curve.append([ym_add(ym, j), round(float(v), 2)])
        cash = float(vals[HOLD])
        periods.append(cash / start_cash - 1.0)
    peak = 100.0; maxdd = 0.0; last_high_i = 0; longest_gap = 0
    for i, (_, v) in enumerate(curve):
        if v >= peak: peak = v; last_high_i = i
        else: longest_gap = max(longest_gap, i - last_high_i)
        maxdd = max(maxdd, 1 - v / peak) if peak else 0.0
    # longest losing streak over periods
    streak = 0; worst_streak = 0
    for r in periods:
        streak = streak + 1 if r < 0 else 0
        worst_streak = max(worst_streak, streak)
    a = spy.get(f'{form_years[0]:04d}-02'); b = spy.get(ym_add(f'{form_years[-1]:04d}-02', HOLD))
    spyfin = round(100 * b / a, 2) if a and b else None
    med = float(np.median(periods)) if periods else None
    return {'final': round(cash, 2), 'costs': round(costs, 2),
            'max_dd': round(maxdd, 4), 'spy_same_window': spyfin,
            'period_returns': [round(r, 4) for r in periods],
            'median_period': round(med, 4) if med is not None else None,
            'share_positive': round(float(np.mean([r > 0 for r in periods])), 3) if periods else None,
            'best_period': round(max(periods), 4) if periods else None,
            'worst_period': round(min(periods), 4) if periods else None,
            'longest_losing_streak_periods': worst_streak,
            'longest_months_between_new_highs': longest_gap,
            'pond_sizes': pond_sizes, 'curve': curve}

ROADS = {'LONGEST': list(range(2016, 2026)), 'DECADE': list(range(2017, 2026)),
         'CONT': list(range(2019, 2026)), 'VAL': list(range(2023, 2026)),
         'FOLD_A_2016_2020': list(range(2016, 2021)), 'FOLD_B_2021_2025': list(range(2021, 2026))}

def main():
    out = {'family': 'catalog-hlz-political-contributions', 'spec': 'BEST-RULES-SPEC.md',
           'roads': {}}
    for road, years in ROADS.items():
        res = run_road(years, 'signal')
        twins = []
        for s in range(1, 21):
            twins.append(run_road(years, 'placebo', seed=s)['final'])
        res['placebo_finals'] = twins
        res['placebos_beaten'] = int(sum(1 for t in twins if res['final'] > t))
        out['roads'][road] = res
        print(road, 'final', res['final'], 'maxDD', res['max_dd'], 'SPY', res['spy_same_window'],
              'pb', res['placebos_beaten'], '/20', 'pond', res['pond_sizes'], flush=True)
    # half-windows for LONGEST/CONT/VAL/DECADE (confirmation machinery)
    hw = {}
    for road in ('LONGEST', 'DECADE', 'CONT', 'VAL'):
        yrs = ROADS[road]; h = len(yrs) // 2
        hw[road] = {'first_half': run_road(yrs[:h], 'signal'),
                    'second_half': run_road(yrs[h:], 'signal')}
        for k, v in hw[road].items():
            print(road, k, 'final', v['final'], 'SPY', v['spy_same_window'], flush=True)
    out['half_windows'] = hw
    json.dump(out, open(os.path.join(FAM, 'results.json'), 'w'), indent=1)
    print('saved results.json')

if __name__ == '__main__':
    main()
