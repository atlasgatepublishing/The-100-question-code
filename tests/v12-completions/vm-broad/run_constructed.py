#!/usr/bin/env python3
"""vm-broad v12 CONSTRUCTED: AMP value+momentum on the broad W04 EDGAR
universe (658 CIKs), long-only top-30, annual June-30 formation, vanished
prices to ZERO, W04 tiered costs, no floor, 20-seed placebos.
Spec frozen in CONSTRUCTION-SPEC.md before this run. Shared W04 data
read-only; writes only in this folder. Simulation only."""
import json, os, sys, random
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

def eligible(F):
    s = E.snapshot(F)
    pool = {}
    for c, v in s.items():
        if not v['cap'] or v['cap'] < 50e6: continue
        if not v['equity'] or v['equity'] <= 0: continue
        if not v['shares'] or not v['px_adj']: continue
        if not D.has_price_month(c, ym(F, 6)): continue
        if not D.has_price_month(c, ym(F, 5)): continue
        if not D.has_price_month(c, ym(F - 1, 6)): continue
        p_may = D.price(c, ym(F, 5)); p_jun_prev = D.price(c, ym(F - 1, 6))
        if not p_may or not p_jun_prev: continue
        bm = v['equity'] / v['cap']
        mom = p_may / p_jun_prev - 1.0
        pool[c] = dict(bm=bm, mom=mom, cap=v['cap'], ticker=v['ticker'], px=v['px_adj'])
    return s, pool

def picks_for(F):
    s, pool = eligible(F)
    if len(pool) < 30: return [], pool, s
    vr = pct_ranks({c: v['bm'] for c, v in pool.items()})
    mr = pct_ranks({c: v['mom'] for c, v in pool.items()})
    comb = {c: (vr[c] + mr[c]) / 2 for c in pool}
    return sorted(pool, key=lambda c: -comb[c])[:30], pool, s

def run(formations, seed=None):
    cash = 100.0; curve = []; costs = 0.0; orders = 0; yearly = []; zeroed = 0
    for F in formations:
        if seed is None:
            picks, pool, s = picks_for(F)
        else:
            _, pool, s = picks_for(F)
            rng = random.Random(seed * 7919 + F)
            keys = list(pool.keys()); rng.shuffle(keys); picks = keys[:30]
        start = cash
        if not picks:
            yearly.append({'formation': F, 'pool': len(pool), 'picks': [], 'ret': 0.0}); continue
        w = cash / len(picks); pos = {}
        for c in picks:
            r = E.cost_rate(pool[c]['cap']); costs += w * r; orders += 1
            pos[c] = (w - w * r) / pool[c]['px']
        months = [ym(F, m) for m in range(7, 13)] + [ym(F + 1, m) for m in range(1, 7)]
        for mm in months:
            val = 0.0
            for c, sh in pos.items():
                if D.has_price_month(c, mm): val += sh * D.price(c, mm)
                else: zeroed += 1  # vanished -> ZERO, never frozen
            curve.append([mm, round(val, 2)])
        end = 0.0
        for c, sh in pos.items():
            if D.has_price_month(c, ym(F + 1, 6)):
                gross = sh * D.price(c, ym(F + 1, 6))
                r = E.cost_rate(pool[c]['cap']); costs += gross * r; orders += 1
                end += gross - gross * r
            else: zeroed += 1  # sale month vanished -> ZERO proceeds
        cash = end
        yearly.append({'formation': F, 'pool': len(pool),
                       'picks': [pool[c]['ticker'] for c in picks],
                       'ret': round(cash / start - 1, 4) if start else 0.0})
    peak = 100.0; maxdd = 0.0
    for _, v in curve: peak = max(peak, v); maxdd = max(maxdd, 1 - v / peak) if peak else 0
    spy = None
    if formations and D.spy:
        a = D.spy.get(ym(formations[0], 6)); b = D.spy.get(ym(formations[-1] + 1, 6))
        if a and b: spy = round(100 * b / a, 2)
    return {'final': round(cash, 2), 'max_dd': round(maxdd, 4), 'costs': round(costs, 2),
            'orders': orders, 'zeroed_name_months': zeroed, 'curve': curve,
            'yearly': yearly, 'spy_final_same_window': spy}

def main():
    roads = {'FULL_2017_2025': list(range(2017, 2026)),
             'CONT_era_2019_2025': list(range(2019, 2026)),
             'VAL_era_2023_2025': list(range(2023, 2026)),
             'fold_2017_2020': list(range(2017, 2021)),
             'fold_2021_2025': list(range(2021, 2026))}
    out = {'family': 'vm-broad', 'constructed': True}
    for name, forms in roads.items():
        r = run(forms); out[name] = r
        print(name, 'final', r['final'], 'spy', r['spy_final_same_window'], 'maxdd', r['max_dd'], 'zeroed', r['zeroed_name_months'], flush=True)
        twins = []
        for seed in range(1, 21):
            t = run(forms, seed=seed); twins.append(t['final']); print(' twin', seed, t['final'], flush=True)
        out[name + '_placebo_finals'] = twins
        out[name + '_placebos_beaten'] = sum(1 for t in twins if r['final'] > t)
        import statistics; out[name + '_placebo_median'] = round(statistics.median(twins), 2)
    json.dump(out, open(os.path.join(HERE, 'results.json'), 'w'), indent=1)
    print('saved')

if __name__ == '__main__': main()
