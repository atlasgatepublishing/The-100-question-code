#!/usr/bin/env python3
"""V13 best-rules run for catalog-aaii-fisher (Philip Fisher AAII screen).
Spec: ../BEST-RULES-SPEC.md (frozen before this run).
Chassis: annual June review; hold ALL passers equal-weight; sell only
names failing the screen at a review (continuing passers are held, not
round-tripped); no floor; cash when nothing passes. Data layer and the
published screen are imported read-only from the v12 engine.
20-seed placebos draw the same count from the same eligible pond.
Simulation only. Writes ../results.json."""
import json, os, sys, math, random
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FAM = os.path.join(HERE, '..')
V12 = os.path.expanduser('~/workspace/stock-app/backtests/v12-completions/catalog-aaii-fisher/scripts')
sys.path.insert(0, V12)
import engine as E  # loads W04 stack; S_fisher is the published screen

MONTHS = E.MONTHS; MIDX = E.MIDX; PXA = E.PXA; SPY = E.SPY

# cleaned price series per CIK-array-index: last-known carried, 0 after last bar
LASTBAR = {}
for i in range(PXA.shape[0]):
    nz = np.where(~np.isnan(PXA[i]))[0]
    LASTBAR[i] = int(nz[-1]) if len(nz) else -1

def price(i, j):
    if j > LASTBAR[i]:
        return 0.0
    v = PXA[i, j]
    if not np.isnan(v):
        return float(v)
    k = j - 1
    while k >= 0 and np.isnan(PXA[i, k]):
        k -= 1
    return float(PXA[i, k]) if k >= 0 else 0.0

def simulate(start, end, seed=None):
    """seed=None -> the screen's picks; seed=int -> placebo draw from pond."""
    s, e = MIDX[start], MIDX[end]
    cash = 100.0
    shares = {}          # cik-array-index -> shares
    costs = 0.0
    curve = []
    reviews = [ym for ym in MONTHS[s:e] if ym[5:7] == '06']
    review_set = set(reviews)
    last_rates = {}
    for j in range(s, e + 1):
        ym = MONTHS[j]
        if ym in review_set:
            F = E.features(ym)
            pos_of = {int(F['idx'][k]): k for k in range(len(F['idx']))}
            if seed is None:
                mask, _ = E.S_fisher(F, 'native')
                picks = [int(x) for x in F['idx'][mask]]
            else:
                mask, _ = E.S_fisher(F, 'native')
                n = int(mask.sum())
                pond = [int(x) for x in F['idx']]
                rng = random.Random(seed * 100003 + reviews.index(ym) * 131 + j)
                picks = rng.sample(pond, min(n, len(pond))) if n else []
            pick_set = set(picks)
            def rate_of(i):
                if i in pos_of:
                    return float(F['rate'][pos_of[i]])
                return 0.0075
            # sell failers
            for i in list(shares):
                if i not in pick_set:
                    p = price(i, j)
                    proceeds = shares[i] * p
                    c = proceeds * rate_of(i)
                    costs += c; cash += proceeds - c
                    del shares[i]
            # equity and equal-weight targets
            equity = cash + sum(sh * price(i, j) for i, sh in shares.items())
            if picks:
                target = equity / len(picks)
                # trims first (passers above target)
                for i in picks:
                    p = price(i, j)
                    if p <= 0:
                        continue
                    cur = shares.get(i, 0.0) * p
                    if cur > target:
                        sell_amt = cur - target
                        c = sell_amt * rate_of(i)
                        costs += c; cash += sell_amt - c
                        shares[i] = target / p
                # buys
                needs = []
                total_need = 0.0
                for i in picks:
                    p = price(i, j)
                    if p <= 0:
                        continue
                    cur = shares.get(i, 0.0) * p
                    need = target - cur
                    if need > 1e-9:
                        needs.append((i, p, need)); total_need += need
                if total_need > 0:
                    scale = min(1.0, cash / total_need) if total_need > 0 else 0.0
                    for i, p, need in needs:
                        spend = need * scale
                        r = rate_of(i)
                        costs += spend * r
                        shares[i] = shares.get(i, 0.0) + spend * (1 - r) / p
                        cash -= spend
                last_rates = {i: rate_of(i) for i in shares}
        eq = cash + sum(sh * price(i, j) for i, sh in shares.items())
        curve.append([ym, round(float(eq), 2)])
    # liquidation value at end (sell costs on holdings)
    liq = cash
    for i, sh in shares.items():
        v = sh * price(i, e)
        liq += v * (1 - last_rates.get(i, 0.0075))
    spy_fin = round(100 * float(SPY[e]) / float(SPY[s]), 2)
    # max drawdown on curve
    peak = 100.0; maxdd = 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, 1 - v / peak)
    return {'final': round(float(liq), 2), 'final_mark': round(float(curve[-1][1]), 2),
            'costs': round(costs, 2), 'max_dd': round(maxdd, 4),
            'spy_same_window': spy_fin, 'curve': curve,
            'n_reviews': len(reviews)}

