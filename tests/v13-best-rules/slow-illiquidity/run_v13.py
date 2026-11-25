#!/usr/bin/env python3
"""V13 slow-illiquidity BEST-RULES run — implements BEST-RULES-SPEC.md exactly.

Annual formation (December month-end), 15 names (5 most-illiquid per volatility
tercile), buy at January first-open, hold the calendar year, sell at December
last close. Corwin-Schultz per-name costs identical to the v12 model. ZERO rule
for vanished names. 20-seed placebos. Zero-cost twin diagnostic.
Data: v12 slow-illiquidity data cache + v11 broad candidates (READ-ONLY).
"""
import json, os, sys, math, random, bisect
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
V12 = '/home/hatch/workspace/stock-app/backtests/v12-completions/slow-illiquidity'
BROAD = '/home/hatch/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data'
DATA = os.path.join(V12, 'data')
START_CASH = 100.0
N_PER_TERCILE = 5
FINAL_MONTH = '2026-11'

cand = {int(k): v for k, v in json.load(open(os.path.join(BROAD, 'candidates.json'))).items()}
def load_frame(name):
    p = os.path.join(BROAD, 'frames', name)
    return {int(k) for k in json.load(open(p))} if os.path.exists(p) else set()
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

# ---- per-ticker bars + monthly stats (identical computation to v12 run_np.py)
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
    """Returns (pool, picks): pool = ticker -> (illiq, vol, cost, close);
    picks = 5 most-illiquid per volatility tercile (15 names)."""
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
        pool = dict(srt[:max(1, int(len(srt) * 0.99))])  # drop top 1% ILLIQ
        items = sorted(pool.items(), key=lambda kv: kv[1][1])  # by vol
        n = len(items)
        for k in range(3):
            terc = items[k * n // 3:(k + 1) * n // 3]
            terc.sort(key=lambda kv: kv[1][0], reverse=True)  # ILLIQ desc
            picks += [t for t, _ in terc[:N_PER_TERCILE]]
    _FCACHE[form_month] = (pool, picks)
    return pool, picks

def last_bar_idx(t, upto_date):
    D, O, C = BARS[t]
    return bisect.bisect_right(D, upto_date) - 1

def is_vanished(t, month_last):
    D, O, C = BARS[t]
    # vanished: series ended before this month's end, tape continued without it
    return D[-1] < month_last and D[-1][:7] != FINAL_MONTH

def run_road(start, end, placebo_seed=None, zero_cost=False):
    cash = START_CASH
    positions = []  # (ticker, shares, sell_cost_rate)
    curve = []      # [date, value] month-end marks (+ final point)
    trades = 0; zeroed = 0; total_cost = 0.0
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    picks_log = []
    mi0, mi1 = MIDX[start[:7]], MIDX[end[:7]]
    for mi in range(mi0, mi1 + 1):
        m = MONTHS[mi]
        mlast = MONTH_LAST[m]
        # --- January: buy new formation (Dec of prior year)
        if m[5:7] == '01':
            form_month = f'{int(m[:4]) - 1}-12'
            pool, picks = formation(form_month)
            if picks:
                use = list(picks)
                if rng is not None:
                    use = rng.sample(sorted(pool.keys()), min(len(picks), len(pool)))
                picks_log.append({'formation': form_month, 'picks': use})
                first_d = MONTH_FIRST[m]
                per = cash / len(use)
                spent = 0.0
                for t in use:
                    D, O, C = BARS[t]
                    j = bisect.bisect_left(D, first_d)
                    if j >= len(D) or D[j][:7] != m or O[j] <= 0: continue
                    cs = 0.0 if zero_cost else pool[t][2]
                    positions.append((t, per * (1 - cs) / O[j], pool[t][2]))
                    spent += per; total_cost += per * cs
                cash -= spent
        # --- vanish check + month-end mark
        alive = []
        for (t, sh, csr) in positions:
            if is_vanished(t, mlast):
                zeroed += 1; trades += 1
                continue
            alive.append((t, sh, csr))
        positions = alive
        # --- December: sell everything at last close of the month
        if m[5:7] == '12':
            for (t, sh, csr) in positions:
                j = last_bar_idx(t, mlast)
                val = sh * BARS[t][2][j]
                cs = 0.0 if zero_cost else csr
                fee = 0.0 if zero_cost else 0.01
                cash += val * (1 - cs) - fee
                total_cost += val * cs + fee
                trades += 1
            positions = []
            curve.append([mlast, round(cash, 4)])
        else:
            val = cash
            for (t, sh, csr) in positions:
                j = last_bar_idx(t, mlast)
                if j >= 0: val += sh * BARS[t][2][j]
            curve.append([mlast, round(val, 4)])
    # --- final liquidation at road end
    for (t, sh, csr) in positions:
        if is_vanished(t, end):
            zeroed += 1; trades += 1; continue
        j = last_bar_idx(t, end)
        if j < 0: zeroed += 1; trades += 1; continue
        val = sh * BARS[t][2][j]
        cs = 0.0 if zero_cost else csr
        fee = 0.0 if zero_cost else 0.01
        cash += val * (1 - cs) - fee
        total_cost += val * cs + fee
        trades += 1
    positions = []
    if not curve or curve[-1][0] != end:
        curve.append([end, round(cash, 4)])
    else:
        curve[-1][1] = round(cash, 4)
    return {'final': round(cash, 2), 'curve': curve, 'trades': trades,
            'zeroed': zeroed, 'total_cost': round(total_cost, 2), 'picks_log': picks_log}

def max_dd(curve):
    peak, dd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0: dd = min(dd, v / peak - 1)
    return round(dd * 100, 1)

def dist_stats(curve):
    vals = [v for _, v in curve]
    rets = []
    prev = START_CASH
    for v in vals:
        rets.append(v / prev - 1.0 if prev > 0 else 0.0)
        prev = v
    if not rets: return {}
    srt = sorted(rets)
    n = len(rets)
    med = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2
    pos = sum(1 for r in rets if r > 0)
    # longest losing streak
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0
        streak = max(streak, cur)
    # longest stretch between new highs (in periods, from curve values incl. start)
    series = [START_CASH] + vals
    peak = series[0]; last_high = 0; longest = 0
    for i, v in enumerate(series):
        if v >= peak: peak = v; last_high = i
        longest = max(longest, i - last_high)
    return {'periods': n, 'pct_positive': round(100.0 * pos / n, 1),
            'median_pct': round(med * 100, 2), 'best_pct': round(max(rets) * 100, 2),
            'worst_pct': round(min(rets) * 100, 2),
            'longest_losing_streak': streak,
            'longest_stretch_between_highs_periods': longest,
            'mean_pct_secondary': round(sum(rets) / n * 100, 2)}

def annual_stats(curve, start, end):
    """Calendar-year period returns from month-end curve (Dec-to-Dec + stubs)."""
    pts = [(start, START_CASH)] + [(d, v) for d, v in curve]
    out = []
    bounds = []
    years = sorted({d[:4] for d, _ in pts})
    marks = {}
    for d, v in pts: marks[d[:7]] = v
    prev_val, prev_lab = START_CASH, start
    for y in years:
        dec = marks.get(f'{y}-12')
        if dec is not None and f'{y}-12' >= start[:7]:
            out.append({'period': y, 'ret_pct': round((dec / prev_val - 1) * 100, 2),
                        'from': prev_lab, 'to': f'{y}-12'})
            prev_val, prev_lab = dec, f'{y}-12-end'
    last_d, last_v = pts[-1]
    if last_d[:7] != prev_lab[:7] and last_d > (prev_lab if len(prev_lab) == 10 else last_d):
        out.append({'period': f'{last_d[:4]}-stub', 'ret_pct': round((last_v / prev_val - 1) * 100, 2),
                    'from': prev_lab, 'to': last_d})
    return out

def spy_road(start, end):
    s = next(c for d, c in spy if d >= start)
    e = [c for d, c in spy if d <= end][-1]
    return round(START_CASH * e / s, 2)

ROADS = {'LONGEST': ('2016-01-04', '2026-11-20'), 'DECADE': ('2016-11-21', '2026-11-20'),
         'CONT': ('2019-01-02', '2026-11-20'), 'VAL': ('2023-01-03', '2026-11-20')}
CHAMP = {'LONGEST': 1415.62, 'DECADE': 667.35, 'CONT': 544.47, 'VAL': 288.05}
which = sys.argv[1:] or list(ROADS)
out = {'family': 'slow-illiquidity', 'program': 'v13-best-rules',
       'universe': {'candidates': len(cand), 'listed_with_prices': len(BARS)},
       'roads': {}}
for name in which:
    s, e = ROADS[name]
    main = run_road(s, e)
    twin = run_road(s, e, zero_cost=True)
    pls = sorted(run_road(s, e, placebo_seed=1000 + seed)['final'] for seed in range(20))
    beat = sum(1 for x in pls if main['final'] > x)
    spyf = spy_road(s, e)
    out['roads'][name] = {
        'window': [s, e], 'final': main['final'], 'max_dd_pct': max_dd(main['curve']),
        'trades': main['trades'], 'zeroed': main['zeroed'], 'total_cost': main['total_cost'],
        'curve': main['curve'], 'picks_log': main['picks_log'],
        'monthly_distribution': dist_stats(main['curve']),
        'annual_periods': annual_stats(main['curve'], s, e),
        'zero_cost_twin_final': twin['final'], 'zero_cost_twin_curve': twin['curve'],
        'zero_cost_twin_max_dd_pct': max_dd(twin['curve']),
        'zero_cost_twin_monthly_distribution': dist_stats(twin['curve']),
        'spy_final': spyf, 'champion_vm': CHAMP[name],
        'beats_champion': main['final'] > CHAMP[name],
        'placebos': {'finals': pls, 'median': pls[10], 'beat_count_of_20': beat}}
    print(name, main['final'], 'dd', out['roads'][name]['max_dd_pct'], 'twin', twin['final'],
          'spy', spyf, 'pmed', pls[10], 'beat', beat, 'costs', main['total_cost'],
          'zeroed', main['zeroed'], file=sys.stderr)
print(json.dumps(out))
