#!/usr/bin/env python3
"""catalog-hxz-cash-holdings v13 BEST-RULES engine (spec: BEST-RULES-SPEC.md, frozen before run) — decile chassis; v12 engine — frozen by SPEC-FROZEN.md. Generic HXZ-sort chassis:
June formations, 12-month holds, W04 broad price stack + EDGAR frames,
tiered program costs, vanished->ZERO, v9 house floor variant, full
pre-registered grid, 20-seed placebos (annual cadence full; other cadences
LONGEST road, 10 seeds). Simulation only."""
import json, os, math, random
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FAM = os.path.join(HERE, '..')
W04 = os.path.join(FAM, '..', '..', 'v11-native-rules', '_w04_broad_data')
WFR = os.path.join(W04, 'frames')
LFR = os.path.join(FAM, 'data', 'frames')

def loadj(p):
    return json.load(open(p)) if os.path.exists(p) else {}

def frame(tag, y, suf):
    """Local family frames override W04 frames."""
    for base in (LFR, WFR):
        d = loadj(os.path.join(base, f'{tag}_{y}{suf}.json'))
        if d: return {int(k): v for k, v in d.items()}
    return {}

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

YEARS = list(range(2009, 2026))
def F_series(tag, suf):
    return {y: frame(tag, y, suf) for y in YEARS}
AT = F_series('Assets', 'I'); CHE = F_series('CashAndCashEquivalentsAtCarryingValue', 'I')
PPE = F_series('PropertyPlantAndEquipmentNet', 'I'); LT = F_series('Liabilities', 'I')
LTE = F_series('StockholdersEquity', 'I'); LTD = F_series('LongTermDebt', 'I')
DCUR = F_series('DebtCurrent', 'I'); SH = F_series('Shares', 'I')
NI = F_series('NetIncomeLoss', 'D'); OCF = F_series('NetCashProvidedByUsedInOperatingActivities', 'D')
OI = F_series('OperatingIncomeLoss', 'D')
ARF = F_series('AccountsReceivableNetCurrent', 'I'); INV = F_series('InventoryNet', 'I')
SEC = F_series('SecuredDebt', 'I'); CONV = F_series('ConvertibleDebt', 'I')
def sales(y):
    out = {}
    for tag in ('SalesRevenueNet', 'RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues'):
        for k, v in frame(tag, y, 'D').items(): out.setdefault(k, v)
    return out
SALES = {y: sales(y) for y in YEARS}

sf = {}
for cik in cand:
    avail = [(y, SH[y][cik]) for y in YEARS if cik in SH[y]]
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
    sh = SH.get(F - 1, {}).get(cik) or SH.get(F - 2, {}).get(cik)
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

def debt(y, cik):
    a = LTD[y].get(cik); b = DCUR[y].get(cik)
    if a is None and b is None: return None
    return (a or 0) + (b or 0)

def ym(y, m): return f'{y:04d}-{m:02d}'

# === SIGNALS injected per family: build_signals() -> {F: {cik: {name: val}}} ===
SIGNALS_META = {}  # name -> +1 long HIGH / -1 long LOW (published direction)
SIGNALS_META.update({'Cta': 1})
def build_signals():
    out = {}
    for F in range(2016, 2026):
        y = F - 1; d = {}
        for cik in cand:
            at = AT[y].get(cik); che = CHE[y].get(cik)
            if not at or che is None: continue
            d[cik] = {'Cta': che / at}
        out[F] = d
    return out

SIG = build_signals()

POOLS = {}
for F in range(2016, 2026):
    for uni in ('native', 'broad'):
        pool = {}
        for cik, sigs in SIG.get(F, {}).items():
            if cik not in px: continue
            e = px[cik].get(ym(F, 6))
            if not e or not e[0]: continue
            if uni == 'native':
                sic = str(cand[cik].get('sic') or '')
                if sic[:2] == '60' or sic[:2] == '61' or sic[:2] == '62' or sic[:2] == '63' or sic[:2] == '64' or sic[:2] == '65' or sic[:1] == '6': continue
            cap = cap_of(cik, F)
            pool[cik] = {'sigs': sigs, 'cap': cap, 'rate': cost_rate(cap), 'px0': e[0]}
        POOLS[(F, uni)] = pool

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
                if lastbar is not None and mm > lastbar: M[i, j] = 0.0
                elif last is not None: M[i, j] = last
        MATS[(F, uni)] = (ciks, M)

def picks_for(F, uni, signal, count):
    pool = POOLS[(F, uni)]
    items = [(c, v['sigs'][signal]) for c, v in pool.items() if signal in v['sigs']]
    items.sort(key=lambda kv: -kv[1] if SIGNALS_META[signal] > 0 else kv[1])
    if count == 'ALL': return [c for c, _ in items]
    if count == 'QUINTILE':
        n = max(1, math.ceil(len(items) * 0.20)); return [c for c, _ in items[:n]]
    if count == 'DECILE':
        n = max(1, math.ceil(len(items) * 0.10)); return [c for c, _ in items[:n]]
    return [c for c, _ in items[:min(count, len(items))]]

def pool_for_signal(F, uni, signal):
    return [c for c, v in POOLS[(F, uni)].items() if signal in v['sigs']]

REBAL = {'annual': {0}, 'quarterly': {0, 3, 6, 9}, 'monthly': set(range(12))}

