#!/usr/bin/env python3
"""V13 BEST RULES — Quality Standalone (Novy-Marx GP/A).

Frozen spec: BEST-RULES-SPEC.md in this folder. My rules converge to the
published native form by design (broad non-financial universe, GP/A with
the >1.0 artifact guard, no ROA substitution, TOP QUINTILE equal-weight,
annual June-30 formation on prior-FY data, 1-year holds, tiered habitat
costs, NO floor). Chassis: v11 W04 broad engine, READ-ONLY import.
Integrity gate: finals must reproduce v11's published native record to
the cent (FULL 376.97 / CONT 286.06 / VAL 158.49 / FOLD1 220.80 /
FOLD2 170.73) before anything is claimed.
Roads honestly supported by this stack (frames begin 2014, formations
frozen from 2017): FULL 2017-2025 formations, CONT 2019-2025, VAL
2023-2025, FOLD1 2017-2020, FOLD2 2021-2025. LONG/DECADE not supported,
not fabricated. Placebos: 20 seeds, random same-count (per-formation
quintile count) draws from the same eligible pool, same costs/form.
"""
import json, os, sys, random, statistics, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
ENG_PATH = os.path.expanduser('~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data/engine_w04.py')
spec = importlib.util.spec_from_file_location('engine_w04', ENG_PATH)
eng = importlib.util.module_from_spec(spec); spec.loader.exec_module(eng)

ROADS = {'FULL': list(range(2017, 2026)), 'CONT': list(range(2019, 2026)),
         'VAL': list(range(2023, 2026)), 'FOLD1': list(range(2017, 2021)),
         'FOLD2': list(range(2021, 2026))}
PUBLISHED = {'FULL': 376.97, 'CONT': 286.06, 'VAL': 158.49, 'FOLD1': 220.80, 'FOLD2': 170.73}

def ym(y, m): return f'{y:04d}-{m:02d}'

