#!/usr/bin/env python3
"""V13 best-rules run for catalog-hlz-meta-signals.
Single frozen cell from BEST-RULES-SPEC.md:
  MetaComp | native universe | native (no floor) | annual | QUINTILE
Chassis copied verbatim from the v12 engine (same PIT stack, tiered
costs, vanished->ZERO, 20-seed placebos) with roads relabeled to the
family's honest calendar: LONG=2016-2025, DECADE=2017-2025,
CONT=2019-2025, VAL=2023-2025 formations.
Also emits FOLD_A (2016-2020) / FOLD_B (2021-2025) diagnostics.
"""
import json, os, math, random, statistics
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); FAM = os.path.join(HERE, '..')
V12 = os.path.join(FAM, '..', '..', 'v12-completions', 'catalog-hlz-meta-signals')
W04 = os.path.join(FAM, '..', '..', 'v11-native-rules', '_w04_broad_data')

def loadj(p): return json.load(open(p)) if os.path.exists(p) else {}
cand = {int(k): v for k, v in loadj(os.path.join(W04, 'candidates.json')).items()}
px = {}
for cik, info in cand.items():
    t = info['ticker'].replace('/', '-'); p = os.path.join(W04, f'px_{t}.json')
    if os.path.exists(p):
        try: px[cik] = {r[0]: (r[1], r[2]) for r in loadj(p)}
        except Exception: pass
spy = {r[0]: r[1] for r in loadj(os.path.join(W04, 'px_SPY.json'))}
SIG = loadj(os.path.join(FAM, 'signals.json'))['signals']
shares_f = {}
for y in range(2009, 2026):
    shares_f[y] = {int(k): v for k, v in loadj(os.path.join(W04, 'frames', f'Shares_{y}I.json')).items()}
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

def cap_of(cik, F):
    sh = shares_f.get(F - 1, {}).get(cik) or shares_f.get(F - 2, {}).get(cik)
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

def ym(y, m): return f'{y:04d}-{m:02d}'
POOLS = {}; MATS = {}
FORMS = sorted({int(f) for s in SIG.values() for f in s['values']})
for F in FORMS:
    for uni in ('native',):
        for sname, sig in SIG.items():
            vals = {int(k): v for k, v in sig['values'].get(str(F), {}).items()}
            pool = {}
            for cik, score in vals.items():
                if cik not in px: continue
                e = px[cik].get(ym(F, 6))
                if not e or not e[0]: continue
                if uni == 'native':
                    sic = str(cand[cik].get('sic') or '')
                    if sic[:1] in ('4', '6'): continue
                cap = cap_of(cik, F)
                pool[cik] = {'score': score, 'cap': cap, 'rate': cost_rate(cap)}
            POOLS[(sname, F, uni)] = pool
    cols = [ym(F, m) for m in range(6, 13)] + [ym(F + 1, m) for m in range(1, 7)]
    allciks = sorted({c for (sn, f, u), p in POOLS.items() if f == F for c in p})
    M = np.full((len(allciks), 13), np.nan); idx = {c: i for i, c in enumerate(allciks)}
    for i, cik in enumerate(allciks):
        s = px[cik]; last = None; lastbar = max(s) if s else None
        for j, mm in enumerate(cols):
            if mm in s: last = s[mm][0]
            if lastbar is not None and mm > lastbar: M[i, j] = 0.0
            elif last is not None: M[i, j] = last
    MATS[F] = (idx, M)

def picks_for(sname, F, uni, count):
    pool = POOLS[(sname, F, uni)]; sig = SIG[sname]
    items = sorted(pool.items(), key=lambda kv: kv[1]['score'], reverse=(sig['dir'] == 'high'))
    if count == 'QUINTILE':
        n = max(1, math.ceil(len(items) * 0.20)); return [c for c, _ in items[:n]]
    return [c for c, _ in items[:min(count, len(items))]]

REBAL = {'annual': {0}}
def run_road(formations, sname, uni, count, cadence='annual', house=False, seed=None):
    cash = 100.0; peak = 100.0; curve = []; total_costs = 0.0; picks_by_year = {}
    for F in formations:
        idx, M = MATS[F]; pool = POOLS[(sname, F, uni)]
        if seed is None:
            picks = picks_for(sname, F, uni, count); picks_by_year[F] = picks
        else:
            rng = random.Random(seed * 100003 + F); keys = list(pool.keys()); rng.shuffle(keys)
            n = max(1, math.ceil(len(keys) * 0.20)) if count == 'QUINTILE' else min(count, len(keys))
            picks = keys[:n]
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
                tgt = val / len(picks); trade = np.abs(tgt - vals); cst = float(np.sum(trade * rates))
                total_costs += cst
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
                total_costs += sell; cash = cash - sell; in_cash = True; curve[-1] = [cols[j], round(cash, 2)]
        peak = max(peak, cash)
    peak2 = 100.0; maxdd = 0.0
    for _, v in curve:
        peak2 = max(peak2, v); maxdd = max(maxdd, 1 - v / peak2) if peak2 else 0.0
    return round(cash, 2), curve, round(total_costs, 2), round(maxdd, 4), picks_by_year

