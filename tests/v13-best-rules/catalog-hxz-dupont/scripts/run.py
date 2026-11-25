#!/usr/bin/env python3
"""catalog-hxz-dupont v13 best-rules run — frozen by BEST-RULES-SPEC.md.
Candidate: Rna (catalog definition, inherited from v12 engine), native
universe (ex-financials), annual June formation, top quintile, equal
weight, NO floor, tiered program costs, vanished->ZERO.
Comparator (grading only, identical chassis): raw ROE = NI / Equity.
20-seed placebos share the chassis. Simulation only, public data."""
import json, os, math, random, statistics
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FAM = os.path.join(HERE, '..')
V12 = os.path.join(FAM, '..', '..', 'v12-completions', 'catalog-hxz-dupont')
W04 = os.path.join(FAM, '..', '..', 'v11-native-rules', '_w04_broad_data')
WFR = os.path.join(W04, 'frames')
LFR = os.path.join(V12, 'data', 'frames')

def loadj(p):
    return json.load(open(p)) if os.path.exists(p) else {}

def frame(tag, y, suf):
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

YEARS = list(range(2009, 2026))
def F_series(tag, suf):
    return {y: frame(tag, y, suf) for y in YEARS}
AT = F_series('Assets', 'I'); CHE = F_series('CashAndCashEquivalentsAtCarryingValue', 'I')
LT = F_series('Liabilities', 'I'); LTD = F_series('LongTermDebt', 'I')
DCUR = F_series('DebtCurrent', 'I'); SH = F_series('Shares', 'I')
LTE = F_series('StockholdersEquity', 'I'); NI = F_series('NetIncomeLoss', 'D')
OI = F_series('OperatingIncomeLoss', 'D')

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

def build_signals():
    """Rna exactly as v12; ROE comparator = NI/LTE (same fiscal year)."""
    out = {}
    for F in range(2016, 2026):
        y = F - 1; d = {}
        for cik in cand:
            at = AT[y].get(cik); che = CHE[y].get(cik); lt = LT[y].get(cik)
            oi = OI[y].get(cik); db = debt(y, cik)
            s = {}
            if at and che is not None and lt is not None and db is not None and oi is not None:
                noa = at - che - (lt - db)
                if noa > 0: s['Rna'] = oi / noa
            ni = NI[y].get(cik); lte = LTE[y].get(cik)
            if ni is not None and lte and lte > 0: s['ROE'] = ni / lte
            if s: d[cik] = s
        out[F] = d
    return out

SIG = build_signals()

POOLS = {}
for F in range(2016, 2026):
    pool = {}
    for cik, sigs in SIG.get(F, {}).items():
        if cik not in px: continue
        e = px[cik].get(ym(F, 6))
        if not e or not e[0]: continue
        sic = str(cand[cik].get('sic') or '')
        if sic[:1] == '6': continue  # native: ex-financials
        cap = cap_of(cik, F)
        pool[cik] = {'sigs': sigs, 'cap': cap, 'rate': cost_rate(cap), 'px0': e[0]}
    POOLS[F] = pool

MATS = {}
for F in range(2016, 2026):
    cols = [ym(F, m) for m in range(6, 13)] + [ym(F + 1, m) for m in range(1, 7)]
    pool = POOLS[F]
    ciks = sorted(pool)
    M = np.full((len(ciks), len(cols)), np.nan)
    for i, cik in enumerate(ciks):
        s = px[cik]; last = None; lastbar = max(s) if s else None
        for j, mm in enumerate(cols):
            if mm in s: last = s[mm][0]
            if lastbar is not None and mm > lastbar: M[i, j] = 0.0
            elif last is not None: M[i, j] = last
    MATS[F] = (ciks, M)

def picks_for(F, signal):
    pool = POOLS[F]
    items = [(c, v['sigs'][signal]) for c, v in pool.items() if signal in v['sigs']]
    items.sort(key=lambda kv: -kv[1])
    n = max(1, math.ceil(len(items) * 0.20))
    return [c for c, _ in items[:n]]

def pool_for_signal(F, signal):
    return [c for c, v in POOLS[F].items() if signal in v['sigs']]

