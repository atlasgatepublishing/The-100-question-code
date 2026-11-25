#!/usr/bin/env python3
"""Slice-1 AAII screen engine. Usage: engine.py <cash-rich|dreman>
Frozen by SPEC-FROZEN.md. W04 broad stack (read-only): monthly prices,
EDGAR frames (Assets, Cash, Liabilities, LiabilitiesCurrent, LongTermDebt*,
NetIncomeLoss, Shares, StockholdersEquity) + this folder's dividend frames
(dreman only). June formations, 12-month holds, tiered program costs,
vanished->ZERO, v9 house floor variant, holdings grid, 20-seed placebos."""
import json, os, sys, math, random
import numpy as np

MODE = sys.argv[1]
SLUG = 'catalog-aaii-cash-rich' if MODE == 'cash-rich' else 'catalog-aaii-dreman'
BASE = os.path.expanduser('~/workspace/stock-app/backtests/v12-completions')
FAM = os.path.join(BASE, SLUG)
W04 = os.path.join(BASE, '..', 'v11-native-rules', '_w04_broad_data')

def loadj(p): return json.load(open(p)) if os.path.exists(p) else {}
cand = {int(k): v for k, v in loadj(os.path.join(W04, 'candidates.json')).items()}
px = {}
for cik, info in cand.items():
    t = info['ticker'].replace('/', '-')
    p = os.path.join(W04, f'px_{t}.json')
    if os.path.exists(p):
        try: px[cik] = {r[0]: (r[1], r[2]) for r in loadj(p)}
        except Exception: pass
spy = {r[0]: r[1] for r in loadj(os.path.join(W04, 'px_SPY.json'))}

def frame(name, y, kind='I'):
    return {int(k): v for k, v in loadj(os.path.join(W04, 'frames', f'{name}_{y}{kind}.json')).items()}
FR = {}
for nm in ('Assets', 'CashAndCashEquivalentsAtCarryingValue', 'Liabilities', 'LiabilitiesCurrent',
           'LongTermDebtCurrent', 'LongTermDebtNoncurrent', 'Shares', 'StockholdersEquity'):
    FR[nm] = {y: frame(nm, y) for y in range(2009, 2026)}
NI = {y: frame('NetIncomeLoss', y, 'D') for y in range(2009, 2026)}
DIV = {}
if MODE == 'dreman':
    for y in range(2009, 2026):
        d1 = {int(k): v for k, v in loadj(os.path.join(FAM, 'data', 'frames', f'PaymentsOfDividendsCommonStock_{y}D.json')).items()}
        d2 = {int(k): v for k, v in loadj(os.path.join(FAM, 'data', 'frames', f'PaymentsOfDividends_{y}D.json')).items()}
        DIV[y] = d1 if d1 else d2

shares_f = FR['Shares']
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

def ym(y, m): return f'{y:04d}-{m:02d}'
def cap_of(cik, F):
    sh = shares_f.get(F - 1, {}).get(cik) or shares_f.get(F - 2, {}).get(cik)
    s = px.get(cik)
    if not sh or not s: return None
    e = s.get(ym(F, 6))
    if not e or not e[1]: return None
    return sh * e[1] * sf.get(cik, {}).get(F, 1.0)
def cost_rate(cap):
    if cap is None: return 0.0075
    if cap >= 5e9: return 0.0010
    if cap >= 1e9: return 0.0025
    return 0.0075
def ltd(cik, y):
    a = FR['LongTermDebtCurrent'][y].get(cik); b = FR['LongTermDebtNoncurrent'][y].get(cik)
    if a is None and b is None: return None
    return (a or 0) + (b or 0)

