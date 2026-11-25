#!/usr/bin/env python3
"""V13 BEST-RULES run — Tiny Titans. Spec: ../BEST-RULES-SPEC.md (frozen).
Single cell: native universe | native rulebook (NO floor) | ANNUAL (June)
formations | ALL passing capped at published 25 | habitat cost override
2.50%/side for caps < $1B (every name this screen can hold is $25-250M).
Reuses the v12 slice engine copy (engine_base.py) read-only logic;
placebos: engine's 20 seeded twins, same chassis. Simulation only."""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine_base as E

# --- patches per frozen spec ---
E.SYF = os.path.join(E.FAM, '..', '..', 'v12-completions', 'shareholder-yield', 'data', 'frames')
_orig_cost = E.cost_rate
def habitat_cost(cap):
    if cap is None or (isinstance(cap, float) and np.isnan(cap)): return 0.025
    if cap < 1e9: return 0.025
    return _orig_cost(cap)
E.cost_rate = habitat_cost
# features() caches rates at first call; patch before any features() call. OK.

def dist_from_curve(curve):
    """Annual (12-month hold) period distribution from monthly curve."""
    vals = [100.0] + [v for _, v in curve]
    rets = []
    for i in range(12, len(vals), 12):
        rets.append(vals[i] / vals[i - 12] - 1)
    if not rets: return None
    pos = sum(1 for r in rets if r > 0)
    # longest losing streak (periods)
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0
        streak = max(streak, cur)
    # longest stretch between new highs (months, on monthly curve)
    peak = 100.0; since = 0; longest = 0
    for _, v in curve:
        if v >= peak: peak = v; since = 0
        else:
            since += 1; longest = max(longest, since)
    return {'n_periods': len(rets), 'periods_positive': pos,
            'median_period_pct': round(float(np.median(rets)) * 100, 1),
            'mean_period_pct_secondary': round(float(np.mean(rets)) * 100, 1),
            'best_period_pct': round(max(rets) * 100, 1),
            'worst_period_pct': round(min(rets) * 100, 1),
            'longest_losing_streak_periods': streak,
            'longest_stretch_between_new_highs_months': longest,
            'period_returns_pct': [round(r * 100, 2) for r in rets]}

def main():
    fn, native_count = E.SCREENS['tiny-titans']
    out = {'family': 'catalog-aaii-oshaughnessy-tiny-titans',
           'spec': 'native|nofloor|annual-june|all-passing-cap25|habitat-cost-2.5pct-side',
           'cost_load': '2.50% per side on all trades (caps < $1B); placebos identical',
           'roads': {}}
    pools = {}
    for y in range(2016, 2027):
        F = E.features(f'{y:04d}-06')
        mask, _ = fn(F, 'native')
        pools[str(y)] = int(mask.sum())
    out['pool_sizes_june_native'] = pools
    for road in ('LONGEST', 'DECADE', 'CONT', 'VAL', 'FOLD1', 'FOLD2'):
        cell = E.run_cell(fn, 'native', 'native', 'annual', 'NATIVE', road, native_count)
        cell['distribution_annual_periods'] = dist_from_curve(cell['curve'])
        out['roads'][road] = cell
        print(road, cell['final'], 'spy', cell['spy_same_window'], 'pb',
              cell['placebos_beaten'], 'dd', cell['max_dd'], 'costs', cell['costs'], flush=True)
    dest = os.path.join(E.FAM, 'results.json')
    json.dump(out, open(dest, 'w'), indent=1)
    print('saved', dest)

if __name__ == '__main__':
    main()
