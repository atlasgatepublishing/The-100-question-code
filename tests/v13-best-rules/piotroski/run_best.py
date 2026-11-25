#!/usr/bin/env python3
"""V13 best-rules Piotroski run. Spec: BEST-RULES-SPEC.md (frozen before run).
Imports the read-only v11 W04 broad chassis (Data/snapshot/costs/run) and
changes ONLY the selection rules per the frozen spec:
top-40% B/M pond, financials excluded, partial scoring (>=7 of 9 computable),
rank by (F desc, B/M desc), F>=6 gate, top 15, annual June-30, no floor.
Simulation only; public EDGAR data only."""
import json, os, sys, random, statistics
sys.path.insert(0, os.path.expanduser('~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data'))
import engine_w04 as eng

eng.D = eng.Data()
D = eng.D

def fscore_partial(v):
    """Return (score, n_computable) or (None, n) if <7 computable or core missing."""
    sigs = []
    if v['ni'] is not None and v['assets0']:
        roa = v['ni'] / v['assets0']
        sigs.append(1 if roa > 0 else 0)
        if v['cfo'] is not None:
            sigs.append(1 if v['cfo'] / v['assets0'] > roa else 0)
        if v['ni0'] is not None:
            sigs.append(1 if roa > v['ni0'] / v['assets0'] else 0)
    if v['cfo'] is not None:
        sigs.append(1 if v['cfo'] > 0 else 0)
    if v['ltd'] is not None and v['ltd0'] is not None and v['assets'] and v['assets0']:
        sigs.append(1 if v['ltd'] / v['assets'] < v['ltd0'] / v['assets0'] else 0)
    if None not in (v['ca'], v['cl'], v['ca0'], v['cl0']) and v['cl'] and v['cl0']:
        sigs.append(1 if v['ca'] / v['cl'] > v['ca0'] / v['cl0'] else 0)
    if v['shares'] is not None and v['shares0'] is not None:
        sigs.append(1 if v['shares'] <= v['shares0'] else 0)
    if v['gp'] is not None and v['gp0'] is not None and v['rev'] and v['rev0']:
        sigs.append(1 if v['gp'] / v['rev'] > v['gp0'] / v['rev0'] else 0)
    if v['rev'] and v['rev0'] and v['assets0']:
        sigs.append(1 if v['rev'] / v['assets0'] > v['rev0'] / v['assets0'] else 0)
    if len(sigs) < 7:
        return None, len(sigs)
    return sum(sigs), len(sigs)

DIAG = {}

def best_picks(s, F):
    pool_all = {c: v for c, v in s.items()
                if v['equity'] and v['cap'] and v['equity'] > 0 and v['px_adj']
                and not eng.is_fin(v['sic'])}
    bm = {c: v['equity'] / v['cap'] for c, v in pool_all.items()}
    n40 = max(1, int(len(bm) * 0.40))
    pond = sorted(bm, key=lambda c: -bm[c])[:n40]
    scored = {}
    for c in pond:
        fs, ncomp = fscore_partial(pool_all[c])
        if fs is not None:
            scored[c] = fs
    ranked = sorted(scored, key=lambda c: (-scored[c], -bm[c]))
    picks = [c for c in ranked if scored[c] >= 6][:15]
    DIAG[F] = {'pond': len(pond), 'scored': len(scored),
               'ge6': sum(1 for v in scored.values() if v >= 6),
               'picks': [pool_all[c]['ticker'] for c in picks],
               'scores': {pool_all[c]['ticker']: scored[c] for c in picks}}
    return picks, {c: pool_all[c] for c in scored}

def pf(s, F):
    return best_picks(s, F)
pf.count = 15

def run_placebo(formations, seed):
    cash = 100.0; total_costs = 0.0
    for F in formations:
        s = eng.snapshot(F)
        picks_nat, pool = best_picks(s, F)
        n = len(picks_nat)
        if n == 0:
            continue
        rng = random.Random(seed * 7919 + F)
        keys = list(pool.keys()); rng.shuffle(keys)
        picks = keys[:n]
        pos = {}
        for c in picks:
            rate = eng.cost_rate(s[c]['cap']); total_costs += (cash / n) * rate
            pos[c] = ((cash / n) - (cash / n) * rate) / s[c]['px_adj']
        end_val = 0.0
        for c, sh in pos.items():
            p = D.price(c, eng.ym(F + 1, 6), adj=True) or s[c]['px_adj']
            gross = sh * p; r = eng.cost_rate(s[c]['cap'])
            total_costs += gross * r; end_val += gross - gross * r
        cash = end_val
    return round(cash, 2)

def distribution(yearly):
    rets = [y['ret'] for y in yearly]
    if not rets:
        return {}
    pos = sum(1 for r in rets if r > 0)
    # longest losing streak & months between new highs handled from curve separately
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0
        streak = max(streak, cur)
    return {'periods': len(rets), 'pct_positive': round(100 * pos / len(rets), 1),
            'median_period_pct': round(100 * statistics.median(rets), 2),
            'best_pct': round(100 * max(rets), 2), 'worst_pct': round(100 * min(rets), 2),
            'longest_losing_streak_periods': streak,
            'avg_period_pct_secondary': round(100 * statistics.mean(rets), 2)}

def months_between_highs(curve):
    peak = -1; last_high = 0; worst = 0
    for i, (_, v) in enumerate(curve):
        if v >= peak:
            peak = v; worst = max(worst, i - last_high); last_high = i
    worst = max(worst, len(curve) - 1 - last_high)
    return worst

def main():
    roads = {'full_2017_2025': list(range(2017, 2026)),
             'cont_2019_2025': list(range(2019, 2026)),
             'val_2023_2025': list(range(2023, 2026)),
             'foldA_2017_2020': list(range(2017, 2021)),
             'foldB_2021_2025': list(range(2021, 2026))}
    res = {'family': 'piotroski-v13-best-rules', 'spec': 'BEST-RULES-SPEC.md', 'roads': {}}
    for name, forms in roads.items():
        r = eng.run(pf, forms)
        r['distribution'] = distribution(r['yearly'])
        r['months_between_new_highs'] = months_between_highs(r['curve'])
        res['roads'][name] = r
        print(name, 'final', r['final'], 'maxdd', r['max_dd'], 'spy', r['spy_final_same_window'], flush=True)
    res['diagnostics'] = {str(k): v for k, v in sorted(DIAG.items())}
    for name in ('full_2017_2025', 'cont_2019_2025', 'val_2023_2025'):
        twins = [run_placebo(roads[name], seed) for seed in range(1, 21)]
        fin = res['roads'][name]['final']
        res['roads'][name]['placebo_finals'] = twins
        res['roads'][name]['placebos_beaten'] = sum(1 for t in twins if fin > t)
        res['roads'][name]['placebo_median'] = statistics.median(twins)
        print(name, 'placebos beaten', res['roads'][name]['placebos_beaten'], '/20 median', statistics.median(twins), flush=True)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results.json')
    json.dump(res, open(out, 'w'), indent=1)
    print('saved', out)

if __name__ == '__main__':
    main()