def dist_stats(curve, period_months):
    vals = [v for _, v in curve]
    rets = []
    for k in range(period_months, len(vals), period_months):
        if vals[k - period_months] > 0:
            rets.append(vals[k] / vals[k - period_months] - 1)
    if not rets:
        return None
    med = float(np.median(rets))
    pos = sum(1 for r in rets if r > 0)
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0
        streak = max(streak, cur)
    # longest stretch between new highs on the full monthly curve
    peak = -1.0; last_high = 0; longest = 0
    for idx, v in enumerate(vals):
        if v >= peak:
            peak = v; longest = max(longest, idx - last_high); last_high = idx
    longest = max(longest, len(vals) - 1 - last_high)
    return {'n_periods': len(rets), 'n_positive': pos,
            'median': round(med, 4), 'best': round(max(rets), 4),
            'worst': round(min(rets), 4), 'mean_secondary': round(float(np.mean(rets)), 4),
            'longest_losing_streak': streak,
            'longest_months_between_new_highs': int(longest),
            'period_returns_pct': [round(r * 100, 1) for r in rets]}

ROADS = {'LONG': ('2016-06', '2026-06'), 'DECADE': ('2017-06', '2026-06'),
         'CONT': ('2019-06', '2026-06'), 'VAL': ('2023-06', '2026-06'),
         'FOLD1': ('2016-06', '2021-06'), 'FOLD2': ('2021-06', '2026-06')}

def main():
    out = {'family': 'catalog-aaii-fisher', 'spec': 'BEST-RULES-SPEC.md (frozen pre-run)',
           'roads': {}}
    # June passing-pool sizes (structural record)
    pools = {}
    for y in range(2016, 2026):
        F = E.features(f'{y:04d}-06')
        mask, _ = E.S_fisher(F, 'native')
        pools[str(y)] = int(mask.sum())
    out['pool_sizes_june_native'] = pools
    for road, (s, e) in ROADS.items():
        r = simulate(s, e)
        twins = []
        for seed in range(1, 21):
            t = simulate(s, e, seed=seed)
            twins.append(t['final'])
        r['placebo_finals'] = [round(float(x), 2) for x in twins]
        r['placebos_beaten'] = int(sum(1 for t in twins if r['final'] > t))
        r['placebo_median'] = round(float(np.median(twins)), 2)
        r['dist_monthly'] = dist_stats(r['curve'], 1)
        # annual periods: June-to-June from curve points at Junes
        june_vals = [(ym, v) for ym, v in r['curve'] if ym[5:7] == '06']
        r['dist_annual'] = dist_stats(june_vals, 1)
        out['roads'][road] = r
        print(road, r['final'], 'spy', r['spy_same_window'], 'pb',
              r['placebos_beaten'], 'dd', r['max_dd'], flush=True)
    json.dump(out, open(os.path.join(FAM, 'results.json'), 'w'), indent=1)
    print('saved results.json')

if __name__ == '__main__':
    main()
