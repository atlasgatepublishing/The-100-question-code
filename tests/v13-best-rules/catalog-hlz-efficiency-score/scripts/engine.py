#!/usr/bin/env python3
"""V13 Best-Rules engine — catalog-hlz-efficiency-score. Frozen by BEST-RULES-SPEC.md.
Adapted from the v12 engine (read-only): same W04 PIT stack, same three
published input/output ratios, same tiered costs, vanished->ZERO.
Spec changes ONLY: (1) each ratio percentile-ranked WITHIN SIC-2 industry
(>=8 names; fallback SIC-1, then global) — restoring the paper's
industry-by-industry frontier structure; (2) all three ratios required;
(3) single design — native universe, top QUINTILE EW, annual June
formation, 12-month hold, NO floor; (4) entry gate June price > 0;
(5) 20-seed placebos draw the quintile count from the year's eligible
native pool through the identical chassis."""
import json, os, math, random
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..')
V12 = os.path.expanduser('~/workspace/stock-app/backtests/v12-completions/catalog-hlz-efficiency-score')
W04 = os.path.expanduser('~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data')
FR = os.path.join(V12, 'data', 'frames')

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

def frame(concept, kind):
    return {y: {int(k): v for k, v in loadj(os.path.join(FR, f'{concept}_{y}{kind}.json')).items()}
            for y in range(2009, 2026)}
AT = frame('Assets', 'I'); PPE = frame('PropertyPlantAndEquipmentNet', 'I'); GP = frame('GrossProfit', 'D')
REV = {}
for y in range(2009, 2026):
    d = {}
    for c in ('SalesRevenueNet', 'RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues'):
        for k, v in loadj(os.path.join(FR, f'{c}_{y}D.json')).items():
            d.setdefault(int(k), v)
    REV[y] = d
def g(fr, y, cik): return fr.get(y, {}).get(cik)

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

# ---- signal construction (spec choices 1-4, 7) ----
def pct_within(vals_by_cik, sic_of):
    """Percentile rank within SIC-2 group (>=8), fallback SIC-1 (>=8), else global."""
    groups2, groups1 = {}, {}
    for cik in vals_by_cik:
        sic = sic_of(cik)
        groups2.setdefault(sic[:2], []).append(cik)
        groups1.setdefault(sic[:1], []).append(cik)
    all_sorted = sorted(vals_by_cik.items(), key=lambda kv: kv[1])
    global_pct = {c: (i + 0.5) / len(all_sorted) for i, (c, _) in enumerate(all_sorted)}
    def rank_in(members):
        s = sorted(members, key=lambda c: vals_by_cik[c])
        return {c: (i + 0.5) / len(s) for i, c in enumerate(s)}
    cache2 = {k: rank_in(v) for k, v in groups2.items() if len(v) >= 8}
    cache1 = {k: rank_in(v) for k, v in groups1.items() if len(v) >= 8}
    out = {}
    for cik in vals_by_cik:
        sic = sic_of(cik)
        if sic[:2] in cache2: out[cik] = cache2[sic[:2]][cik]
        elif sic[:1] in cache1: out[cik] = cache1[sic[:1]][cik]
        else: out[cik] = global_pct[cik]
    return out

