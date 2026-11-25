#!/usr/bin/env python3
"""Holdings-count sweep: Piotroski F-score (v12 wing, pre-registered grid).

Chassis: v11 native engine (broad EDGAR-frames universe, annual June-30
formation, top-B/M-quintile pond, F-score >= 8 qualifiers ranked by B/M
descending -- the ranking the v11 NATIVE-SPEC itself uses for its cap-30).
A "count" N caps the qualifier list at N names (highest B/M first).
ALL-ELIGIBLE = all qualifiers (the native form; v11 capped at 30, never hit:
max qualifiers in any formation = 5).

Forms:
  native: no floor, v11 tiered habitat costs (reproduces v11 $125.78 at ALL).
  house : v9 protections (episode floor -15% from episode start, checked on
          monthly closes -- the only marks this chassis has; on halt liquidate,
          sit in cash to the next annual formation, restart once; second halt
          ends the run) + program costs 0.10%/side + $0.01 per share sold.

Roads (only those the data honestly supports -- formations 2017-2025):
  FULL  2017-2025 formations (the v11 full road; DECADE-analog)
  CONT  2019-2025 formations
  VAL   2023-2025 formations
  FOLD-A 2017-2020, FOLD-B 2021-2025 (confirmation / different-years roads)

Placebos: 20 seeds per cell; each twin draws, per formation, the same number
of names the cell actually held, randomly from the same top-B/M-quintile pool
(the v11 placebo convention), same form/costs.
"""
import json, os, sys, random, importlib.util, statistics

HERE = os.path.dirname(os.path.abspath(__file__))
ENG_PATH = os.path.expanduser('~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data/engine_w04.py')
spec = importlib.util.spec_from_file_location('engine_w04', ENG_PATH)
E = importlib.util.module_from_spec(spec); spec.loader.exec_module(E)

E.D = E.Data()
D = E.D
ym = E.ym

_snap_cache = {}
def snapshot(F):
    if F not in _snap_cache: _snap_cache[F] = E.snapshot(F)
    return _snap_cache[F]

def qualifiers(F):
    """Returns (ranked qualifier ciks by B/M desc, quintile pool ciks, scores)."""
    s = snapshot(F)
    picks, pool, scores = E.piotroski_picks(s)
    return picks, list(pool.keys()), scores, s

QUAL = {}
def get_qual(F):
    if F not in QUAL: QUAL[F] = qualifiers(F)
    return QUAL[F]

COUNTS = [1, 2, 3, 5, 8, 10, 15, 20, 30, 'ALL']
def cap_count(c): return 10**9 if c == 'ALL' else c

def tiered_rate(cap): return E.cost_rate(cap)

def run(formations, count, form, picks_override=None):
    """picks_override: dict F -> list of ciks (placebos). Returns result dict."""
    cash = 100.0; curve = []; total_costs = 0.0; n_orders = 0; yearly = []
    episode = 1; ep_start = 100.0; halted_final = False; halts = []
    for F in formations:
        ranked, pool, scores, s = get_qual(F)
        if picks_override is not None:
            picks = picks_override.get(F, [])
        else:
            picks = ranked[:cap_count(count)]
        start_val = cash
        if halted_final or not picks:
            yearly.append({'formation': F, 'picks': [s[c]['ticker'] for c in picks] if not halted_final else [],
                           'n_held': 0 if halted_final else 0, 'ret': 0.0})
            for mm in [ym(F, m) for m in range(7, 13)] + [ym(F+1, m) for m in range(1, 7)]:
                curve.append([mm, round(cash, 2)])
            continue
        w = cash / len(picks); pos = {}
        for c in picks:
            if form == 'native':
                rate = tiered_rate(s[c]['cap']); cost = w * rate
            else:
                cost = w * 0.0010
            total_costs += cost; n_orders += 1
            pos[c] = (w - cost) / s[c]['px_adj']
        months = [ym(F, m) for m in range(7, 13)] + [ym(F+1, m) for m in range(1, 7)]
        floor = 0.85 * ep_start if form == 'house' else None
        halted_this_year = False
        for i, mm in enumerate(months):
            val = sum(sh * (D.price(c, mm, adj=True) or s[c]['px_adj']) for c, sh in pos.items())
            if floor is not None and val <= floor and not halted_this_year:
                # liquidate at this month's close
                end_val = 0.0
                for c, sh in pos.items():
                    p = D.price(c, mm, adj=True) or s[c]['px_adj']
                    gross = sh * p; sell_cost = gross * 0.0010 + 0.01 * sh
                    total_costs += sell_cost; n_orders += 1; end_val += gross - sell_cost
                cash = end_val; halted_this_year = True
                halts.append({'formation': F, 'month': mm, 'episode': episode, 'value': round(cash, 2)})
                curve.append([mm, round(cash, 2)])
                for mm2 in months[i+1:]:
                    curve.append([mm2, round(cash, 2)])
                if episode == 1:
                    episode = 2; ep_start = cash
                else:
                    halted_final = True
                break
            curve.append([mm, round(val, 2)])
        if halted_this_year:
            yearly.append({'formation': F, 'picks': [s[c]['ticker'] for c in picks],
                           'n_held': len(picks), 'ret': round(cash / start_val - 1, 4) if start_val else 0.0,
                           'halted': True})
            continue
        end_val = 0.0
        for c, sh in pos.items():
            p = D.price(c, ym(F+1, 6), adj=True) or s[c]['px_adj']
            gross = sh * p
            if form == 'native':
                sell_cost = gross * tiered_rate(s[c]['cap'])
            else:
                sell_cost = gross * 0.0010 + 0.01 * sh
            total_costs += sell_cost; n_orders += 1; end_val += gross - sell_cost
        cash = end_val
        yearly.append({'formation': F, 'picks': [s[c]['ticker'] for c in picks],
                       'n_held': len(picks), 'ret': round(cash / start_val - 1, 4) if start_val else 0.0})
    peak = 100.0; maxdd = 0.0
    for _, v in curve:
        peak = max(peak, v); maxdd = max(maxdd, 1 - v / peak)
    spy_ret = None
    if formations and D.spy:
        a = D.spy.get(ym(formations[0], 6)); b = D.spy.get(ym(formations[-1] + 1, 6))
        if a and b: spy_ret = round(100 * b / a, 2)
    return {'final': round(cash, 2), 'max_dd': round(maxdd, 4), 'costs': round(total_costs, 2),
            'orders': n_orders, 'curve': curve, 'yearly': yearly, 'halts': halts,
            'spy_final_same_window': spy_ret}

