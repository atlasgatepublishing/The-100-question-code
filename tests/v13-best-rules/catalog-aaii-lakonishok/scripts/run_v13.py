#!/usr/bin/env python3
"""V13 best-rules run for catalog-aaii-lakonishok.
Spec (frozen in ../BEST-RULES-SPEC.md): S_lakonishok as published (buildable
core, revision leg omitted as in v12), native universe, NO floor (native
rulebook), ANNUAL June formation / 12-month hold, ALL passing names,
equal weight, tiered program costs, vanished->ZERO.
Reuses the v12 slice engine (engine_base.py, copy of the v12 engine with the
shareholder-yield frames path made absolute). Simulation only."""
import json, os, sys, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine_base as E

# extra half-window roads (confirmation evidence, frozen in the spec)
E.ROADS.update({
    'DECADE_H1': ('2017-06', '2021-06'), 'DECADE_H2': ('2021-06', '2026-06'),
    'CONT_H1': ('2019-06', '2022-06'), 'CONT_H2': ('2022-06', '2026-06'),
    'VAL_H1': ('2023-06', '2024-06'), 'VAL_H2': ('2024-06', '2026-06'),
})

def dist(curve, step):
    """Per-period distribution from a monthly equity curve.
    step=1 -> monthly periods; step=12 -> annual formation periods."""
    vals = [100.0] + [v for _, v in curve]
    rets = []
    for i in range(step, len(vals), step):
        if vals[i - step] > 0:
            rets.append(vals[i] / vals[i - step] - 1)
    if not rets:
        return None
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0
        streak = max(streak, cur)
    # longest stretch between new highs, in months, from the monthly curve
    peak = vals[0]; last_high = 0; longest = 0
    for i, v in enumerate(vals):
        if v >= peak:
            peak = v; longest = max(longest, i - last_high); last_high = i
    longest = max(longest, len(vals) - 1 - last_high)
    return {'n_periods': len(rets),
            'share_positive': round(sum(1 for r in rets if r > 0) / len(rets), 3),
            'median_pct': round(statistics.median(rets) * 100, 2),
            'mean_pct': round(statistics.mean(rets) * 100, 2),
            'best_pct': round(max(rets) * 100, 2),
            'worst_pct': round(min(rets) * 100, 2),
            'longest_losing_streak': streak,
            'longest_months_between_new_highs': longest,
            'period_returns_pct': [round(r * 100, 2) for r in rets]}

def main():
    fn, native_count = E.SCREENS['lakonishok']
    roads = ['LONGEST', 'DECADE', 'CONT', 'VAL', 'FOLD1', 'FOLD2',
             'DECADE_H1', 'DECADE_H2', 'CONT_H1', 'CONT_H2', 'VAL_H1', 'VAL_H2']
    out = {'family': 'catalog-aaii-lakonishok',
           'spec': 'native universe | native rulebook (NO floor) | annual June | ALL passing',
           'roads': {}}
    for road in roads:
        cell = E.run_cell(fn, 'native', 'native', 'annual', 'ALL', road, native_count)
        cell['dist_annual'] = dist(cell['curve'], 12)
        cell['dist_monthly'] = dist(cell['curve'], 1)
        out['roads'][road] = cell
        print(road, cell['final'], 'spy', cell['spy_same_window'],
              'dd', cell['max_dd'], 'pb', cell['placebos_beaten'],
              'costs', cell['costs'], flush=True)
    pools = {}
    for y in range(2016, 2026):
        F = E.features(f'{y:04d}-06')
        mask, _ = fn(F, 'native')
        pools[str(y)] = int(mask.sum())
    out['pool_sizes_june_native'] = pools
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'results.json')
    json.dump(out, open(p, 'w'), indent=1)
    print('saved', p)

if __name__ == '__main__':
    main()
