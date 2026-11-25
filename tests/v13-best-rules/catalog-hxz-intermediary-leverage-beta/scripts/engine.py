#!/usr/bin/env python3
"""V13 best-rules engine — catalog-hxz-intermediary-leverage-beta.
Frozen by BEST-RULES-SPEC.md (written before this run):
- Factor: FRED Z.1 broker-dealer leverage (BOGZ1FL664090005Q assets /
  (assets - BOGZ1FL664190005Q liabilities)), quarterly log growth,
  usable only 3 months after quarter-end (release-lag PIT).
- Monthly regressor: latest available quarterly growth at each month-end.
- BetaLev: OLS slope of monthly total returns on regressor, trailing
  up-to-60 months ending month before June formation, min 36 obs.
- Portfolio: top quintile by BetaLev, equal weight, June formation,
  12-month hold (final formation 2026 truncated at 2026-11), no floor,
  tiered program costs, vanished->ZERO, 20-seed placebos.
Reads W04 broad stack read-only. Writes results.json in this folder only.
"""
import json, os, math, random, sys, csv
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FAM = os.path.dirname(HERE)
W04 = os.path.expanduser('~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data')
DATA = os.path.join(FAM, 'data')

def loadj(p):
    return json.load(open(p)) if os.path.exists(p) else {}

# ---------------- factor (FRED Z.1 levels, quarterly) ----------------
def fred_series(sid):
    out = {}
    with open(os.path.join(DATA, f'{sid}.csv')) as fh:
        rdr = csv.reader(fh); next(rdr)
        for row in rdr:
            if len(row) < 2 or row[1] in ('.', ''): continue
            y, m = int(row[0][:4]), int(row[0][5:7])
            q = (m - 1) // 3  # 0..3, quarter starting month
            out[(y, q)] = float(row[1])
    return out

ASSETS = fred_series('BOGZ1FL664090005Q')
LIABS = fred_series('BOGZ1FL664190005Q')
LEV = {}
for k in ASSETS:
    if k in LIABS:
        nw = ASSETS[k] - LIABS[k]
        if nw > 0: LEV[k] = ASSETS[k] / nw
