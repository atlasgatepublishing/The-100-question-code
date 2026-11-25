#!/usr/bin/env python3
"""V13 best-rules run for catalog-aaii-oshaughnessy.
Chassis frozen in BEST-RULES-SPEC.md: native universe, ANNUAL June formation,
NO floor (native rulebook), top-10 equal weight, program tiered costs,
20-seed placebos (engine series 1..20). Carrier = Growth II; the other four
sub-screens run under the identical template as secondary context.
Reuses the v12 engine copy in this folder (data layer = W04 stack, read-only).
"""
import json, os, sys, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E

HERE = os.path.dirname(os.path.abspath(__file__))
FAM = os.path.join(HERE, '..')

def dist(curve):
    """Per-period distribution from monthly equity curve [[ym, val], ...]."""
    vals = [100.0] + [v for _, v in curve]
    mrets = [vals[i] / vals[i - 1] - 1 for i in range(1, len(vals)) if vals[i - 1] > 0]
    arets = []
    for i in range(12, len(vals), 12):
        if vals[i - 12] > 0:
            arets.append(vals[i] / vals[i - 12] - 1)
    def block(rets, label):
        if not rets:
            return {'label': label, 'n': 0}
        pos = sum(1 for r in rets if r > 0)
        streak = cur = 0
        for r in rets:
            cur = cur + 1 if r <= 0 else 0
            streak = max(streak, cur)
        return {'label': label, 'n': len(rets), 'n_positive': pos,
                'median_pct': round(statistics.median(rets) * 100, 1),
                'best_pct': round(max(rets) * 100, 1),
                'worst_pct': round(min(rets) * 100, 1),
                'longest_losing_streak': streak,
                'mean_pct_secondary': round(statistics.mean(rets) * 100, 1)}
    peak = 100.0; since_high = 0; max_since = 0
    for v in vals[1:]:
        if v >= peak:
            peak = v; since_high = 0
        else:
            since_high += 1; max_since = max(max_since, since_high)
    return {'monthly': block(mrets, 'monthly'), 'annual': block(arets, 'annual'),
            'longest_months_between_new_highs': max_since}

def run_screen(key, count=10):
    fn, native_count = E.SCREENS[key]
    out = {}
    for road in ('LONGEST', 'DECADE', 'CONT', 'VAL', 'FOLD1', 'FOLD2'):
        cell = E.run_cell(fn, 'native', 'native', 'annual', count, road, native_count)
        if cell is None:
            out[road] = None; continue
        cell = dict(cell)
        cell['distribution'] = dist(cell['curve'])
        out[road] = cell
        print(key, road, cell['final'], 'spy', cell['spy_same_window'],
              'pb', cell['placebos_beaten'], 'dd', cell['max_dd'], flush=True)
    pools = {}
    for y in range(2016, 2026):
        F = E.features(f'{y:04d}-06')
        mask, _ = fn(F, 'native')
        pools[str(y)] = int(mask.sum())
    return {'native_count': native_count, 'count_run': count,
            'pool_sizes_june_native': pools, 'roads': out}

def main():
    res = {'family': 'catalog-aaii-oshaughnessy', 'program': 'v13-best-rules',
           'chassis': 'native universe | annual June | no floor | top-10 | tiered costs',
           'carrier': 'oshaughnessy-growth2',
           'screens': {}}
    res['screens']['oshaughnessy-growth2'] = run_screen('oshaughnessy-growth2', 10)
    for key in ('oshaughnessy-value', 'oshaughnessy-scgv', 'oshaughnessy-gml', 'oshaughnessy-allcap'):
        res['screens'][key] = run_screen(key, 10)
    with open(os.path.join(FAM, 'results.json'), 'w') as f:
        json.dump(res, f, indent=1)
    print('saved results.json')

if __name__ == '__main__':
    main()
