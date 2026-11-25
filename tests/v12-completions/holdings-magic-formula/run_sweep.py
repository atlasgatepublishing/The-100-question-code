#!/usr/bin/env python3
"""v12 HOLDINGS-COUNT SWEEP — Magic Formula (Greenblatt).

Reuses the v11 W04 broad-universe engine (READ-ONLY import from
v11-native-rules/_w04_broad_data/engine_w04.py) for data + snapshots +
the exact v11 Magic Formula scoring. This script adds only:
  - variable holdings counts (pre-registered grid 1,2,3,5,8,10,15,20,30,ALL)
  - a HOUSE (v9) form: flat program costs 0.10%/side + $0.01/sell order,
    plain -15% floor from episode start checked at monthly marks,
    one restart after a 90-day sit-out, second halt ends the run
  - the NATIVE form exactly as v11: tiered habitat costs, NO floor
  - 20-seed placebos per cell (random N from the same eligible pool)
Roads (formations June 30, 1-year holds, monthly marks — the only roads
this data stack honestly supports; frames begin 2014, v11 froze 2017):
  FULL  formations 2017-2025 (2017->2026)   CONT formations 2019-2025
  VAL   formations 2023-2025               FOLD1 2017-2020, FOLD2 2021-2025
  (folds = Terry's CONFIRMATION RULE re-run on different years)
LONG 2010 is NOT supported by this stack and is not fabricated.
"""
import json, os, sys, random, statistics, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
ENG_PATH = os.path.expanduser('~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data/engine_w04.py')
spec = importlib.util.spec_from_file_location('engine_w04', ENG_PATH)
eng = importlib.util.module_from_spec(spec); spec.loader.exec_module(eng)

COUNTS = [1, 2, 3, 5, 8, 10, 15, 20, 30, 'ALL']
ROADS = {'FULL': list(range(2017, 2026)), 'CONT': list(range(2019, 2026)),
         'VAL': list(range(2023, 2026)), 'FOLD1': list(range(2017, 2021)),
         'FOLD2': list(range(2021, 2026))}

def ym(y, m): return f'{y:04d}-{m:02d}'

# ---------- precompute snapshots, rankings, pools once ----------
SNAPS = {}; RANKED = {}; POOL = {}; SCORED_N = {}
def prepare():
    eng.D = eng.Data()
    for F in range(2017, 2026):
        s = eng.snapshot(F); SNAPS[F] = s
        pool = eng.eligible_magic(s); POOL[F] = pool
        scored = {}
        for c, v in pool.items():
            ebit = v['opinc'] + (v['interest'] or 0)
            ev = v['cap'] + (v['ltd'] or 0) - (v['cash'] or 0)
            capital = (v['ca'] - (v['cash'] or 0)) - v['cl'] + v['ppe']
            if ev <= 0 or capital <= 0: continue
            scored[c] = (ebit / ev, ebit / capital)
        ey = sorted(scored, key=lambda c: -scored[c][0])
        rc = sorted(scored, key=lambda c: -scored[c][1])
        eyi = {c: i for i, c in enumerate(ey)}; rci = {c: i for i, c in enumerate(rc)}
        RANKED[F] = sorted(scored, key=lambda c: eyi[c] + rci[c])
        SCORED_N[F] = len(scored)
        print('formation', F, 'eligible', len(pool), 'scored', len(scored), flush=True)

def picks_for(F, count, seed=None):
    if seed is not None:
        rng = random.Random(seed * 7919 + F)
        keys = list(POOL[F].keys()); rng.shuffle(keys)
        n = len(RANKED[F]) if count == 'ALL' else min(count, len(keys))
        return keys[:n]
    if count == 'ALL': return list(RANKED[F])
    return RANKED[F][:count]