def qkey(y, q): return y * 4 + q
def q_of(idx): return (idx // 4, idx % 4)
GROWTH = {}  # quarter idx -> log growth, available 3 months after quarter end
for idx in sorted(qkey(*k) for k in LEV):
    if idx - 1 in [qkey(*k) for k in LEV]:
        y0, q0 = q_of(idx - 1)
        if (y0, q0) in LEV and q_of(idx) in LEV:
            GROWTH[idx] = math.log(LEV[q_of(idx)]) - math.log(LEV[(y0, q0)])
LEV_BY_IDX = {qkey(*k): v for k, v in LEV.items()}
GROWTH = {}
for idx in sorted(LEV_BY_IDX):
    if idx - 1 in LEV_BY_IDX:
        GROWTH[idx] = math.log(LEV_BY_IDX[idx]) - math.log(LEV_BY_IDX[idx - 1])

def avail_month_idx(idx):
    """Quarter idx ends at month (year*12 + q*3+2) (0-based month count);
    growth usable 3 months after quarter end -> first usable month-end."""
    y, q = q_of(idx)
    end_month = y * 12 + (q * 3 + 2)  # Dec for Q4 etc, month index y*12+(month-1)
    return end_month + 3

def regressor_for_month(y, m):
    """Latest quarterly growth available at end of month (y, m 1..12)."""
    mi = y * 12 + (m - 1)
    best = None
    for idx, g in GROWTH.items():
        if avail_month_idx(idx) <= mi:
            if best is None or idx > best[0]: best = (idx, g)
    return best[1] if best else None

# ---------------- prices ----------------
cand = {int(k): v for k, v in loadj(os.path.join(W04, 'candidates.json')).items()}
px = {}
for cik, info in cand.items():
    t = info['ticker'].replace('/', '-')
    p = os.path.join(W04, f'px_{t}.json')
    if os.path.exists(p):
        try: px[cik] = {r[0]: (r[1], r[2]) for r in loadj(p)}  # (adjclose, close)
        except Exception: pass
spy = {r[0]: r[1] for r in loadj(os.path.join(W04, 'px_SPY.json'))}
MONTHS = sorted(spy)
MIDX = {m: i for i, m in enumerate(MONTHS)}
def ym(y, m): return f'{y:04d}-{m:02d}'

def monthly_rets(cik):
    s = px.get(cik, {})
    ms = sorted(s)
    out = {}
    for a, b in zip(ms, ms[1:]):
        if s[a][0] and s[b][0]: out[b] = s[b][0] / s[a][0] - 1
    return out
RETS = {cik: monthly_rets(cik) for cik in px}
REG = {mm: regressor_for_month(int(mm[:4]), int(mm[5:7])) for mm in MONTHS}

# ---------------- cap / costs (program chassis, as v12) ----------------
def frame(concept, unit):
    out = {}
    for y in range(2014, 2026):
        d = loadj(os.path.join(W04, 'frames', f'{concept}_{y}{unit}.json'))
        out[y] = {int(k): v for k, v in d.items()}
    return out
SHARES = frame('Shares', 'I')
sf = {}
for cik in cand:
    avail = [(y, SHARES[y][cik]) for y in range(2014, 2026) if cik in SHARES.get(y, {})]
    d = {}
    for F in range(2016, 2028):
        f = 1.0
        for (y0, a), (y1, b) in zip(avail, avail[1:]):
            if y1 >= F and a:
                r = b / a
                if r >= 1.6 or r <= 0.625: f *= r
        d[F] = f
    sf[cik] = d
def cap_of(cik, F):
    sh = (SHARES.get(F - 1, {}).get(cik) or SHARES.get(F - 2, {}).get(cik))
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

# ---------------- betas ----------------
def beta_lev(cik, F):
    """Trailing up-to-60 months ending May of formation year F, min 36."""
    r = RETS.get(cik, {})
    end_i = MIDX.get(ym(F, 5))
    if end_i is None: return None
    xs, ys = [], []
    for mm in MONTHS[max(0, end_i - 59): end_i + 1]:
        if mm in r and REG.get(mm) is not None:
            xs.append(REG[mm]); ys.append(r[mm])
    if len(ys) < 36: return None
    X = np.array(xs); yv = np.array(ys)
    if np.var(X) == 0: return None
    return float(np.cov(yv, X, ddof=0)[0, 1] / np.var(X))

POOLS = {}
for F in range(2019, 2027):
    pool = {}
    for cik in cand:
        if cik not in px: continue
        e = px[cik].get(ym(F, 6))
        if not e or not e[0]: continue
        b = beta_lev(cik, F)
        if b is None: continue
        cap = cap_of(cik, F)
        pool[cik] = {'sig': b, 'cap': cap, 'rate': cost_rate(cap)}
    POOLS[F] = pool
    print('pool', F, len(pool), flush=True)

def picks_for(F, seed=None):
    pool = POOLS[F]
    if seed is None:
        items = sorted(pool.items(), key=lambda kv: kv[1]['sig'], reverse=True)
        n = max(1, math.ceil(len(items) * 0.20))
        return [c for c, _ in items[:n]]
    rng = random.Random(seed * 100003 + F)
    keys = list(pool.keys()); rng.shuffle(keys)
    n = max(1, math.ceil(len(keys) * 0.20))
    return keys[:n]

def run_road(formations, seed=None):
    cash = 100.0; curve = []; total_costs = 0.0; periods = []
    for F in formations:
        pool = POOLS[F]
        picks = picks_for(F, seed=seed)
        start_val = cash
        if F < 2026:
            cols = [ym(F, m) for m in range(6, 13)] + [ym(F + 1, m) for m in range(1, 7)]
        else:
            cols = [ym(F, m) for m in range(6, 12)]  # truncated at 2026-11
        if not picks:
            for mm in cols[1:]: curve.append([mm, round(cash, 2)])
            periods.append(0.0); continue
        lastbar = {c: (max(px[c]) if px.get(c) else None) for c in picks}
        lastpx = {}
        shares = {}
        w = cash / len(picks)
        for c in picks:
            p0 = px[c][ym(F, 6)][0]
            rate = pool[c]['rate']
            total_costs += w * rate
            shares[c] = (w * (1 - rate)) / p0
            lastpx[c] = p0
        for mm in cols[1:]:
            val = 0.0
            for c in picks:
                s = px[c]
                if mm in s: lastpx[c] = s[mm][0]
                if lastbar[c] is not None and mm > lastbar[c]:
                    val += 0.0  # vanished -> ZERO
                else:
                    val += shares[c] * lastpx[c]
            cash = val
            curve.append([mm, round(cash, 2)])
        # exit cost at end of hold
        sell = sum(shares[c] * (lastpx[c] if not (lastbar[c] and cols[-1] > lastbar[c]) else 0.0) * pool[c]['rate'] for c in picks)
        total_costs += sell; cash = cash - sell
        if curve: curve[-1] = [curve[-1][0], round(cash, 2)]
        periods.append(round((cash / start_val - 1) * 100, 2) if start_val else 0.0)
    peak = 100.0; maxdd = 0.0; last_high_i = 0; longest_gap = 0
    full = [[ym(formations[0], 6), 100.0]] + curve
    for i, (_, v) in enumerate(full):
        if v >= peak: peak = v; last_high_i = i
        longest_gap = max(longest_gap, i - last_high_i)
        if peak: maxdd = max(maxdd, 1 - v / peak)
    return {'final': round(cash, 2), 'curve': curve, 'costs': round(total_costs, 2),
            'max_dd': round(maxdd, 4), 'periods_pct': periods,
            'longest_months_between_highs': longest_gap}

def spy_final(formations):
    a = spy.get(ym(formations[0], 6))
    lastF = formations[-1]
    b = spy.get(ym(2026, 11)) if lastF == 2026 else spy.get(ym(lastF + 1, 6))
    return round(100 * b / a, 2) if a and b else None

def dist_stats(periods):
    if not periods: return {}
    med = float(np.median(periods))
    pos = sum(1 for p in periods if p > 0)
    streak = cur = 0
    for p in periods:
        cur = cur + 1 if p <= 0 else 0
        streak = max(streak, cur)
    return {'median_period_pct': round(med, 2), 'share_positive': f'{pos}/{len(periods)}',
            'best_pct': max(periods), 'worst_pct': min(periods),
            'longest_losing_streak_periods': streak,
            'mean_period_pct_secondary': round(float(np.mean(periods)), 2)}

ROADS = {'LONGEST_2019_2026': list(range(2019, 2027)),
         'DECADE_2019_2026': list(range(2019, 2027)),
         'CONT_2019_2026': list(range(2019, 2027)),
         'VAL_2023_2026': list(range(2023, 2027)),
         'FOLD_2019_2022': list(range(2019, 2023)),
         'FOLD_2023_2026': list(range(2023, 2027))}

def main():
    out = {'family': 'catalog-hxz-intermediary-leverage-beta', 'program': 'v13-best-rules',
           'spec': 'BEST-RULES-SPEC.md',
           'factor': {'assets_series': 'BOGZ1FL664090005Q', 'liabilities_series': 'BOGZ1FL664190005Q',
                      'leverage_q_recent': {f'{q_of(i)}': round(LEV_BY_IDX[i], 2) for i in sorted(LEV_BY_IDX)[-5:]},
                      'note': 'current-vintage levels; 3-month release lag enforced'},
           'pool_sizes': {str(F): len(POOLS[F]) for F in sorted(POOLS)},
           'roads': {}}
    for rname, forms in ROADS.items():
        r = run_road(forms)
        twins = []
        for sd in range(1, 21):
            twins.append(run_road(forms, seed=sd)['final'])
        r['placebo_finals'] = twins
        r['placebos_beaten'] = sum(1 for t in twins if r['final'] > t)
        r['spy_same_window'] = spy_final(forms)
        r['distribution'] = dist_stats(r['periods_pct'])
        out['roads'][rname] = r
        print(rname, r['final'], 'spy', r['spy_same_window'], 'pb', r['placebos_beaten'],
              'dd', r['max_dd'], 'periods', r['periods_pct'], flush=True)
    with open(os.path.join(FAM, 'results.json'), 'w') as fh:
        json.dump(out, fh, indent=1)
    print('saved results.json')

if __name__ == '__main__':
    main()