def run_road(formations, signal, seed=None):
    cash = 100.0; curve = []; total_costs = 0.0
    for F in formations:
        ciks_all, M = MATS[F]
        idx = {c: i for i, c in enumerate(ciks_all)}
        pool = POOLS[F]
        if seed is None:
            picks = picks_for(F, signal)
        else:
            rng = random.Random(seed * 100003 + F)
            keys = pool_for_signal(F, signal); rng.shuffle(keys)
            n = max(1, math.ceil(len(keys) * 0.20))
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
        for j in range(1, 13):
            pj = P[:, j]
            vals = shares * np.where(np.isnan(pj), 0.0, pj)
            val = float(np.sum(vals))
            if j == 12:
                sell = float(np.sum(vals * rates)); total_costs += sell; cash = val - sell
            else:
                cash = val
            curve.append([cols[j], round(cash, 2)])
    peak2 = 100.0; maxdd = 0.0
    for _, v in curve:
        peak2 = max(peak2, v); maxdd = max(maxdd, 1 - v / peak2) if peak2 else 0.0
    return round(cash, 2), curve, round(total_costs, 2), round(maxdd, 4)

ROADS = {'LONGEST_2016_2025': list(range(2016, 2026)), 'DECADE_2017_2025': list(range(2017, 2026)),
         'CONT_2019_2025': list(range(2019, 2026)), 'VAL_2023_2025': list(range(2023, 2026)),
         'FOLD_2016_2020': list(range(2016, 2021)), 'FOLD_2021_2025': list(range(2021, 2026)),
         'HALF1_2016_2020': list(range(2016, 2021)), 'HALF2_2021_2025': list(range(2021, 2026))}

def spy_final(formations):
    a = spy.get(ym(formations[0], 6)); b = spy.get(ym(formations[-1] + 1, 6))
    return round(100 * b / a, 2) if a and b else None

def distribution(curve, formations):
    """Annual-period distribution from the monthly curve."""
    vals = {m: v for m, v in curve}
    rets = []
    prev = 100.0
    for F in formations:
        end = vals.get(ym(F + 1, 6))
        if end is None: continue
        rets.append(round((end / prev - 1) * 100, 1)); prev = end
    if not rets: return {}
    pos = sum(1 for r in rets if r > 0)
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; streak = max(streak, cur)
    peak = 100.0; high_m = None; longest = 0; run = 0
    for m, v in curve:
        if v >= peak: peak = v; high_m = m; run = 0
        else: run += 1; longest = max(longest, run)
    return {'periods': len(rets), 'period_rets_pct': rets, 'median_pct': round(statistics.median(rets), 1),
            'share_positive': f'{pos}/{len(rets)}', 'best_pct': max(rets), 'worst_pct': min(rets),
            'longest_losing_streak': streak, 'longest_months_between_new_highs': longest,
            'mean_pct_secondary': round(statistics.mean(rets), 1)}

def main():
    out = {'family': 'catalog-hxz-dupont', 'program': 'v13-best-rules', 'spec': 'BEST-RULES-SPEC.md',
           'candidate': 'Rna|native|annual|QUINTILE|no-floor', 'comparator': 'ROE|native|annual|QUINTILE|no-floor (grading only)',
           'pool_sizes_native': {str(F): len(POOLS[F]) for F in range(2016, 2026)}, 'roads': {}}
    for label, signal in (('candidate_Rna', 'Rna'), ('comparator_ROE', 'ROE')):
        out['roads'][label] = {}
        for rname, forms in ROADS.items():
            fin, curve, costs, maxdd = run_road(forms, signal)
            twins = []
            for s in range(1, 21):
                tf, _, _, _ = run_road(forms, signal, seed=s)
                twins.append(tf)
            out['roads'][label][rname] = {'final': fin, 'costs': costs, 'max_dd': maxdd,
                'spy_same_window': spy_final(forms), 'placebo_finals': twins,
                'placebos_beaten': sum(1 for t in twins if fin > t),
                'distribution': distribution(curve, forms), 'curve': curve}
            print(label, rname, fin, 'spy', spy_final(forms), 'pb', sum(1 for t in twins if fin > t), 'dd', maxdd, flush=True)
    with open(os.path.join(FAM, 'results.json'), 'w') as fh: json.dump(out, fh, indent=1)
    print('saved results.json')

if __name__ == '__main__': main()
