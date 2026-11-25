#!/usr/bin/env python3
"""V12 slow-illiquidity CONSTRUCTED run — numpy-vectorized implementation of
CONSTRUCTION-SPEC.md (identical rules; v2 pure-python was too slow under CPU
contention). Prints results JSON to stdout."""
import json, os, sys, math, random, bisect
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
BROAD = '/home/hatch/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data'
DATA = os.path.join(HERE, 'data')
START_CASH = 100.0

cand = {int(k): v for k, v in json.load(open(os.path.join(BROAD, 'candidates.json'))).items()}
def load_frame(name):
    p = os.path.join(BROAD, 'frames', name)
    return {int(k) for k in json.load(open(p)).keys()} if os.path.exists(p) else set()
shares_years = {y: load_frame(f'Shares_{y}I.json') for y in range(2014, 2026)}
LISTED = {'NYSE', 'NASDAQ', 'TXSE', 'CBOE'}
ticker2cik = {}
for cik, info in cand.items():
    if info.get('exchange') in LISTED and info.get('ticker'):
        ticker2cik[info['ticker'].replace('/', '-')] = cik

spy_rows = json.load(open(os.path.join(DATA, 'px_SPY.json')))
spy = [(r[0], r[5]) for r in spy_rows if r[5]]
ALL_DATES = sorted(d for d, _ in spy)
MONTHS, _seen = [], set()
MONTH_LAST, MONTH_FIRST = {}, {}
for d in ALL_DATES:
    m = d[:7]
    if m not in _seen: _seen.add(m); MONTHS.append(m); MONTH_FIRST[m] = d
    MONTH_LAST[m] = d
MIDX = {m: i for i, m in enumerate(MONTHS)}

# per ticker: bars (lists) + stats dict month -> (illiq, vol, cost, last_close)
BARS, STATS = {}, {}
for t in sorted(ticker2cik):
    p = os.path.join(DATA, f'px_{t}.json')
    if not os.path.exists(p): continue
    rows = json.load(open(p))
    D, O, H, L, C, RC, V = [], [], [], [], [], [], []
    for d, o, h, l, c, adj, v in rows:
        if adj is None or adj <= 0 or c is None or c <= 0: continue
        f = adj / c
        D.append(d); O.append((o or c) * f); H.append((h or c) * f); L.append((l or c) * f)
        C.append(adj); RC.append(c); V.append(v or 0)
    n = len(D)
    if n < 60: continue
    BARS[t] = (D, O, C)
    Ca = np.array(C); Ra = np.array(RC); Va = np.array(V, dtype=float)
    Ha = np.array(H); La = np.array(L)
    rets = np.zeros(n); rets[1:] = Ca[1:] / Ca[:-1] - 1.0
    dv = np.where((Va > 0) & (Ra > 0), np.abs(rets) / np.where(Ra * Va > 0, Ra * Va, 1.0), np.nan)
    # Corwin-Schultz per-pair spread estimates (pair i uses days i, i+1)
    with np.errstate(divide='ignore', invalid='ignore'):
        lh_a = np.log(Ha[:-1] / La[:-1]); lh_b = np.log(Ha[1:] / La[1:])
        beta = lh_a ** 2 + lh_b ** 2
        h2 = np.maximum(Ha[:-1], Ha[1:]); l2 = np.minimum(La[:-1], La[1:])
        gamma = np.log(h2 / l2) ** 2
    denom = 3 - 2 * math.sqrt(2)
    alpha = (np.sqrt(2 * beta) - np.sqrt(beta)) / denom - np.sqrt(gamma / denom)
    ea = np.exp(alpha)
    pair_s = np.where(np.isfinite(alpha), np.maximum(0.0, 2 * (ea - 1) / (1 + ea)), np.nan)
    def csum(x):
        y = np.where(np.isfinite(x), x, 0.0)
        return np.concatenate([[0.0], np.cumsum(y)])
    def ccnt(x):
        return np.concatenate([[0.0], np.cumsum(np.isfinite(x).astype(float))])
    cs_dv, cn_dv = csum(dv), ccnt(dv)
    cs_r, cs_r2 = csum(rets), csum(rets * rets)
    cs_s, cn_s = csum(pair_s), ccnt(pair_s)
    mend = {}
    for i, d in enumerate(D): mend[d[:7]] = i
    st = {}
    for m, ei in mend.items():
        i0 = max(0, ei - 62); cnt = ei - i0
        if cnt < 40: continue
        # rets/dv window: indices i0+1..ei
        ndv = cn_dv[ei + 1] - cn_dv[i0 + 1]
        if ndv < 40: continue
        illiq = (cs_dv[ei + 1] - cs_dv[i0 + 1]) / ndv * 1e6
        mr = (cs_r[ei + 1] - cs_r[i0 + 1]) / cnt
        var = (cs_r2[ei + 1] - cs_r2[i0 + 1]) / cnt - mr * mr
        vol = math.sqrt(var) if var > 0 else 0.0
        ns = cn_s[ei] - cn_s[i0]
        cs = (cs_s[ei] - cs_s[i0]) / ns if ns > 0 else 0.01
        cost = min(0.075, max(0.005, cs / 2.0)) + 0.001
        st[m] = (float(illiq), float(vol), float(cost), float(Ca[ei]))
    STATS[t] = st