def run(formations, count, form, seed=None):
    """form: 'native' (tiered costs, no floor) or 'house' (flat 0.10%/side
    + $0.01/sell, v9 plain -15% floor / one restart / second halt ends)."""
    cash = 100.0; curve = []; total_costs = 0.0; orders = 0; yearly = []
    halts = 0; ended = False; anchor = 100.0; skip_until = None  # ym string
    for F in formations:
        if ended:
            for mm in [ym(F, m) for m in range(7, 13)] + [ym(F + 1, m) for m in range(1, 7)]:
                curve.append([mm, round(cash, 2)])
            yearly.append({'formation': F, 'picks': [], 'ret': 0.0, 'note': 'run ended (2nd halt)'})
            continue
        if skip_until and ym(F, 6) < skip_until:
            for mm in [ym(F, m) for m in range(7, 13)] + [ym(F + 1, m) for m in range(1, 7)]:
                curve.append([mm, round(cash, 2)])
            yearly.append({'formation': F, 'picks': [], 'ret': 0.0, 'note': '90-day sit-out'})
            continue
        s = SNAPS[F]; picks = picks_for(F, count, seed)
        start_val = cash; anchor = cash
        if not picks:
            yearly.append({'formation': F, 'picks': [], 'ret': 0.0}); continue
        w = cash / len(picks); pos = {}
        for c in picks:
            if form == 'native':
                rate = eng.cost_rate(s[c]['cap']); cost = w * rate
            else:
                cost = w * 0.0010
            total_costs += cost; orders += 1
            pos[c] = (w - cost) / s[c]['px_adj']
        months = [ym(F, m) for m in range(7, 13)] + [ym(F + 1, m) for m in range(1, 7)]
        halted = False
        for i, mm in enumerate(months):
            val = sum(sh * (eng.D.price(c, mm, adj=True) or s[c]['px_adj']) for c, sh in pos.items())
            if form == 'house' and val <= 0.85 * anchor:
                # liquidate at this month's marks
                end_val = 0.0
                for c, sh in pos.items():
                    p = eng.D.price(c, mm, adj=True) or s[c]['px_adj']
                    gross = sh * p; cost = gross * 0.0010 + 0.01
                    total_costs += cost; orders += 1; end_val += gross - cost
                cash = end_val; halts += 1; halted = True
                curve.append([mm, round(cash, 2)])
                for mm2 in months[i + 1:]:
                    curve.append([mm2, round(cash, 2)])
                # 90-day sit-out from halt month
                hy, hm = int(mm[:4]), int(mm[5:7]); hm += 3
                if hm > 12: hm -= 12; hy += 1
                skip_until = ym(hy, hm)
                if halts >= 2: ended = True
                break
            curve.append([mm, round(val, 2)])
        if halted:
            yearly.append({'formation': F, 'picks': [s[c]['ticker'] for c in picks],
                           'ret': round(cash / start_val - 1, 4) if start_val else 0.0, 'halted': True})
            continue
        end_val = 0.0
        for c, sh in pos.items():
            p = eng.D.price(c, ym(F + 1, 6), adj=True) or s[c]['px_adj']
            gross = sh * p
            if form == 'native':
                cost = gross * eng.cost_rate(s[c]['cap'])
            else:
                cost = gross * 0.0010 + 0.01
            total_costs += cost; orders += 1; end_val += gross - cost
        cash = end_val
        yearly.append({'formation': F, 'picks': [s[c]['ticker'] for c in picks],
                       'ret': round(cash / start_val - 1, 4) if start_val else 0.0})
    peak = 100.0; maxdd = 0.0
    for _, v in curve:
        peak = max(peak, v); maxdd = max(maxdd, 1 - v / peak)
    spy = None
    if formations and eng.D.spy:
        a = eng.D.spy.get(ym(formations[0], 6)); b = eng.D.spy.get(ym(formations[-1] + 1, 6))
        if a and b: spy = round(100 * b / a, 2)
    return {'final': round(cash, 2), 'max_dd': round(maxdd, 4), 'costs': round(total_costs, 2),
            'orders': orders, 'halts': halts, 'curve': curve, 'yearly': yearly,
            'spy_final_same_window': spy}

def period_stats(res):
    """Annual-tempo distribution from yearly returns + monthly curve."""
    rets = [y['ret'] for y in res['yearly']]
    n = len(rets); prof = sum(1 for r in rets if r > 0)
    med = statistics.median(rets) if rets else 0.0
    avg = statistics.mean(rets) if rets else 0.0
    worst_run = 0; cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; worst_run = max(worst_run, cur)
    # longest stretch between new highs, in months, from curve (start $100)
    peak = 100.0; since = 0; longest = 0
    for _, v in res['curve']:
        if v >= peak: peak = v; longest = max(longest, since); since = 0
        else: since += 1
    longest = max(longest, since)
    return {'n_periods': n, 'pct_profitable': round(100 * prof / n, 1) if n else 0.0,
            'median_period_ret': round(med, 4), 'best_period_ret': round(max(rets), 4) if rets else 0.0,
            'worst_period_ret': round(min(rets), 4) if rets else 0.0,
            'longest_losing_run_periods': worst_run,
            'longest_months_between_new_highs': longest,
            'average_period_ret_secondary': round(avg, 4)}

def main():
    prepare()
    out = {'family': 'magic-formula', 'sweep': 'v12 holdings-count',
           'counts_grid': [str(c) for c in COUNTS],
           'scored_pool_sizes': {str(F): SCORED_N[F] for F in SCORED_N},
           'eligible_pool_sizes': {str(F): len(POOL[F]) for F in POOL},
           'cells': {}}
    for form in ('native', 'house'):
        out['cells'][form] = {}
        for count in COUNTS:
            key = str(count); out['cells'][form][key] = {}
            for road, forms_ in ROADS.items():
                r = run(forms_, count, form)
                cell = {k: r[k] for k in ('final', 'max_dd', 'costs', 'orders', 'halts', 'spy_final_same_window')}
                if road in ('FULL', 'CONT', 'VAL') and count != 'ALL':
                    twins = [run(forms_, count, form, seed=s)['final'] for s in range(1, 21)]
                    cell['placebo_finals'] = twins
                    cell['placebos_beaten'] = sum(1 for t in twins if r['final'] > t)
                    cell['placebo_median'] = round(statistics.median(twins), 2)
                out['cells'][form][key][road] = cell
                if road == 'FULL':
                    out['cells'][form][key]['_full_detail'] = {'curve': r['curve'], 'yearly': r['yearly'],
                                                               'period_stats': period_stats(r)}
                print(form, key, road, r['final'], 'halts', r['halts'], flush=True)
    json.dump(out, open(os.path.join(HERE, 'results.json'), 'w'), indent=1)
    print('saved', flush=True)

if __name__ == '__main__':
    main()