POOLS = {}   # F -> {cik: {'score','cap','rate'}}
PICKS = {}   # F -> [cik] quintile picks
for F in range(2016, 2026):
    y = F - 1
    sic_of = lambda cik: str(cand[cik].get('sic') or '')
    raw = {}
    for cik in cand:
        if sic_of(cik)[:1] in ('4', '6'): continue          # native universe
        if cik not in px: continue
        e = px[cik].get(ym(F, 6))
        if not e or not e[0] or e[0] <= 0: continue          # entry gate: price > 0
        at = g(AT, y, cik); rev = g(REV, y, cik); gp = g(GP, y, cik); pp = g(PPE, y, cik)
        if not at or not rev or gp is None or not pp: continue  # all three ratios required
        raw[cik] = (rev / at, gp / at, rev / pp)
    pa = pct_within({c: v[0] for c, v in raw.items()}, sic_of)
    pb = pct_within({c: v[1] for c, v in raw.items()}, sic_of)
    pc = pct_within({c: v[2] for c, v in raw.items()}, sic_of)
    pool = {}
    for cik in raw:
        cap = cap_of(cik, F)
        pool[cik] = {'score': (pa[cik] + pb[cik] + pc[cik]) / 3.0, 'cap': cap, 'rate': cost_rate(cap)}
    POOLS[F] = pool
    items = sorted(pool.items(), key=lambda kv: kv[1]['score'], reverse=True)
    n = max(1, math.ceil(len(items) * 0.20))
    PICKS[F] = [c for c, _ in items[:n]]
    print(F, 'pool', len(pool), 'quintile', n, flush=True)

# ---- price matrices (v12 chassis) ----
MATS = {}
FORMS = list(range(2016, 2026))
for F in FORMS:
    cols = [ym(F, m) for m in range(6, 13)] + [ym(F + 1, m) for m in range(1, 7)]
    allciks = sorted(POOLS[F])
    M = np.full((len(allciks), 13), np.nan); idx = {c: i for i, c in enumerate(allciks)}
    for i, cik in enumerate(allciks):
        s = px[cik]; last = None; lastbar = max(s) if s else None
        for j, mm in enumerate(cols):
            if mm in s: last = s[mm][0]
            if lastbar is not None and mm > lastbar: M[i, j] = 0.0
            elif last is not None: M[i, j] = last
    MATS[F] = (idx, M)

def run_road(formations, seed=None):
    cash = 100.0; curve = []; total_costs = 0.0
    for F in formations:
        idx, M = MATS[F]; pool = POOLS[F]
        if seed is None: picks = PICKS[F]
        else:
            rng = random.Random(seed * 100003 + F); keys = list(pool.keys()); rng.shuffle(keys)
            picks = keys[:len(PICKS[F])]
        cols = [ym(F, m) for m in range(6, 13)] + [ym(F + 1, m) for m in range(1, 7)]
        if not picks:
            for mm in cols[1:]: curve.append([mm, round(cash, 2)])
            continue
        rows = np.array([idx[c] for c in picks]); P = M[rows, :]
        rates = np.array([pool[c]['rate'] for c in picks])
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

def spy_final(formations):
    a = spy.get(ym(formations[0], 6)); b = spy.get(ym(formations[-1] + 1, 6))
    return round(100 * b / a, 2) if a and b else None

ROADS = {'LONG': FORMS, 'DECADE': [f for f in FORMS if f >= 2017],
         'CONT': [f for f in FORMS if f >= 2019], 'VAL': [f for f in FORMS if f >= 2023]}
def main():
    res = {'family': 'catalog-hlz-efficiency-score', 'design': 'industry-neutral constructed composite, native, annual, QUINTILE, no floor',
           'roads_formations': ROADS, 'pool_sizes': {str(F): len(POOLS[F]) for F in FORMS},
           'picks': {str(F): [cand[c]['ticker'] for c in PICKS[F]] for F in FORMS}, 'roads': {}}
    for rname, forms in ROADS.items():
        fin, curve, costs, maxdd = run_road(forms)
        twins = []
        for sd in range(1, 21):
            tf, _, _, _ = run_road(forms, seed=sd); twins.append(tf)
        res['roads'][rname] = {'final': fin, 'costs': costs, 'max_dd': maxdd,
                               'spy_same_window': spy_final(forms), 'placebo_finals': twins,
                               'placebos_beaten': sum(1 for t in twins if fin > t), 'curve': curve}
        print(rname, fin, 'dd', maxdd, 'pb', res['roads'][rname]['placebos_beaten'], 'spy', spy_final(forms), flush=True)
    with open(os.path.join(OUT, 'results.json'), 'w') as fh: json.dump(res, fh, indent=1)
    print('saved results.json')
if __name__ == '__main__': main()