print('loaded tickers:', len(BARS), file=sys.stderr)

_FCACHE = {}
def formation(form_month):
    if form_month in _FCACHE: return _FCACHE[form_month]
    year = int(form_month[:4])
    members = shares_years.get(year, set()) | shares_years.get(year - 1, set())
    pool = {}
    for t, cik in ticker2cik.items():
        if cik not in members: continue
        s = STATS.get(t, {}).get(form_month)
        if s is None or s[3] < 1.00: continue
        pool[t] = s
    picks = []
    if len(pool) >= 30:
        srt = sorted(pool.items(), key=lambda kv: kv[1][0])
        pool = dict(srt[:max(1, int(len(srt) * 0.99))])
        items = sorted(pool.items(), key=lambda kv: kv[1][1])
        n = len(items)
        for k in range(3):
            terc = items[k * n // 3:(k + 1) * n // 3]
            terc.sort(key=lambda kv: kv[1][0], reverse=True)
            picks += [t for t, _ in terc[:max(1, len(terc) // 5)]]
    _FCACHE[form_month] = (pool, picks)
    return pool, picks

def run_road(start, end, placebo_seed=None, zero_cost=False):
    cash = START_CASH
    curve, trades, zeroed, total_cost = [], 0, 0, 0.0
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    for mi in range(MIDX[start[:7]], MIDX[end[:7]] + 1):
        hold_month = MONTHS[mi]
        if mi - 3 < 0:
            curve.append([MONTH_LAST[hold_month], round(cash, 4)]); continue
        pool, picks = formation(MONTHS[mi - 3])
        if not picks:
            curve.append([MONTH_LAST[hold_month], round(cash, 4)]); continue
        if rng is not None:
            picks = rng.sample(sorted(pool.keys()), min(len(picks), len(pool)))
        first_d = MONTH_FIRST[hold_month]
        per = cash / len(picks)
        pos, spent = [], 0.0
        for t in picks:
            D, O, C = BARS[t]
            j = bisect.bisect_left(D, first_d)
            if j >= len(D) or D[j][:7] != hold_month or O[j] <= 0: continue
            cs = 0.0 if zero_cost else pool[t][2]
            pos.append((t, per * (1 - cs) / O[j], pool[t][2]))
            spent += per; total_cost += per * cs
        cash -= spent
        for t, sh, cs0 in pos:
            D, O, C = BARS[t]
            if D[-1] < MONTH_LAST[hold_month]:
                zeroed += 1; trades += 1; continue
            j = bisect.bisect_right(D, MONTH_LAST[hold_month]) - 1
            if j < 0 or D[j][:7] != hold_month:
                zeroed += 1; trades += 1; continue
            cs = 0.0 if zero_cost else cs0
            val = sh * C[j]
            fee = 0.0 if zero_cost else 0.01
            cash += val * (1 - cs) - fee
            total_cost += val * cs + fee
            trades += 1
        curve.append([MONTH_LAST[hold_month], round(cash, 4)])
    return {'final': round(cash, 2), 'curve': curve, 'trades': trades,
            'zeroed': zeroed, 'total_cost': round(total_cost, 2)}

def max_dd(curve):
    peak, dd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0: dd = min(dd, v / peak - 1)
    return round(dd * 100, 1)

def spy_road(start, end):
    s = next(c for d, c in spy if d >= start)
    e = [c for d, c in spy if d <= end][-1]
    return round(START_CASH * e / s, 2)

ROADS = {'LONGEST': ('2016-01-04', '2026-11-20'), 'DECADE': ('2016-11-21', '2026-11-20'),
         'CONT': ('2019-01-02', '2026-11-20'), 'VAL': ('2023-01-03', '2026-11-20')}
CHAMP = {'LONGEST': None, 'DECADE': 667.35, 'CONT': 544.47, 'VAL': 288.05}
which = sys.argv[1:] or list(ROADS)
out = {'universe': {'candidates': len(cand), 'listed_with_prices': len(BARS)}, 'roads': {}}
for name in which:
    s, e = ROADS[name]
    main = run_road(s, e)
    twin = run_road(s, e, zero_cost=True)
    pls = sorted(run_road(s, e, placebo_seed=1000 + seed)['final'] for seed in range(20))
    beat = sum(1 for x in pls if main['final'] > x)
    out['roads'][name] = {'window': [s, e], 'final': main['final'],
        'max_dd_pct': max_dd(main['curve']), 'trades': main['trades'],
        'zeroed': main['zeroed'], 'total_cost': main['total_cost'], 'curve': main['curve'],
        'zero_cost_twin_final': twin['final'], 'zero_cost_twin_curve': twin['curve'],
        'zero_cost_twin_max_dd_pct': max_dd(twin['curve']),
        'spy_final': spy_road(s, e), 'champion_vm': CHAMP[name],
        'placebos': {'finals': pls, 'median': pls[10], 'beat_count_of_20': beat}}
    print(name, main['final'], 'twin', twin['final'], 'spy', out['roads'][name]['spy_final'],
          'pmed', pls[10], 'beat', beat, file=sys.stderr)
print(json.dumps(out))
