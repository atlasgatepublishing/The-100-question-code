#!/usr/bin/env python3
"""V13 best-rules run — catalog-aronson-cn-extremes-spreads.
Implements BEST-RULES-SPEC.md exactly (frozen 2026-11-22 before this run):
monthly level-based two-gauge stress dial on SPY, long-only.
  DUR = DGS10 - DGS3MO (pp); QUAL = DBAA - DAAA (pp), FRED via v12 data files
  read in place (signal input only, not cached).
  stress = (DUR<0) + (QUAL>=1.50); weight = {0:1.0, 1:0.5, 2:0.0}[stress]
  Signal for month M+1 from month-end M values (1-month lag, point-in-time).
  Cost 0.10% per unit position change. No floor. Cash earns 0%.
Placebos: 20 circular phase-shifts of the monthly weight series per road.
Simulation only."""
import json, os, csv, datetime, random
import numpy as np

HOME = os.path.expanduser('~')
OUT = os.path.join(HOME, 'workspace/stock-app/backtests/v13-best-rules/catalog-aronson-cn-extremes-spreads')
SPYJ = os.path.join(HOME, 'workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json')
FRED = os.path.join(HOME, 'workspace/stock-app/backtests/v12-completions/catalog-aronson-cn-extremes-spreads/data')

# ---------- SPY daily ----------
d = json.load(open(SPYJ))['chart']['result'][0]
ts = d['timestamp']; q = d['indicators']['quote'][0]
dates, C = [], []
for i, t in enumerate(ts):
    if q['close'][i] is None: continue
    dates.append(datetime.datetime.utcfromtimestamp(t).date())
    C.append(q['close'][i])
C = np.array(C, dtype=float); N = len(C)
ret = np.zeros(N); ret[1:] = C[1:] / C[:-1] - 1

# ---------- FRED spreads (signal input only) ----------
def load_yield(name):
    out = {}
    for row in csv.DictReader(open(os.path.join(FRED, name + '.csv'))):
        try: out[datetime.date.fromisoformat(row['observation_date'])] = float(row[name])
        except Exception: pass
    return out

y10, y3m, yaaa, ybaa = load_yield('DGS10'), load_yield('DGS3MO'), load_yield('DAAA'), load_yield('DBAA')

def month_end_spreads():
    """{(year, month): (DUR, QUAL)} using last available observation in that month."""
    months = {}
    all_dates = sorted(set(y10) | set(y3m) | set(yaaa) | set(ybaa))
    last = {}
    for dt in all_dates:
        for nm, src in (('y10', y10), ('y3m', y3m), ('yaaa', yaaa), ('ybaa', ybaa)):
            if dt in src: last[nm] = src[dt]
        if len(last) == 4:
            months[(dt.year, dt.month)] = (last['y10'] - last['y3m'], last['ybaa'] - last['yaaa'])
    return months

ME = month_end_spreads()

def prev_month(y, m):
    return (y - 1, 12) if m == 1 else (y, m - 1)

def weight_for_month(y, m):
    """Weight held during month (y,m) from month-end values of the prior month."""
    pm = prev_month(y, m)
    if pm not in ME: return 1.0  # no signal history -> fully invested (pre-2010 never traded)
    dur, qual = ME[pm]
    stress = (1 if dur < 0 else 0) + (1 if qual >= 1.50 else 0)
    return {0: 1.0, 1: 0.5, 2: 0.0}[stress]

# daily weight series over the full SPY history
W = np.array([weight_for_month(dt.year, dt.month) for dt in dates])

ROADS = {'LONG': ('2010-01-04', '2026-11-20'), 'DECADE': ('2016-11-21', '2026-11-20'),
         'CONT': ('2019-01-02', '2026-11-20'), 'VAL': ('2023-01-03', '2026-11-20')}
CHAMP = {'LONG': 1415.62, 'DECADE': 667.35, 'CONT': 544.47, 'VAL': 288.05}
SPYREF = {'LONG': 822.94, 'DECADE': 367.80, 'CONT': 313.62, 'VAL': 187.77}

def road_idx(a, b):
    i0 = next(i for i, dt in enumerate(dates) if dt >= datetime.date.fromisoformat(a))
    i1 = max(i for i, dt in enumerate(dates) if dt <= datetime.date.fromisoformat(b))
    return i0, i1

def run(w, i0, i1):
    eq = 100.0; curve = [[str(dates[i0]), 100.0]]; costs = 0.0; prev = 0.0
    for i in range(i0 + 1, i1 + 1):
        p = w[i - 1]  # weight decided before day i (monthly, lagged) applies to ret[i]
        chg = abs(p - prev)
        if chg > 0:
            c = eq * chg * 0.001; eq -= c; costs += c
        eq *= (1 + p * ret[i]); prev = p
        curve.append([str(dates[i]), round(eq, 2)])
    peak = 100.0; mdd = 0.0
    for _, v in curve:
        peak = max(peak, v); mdd = max(mdd, 1 - v / peak)
    return round(eq, 2), curve, round(costs, 2), round(mdd, 4)

