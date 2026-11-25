#!/usr/bin/env python3
"""V13 Best-Rules run for catalog-aaii-driehaus.
Chassis frozen in ../BEST-RULES-SPEC.md: BROAD universe, MONTHLY formation,
ALL passing names equal-weight, NO floor, program tiered costs, vanished->ZERO.
Placebos: 20 seeds drawing the same count from the formation's full eligible
feature pool (see spec). Data layer + screen = v12 chassis copy (chassis.py).
Simulation only. Writes ../results.json."""
import json, os, sys, random
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import chassis as C

ROADS = {'LONGEST': ('2016-06', '2026-06'), 'DECADE': ('2017-06', '2026-06'),
         'CONT': ('2019-06', '2026-06'), 'VAL': ('2023-06', '2026-06')}
NS = 21  # actual + 20 placebos

def run_road(road):
    start, end = ROADS[road]
    forms = C.formation_months('monthly', start, end)
    cash = np.full(NS, 100.0)
    costs = 0.0
    curve = []
    pool_pass = []   # passing count per formation
    pool_elig = []
    for fi, ym in enumerate(forms):
        F = C.features(ym)
        mask, rank = C.S_driehaus(F, 'broad')
        pool_pos = np.where(mask)[0]
        n = len(pool_pos)
        pool_pass.append(int(n)); pool_elig.append(int(len(F['idx'])))
        nxt = C.ym_add(ym, 1)
        if n == 0:
            curve.append([nxt, round(float(cash[0]), 2)])
            continue
        picks = [pool_pos]
        for s in range(1, NS):
            rng = random.Random(s * 100003 + fi * 131 + C.MIDX[ym])
            picks.append(np.array(rng.sample(range(len(F['idx'])), n)))
        M = C.price_matrix(F['idx'], ym, 1)
        rates = F['rate']
        vals = cash.copy()
        for s in range(NS):
            pk = picks[s]
            P = M[pk, :]
            r = rates[pk]
            p0 = P[:, 0].copy(); p0[p0 <= 0] = np.nan
            w = cash[s] / len(pk)
            sh = np.where(np.isnan(p0), 0.0, w * (1 - r) / np.where(np.isnan(p0), 1.0, p0))
            if s == 0: costs += float(np.sum(w * r))
            v = float(np.nansum(sh * np.where(np.isnan(P[:, 1]), 0.0, P[:, 1])))
            sell = float(np.nansum(sh * np.where(np.isnan(P[:, 1]), 0.0, P[:, 1]) * r))
            vals[s] = v - sell
            if s == 0: costs += sell
        cash = vals
        curve.append([nxt, round(float(cash[0]), 2)])
    # max drawdown on actual curve (with 100 start)
    peak = 100.0; maxdd = 0.0
    for _, v in curve:
        peak = max(peak, v); maxdd = max(maxdd, 1 - v / peak) if peak else 0.0
    a = C.spy.get(forms[0]); b = C.spy.get(C.ym_add(forms[-1], 1))
    spyfin = round(100 * b / a, 2) if a and b else None
    twins = [round(float(x), 2) for x in cash[1:]]
    return {'final': round(float(cash[0]), 2), 'costs': round(costs, 2),
            'max_dd': round(maxdd, 4), 'spy_same_window': spyfin,
            'placebo_finals': twins,
            'placebos_beaten': int(sum(1 for t in twins if cash[0] > t)),
            'curve': curve, 'n_formations': len(forms),
            'passing_per_formation': pool_pass, 'eligible_per_formation': pool_elig,
            'formations_invested': int(sum(1 for x in pool_pass if x > 0))}

def dist_stats(curve, start_val=100.0):
    """Monthly + annual per-period distributions from a monthly curve."""
    vals = [start_val] + [v for _, v in curve]
    months = [m for m, _ in curve]
    rets = [vals[i] / vals[i - 1] - 1 for i in range(1, len(vals))]
    def summarize(rs):
        if not rs: return None
        arr = np.array(rs)
        # longest losing streak
        streak = cur = 0
        for r in rs:
            cur = cur + 1 if r < 0 else 0
            streak = max(streak, cur)
        return {'n': len(rs), 'median_pct': round(float(np.median(arr)) * 100, 2),
                'share_positive': f"{int((arr > 0).sum())}/{len(rs)}",
                'best_pct': round(float(arr.max()) * 100, 2),
                'worst_pct': round(float(arr.min()) * 100, 2),
                'longest_losing_streak': int(streak),
                'avg_pct_secondary': round(float(arr.mean()) * 100, 2)}
    # longest stretch between new highs (months, on the curve incl. start)
    peak = -1; last_high = 0; longest = 0
    for i, v in enumerate(vals):
        if v >= peak: peak = v; last_high = i
        longest = max(longest, i - last_high)
    # annual returns by calendar year-end
    by_year = {}
    prev = start_val
    order = []
    for m, v in curve:
        y = m[:4]
        if y not in by_year: order.append(y)
        by_year[y] = v
    arets = []
    for y in order:
        arets.append(by_year[y] / prev - 1); prev = by_year[y]
    mstats = summarize(rets); astats = summarize(arets)
    if mstats: mstats['longest_stretch_between_new_highs_months'] = int(longest)
    return {'monthly': mstats, 'annual': astats}

def main():
    out = {'family': 'catalog-aaii-driehaus', 'program': 'v13-best-rules',
           'chassis': 'broad universe | monthly | ALL passing | no floor | tiered program costs',
           'roads': {}}
    for road in ROADS:
        r = run_road(road)
        r['distribution'] = dist_stats(r['curve'])
        out['roads'][road] = r
        print(road, 'final', r['final'], 'spy', r['spy_same_window'],
              'pb', r['placebos_beaten'], 'maxdd', r['max_dd'],
              'invested formations', r['formations_invested'], '/', r['n_formations'], flush=True)
    # June passing-pool sizes (broad) for the record
    pools = {}
    for y in range(2016, 2026):
        F = C.features(f'{y:04d}-06')
        mask, _ = C.S_driehaus(F, 'broad')
        pools[str(y)] = int(mask.sum())
    out['pool_sizes_june_broad'] = pools
    with open(os.path.join(HERE, '..', 'results.json'), 'w') as f:
        json.dump(out, f, indent=1)
    print('saved results.json; June broad pools:', pools)

if __name__ == '__main__':
    main()
