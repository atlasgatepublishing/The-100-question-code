#!/usr/bin/env python3
"""V13 best-rules engine — catalog-aronson-cn-extremes-index.
Implements BEST-RULES-SPEC.md exactly (frozen before this run):
CN(205) on SPY adjusted close, 4-day LMA smoothing; default LONG 100%;
CN>=90 -> CASH; in cash re-enter LONG when CN<=50 or CN<=10; never short;
no floor; daily, signal on close t applies to return t+1; cost 0.10%/unit change.
Placebos: 20 circular phase-shifts of the position series (seeds 777+s, v12 convention).
Simulation only. Public data (Yahoo chart API cache saved in ../data/)."""
import json, os, sys, random, datetime
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, 'data', 'px_SPY_yahoo_daily.json')

d = json.load(open(DATA))['chart']['result'][0]
ts = d['timestamp']; q = d['indicators']['quote'][0]
adj = d['indicators']['adjclose'][0]['adjclose']
dates, C = [], []
for i, t in enumerate(ts):
    if adj[i] is None or q['close'][i] is None: continue
    dates.append(datetime.datetime.utcfromtimestamp(t).date())
    C.append(adj[i])  # total-return series: signal and returns on same basis
C = np.array(C, dtype=float); N = len(C)
print(f'data {dates[0]} -> {dates[-1]} n={N}', flush=True)

def cn(x, n):
    out = np.full(len(x), np.nan)
    for i in range(len(x)):
        if i < n - 1: continue
        w = x[i - n + 1:i + 1]
        lo, hi = w.min(), w.max()
        out[i] = 100.0 * (x[i] - lo) / (hi - lo) if hi > lo else 50.0
    return out

def lma4(x):
    out = np.full(len(x), np.nan); w = np.array([1., 2., 3., 4.])
    for i in range(3, len(x)):
        seg = x[i - 3:i + 1]
        if np.isnan(seg).any(): continue
        out[i] = float(np.dot(w, seg) / 10.0)
    return out

def best_rules_positions():
    s = lma4(cn(C, 205))
    pos = np.zeros(N); cur = 1.0  # default LONG
    events = []
    for i in range(N):
        v = s[i]
        if not np.isnan(v):
            if cur == 1.0 and v >= 90.0:
                cur = 0.0; events.append([str(dates[i]), 'EXIT_TO_CASH', round(float(v), 1)])
            elif cur == 0.0 and (v <= 50.0 or v <= 10.0):
                cur = 1.0; events.append([str(dates[i]), 'REENTER_LONG', round(float(v), 1)])
        pos[i] = cur
    return pos, events, s

POS, EVENTS, CN_S = best_rules_positions()
ret = np.zeros(N); ret[1:] = C[1:] / C[:-1] - 1

ROADS = {'LONG': ('2010-01-04', '2026-11-20'), 'DECADE': ('2016-11-21', '2026-11-20'),
         'CONT': ('2019-01-02', '2026-11-20'), 'VAL': ('2023-01-03', '2026-11-20'),
         'LONGEST_2015_AUX': ('2015-06-01', '2026-11-20')}

def road_idx(a, b):
    i0 = next(i for i, dt in enumerate(dates) if dt >= datetime.date.fromisoformat(a))
    i1 = max(i for i, dt in enumerate(dates) if dt <= datetime.date.fromisoformat(b))
    return i0, i1

def run(pos, i0, i1):
    eq = 100.0; curve = [[str(dates[i0]), 100.0]]; costs = 0.0; prev = 0.0; nchg = 0
    for i in range(i0 + 1, i1 + 1):
        p = pos[i - 1]
        chg = abs(p - prev)
        if chg > 0:
            c = eq * chg * 0.001; eq -= c; costs += c; nchg += 1
        eq *= (1 + p * ret[i]); prev = p
        curve.append([str(dates[i]), round(eq, 2)])
    peak = 100.0; mdd = 0.0
    for _, v in curve:
        peak = max(peak, v); mdd = max(mdd, 1 - v / peak)
    exposure = float(np.mean(pos[i0:i1])) if i1 > i0 else 0.0
    return {'final': round(float(curve[-1][1]), 2), 'costs': round(costs, 2), 'max_dd': round(mdd, 4),
            'n_position_changes': nchg, 'exposure_share': round(exposure, 3), 'curve': curve}

def spy_final(i0, i1): return round(100 * C[i1] / C[i0], 2)

def period_stats(curve):
    months = {}
    for ds, v in curve: months[ds[:7]] = v
    ks = sorted(months); vals = [months[k] for k in ks]
    rets = [vals[i] / vals[i - 1] - 1 for i in range(1, len(vals)) if vals[i - 1] > 0]
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

def main():
    out = {'family': 'catalog-aronson-cn-extremes-index', 'program': 'v13-best-rules',
           'spec': 'BEST-RULES-SPEC.md (frozen before run)',
           'data': 'SPY Yahoo chart API daily, dividend-adjusted close, 2009-01-02..2026-11-20, saved in data/',
           'events': EVENTS, 'roads': {}}
    for rname, (a, b) in ROADS.items():
        i0, i1 = road_idx(a, b)
        r = run(POS, i0, i1)
        twins = []
        for s in range(1, 21):
            rng = random.Random(777 + s)
            off = rng.randint(60, N - 60)
            shifted = np.roll(POS, off)
            twins.append(run(shifted, i0, i1)['final'])
        r['spy_same_window_adj'] = spy_final(i0, i1)
        r['placebos_beaten'] = sum(1 for t in twins if r['final'] > t)
        r['placebo_finals'] = twins
        r['period_stats_monthly'] = period_stats(r['curve'])
        out['roads'][rname] = r
        print(rname, r['final'], 'SPY', r['spy_same_window_adj'], 'DD', r['max_dd'],
              'pb', r['placebos_beaten'], '/20', 'chg', r['n_position_changes'], 'expo', r['exposure_share'], flush=True)

    # ---- Confirmation block (frozen bar in spec): only for roads beating V+M champion ----
    CHAMP = {'LONG': 1415.62, 'DECADE': 667.35, 'CONT': 544.47, 'VAL': 288.05}
    conf = {}
    for rname, champ in CHAMP.items():
        if out['roads'][rname]['final'] > champ:
            a, b = ROADS[rname]
            i0, i1 = road_idx(a, b)
            mid = (i0 + i1) // 2
            halves = {'first_half': run(POS, i0, mid)['final'], 'second_half': run(POS, mid, i1)['final']}
            years = {}
            for y in range(int(a[:4]), 2027):
                ya, yb = f'{y}-01-01', f'{y}-12-31'
                try:
                    j0, j1 = road_idx(max(ya, a), min(yb, b))
                    if j1 > j0: years[str(y)] = run(POS, j0, j1)['final']
                except StopIteration:
                    pass
            med_year = round(float(np.median(list(years.values()))), 2) if years else None
            passed = (halves['first_half'] > 100 and halves['second_half'] > 100
                      and med_year is not None and med_year > 100
                      and out['roads'][rname]['placebos_beaten'] >= 15)
            conf[rname] = {'champion': champ, 'half_windows': halves, 'yearly_folds': years,
                           'median_yearly_fold': med_year, 'confirmation_passed': passed}
            print('CONFIRM', rname, conf[rname], flush=True)
    out['confirmation'] = conf
    json.dump(out, open(os.path.join(BASE, 'results.json'), 'w'), indent=1)
    print('events total:', len(EVENTS), flush=True)

if __name__ == '__main__': main()