def period_stats(curve):
    months = {}
    for ds, v in curve: months[ds[:7]] = v
    ks = sorted(months); vals = [months[k] for k in ks]
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
            'median_month_pct': round(100 * float(np.median(rets)), 2),
            'best_month_pct': round(100 * max(rets), 2), 'worst_month_pct': round(100 * min(rets), 2),
            'longest_losing_streak_months': los, 'longest_between_highs_months': longest,
            'avg_month_pct_secondary': round(100 * float(np.mean(rets)), 2)}

def monthly_weights(i0, i1):
    """Ordered list of (year, month, weight) covering the road, for placebo shifts."""
    seen = []
    for i in range(i0, i1 + 1):
        ym = (dates[i].year, dates[i].month)
        if not seen or seen[-1][:2] != ym: seen.append((ym[0], ym[1], float(W[i])))
    return seen

def weights_from_monthly(mw):
    lut = {(y, m): w for y, m, w in mw}
    return np.array([lut.get((dt.year, dt.month), 1.0) for dt in dates])

def spy_final(i0, i1): return round(100 * C[i1] / C[i0], 2)

def main():
    out = {'family': 'catalog-aronson-cn-extremes-spreads', 'program': 'v13-best-rules',
           'design': 'monthly level dial: stress=(DUR<0)+(QUAL>=1.50); w={0:1.0,1:0.5,2:0.0}; 1-month lag; long-only; no floor; cost 0.10%/unit',
           'roads': {}}
    for rname, (a, b) in ROADS.items():
        i0, i1 = road_idx(a, b)
        fin, curve, costs, mdd = run(W, i0, i1)
        mw = monthly_weights(i0, i1)
        wvals = [w for _, _, w in mw]
        twins = []
        for s in range(1, 21):
            rng = random.Random(777 + s)
            off = rng.randint(1, len(wvals) - 1)
            shifted = [(y, m, wvals[(k - off) % len(wvals)]) for k, (y, m, _) in enumerate(mw)]
            tf, _, _, _ = run(weights_from_monthly(shifted), i0, i1)
            twins.append(tf)
        # yearly folds + half windows (printed always; confirmation bars applied in RESULTS if triggered)
        years = {}
        for yr in range(dates[i0].year, dates[i1].year + 1):
            yi = [i for i in range(i0, i1 + 1) if dates[i].year == yr]
            if len(yi) < 20: continue
            yf, _, _, _ = run(W, yi[0], yi[-1])
            years[str(yr)] = {'final': yf, 'spy': spy_final(yi[0], yi[-1]), 'beats_spy': bool(yf > spy_final(yi[0], yi[-1]))}
        mid = (i0 + i1) // 2
        h1, _, _, h1dd = run(W, i0, mid); h2, _, _, h2dd = run(W, mid, i1)
        out['roads'][rname] = {
            'window': [a, b], 'final': fin, 'costs': costs, 'max_dd': mdd,
            'spy_same_window_computed': spy_final(i0, i1), 'spy_reference': SPYREF[rname],
            'champion_vm': CHAMP[rname], 'beats_champion': bool(fin > CHAMP[rname]),
            'avg_weight': round(float(np.mean(W[i0:i1 + 1])), 3),
            'months_at_weights': {str(w): wvals.count(w) for w in sorted(set(wvals))},
            'placebos_beaten': sum(1 for t in twins if fin > t), 'placebo_finals': twins,
            'period_stats_monthly': period_stats(curve),
            'yearly_folds': years, 'half_windows': {'first': {'final': h1, 'max_dd': h1dd}, 'second': {'final': h2, 'max_dd': h2dd}},
            'curve': curve}
        print(rname, 'final', fin, 'dd', mdd, 'spy', spy_final(i0, i1), 'pb', out['roads'][rname]['placebos_beaten'], '/20', flush=True)
    # Diagnostic only (not a road): same frozen rules on v12's LONGEST window
    # 2015-06-01->2026-11-20 for a same-window comparison vs the published form.
    i0, i1 = road_idx('2015-06-01', '2026-11-20')
    fin, curve, costs, mdd = run(W, i0, i1)
    out['diagnostic_v12_window'] = {'window': ['2015-06-01', '2026-11-20'], 'final': fin, 'costs': costs,
                                    'max_dd': mdd, 'spy_same_window_computed': spy_final(i0, i1),
                                    'period_stats_monthly': period_stats(curve)}
    print('DIAG_2015', fin, 'spy', spy_final(i0, i1), flush=True)
    json.dump(out, open(os.path.join(OUT, 'results.json'), 'w'), indent=1)
    print('DONE')

if __name__ == '__main__': main()