def median(v):
    v = sorted(v); return v[len(v) // 2] if v else None

POOLS = {}
for F in range(2016, 2026):
    y = F - 1
    base = {}
    for cik in cand:
        if cik not in px: continue
        e = px[cik].get(ym(F, 6))
        if not e or not e[0] or not e[1]: continue
        at = FR['Assets'][y].get(cik); liab = FR['Liabilities'][y].get(cik)
        cash = FR['CashAndCashEquivalentsAtCarryingValue'][y].get(cik)
        ni = NI[y].get(cik); cap = cap_of(cik, F)
        if None in (at, liab, cash, ni) or not cap: continue
        sic = str(cand[cik].get('sic') or '')
        base[cik] = {'at': at, 'liab': liab, 'cash': cash, 'ni': ni, 'cap': cap,
                     'liab_at': liab / at, 'sic2': sic[:2], 'price': e[1],
                     'ltd': ltd(cik, y), 'eq': FR['StockholdersEquity'][y].get(cik),
                     'lcur': FR['LiabilitiesCurrent'][y].get(cik), 'px0': e[0],
                     'rate': cost_rate(cap)}
    # industry (SIC2) medians of liab/assets
    groups = {}
    for cik, r in base.items(): groups.setdefault(r['sic2'], []).append(r['liab_at'])
    med = {g: median(v) for g, v in groups.items()}
    pool = {}
    if MODE == 'cash-rich':
        groups2 = {}
        for cik, r in base.items():
            if r['ltd'] is not None and r['eq']: groups2.setdefault(r['sic2'], []).append(r['ltd'] / (r['ltd'] + r['eq']))
        med2 = {g: median(v) for g, v in groups2.items()}
        for cik, r in base.items():
            sic = str(cand[cik].get('sic') or '')
            if sic[:1] in ('4', '6'): continue                      # utilities + financials excluded (RE sits in 6xxx in this stack — fence in RESULTS)
            if r['ni'] <= 0: continue
            if r['cap'] <= 50e6 or r['price'] <= 5: continue
            if r['liab_at'] >= med.get(r['sic2'], 1e9): continue
            if r['ltd'] is None or not r['eq']: continue
            if r['ltd'] / (r['ltd'] + r['eq']) >= med2.get(r['sic2'], 1e9): continue
            if r['lcur'] is None: continue
            cash_p = r['cash'] / r['cap']; net_p = (r['cash'] - r['lcur']) / r['cap']
            if cash_p <= 0.20 or net_p <= 0.20: continue
            r = dict(r); r['rank'] = net_p
            pool[cik] = r
    else:  # dreman
        pes = []
        for cik, r in base.items():
            sh = shares_f[y].get(cik)
            if not sh: continue
            eps = r['ni'] / (sh * sf.get(cik, {}).get(F, 1.0))
            r['eps'] = eps
            if eps > 0: pes.append(r['price'] / eps)
        pes.sort(); pe_cut = pes[int(0.40 * len(pes))] if pes else 1e18
        caps = sorted(r['cap'] for r in base.values()); cap_cut = caps[int(0.70 * len(caps))] if caps else 0
        growth = {}
        for cik, r in base.items():
            ni0 = NI[y - 1].get(cik) if y - 1 in NI else None
            sh = shares_f[y].get(cik); sh0 = shares_f[y - 1].get(cik) if y - 1 in shares_f else None
            if ni0 and sh and sh0:
                e0 = ni0 / (sh0 * sf.get(cik, {}).get(F, 1.0)); e1 = r['eps']
                if e0 > 0 and e1 > 0: growth[cik] = e1 / e0 - 1
        gmed = median(list(growth.values())) if growth else 0
        for cik, r in base.items():
            if r.get('eps', -1) <= 0: continue
            if r['price'] / r['eps'] > pe_cut: continue
            if r['cap'] < cap_cut: continue
            if r['liab_at'] >= med.get(r['sic2'], 1e9): continue
            div = DIV.get(y, {}).get(cik)
            if not div: continue
            if div / r['cap'] < 0.015: continue
            if cik not in growth or growth[cik] <= gmed: continue
            r = dict(r); r['rank'] = -r['price'] / r['eps']   # ranked by P/E ascending (published list order)
            pool[cik] = r
    POOLS[F] = pool

MATS = {}
for F in range(2016, 2026):
    cols = [ym(F, m) for m in range(6, 13)] + [ym(F + 1, m) for m in range(1, 7)]
    pool = POOLS[F]; ciks = sorted(pool)
    M = np.full((len(ciks), len(cols)), np.nan)
    for i, cik in enumerate(ciks):
        s = px[cik]; last = None; lastbar = max(s) if s else None
        for j, mm in enumerate(cols):
            if mm in s: last = s[mm][0]
            if lastbar is not None and mm > lastbar: M[i, j] = 0.0
            elif last is not None: M[i, j] = last
    MATS[F] = (ciks, M)

def picks_for(F, count):
    items = sorted(POOLS[F].items(), key=lambda kv: -kv[1]['rank'])
    if count == 'ALL': return [c for c, _ in items]
    return [c for c, _ in items[:min(count, len(items))]]

REBAL = {'annual': {0}, 'quarterly': {0, 3, 6, 9}, 'monthly': set(range(12))}
def run_road(formations, count, cadence, house, seed=None):
    cash = 100.0; peak = 100.0; curve = []; total_costs = 0.0
    for F in formations:
        ciks_all, M = MATS[F]; idx = {c: i for i, c in enumerate(ciks_all)}; pool = POOLS[F]
        if seed is None: picks = picks_for(F, count)
        else:
            rng = random.Random(seed * 100003 + F); keys = list(pool.keys()); rng.shuffle(keys)
            n = len(keys) if count == 'ALL' else min(count, len(keys)); picks = keys[:n]
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
            if in_cash:
                curve.append([cols[j], round(cash, 2)]); continue
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

ROADS = {'LONGEST_2016_2025': list(range(2016, 2026)), 'DECADE_2017_2025': list(range(2017, 2026)),
         'CONT_2019_2025': list(range(2019, 2026)), 'VAL_2023_2025': list(range(2023, 2026)),
         'FOLD_2016_2020': list(range(2016, 2021)), 'FOLD_2021_2025': list(range(2021, 2026))}
def spy_final(formations):
    a = spy.get(ym(formations[0], 6)); b = spy.get(ym(formations[-1] + 1, 6))
    return round(100 * b / a, 2) if a and b else None

def period_stats(curve):
    vals = [v for _, v in curve]
    rets = [vals[i] / vals[i - 1] - 1 for i in range(1, len(vals)) if vals[i - 1] > 0]
    if not rets: return {}
    los = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0; los = max(los, cur)
    peak = -1; since = 0; longest = 0
    for v in vals:
        if v >= peak: peak = v; since = 0
        else: since += 1; longest = max(longest, since)
    return {'n_months': len(rets), 'share_positive': round(sum(1 for r in rets if r > 0) / len(rets), 3),
            'median_month_pct': round(100 * float(np.median(rets)), 2), 'best_month_pct': round(100 * max(rets), 2),
            'worst_month_pct': round(100 * min(rets), 2), 'longest_losing_streak_months': los,
            'longest_between_highs_months': longest, 'avg_month_pct_secondary': round(100 * float(np.mean(rets)), 2)}

def main():
    counts = [1, 2, 3, 5, 8, 10, 15, 20, 30, 'ALL']
    grid = {}
    print('pools', {F: len(POOLS[F]) for F in range(2016, 2026)}, flush=True)
    for rb in ('native', 'house'):
        for cad in ('annual', 'quarterly', 'monthly'):
            for count in counts:
                key = f'{rb}|{cad}|{count}'
                cell = {}
                for rname, forms in ROADS.items():
                    fin, curve, costs, maxdd = run_road(forms, count, cad, rb == 'house')
                    twins = [run_road(forms, count, cad, rb == 'house', seed=s)[0] for s in range(1, 21)]
                    cell[rname] = {'final': fin, 'costs': costs, 'max_dd': maxdd, 'spy_same_window': spy_final(forms),
                                   'placebos_beaten': sum(1 for t in twins if fin > t), 'placebo_finals': twins,
                                   'curve': curve if rname == 'LONGEST_2016_2025' else None}
                grid[key] = cell
                print(key, 'LONGEST', cell['LONGEST_2016_2025']['final'], 'pb', cell['LONGEST_2016_2025']['placebos_beaten'], flush=True)
    native_key = 'native|annual|ALL'
    out = {'family': SLUG, 'pool_sizes': {str(F): len(POOLS[F]) for F in range(2016, 2026)}, 'grid': grid,
           'native_period_stats_monthly': period_stats(grid[native_key]['LONGEST_2016_2025']['curve'])}
    json.dump(out, open(os.path.join(FAM, 'results.json'), 'w'), indent=1)
    print('saved')

if __name__ == '__main__': main()
