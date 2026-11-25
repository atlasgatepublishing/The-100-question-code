#!/usr/bin/env python3
"""V13 best-rules run for catalog-aaii-neff — BEST-RULES-SPEC.md (frozen).
Single cell: native universe, native rulebook (NO floor), ANNUAL June
cadence, top-20 by total return ratio descending, equal weight.
Imports the v12 slice engine (this folder's patched copy) read-only data.
Simulation only."""
import json, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import engine_base as E

def S_neff_best(F, uni):
    m = E.base_pool(F, uni)
    g = F['eps_cagr5'] * 100.0
    dy = F['dy'] * 100.0
    with np.errstate(invalid='ignore', divide='ignore'):
        trr = np.where((F['pe'] > 0) & ((g + dy) > 0), (g + dy) / F['pe'], np.nan)
    m &= ~np.isnan(trr)
    m &= (F['eps_cagr5'] >= 0.07) & (F['eps_cagr5'] <= 0.20)
    return m, trr

# extra roads: folds already in E.ROADS; add half-windows
E.ROADS.update({
    'LONGEST_H1': ('2016-06', '2021-06'), 'LONGEST_H2': ('2021-06', '2026-06'),
    'DECADE_H1': ('2017-06', '2022-06'), 'DECADE_H2': ('2022-06', '2026-06'),
    'CONT_H1': ('2019-06', '2023-06'), 'CONT_H2': ('2023-06', '2026-06'),
    'VAL_H1': ('2023-06', '2025-06'), 'VAL_H2': ('2025-06', '2026-06'),
})

def distribution(curve):
    """curve: [[ym, value], ...] monthly. Per-period = monthly and
    per-formation-year (12m) stats."""
    vals = [100.0] + [v for _, v in curve]
    rets = [vals[i] / vals[i - 1] - 1 for i in range(1, len(vals)) if vals[i - 1] > 0]
    def stats(rs, label):
        if not rs: return {}
        arr = np.array(rs)
        # longest losing streak
        streak = cur = 0
        for r in rs:
            cur = cur + 1 if r < 0 else 0
            streak = max(streak, cur)
        return {'label': label, 'n_periods': len(rs),
                'share_positive': round(float((arr > 0).mean()), 4),
                'median_pct': round(float(np.median(arr)) * 100, 2),
                'best_pct': round(float(arr.max()) * 100, 2),
                'worst_pct': round(float(arr.min()) * 100, 2),
                'longest_losing_streak': int(streak),
                'mean_pct_secondary': round(float(arr.mean()) * 100, 2)}
    # longest stretch between new highs (months, on monthly curve)
    peak = -1; since = 0; longest = 0
    for v in vals:
        if v >= peak: peak = v; since = 0
        else: since += 1; longest = max(longest, since)
    yr = [vals[i] / vals[i - 12] - 1 for i in range(12, len(vals), 12) if vals[i - 12] > 0]
    d = {'monthly': stats(rets, 'monthly'), 'annual': stats(yr, 'annual'),
         'longest_stretch_between_new_highs_months': int(longest)}
    return d

def main():
    roads = ['LONGEST', 'DECADE', 'CONT', 'VAL', 'FOLD1', 'FOLD2',
             'LONGEST_H1', 'LONGEST_H2', 'DECADE_H1', 'DECADE_H2',
             'CONT_H1', 'CONT_H2', 'VAL_H1', 'VAL_H2']
    out = {'family': 'catalog-aaii-neff', 'spec': 'BEST-RULES-SPEC.md (frozen 2026-11-22)',
           'cell': 'native universe | no floor | annual June | top-20 by total return ratio desc | equal weight',
           'construction_note': 'growth = 5yr historical EPS CAGR in place of forward estimates (CONSTRUCTED, inherited from v12)',
           'roads': {}}
    for road in roads:
        cell = E.run_cell(S_neff_best, 'native', 'native', 'annual', 20, road, 'ALL')
        cell['distribution'] = distribution(cell['curve'])
        out['roads'][road] = cell
        print(road, cell['final'], 'spy', cell['spy_same_window'],
              'pb', cell['placebos_beaten'], 'dd', cell['max_dd'], flush=True)
    pools = {}
    for y in range(2016, 2026):
        F = E.features(f'{y:04d}-06')
        mask, _ = S_neff_best(F, 'native')
        pools[str(y)] = int(mask.sum())
    out['pool_sizes_june_native'] = pools
    print('pools', pools, flush=True)
    dest = os.path.join(HERE, '..', 'results.json')
    json.dump(out, open(dest, 'w'), indent=1)
    print('saved', dest)

if __name__ == '__main__':
    main()
