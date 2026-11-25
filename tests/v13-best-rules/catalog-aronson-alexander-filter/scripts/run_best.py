#!/usr/bin/env python3
"""V13 Best Rules — Alexander filter. Implements BEST-RULES-SPEC.md (frozen before run).
My rules: alex 5% on SPY adjclose, LONG/CASH only, daily, next-day, 0.10%/unit change, NO floor.
Comparators (not candidates): published long/short grid {1,2,3,5,10} re-run on same roads/series/costs.
Placebos per road, 20 seeds each: (a) circular phase-shifts of my position series;
(b) Aronson permutation: shuffle road-window daily returns, rebuild prices, run identical filter
    (state direction carried from real warm-up, extreme reset to road-start price).
Confirmation (frozen bars) computed only if a road beats champion V+M on that road.
Simulation only."""
import json, os, random, datetime
import numpy as np

OUT = os.path.expanduser('~/workspace/stock-app/backtests/v13-best-rules/catalog-aronson-alexander-filter')
SPYJ = os.path.expanduser('~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json')
COST = 0.001
CHAMP = {'LONG': 1415.62, 'DECADE': 667.35, 'CONT': 544.47, 'VAL': 288.05}

d = json.load(open(SPYJ))['chart']['result'][0]
ts = d['timestamp']; adj = d['indicators']['adjclose'][0]['adjclose']; q = d['indicators']['quote'][0]
dates, C = [], []
for i, t in enumerate(ts):
    if adj[i] is None or q['close'][i] is None: continue
    dates.append(datetime.datetime.utcfromtimestamp(t).date()); C.append(float(adj[i]))
C = np.array(C); N = len(C)
ret = np.zeros(N); ret[1:] = C[1:] / C[:-1] - 1

def alex_state(price, pct):
    """Returns pos array (+1 up-state / -1 down-state), full series from index 0."""
    pos = np.zeros(len(price)); cur = 0.0; extreme = price[0]
    for i, p in enumerate(price):
        if cur >= 0:
            extreme = max(extreme, p)
            if p <= extreme * (1 - pct / 100.0): cur = -1.0; extreme = p
        if cur <= 0:
            if cur < 0:
                extreme = min(extreme, p)
                if p >= extreme * (1 + pct / 100.0): cur = 1.0; extreme = p
            elif p >= extreme * (1 + pct / 100.0): cur = 1.0; extreme = p
        pos[i] = cur
    return pos

POS = {pct: alex_state(C, pct) for pct in (1, 2, 3, 5, 10)}

ROADS = {'LONG': ('2010-01-04', '2026-11-20'), 'DECADE': ('2016-11-21', '2026-11-20'),
         'CONT': ('2019-01-02', '2026-11-20'), 'VAL': ('2023-01-03', '2026-11-20')}

def road_idx(a, b):
    i0 = next(i for i, dt in enumerate(dates) if dt >= datetime.date.fromisoformat(a))
    i1 = max(i for i, dt in enumerate(dates) if dt <= datetime.date.fromisoformat(b))
    return i0, i1

def run(pos_full, i0, i1, mode):
    """mode 'lc': pos -1 -> cash 0. mode 'ls': pos as-is. Position at i-1 earns ret[i]."""
    eq = 100.0; curve = [[str(dates[i0]), 100.0]]; costs = 0.0; prev = 0.0; flips = 0
    for i in range(i0 + 1, i1 + 1):
        p = pos_full[i - 1]
        if mode == 'lc': p = max(p, 0.0)
        chg = abs(p - prev)
        if chg > 0:
            c = eq * chg * COST; eq -= c; costs += c; flips += 1
        eq *= (1 + p * ret[i]); prev = p
        curve.append([str(dates[i]), round(eq, 2)])
    peak = 100.0; mdd = 0.0
    for _, v in curve:
        peak = max(peak, v); mdd = max(mdd, 1 - v / peak)
    return round(eq, 2), curve, round(costs, 2), round(mdd, 4), flips

