#!/usr/bin/env python3
"""V12 slow-illiquidity CONSTRUCTED run v2 (lean rewrite after v1 died under
memory pressure; identical rules to CONSTRUCTION-SPEC.md).
Amihud ILLIQ (trailing 3mo), top-1% trim, vol-tercile x ILLIQ-quintile sort,
long most-illiquid quintile per tercile, equal-weight, skip-2/hold-1 monthly
cadence, vanished prices to ZERO, Corwin-Schultz name-specific spread costs
(floor 0.50%/side, cap 7.5%/side, +0.10%/side, $0.01 sell fee), 20-seed
placebos, zero-cost twin diagnostic. Simulation only."""
import json, os, math, random, statistics, sys
HERE = os.path.dirname(os.path.abspath(__file__))
BROAD = '/home/hatch/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data'
DATA = os.path.join(HERE, 'data')
START_CASH = 100.0
def log(*a): print(*a, flush=True)

cand = {int(k): v for k, v in json.load(open(os.path.join(BROAD, 'candidates.json'))).items()}
def load_frame(name):
    p = os.path.join(BROAD, 'frames', name)
    if not os.path.exists(p): return set()
    return {int(k) for k in json.load(open(p)).keys()}
shares_years = {y: load_frame(f'Shares_{y}I.json') for y in range(2014, 2026)}
LISTED = {'NYSE', 'NASDAQ', 'TXSE', 'CBOE'}
ticker2cik = {}
for cik, info in cand.items():
    if info.get('exchange') in LISTED and info.get('ticker'):
        ticker2cik[info['ticker'].replace('/', '-')] = cik

# bars: ticker -> (dates[], opens[], highs[], lows[], adjcloses[], rawcloses[], vols[])
bars = {}
for t in ticker2cik:
    p = os.path.join(DATA, f'px_{t}.json')
    if not os.path.exists(p): continue
    rows = json.load(open(p))
    D, O, H, L, C, RC, V = [], [], [], [], [], [], []
    for d, o, h, l, c, adj, v in rows:
        if adj is None or adj <= 0 or c is None or c <= 0: continue
        f = adj / c
        D.append(d); O.append((o or c) * f); H.append((h or c) * f); L.append((l or c) * f)
        C.append(adj); RC.append(c); V.append(v or 0)
    if len(D) >= 60:
        bars[t] = (D, O, H, L, C, RC, V)
log('tickers with bars:', len(bars))

spy_rows = json.load(open(os.path.join(DATA, 'px_SPY.json')))
spy = [(r[0], r[5]) for r in spy_rows if r[5]]
spy_by_date = dict(spy)
ALL_DATES = sorted(spy_by_date)
MONTHS, _seen = [], set()
MONTH_LAST, MONTH_FIRST = {}, {}
for d in ALL_DATES:
    m = d[:7]
    if m not in _seen: _seen.add(m); MONTHS.append(m); MONTH_FIRST[m] = d
    MONTH_LAST[m] = d
MIDX = {m: i for i, m in enumerate(MONTHS)}

def cs_spread(H, L, i0, i1):
    ests = []
    for i in range(i0, i1 - 1):
        a_h, a_l, b_h, b_l = H[i], L[i], H[i + 1], L[i + 1]
        if a_h <= 0 or a_l <= 0 or b_h <= 0 or b_l <= 0: continue
        beta = (math.log(a_h / a_l)) ** 2 + (math.log(b_h / b_l)) ** 2
        h2 = max(a_h, b_h); l2 = min(a_l, b_l)
        if l2 <= 0: continue
        gamma = (math.log(h2 / l2)) ** 2
        denom = 3 - 2 * math.sqrt(2)
        alpha = (math.sqrt(2 * beta) - math.sqrt(beta)) / denom - math.sqrt(gamma / denom)
        s = 2 * (math.exp(alpha) - 1) / (1 + math.exp(alpha))
        ests.append(max(0.0, s))
    return statistics.mean(ests) if ests else 0.01

# Precompute per (ticker, month) trailing-3mo stats once.
# STATS[t][month] = (illiq, vol, cost_side, last_close_adj, n_valid)
STATS = {}
for t, (D, O, H, L, C, RC, V) in bars.items():
    st = {}
    # month-end indices
    mend = {}
    for i, d in enumerate(D):
        mend[d[:7]] = i
    for m, ei in mend.items():
        i0 = max(0, ei - 62)
        n = ei - i0
        if n < 40: continue
        dv, rets = [], []
        for i in range(i0 + 1, ei + 1):
            if C[i - 1] <= 0: dv = []; break
            r = C[i] / C[i - 1] - 1.0
            rets.append(r)
            if V[i] > 0 and RC[i] > 0:
                dv.append(abs(r) / (RC[i] * V[i]))
        if len(dv) < 40 or len(rets) < 40: continue
        st[m] = (statistics.mean(dv) * 1e6, statistics.pstdev(rets),
                 min(0.075, max(0.005, cs_spread(H, L, i0, ei) / 2.0)) + 0.001,
                 C[ei])
    STATS[t] = st
log('stats precomputed')

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
    r = (pool, picks)
    _FCACHE[form_month] = r
    return r

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
        pos = []
        spent = 0.0
        for t in picks:
            D, O, H, L, C, RC, V = bars[t]
            # first bar in hold month
            import bisect
            j = bisect.bisect_left(D, first_d)
            if j >= len(D) or D[j][:7] != hold_month or O[j] <= 0: continue
            cs = 0.0 if zero_cost else pool[t][2]
            sh = per * (1 - cs) / O[j]
            spent += per; total_cost += per * cs
            pos.append((t, sh, pool[t][2]))
        cash -= spent
        for t, sh, cs0 in pos:
            D, O, H, L, C, RC, V = bars[t]
            import bisect
            # ZERO rule (spec): series ended before the market's final trading
            # day of the hold month and never resumes -> position is worth 0.
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
out = {'universe': {'candidates': len(cand), 'listed_with_prices': len(bars)}, 'roads': {}}
for name, (s, e) in ROADS.items():
    main = run_road(s, e)
    twin = run_road(s, e, zero_cost=True)
    pls = sorted(run_road(s, e, placebo_seed=1000 + seed)['final'] for seed in range(20))
    beat = sum(1 for x in pls if main['final'] > x)
    out['roads'][name] = {'window': [s, e], 'final': main['final'],
        'max_dd_pct': max_dd(main['curve']), 'trades': main['trades'],
        'zeroed': main['zeroed'], 'total_cost': main['total_cost'], 'curve': main['curve'],
        'zero_cost_twin_final': twin['final'], 'zero_cost_twin_max_dd_pct': max_dd(twin['curve']),
        'spy_final': spy_road(s, e), 'champion_vm': CHAMP[name],
        'placebos': {'finals': pls, 'median': pls[10], 'beat_count_of_20': beat}}
    log(name, main['final'], 'twin', twin['final'], 'spy', out['roads'][name]['spy_final'],
        'placebo med', pls[10], 'beat', beat, '/20')
json.dump(out, open(os.path.join(HERE, 'results.json'), 'w'), indent=1)
log('DONE')
