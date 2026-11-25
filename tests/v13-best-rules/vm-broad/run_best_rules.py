#!/usr/bin/env python3
"""vm-broad v13 BEST RULES: AMP value+momentum on the broad W04 EDGAR
universe. MY form (frozen in BEST-RULES-SPEC.md): top 50, cap >= $100M,
annual June-30 formation, no floor, W04 tiered costs, vanished -> ZERO.
Reference twin (top 30, cap >= $50M) must reproduce v12 published finals
(FULL $177.89 / CONT-era $176.83 / VAL-era $164.87) before numbers count.
20-seed placebos per road. Shared W04 data read-only; writes only here.
Simulation only."""
import json, os, sys, random, statistics
HERE = os.path.dirname(os.path.abspath(__file__))
W04 = os.path.expanduser('~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data')
sys.path.insert(0, W04)
import engine_w04 as E

E.D = E.Data()
D = E.D

def ym(y, m): return f'{y:04d}-{m:02d}'

def pct_ranks(vals):
    items = sorted(vals.items(), key=lambda kv: kv[1]); n = len(items)
    if n == 1: return {items[0][0]: 0.5}
    return {c: i / (n - 1) for i, (c, _) in enumerate(items)}

def eligible(F, mincap):
    s = E.snapshot(F)
    pool = {}
    for c, v in s.items():
        if not v['cap'] or v['cap'] < mincap: continue
        if not v['equity'] or v['equity'] <= 0: continue
        if not v['shares'] or not v['px_adj']: continue
        if not D.has_price_month(c, ym(F, 6)): continue
        if not D.has_price_month(c, ym(F, 5)): continue
        if not D.has_price_month(c, ym(F - 1, 6)): continue
        p_may = D.price(c, ym(F, 5)); p_jun_prev = D.price(c, ym(F - 1, 6))
        if not p_may or not p_jun_prev: continue
        pool[c] = dict(bm=v['equity'] / v['cap'], mom=p_may / p_jun_prev - 1.0,
                       cap=v['cap'], ticker=v['ticker'], px=v['px_adj'])
    return pool

def picks_for(F, topn, mincap):
    pool = eligible(F, mincap)
    if len(pool) < topn: return [], pool
    vr = pct_ranks({c: v['bm'] for c, v in pool.items()})
    mr = pct_ranks({c: v['mom'] for c, v in pool.items()})
    comb = {c: (vr[c] + mr[c]) / 2 for c in pool}
    return sorted(pool, key=lambda c: -comb[c])[:topn], pool

def run(formations, topn, mincap, seed=None):
    cash = 100.0; curve = []; costs = 0.0; orders = 0; yearly = []; zeroed = 0
    for F in formations:
        picks, pool = picks_for(F, topn, mincap)
        if seed is not None:
            rng = random.Random(seed * 7919 + F)
            keys = list(pool.keys()); rng.shuffle(keys); picks = keys[:topn]
        start = cash
        if not picks:
            yearly.append({'formation': F, 'pool': len(pool), 'picks': [], 'ret': 0.0,
                           'start': round(start, 2), 'end': round(cash, 2)}); continue
        w = cash / len(picks); pos = {}
        for c in picks:
            r = E.cost_rate(pool[c]['cap']); costs += w * r; orders += 1
            pos[c] = (w - w * r) / pool[c]['px']
        months = [ym(F, m) for m in range(7, 13)] + [ym(F + 1, m) for m in range(1, 7)]
        for mm in months:
            val = 0.0
            for c, sh in pos.items():
                if D.has_price_month(c, mm): val += sh * D.price(c, mm)
                else: zeroed += 1
            curve.append([mm, round(val, 2)])
        end = 0.0
        for c, sh in pos.items():
            if D.has_price_month(c, ym(F + 1, 6)):
                gross = sh * D.price(c, ym(F + 1, 6))
                r = E.cost_rate(pool[c]['cap']); costs += gross * r; orders += 1
                end += gross - gross * r
            else: zeroed += 1
        cash = end
        yearly.append({'formation': F, 'pool': len(pool),
                       'picks': [pool[c]['ticker'] for c in picks],
                       'ret': round(cash / start - 1, 4) if start else 0.0,
                       'start': round(start, 2), 'end': round(cash, 2)})
    peak = 100.0; maxdd = 0.0
    for _, v in curve: peak = max(peak, v); maxdd = max(maxdd, 1 - v / peak) if peak else 0
    spy = None
    if formations and D.spy:
        a = D.spy.get(ym(formations[0], 6)); b = D.spy.get(ym(formations[-1] + 1, 6))
        if a and b: spy = round(100 * b / a, 2)
    return {'final': round(cash, 2), 'max_dd': round(maxdd, 4), 'costs': round(costs, 2),
            'orders': orders, 'zeroed_name_months': zeroed, 'curve': curve,
            'yearly': yearly, 'spy_final_same_window': spy}

