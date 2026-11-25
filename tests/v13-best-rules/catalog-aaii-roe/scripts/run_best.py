#!/usr/bin/env python3
"""V13 best-rules run for catalog-aaii-roe — BEST-RULES-SPEC.md (frozen).
Single cell: published screen unchanged, rank ROE descending, top-20,
equal weight, ANNUAL June cadence, NO floor. Engine = the family's v12
engine (engine_base.py, grid section removed), identical data/costs/
zero rule. 20-seed placebos from the same passing pool. Simulation only."""
import json, os, sys, statistics
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import engine_base as E

COUNT, CADENCE, HOUSE = 20, 'annual', False

ROADS = {
    'LONGEST': list(range(2016, 2026)), 'DECADE': list(range(2017, 2026)),
    'CONT': list(range(2019, 2026)), 'VAL': list(range(2023, 2026)),
    'FOLD1': list(range(2016, 2021)), 'FOLD2': list(range(2021, 2026)),
    'LONGEST_H1': list(range(2016, 2021)), 'LONGEST_H2': list(range(2021, 2026)),
    'DECADE_H1': list(range(2017, 2022)), 'DECADE_H2': list(range(2022, 2026)),
    'CONT_H1': list(range(2019, 2023)), 'CONT_H2': list(range(2023, 2026)),
    'VAL_H1': list(range(2023, 2025)), 'VAL_H2': list(range(2025, 2026)),
}

def distribution(curve):
    vals = [100.0] + [v for _, v in curve]
    def stats(rets):
        if not rets: return {}
        run = worst = 0
        for r in rets:
            run = run + 1 if r <= 0 else 0; worst = max(worst, run)
        return {'n_periods': len(rets), 'positive': sum(1 for r in rets if r > 0),
                'share_positive': round(sum(1 for r in rets if r > 0) / len(rets), 4),
                'median_pct': round(statistics.median(rets) * 100, 2),
                'mean_pct_secondary': round(statistics.mean(rets) * 100, 2),
                'best_pct': round(max(rets) * 100, 2), 'worst_pct': round(min(rets) * 100, 2),
                'longest_losing_streak': worst,
                'period_pcts': [round(r * 100, 2) for r in rets]}
    mrets = [vals[i] / vals[i - 1] - 1 for i in range(1, len(vals)) if vals[i - 1] > 0]
    arets = [vals[i] / vals[i - 12] - 1 for i in range(12, len(vals), 12) if vals[i - 12] > 0]
    peak = vals[0]; longest = cur = 0
    for v in vals:
        if v >= peak: peak = v; cur = 0
        else: cur += 1; longest = max(longest, cur)
    return {'monthly': stats(mrets), 'annual': stats(arets),
            'longest_stretch_between_new_highs_months': int(longest)}

def main():
    out = {'family': 'catalog-aaii-roe', 'spec': 'BEST-RULES-SPEC.md (frozen 2026-11-22)',
           'cell': 'published screen | rank ROE desc | top-20 | annual June | no floor | equal weight',
           'roads': {}, 'pool_sizes': {str(k): len(v) for k, v in E.POOLS.items()}}
    for road, forms in ROADS.items():
        r = E.run_road(forms, COUNT, CADENCE, HOUSE)
        beaten = 0; pfin = []
        for s in range(1, 21):
            pr = E.run_road(forms, COUNT, CADENCE, HOUSE, seed=s)
            pfin.append(pr['final'])
            if r['final'] > pr['final']: beaten += 1
        eff = next((f for f in forms if E.POOLS.get(f)), forms[0])
        r['placebos_beaten'] = beaten; r['placebo_finals'] = pfin
        r['spy_same_window'] = E.spy_final(forms)
        r['spy_effective_window'] = E.spy_final(list(range(eff, forms[-1] + 1)))
        r['effective_start_formation'] = eff
        r['distribution'] = distribution(r['curve'])
        out['roads'][road] = r
        print(road, r['final'], 'spy', r['spy_same_window'], 'spy_eff', r['spy_effective_window'],
              'pb', beaten, 'dd', r['maxdd_pct'], 'costs', r['costs'], flush=True)
    dest = os.path.join(HERE, '..', 'results.json')
    json.dump(out, open(dest, 'w'), indent=1)
    print('saved', dest)

if __name__ == '__main__':
    main()
