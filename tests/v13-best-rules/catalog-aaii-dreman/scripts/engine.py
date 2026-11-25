#!/usr/bin/env python3
"""V13 Best-Rules engine — AAII Dreman screen. Frozen by BEST-RULES-SPEC.md.
Adapted from the v12 engine (read-only): same W04 PIT stack, same five
buildable criteria, same tiered costs, vanished->ZERO. Chassis changes per
spec ONLY: (1) dividend yield measured per-CIK as filed (common-stock tag
if that CIK filed it, else generic tag); (2) single design — ALL passers EW,
annual June formation, no intra-year rebalance, NO floor; (3) 20-seed
placebos draw the same count from the year's eligible BASE pool through the
identical chassis. Filter funnel recorded as post-run diagnostics only."""
import json, os, sys, random
import numpy as np

BASE = os.path.expanduser('~/workspace/stock-app/backtests/v12-completions')
FAM12 = os.path.join(BASE, 'catalog-aaii-dreman')
OUT = os.path.expanduser('~/workspace/stock-app/backtests/v13-best-rules/catalog-aaii-dreman')
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
# SPEC CHANGE 1: per-CIK dividend tag fallback (as filed by that filer)
DIV = {}
for y in range(2009, 2026):
    d1 = {int(k): v for k, v in loadj(os.path.join(FAM12, 'data', 'frames', f'PaymentsOfDividendsCommonStock_{y}D.json')).items()}
    d2 = {int(k): v for k, v in loadj(os.path.join(FAM12, 'data', 'frames', f'PaymentsOfDividends_{y}D.json')).items()}
    m = dict(d2); m.update(d1)   # common-stock tag wins where that CIK filed it
    DIV[y] = m

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
def median(v):
    v = sorted(v); return v[len(v) // 2] if v else None

POOLS, BASEPOOL, FUNNEL = {}, {}, {}
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
                     'eq': FR['StockholdersEquity'][y].get(cik),
                     'lcur': FR['LiabilitiesCurrent'][y].get(cik), 'px0': e[0],
                     'rate': cost_rate(cap)}
    BASEPOOL[F] = base
    groups = {}
    for cik, r in base.items(): groups.setdefault(r['sic2'], []).append(r['liab_at'])
    med = {g: median(v) for g, v in groups.items()}
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
            e0 = ni0 / (sh0 * sf.get(cik, {}).get(F, 1.0)); e1 = r.get('eps')
            if e0 and e1 and e0 > 0 and e1 > 0: growth[cik] = e1 / e0 - 1
    gmed = median(list(growth.values())) if growth else 0
    pool = {}; fun = {'base': len(base)}
    stage = list(base.keys())
    def keep(stage, fn, name):
        s2 = [c for c in stage if fn(base[c], c)]; fun[name] = len(s2); return s2
    stage = keep(stage, lambda r, c: r.get('eps', -1) > 0, 'pos_eps')
    stage = keep(stage, lambda r, c: r['price'] / r['eps'] <= pe_cut, 'pe_bottom40')
    stage = keep(stage, lambda r, c: r['cap'] >= cap_cut, 'cap_top30')
    stage = keep(stage, lambda r, c: r['liab_at'] < med.get(r['sic2'], 1e9), 'liab_below_industry')
    stage = keep(stage, lambda r, c: bool(DIV.get(y, {}).get(c)) and DIV[y][c] / r['cap'] >= 0.015, 'yield_ge_1.5')
    stage = keep(stage, lambda r, c: c in growth and growth[c] > gmed, 'eps_growth_above_median')
    for cik in stage:
        r = dict(base[cik]); r['rank'] = -r['price'] / r['eps']; pool[cik] = r
    fun['pass'] = len(pool)
    POOLS[F] = pool; FUNNEL[F] = fun

MATS = {}
for F in range(2016, 2026):
    cols = [ym(F, m) for m in range(6, 13)] + [ym(F + 1, m) for m in range(1, 7)]
    allciks = sorted(set(POOLS[F]) | set(BASEPOOL[F]))
    M = np.full((len(allciks), len(cols)), np.nan)
    for i, cik in enumerate(allciks):
        s = px[cik]; last = None; lastbar = max(s) if s else None
        for j, mm in enumerate(cols):
            if mm in s: last = s[mm][0]
            if lastbar is not None and mm > lastbar: M[i, j] = 0.0
            elif last is not None: M[i, j] = last
    MATS[F] = (allciks, M)