def placebo(formations, count, form, seed):
    override = {}
    for F in formations:
        ranked, pool, scores, s = get_qual(F)
        n = min(cap_count(count), len(ranked))
        if n == 0: override[F] = []; continue
        rng = random.Random(seed * 7919 + F)
        keys = list(pool); rng.shuffle(keys)
        override[F] = keys[:n]
    return run(formations, count, form, picks_override=override)

def period_dist(result):
    """Annual-period distribution (strategy tempo = annual) + new-high stretch
    in months from the monthly curve."""
    rets = [y['ret'] for y in result['yearly']]
    n = len(rets)
    prof = sum(1 for r in rets if r > 0)
    longest_loss = 0; cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0
        longest_loss = max(longest_loss, cur)
    # longest stretch between new highs, in months, from monthly curve (incl. start)
    vals = [100.0] + [v for _, v in result['curve']]
    peak = vals[0]; since = 0; longest = 0
    for v in vals[1:]:
        if v >= peak: peak = v; longest = max(longest, since); since = 0
        else: since += 1
    longest = max(longest, since)
    return {'periods': n, 'pct_profitable': round(100 * prof / n, 1) if n else 0.0,
            'median_period_pct': round(100 * statistics.median(rets), 2) if rets else 0.0,
            'best_period_pct': round(100 * max(rets), 2) if rets else 0.0,
            'worst_period_pct': round(100 * min(rets), 2) if rets else 0.0,
            'longest_losing_run_periods': longest_loss,
            'longest_between_new_highs_months': longest,
            'mean_period_pct_secondary': round(100 * statistics.mean(rets), 2) if rets else 0.0}

ROADS = {'FULL': list(range(2017, 2026)), 'CONT': list(range(2019, 2026)),
         'VAL': list(range(2023, 2026)), 'FOLD-A': list(range(2017, 2021)),
         'FOLD-B': list(range(2021, 2026))}

def main():
    out = {'family': 'piotroski', 'grid_counts': [str(c) for c in COUNTS],
           'native_count': 'ALL-ELIGIBLE (all F>=8 qualifiers; observed 0-5 per formation)',
           'qualifiers_per_formation': {}, 'cells': {}}
    for F in range(2017, 2026):
        ranked, pool, scores, s = get_qual(F)
        out['qualifiers_per_formation'][str(F)] = {
            'n_qualifiers': len(ranked),
            'tickers_ranked_by_BM': [s[c]['ticker'] for c in ranked],
            'quintile_pool_size': len(pool), 'scored_in_quintile': len(scores)}
        print(F, 'qualifiers', len(ranked), [s[c]['ticker'] for c in ranked], flush=True)
    for form in ('native', 'house'):
        out['cells'][form] = {}
        for road, forms_ in ROADS.items():
            out['cells'][form][road] = {}
            for c in COUNTS:
                r = run(forms_, c, form)
                twins = [placebo(forms_, c, form, seed)['final'] for seed in range(1, 21)]
                beaten = sum(1 for t in twins if r['final'] > t)
                cell = {'final': r['final'], 'max_dd': r['max_dd'], 'costs': r['costs'],
                        'orders': r['orders'], 'spy_final_same_window': r['spy_final_same_window'],
                        'placebo_finals': twins, 'placebos_beaten': beaten, 'halts': r['halts']}
                if road == 'FULL':
                    cell['curve'] = r['curve']; cell['yearly'] = r['yearly']
                    cell['period_distribution'] = period_dist(r)
                out['cells'][form][road][str(c)] = cell
                print(form, road, c, r['final'], 'beaten', beaten, '/20', flush=True)
    json.dump(out, open(os.path.join(HERE, 'results.json'), 'w'), indent=1)
    print('saved results.json', flush=True)

if __name__ == '__main__':
    main()