def distribution(res):
    """Per-period (formation-year) distribution + months between new highs."""
    yrs = res['yearly']
    deltas = [round(y['end'] - y['start'], 2) for y in yrs]
    rets = [y['ret'] for y in yrs]
    pos = sum(1 for r in rets if r > 0)
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; streak = max(streak, cur)
    # longest stretch between new highs, in months, from monthly curve
    peak = 100.0; last_high = -1; longest = 0
    for i, (_, v) in enumerate(res['curve']):
        if v >= peak: peak = v; last_high = i
        else: longest = max(longest, i - last_high)
    # trailing stretch if curve ends below peak counts too (already in loop)
    best_i = max(range(len(rets)), key=lambda i: rets[i]) if rets else None
    worst_i = min(range(len(rets)), key=lambda i: rets[i]) if rets else None
    return {'periods': len(rets),
            'median_period_dollars': round(statistics.median(deltas), 2) if deltas else None,
            'median_period_return': round(statistics.median(rets), 4) if rets else None,
            'share_positive': round(pos / len(rets), 3) if rets else None,
            'best_period': {'formation': yrs[best_i]['formation'], 'dollars': deltas[best_i], 'ret': rets[best_i]} if rets else None,
            'worst_period': {'formation': yrs[worst_i]['formation'], 'dollars': deltas[worst_i], 'ret': rets[worst_i]} if rets else None,
            'longest_losing_streak_periods': streak,
            'longest_stretch_between_new_highs_months': longest,
            'mean_period_dollars_secondary': round(statistics.mean(deltas), 2) if deltas else None}

ROADS = {'FULL_2017_2025': list(range(2017, 2026)),
         'CONT_era_2019_2025': list(range(2019, 2026)),
         'VAL_era_2023_2025': list(range(2023, 2026)),
         'fold_2017_2020': list(range(2017, 2021)),
         'fold_2021_2025': list(range(2021, 2026))}
V12_REF = {'FULL_2017_2025': 177.89, 'CONT_era_2019_2025': 176.83, 'VAL_era_2023_2025': 164.87}

def main():
    log = open(os.path.join(HERE, 'run.log'), 'w')
    def say(*a):
        print(*a, flush=True); print(*a, file=log, flush=True)
    out = {'family': 'vm-broad', 'program': 'v13-best-rules', 'constructed_broad_stack': True,
           'survivorship_fence': 'Universe is current-ticker-mapped EDGAR filers; delisted names that lost mapping absent. All finals are UPPER BOUNDS.',
           'my_rules': {'topn': 50, 'min_cap': 100e6, 'cadence': 'annual June-30', 'floor': None,
                        'costs': 'W04 tiered 0.10/0.25/0.75% per side by cap', 'vanished': 'ZERO'}}
    # Integrity gate: reference twin reproduces v12
    say('== INTEGRITY: reference twin (top30, cap>=50M) vs v12 published ==')
    ok = True
    for name in ['FULL_2017_2025', 'CONT_era_2019_2025', 'VAL_era_2023_2025']:
        r = run(ROADS[name], 30, 50e6)
        match = abs(r['final'] - V12_REF[name]) < 0.02
        ok = ok and match
        say(f'{name}: twin {r["final"]} vs v12 {V12_REF[name]} -> {"MATCH" if match else "MISMATCH"}')
        out.setdefault('reference_twin', {})[name] = {'final': r['final'], 'max_dd': r['max_dd']}
    if not ok:
        say('INTEGRITY FAILED — aborting'); log.close(); sys.exit(1)
    say('== MY RULES (top50, cap>=100M) ==')
    for name, forms in ROADS.items():
        r = run(forms, 50, 100e6)
        r['distribution'] = distribution(r)
        out[name] = r
        say(f'{name}: final {r["final"]} spy {r["spy_final_same_window"]} maxdd {r["max_dd"]} '
            f'costs {r["costs"]} orders {r["orders"]} zeroed {r["zeroed_name_months"]} '
            f'pools {[y["pool"] for y in r["yearly"]]}')
        twins = []
        for seed in range(1, 21):
            t = run(forms, 50, 100e6, seed=seed); twins.append(t['final'])
            say(f'  twin {seed}: {t["final"]}')
        out[name + '_placebo_finals'] = twins
        out[name + '_placebos_beaten'] = sum(1 for t in twins if r['final'] > t)
        out[name + '_placebo_median'] = round(statistics.median(twins), 2)
        say(f'  placebos beaten {out[name + "_placebos_beaten"]}/20 median {out[name + "_placebo_median"]}')
    json.dump(out, open(os.path.join(HERE, 'results.json'), 'w'), indent=1)
    say('saved results.json'); log.close()

if __name__ == '__main__': main()