def spy_final(formations):
    if not formations: return None
    a = spy.get(ym(formations[0], 6)); b = spy.get(ym(formations[-1] + 1, 6))
    return round(100 * b / a, 2) if a and b else None

def period_stats(curve):
    vals = [100.0] + [v for _, v in curve]
    rets = [vals[i] / vals[i - 12] - 1 for i in range(12, len(vals), 12)]
    mrets = [vals[i] / vals[i - 1] - 1 for i in range(1, len(vals))]
    def dist(rs):
        if not rs: return None
        pos = sum(1 for r in rs if r > 0); run = 0; worst_run = 0
        for r in rs:
            run = run + 1 if r <= 0 else 0; worst_run = max(worst_run, run)
        return {'periods': len(rs), 'positive': pos, 'share_positive_pct': round(100 * pos / len(rs), 1),
                'median_pct': round(statistics.median(rs) * 100, 1),
                'mean_pct_secondary': round(statistics.mean(rs) * 100, 1),
                'best_pct': round(max(rs) * 100, 1), 'worst_pct': round(min(rs) * 100, 1),
                'longest_losing_streak': worst_run}
    peak = vals[0]; longest = 0; cur = 0
    for v in vals:
        if v >= peak: peak = v; cur = 0
        else: cur += 1; longest = max(longest, cur)
    a = dist(rets); a['longest_months_between_highs'] = longest
    a['yearly_pct'] = [round(r * 100, 1) for r in rets]
    m = dist(mrets); m['longest_months_between_highs'] = longest
    return {'annual': a, 'monthly': m}

ROADS = {'LONG': ALLF if (ALLF := FORMS) else [], 'DECADE': [f for f in FORMS if f >= 2017],
         'CONT': [f for f in FORMS if f >= 2019], 'VAL': [f for f in FORMS if f >= 2023],
         'FOLD_A': [f for f in FORMS if f <= 2020], 'FOLD_B': [f for f in FORMS if f >= 2021]}

def main():
    out = {'family': 'catalog-hlz-meta-signals', 'spec_cell': 'MetaComp|native|native(no floor)|annual|QUINTILE',
           'components': ['12-1 momentum', 'earnings yield (NI/mktcap)', 'low accruals (-(NI-OCF)/avgAT)', 'gross profitability (GP/AT)'],
           'roads_formations': {k: v for k, v in ROADS.items()},
           'pool_sizes_native': {str(F): len(POOLS[('MetaComp', F, 'native')]) for F in FORMS},
           'roads': {}}
    for rname, forms in ROADS.items():
        fin, curve, costs, maxdd, picks = run_road(forms, 'MetaComp', 'native', 'QUINTILE')
        twins = []
        if rname in ('LONG', 'DECADE', 'CONT', 'VAL'):
            for sd in range(1, 21):
                tf, _, _, _, _ = run_road(forms, 'MetaComp', 'native', 'QUINTILE', seed=sd); twins.append(tf)
        out['roads'][rname] = {'final': fin, 'costs': costs, 'max_dd': maxdd,
                               'spy_same_window': spy_final(forms),
                               'placebo_finals': twins,
                               'placebos_beaten': sum(1 for t in twins if fin > t),
                               'placebo_median': round(statistics.median(twins), 2) if twins else None,
                               'period_stats': period_stats(curve) if rname in ('LONG', 'DECADE', 'CONT', 'VAL') else None,
                               'picks': {str(F): [cand[c]['ticker'] for c in picks.get(F, [])] for F in forms} if rname == 'LONG' else None,
                               'curve': curve}
        print(rname, fin, 'dd', maxdd, 'pb', out['roads'][rname]['placebos_beaten'], 'spy', out['roads'][rname]['spy_same_window'], flush=True)
    with open(os.path.join(FAM, 'results.json'), 'w') as fh: json.dump(out, fh, indent=1)
    print('saved results.json')

if __name__ == '__main__': main()