SNAPS = {}; RANKED = {}; POOL = {}; QUINT_N = {}; FLAGGED = {}
def prepare():
    eng.D = eng.Data()
    for F in range(2017, 2026):
        s = eng.snapshot(F); SNAPS[F] = s
        pool, flagged = eng.eligible_quality(s)
        POOL[F] = pool; FLAGGED[F] = flagged
        RANKED[F] = sorted(pool, key=lambda c: -pool[c])
        QUINT_N[F] = max(1, len(pool) // 5)
        print('formation', F, 'eligible', len(pool), 'quintile_n', QUINT_N[F],
              'flagged_gpa_gt_1', flagged, flush=True)

def picks_for(F, seed=None):
    n = QUINT_N[F]
    if seed is not None:
        rng = random.Random(seed * 7919 + F)
        keys = list(POOL[F].keys()); rng.shuffle(keys)
        return keys[:n]
    return RANKED[F][:n]

def run(formations, seed=None):
    cash = 100.0; curve = []; total_costs = 0.0; orders = 0; yearly = []
    for F in formations:
        s = SNAPS[F]; picks = picks_for(F, seed)
        start_val = cash
        if not picks:
            yearly.append({'formation': F, 'picks': [], 'ret': 0.0}); continue
        w = cash / len(picks); pos = {}
        for c in picks:
            rate = eng.cost_rate(s[c]['cap']); cost = w * rate
            total_costs += cost; orders += 1
            pos[c] = (w - cost) / s[c]['px_adj']
        months = [ym(F, m) for m in range(7, 13)] + [ym(F + 1, m) for m in range(1, 7)]
        for mm in months:
            val = sum(sh * (eng.D.price(c, mm, adj=True) or s[c]['px_adj']) for c, sh in pos.items())
            curve.append([mm, round(val, 2)])
        end_val = 0.0
        for c, sh in pos.items():
            p = eng.D.price(c, ym(F + 1, 6), adj=True) or s[c]['px_adj']
            gross = sh * p; cost = gross * eng.cost_rate(s[c]['cap'])
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
    yrs = len(formations)
    return {'final': round(cash, 2),
            'cagr': round((cash / 100) ** (1 / yrs) - 1, 4) if cash > 0 else -1,
            'max_dd': round(maxdd, 4), 'costs': round(total_costs, 2),
            'orders': orders, 'curve': curve, 'yearly': yearly,
            'spy_final_same_window': spy}

def period_stats(res):
    rets = [y['ret'] for y in res['yearly']]
    n = len(rets); prof = sum(1 for r in rets if r > 0)
    worst_run = 0; cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; worst_run = max(worst_run, cur)
    peak = 100.0; since = 0; longest = 0
    for _, v in res['curve']:
        if v >= peak: peak = v; longest = max(longest, since); since = 0
        else: since += 1
    longest = max(longest, since)
    return {'tempo': 'annual (one holding period per formation year)',
            'n_periods': n, 'pct_profitable': round(100 * prof / n, 1) if n else 0.0,
            'median_period_ret': round(statistics.median(rets), 4) if rets else 0.0,
            'best_period_ret': round(max(rets), 4) if rets else 0.0,
            'worst_period_ret': round(min(rets), 4) if rets else 0.0,
            'longest_losing_run_periods': worst_run,
            'longest_months_between_new_highs': longest,
            'average_period_ret_secondary': round(statistics.mean(rets), 4) if rets else 0.0}

def monthly_stats(res):
    curve = res['curve']; rets = []
    prev = 100.0
    for _, v in curve:
        rets.append(v / prev - 1); prev = v
    n = len(rets); prof = sum(1 for r in rets if r > 0)
    worst_run = 0; cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; worst_run = max(worst_run, cur)
    return {'tempo': 'monthly marks', 'n_periods': n,
            'pct_positive': round(100 * prof / n, 1) if n else 0.0,
            'median_pct': round(100 * statistics.median(rets), 2) if rets else 0.0,
            'best_pct': round(100 * max(rets), 2) if rets else 0.0,
            'worst_pct': round(100 * min(rets), 2) if rets else 0.0,
            'longest_losing_streak': worst_run,
            'mean_pct_secondary_average_only': round(100 * statistics.mean(rets), 2) if rets else 0.0}

def main():
    prepare()
    out = {'family': 'quality-standalone', 'program': 'v13-best-rules',
           'spec': 'BEST-RULES-SPEC.md (frozen before run)',
           'form': 'broad non-financial universe, GP/A top quintile, equal weight, annual Jun-30 formation, 1y hold, tiered habitat costs, NO floor',
           'eligible_pool_sizes': {str(F): len(POOL[F]) for F in POOL},
           'quintile_counts_by_formation': {str(F): QUINT_N[F] for F in QUINT_N},
           'flagged_gpa_gt_1_by_formation': {str(F): FLAGGED[F] for F in FLAGGED},
           'roads_not_supported': 'LONG 2010 and DECADE 2016-11-21: EDGAR frames stack begins 2014, formations frozen from 2017. Not fabricated.',
           'roads': {}}
    gate_ok = True
    for road, forms_ in ROADS.items():
        r = run(forms_)
        cell = {k: r[k] for k in ('final', 'cagr', 'max_dd', 'costs', 'orders', 'spy_final_same_window')}
        cell['period_stats_annual'] = period_stats(r)
        cell['curve'] = r['curve']; cell['yearly'] = r['yearly']
        if road == 'FULL':
            cell['period_stats_monthly'] = monthly_stats(r)
        if road in ('FULL', 'CONT', 'VAL'):
            twins = [run(forms_, seed=s)['final'] for s in range(1, 21)]
            cell['placebo_finals'] = twins
            cell['placebos_beaten'] = sum(1 for t in twins if r['final'] > t)
            cell['placebo_median'] = round(statistics.median(twins), 2)
        pub = PUBLISHED[road]
        cell['published_native_final'] = pub
        cell['integrity_gate_match'] = (r['final'] == pub)
        if r['final'] != pub: gate_ok = False
        out['roads'][road] = cell
        print(road, 'final', r['final'], 'published', pub, 'match', r['final'] == pub,
              'max_dd', r['max_dd'], 'costs', r['costs'], 'spy', r['spy_final_same_window'], flush=True)
    out['integrity_gate_all_roads_match_published'] = gate_ok
    json.dump(out, open(os.path.join(HERE, 'results.json'), 'w'), indent=1)
    print('INTEGRITY GATE:', 'PASS' if gate_ok else 'FAIL', flush=True)
    print('saved', flush=True)

if __name__ == '__main__':
    main()