def run_road(formations, uni, signal, count, cadence, house, seed=None):
    cash = 100.0; peak = 100.0; curve = []; total_costs = 0.0
    for F in formations:
        ciks_all, M = MATS[(F, uni)]
        idx = {c: i for i, c in enumerate(ciks_all)}
        pool = POOLS[(F, uni)]
        if seed is None:
            picks = picks_for(F, uni, signal, count)
        else:
            rng = random.Random(seed * 100003 + F)
            keys = pool_for_signal(F, uni, signal); rng.shuffle(keys)
            if count == 'ALL': n = len(keys)
            elif count == 'QUINTILE': n = max(1, math.ceil(len(keys) * 0.20))
            elif count == 'DECILE': n = max(1, math.ceil(len(keys) * 0.10))
            else: n = min(count, len(keys))
            picks = keys[:n]
        cols = [ym(F, m) for m in range(6, 13)] + [ym(F + 1, m) for m in range(1, 7)]
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
    a = spy.get(ym(formations[0], 6)); b = spy.get(ym(formations[-1] + 1, 6))
    return round(100 * b / a, 2) if a and b else None


ROADS_V13 = {'LONG': list(range(2016, 2026)), 'DECADE': list(range(2017, 2026)),
             'CONT': list(range(2019, 2026)), 'VAL': list(range(2023, 2026))}

def dist_stats(curve, start_month):
    pts = [[start_month, 100.0]] + curve
    rets = []
    for (m0, v0), (m1, v1) in zip(pts, pts[1:]):
        if v0 and v0 > 0: rets.append(v1 / v0 - 1.0)
    if not rets: return {}
    med = float(np.median(rets)); share = sum(1 for r in rets if r > 0) / len(rets)
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0; streak = max(streak, cur)
    peak = -1e18; since = 0; longest = 0
    for _, v in pts:
        if v > peak: peak = v; since = 0
        else: since += 1; longest = max(longest, since)
    return {'months': len(rets), 'median_month_pct': round(med * 100, 2),
            'share_positive': round(share, 4), 'best_month_pct': round(max(rets) * 100, 2),
            'worst_month_pct': round(min(rets) * 100, 2), 'mean_month_pct': round(float(np.mean(rets)) * 100, 2),
            'longest_losing_streak_months': streak, 'longest_between_new_highs_months': longest}

def run_cell(count, forms, seeds=range(1, 21)):
    fin, curve, costs, maxdd = run_road(forms, 'native', 'Cta', count, 'annual', False)
    twins = []
    for sd in seeds:
        tf, _, _, _ = run_road(forms, 'native', 'Cta', count, 'annual', False, seed=sd)
        twins.append(tf)
    start_month = ym(forms[0], 6)
    return {'final': fin, 'costs': costs, 'max_dd': maxdd, 'spy_same_window': spy_final(forms),
            'placebo_finals': twins, 'placebos_beaten': sum(1 for t in twins if fin > t),
            'placebo_median': float(np.median(twins)) if twins else None,
            'curve': curve, 'distribution_monthly': dist_stats(curve, start_month)}

def main():
    out = {'family': 'catalog-hxz-cash-holdings', 'program': 'v13-best-rules',
           'spec': 'BEST-RULES-SPEC.md',
           'pool_sizes_native': {str(F): len(POOLS[(F, 'native')]) for F in range(2016, 2026)},
           'decile_picks': {}, 'roads': {}, 'integrity_quintile': {}, 'yearly_folds': {}, 'half_windows': {}}
    for F in range(2016, 2026):
        pk = picks_for(F, 'native', 'Cta', 'DECILE')
        out['decile_picks'][str(F)] = [{'cik': c, 'ticker': cand[c]['ticker'], 'sic': cand[c].get('sic'),
                                        'cta': round(SIG[F][c]['Cta'], 4)} for c in pk]
    for rname, forms in ROADS_V13.items():
        cell = run_cell('DECILE', forms)
        out['roads'][rname] = cell
        print('MYRULES', rname, cell['final'], 'dd', cell['max_dd'], 'pb', cell['placebos_beaten'], 'spy', cell['spy_same_window'], flush=True)
        icell = run_cell('QUINTILE', forms, seeds=[])
        out['integrity_quintile'][rname] = {'final': icell['final'], 'max_dd': icell['max_dd'], 'costs': icell['costs']}
        print('QUINTILE(integrity)', rname, icell['final'], flush=True)
        # yearly folds (single formations) + half windows, no placebos except as confirmation needs
        yf = {}
        for F in forms:
            yc = run_cell('DECILE', [F], seeds=[])
            yf[str(F)] = {'final': yc['final'], 'spy_same_window': yc['spy_same_window'], 'max_dd': yc['max_dd']}
        out['yearly_folds'][rname] = yf
        mid = len(forms) // 2
        hw = {}
        for label, sub in (('first_half', forms[:mid] if mid else forms[:1]), ('second_half', forms[mid:])):
            if sub:
                hc = run_cell('DECILE', sub, seeds=[])
                hw[label] = {'formations': sub, 'final': hc['final'], 'spy_same_window': hc['spy_same_window'], 'max_dd': hc['max_dd']}
        out['half_windows'][rname] = hw
    with open(os.path.join(FAM, 'results.json'), 'w') as fh: json.dump(out, fh, indent=1)
    print('saved results.json')

if __name__ == '__main__': main()