def run_road(formations, seed=None):
    """Annual formation, ALL passers EW (or same-count random base-pool draw
    for placebos), hold 12 months, sell at next formation, no floor."""
    cash = 100.0; curve = []; total_costs = 0.0
    for F in formations:
        ciks_all, M = MATS[F]; idx = {c: i for i, c in enumerate(ciks_all)}
        pool = POOLS[F]; base = BASEPOOL[F]
        if seed is None: picks = sorted(pool)
        else:
            rng = random.Random(seed * 100003 + F); keys = sorted(base); rng.shuffle(keys)
            picks = keys[:len(pool)]
        cols = [ym(F, m) for m in range(6, 13)] + [ym(F + 1, m) for m in range(1, 7)]
        if not picks:
            for mm in cols[1:]: curve.append([mm, round(cash, 2)])
            continue
        rows = np.array([idx[c] for c in picks]); P = M[rows, :]
        rates = np.array([(pool[c]['rate'] if c in pool else base[c]['rate']) for c in picks])
        px0 = P[:, 0].copy(); px0[px0 <= 0] = np.nan
        w = cash / len(picks)
        shares = np.where(np.isnan(px0), 0.0, (w * (1 - rates)) / np.where(np.isnan(px0), 1.0, px0))
        total_costs += float(np.sum(w * rates))
        for j in range(1, 13):
            pj = P[:, j]; vals = shares * np.where(np.isnan(pj), 0.0, pj); val = float(np.sum(vals))
            if j == 12:
                sell = float(np.sum(vals * rates)); total_costs += sell; cash = val - sell
            else: cash = val
            curve.append([cols[j], round(cash, 2)])
    peak2 = 100.0; maxdd = 0.0
    for _, v in curve:
        peak2 = max(peak2, v); maxdd = max(maxdd, 1 - v / peak2) if peak2 else 0.0
    return round(cash, 2), curve, round(total_costs, 2), round(maxdd, 4)

ROADS = {'LONG': list(range(2016, 2026)), 'DECADE': list(range(2017, 2026)),
         'CONT': list(range(2019, 2026)), 'VAL': list(range(2023, 2026))}
def spy_final(formations):
    a = spy.get(ym(formations[0], 6)); b = spy.get(ym(formations[-1] + 1, 6))
    return round(100 * b / a, 2) if a and b else None

def period_stats(curve):
    vals = [100.0] + [v for _, v in curve]
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
    print('pools', {F: len(POOLS[F]) for F in range(2016, 2026)}, flush=True)
    print('funnel', json.dumps(FUNNEL, indent=0), flush=True)
    out = {'family': 'catalog-aaii-dreman', 'program': 'v13-best-rules',
           'spec': 'ALL passers EW, annual June, no floor, per-CIK dividend tags, base-pool placebos',
           'pool_sizes': {str(F): len(POOLS[F]) for F in range(2016, 2026)},
           'base_pool_sizes': {str(F): len(BASEPOOL[F]) for F in range(2016, 2026)},
           'funnel': {str(F): FUNNEL[F] for F in range(2016, 2026)},
           'picks': {str(F): [cand[c]['ticker'] for c in sorted(POOLS[F])] for F in range(2016, 2026)},
           'roads': {}}
    for rname, forms in ROADS.items():
        fin, curve, costs, maxdd = run_road(forms)
        twins = [run_road(forms, seed=s)[0] for s in range(1, 21)]
        out['roads'][rname] = {'final': fin, 'costs': costs, 'max_dd': maxdd,
                               'spy_same_window': spy_final(forms),
                               'placebos_beaten': sum(1 for t in twins if fin > t),
                               'placebo_median': float(np.median(twins)), 'placebo_finals': twins,
                               'period_stats': period_stats(curve), 'curve': curve}
        print(rname, fin, 'dd', maxdd, 'spy', spy_final(forms), 'pb', sum(1 for t in twins if fin > t), '/20', flush=True)
    json.dump(out, open(os.path.join(OUT, 'results.json'), 'w'), indent=1)
    print('saved')

if __name__ == '__main__': main()