def run_on_returns(pos, rets):
    """pos: array aligned so pos[k] earns rets[k+1]... used for permutation: pos over permuted prices."""
    eq = 100.0; prev = 0.0; costs = 0.0
    for k in range(len(rets)):
        p = max(pos[k], 0.0)
        chg = abs(p - prev)
        if chg > 0:
            c = eq * chg * COST; eq -= c; costs += c
        eq *= (1 + p * rets[k]); prev = p
    return round(eq, 2)

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
    my_pos = POS[5]
    out = {'family': 'catalog-aronson-alexander-filter', 'program': 'v13-best-rules',
           'spec': 'alex5, SPY adjclose, long/cash, daily next-day, 0.10%/unit, no floor',
           'roads': {}, 'published_comparators_longshort': {}, 'confirmation': None}
    champ_beaten = []
    for rname, (a, b) in ROADS.items():
        i0, i1 = road_idx(a, b)
        fin, curve, costs, mdd, flips = run(my_pos, i0, i1, 'lc')
        spy = round(100 * C[i1] / C[i0], 2)
        # (a) phase-shift placebos on my position series (within-window rotation)
        seg = np.array([max(my_pos[i], 0.0) for i in range(i0, i1)])
        seg_ret = ret[i0 + 1:i1 + 1]
        twins = []
        for s in range(1, 21):
            rng = random.Random(4200 + s)
            off = rng.randint(60, len(seg) - 60)
            sh = np.roll(seg, off)
            eq = 100.0; prev = 0.0
            for k in range(len(seg_ret)):
                p = sh[k]; chg = abs(p - prev)
                if chg > 0: eq -= eq * chg * COST
                eq *= (1 + p * seg_ret[k]); prev = p
            twins.append(round(eq, 2))
        # (b) Aronson permutation: shuffle road returns, rebuild prices, identical filter
        perm = []
        base_rets = list(ret[i0 + 1:i1 + 1])
        for s in range(1, 21):
            rng = random.Random(9100 + s)
            pr = base_rets[:]; rng.shuffle(pr)
            prices = [C[i0]]
            for r in pr: prices.append(prices[-1] * (1 + r))
            ppos = alex_state(np.array(prices), 5)
            # position at k (decided on permuted close k) earns pr[k]; align: ppos[k] for k in 0..len-1
            perm.append(run_on_returns(ppos[:-1], pr))
        out['roads'][rname] = {'final': fin, 'costs': costs, 'max_dd': mdd, 'flips': flips,
                               'spy_same_window': spy, 'curve': curve,
                               'phase_placebos_beaten': sum(1 for t in twins if fin > t),
                               'phase_placebo_finals': twins, 'phase_placebo_median': round(float(np.median(twins)), 2),
                               'permutation_beaten': sum(1 for t in perm if fin > t),
                               'permutation_finals': perm, 'permutation_median': round(float(np.median(perm)), 2),
                               'period_stats_monthly': period_stats(curve)}
        print(rname, 'MY', fin, 'SPY', spy, 'DD', mdd, 'phase', out['roads'][rname]['phase_placebos_beaten'],
              'perm', out['roads'][rname]['permutation_beaten'], flush=True)
        if fin > CHAMP[rname]: champ_beaten.append(rname)
        # published comparators on same roads
        comp = {}
        for pct in (1, 2, 3, 5, 10):
            f2, _, c2, d2, fl2 = run(POS[pct], i0, i1, 'ls')
            comp[f'alex{pct}_longshort'] = {'final': f2, 'costs': c2, 'max_dd': d2, 'flips': fl2}
            f3, _, c3, d3, fl3 = run(POS[pct], i0, i1, 'lc')
            comp[f'alex{pct}_longcash_reference'] = {'final': f3, 'costs': c3, 'max_dd': d3, 'flips': fl3}
        out['published_comparators_longshort'][rname] = comp
    if champ_beaten:
        conf = {'roads_triggered': champ_beaten, 'half_windows': {}, 'yearly_folds': {}}
        for (a, b), nm in [(('2010-01-04', '2018-12-31'), 'H1'), (('2019-01-02', '2026-11-20'), 'H2')]:
            i0, i1 = road_idx(a, b)
            f, _, _, dd, _ = run(my_pos, i0, i1, 'lc')
            conf['half_windows'][nm] = {'final': f, 'spy': round(100 * C[i1] / C[i0], 2), 'max_dd': dd}
        wins = 0; tot = 0
        for y in range(2010, 2027):
            i0 = next(i for i, dt in enumerate(dates) if dt >= datetime.date(y, 1, 1))
            i1 = max(i for i, dt in enumerate(dates) if dt <= datetime.date(y, 12, 31))
            f, _, _, dd, _ = run(my_pos, i0, i1, 'lc')
            s = round(100 * C[i1] / C[i0], 2); tot += 1; wins += 1 if f > s else 0
            conf['yearly_folds'][str(y)] = {'final': f, 'spy': s, 'max_dd': dd}
        conf['yearly_share_beating_spy'] = round(wins / tot, 3)
        out['confirmation'] = conf
    json.dump(out, open(os.path.join(OUT, 'results.json'), 'w'), indent=1)
    print('DONE champ_beaten=', champ_beaten)

if __name__ == '__main__': main()
