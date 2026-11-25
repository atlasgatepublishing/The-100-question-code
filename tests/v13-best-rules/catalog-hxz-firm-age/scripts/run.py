"""V13 best-rules run for catalog-hxz-firm-age.
Chassis frozen in BEST-RULES-SPEC.md: Age (F - first EDGAR filing year,
exact v12 construction), broad universe, annual June formation, oldest
QUINTILE, equal weight, NO floor, tiered program costs, 20-seed placebos
sharing the chassis. Engine reused from the v12 record (read-only source,
copied into this folder)."""
import json, os, sys, math
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from engine import Family, ROADS, spy_final

V12 = os.path.expanduser('~/workspace/stock-app/backtests/v12-completions/catalog-hxz-firm-age')
first = {int(k): v for k, v in json.load(open(os.path.join(V12, 'data', 'first_filing.json'))).items()}

def age(cik, F):
    y = first.get(cik)
    return None if y is None else float(F - y)

from engine import cand
signals = {}
for F in range(2016, 2026):
    pool = {}
    for cik in cand:
        v = age(cik, F)
        if v is not None:
            pool[cik] = v
    if pool:
        signals[F] = pool

fam = Family({'Age': signals}, {'Age': 'high'})
pool_sizes = {str(F): len(fam.POOLS.get(('Age', F, 'broad'), {})) for F in range(2016, 2026)}
print('pools', pool_sizes, flush=True)

def period_dist(fam, formations):
    """Annual formation-year distribution + monthly-curve gap stats."""
    rets = []
    for F in formations:
        fin, _, _, _ = fam.run_road([F], 'Age', 'broad', 'QUINTILE', 'annual', False)
        rets.append(round(fin - 100.0, 1))
    pos = sum(1 for r in rets if r > 0)
    srt = sorted(rets)
    n = len(srt)
    med = srt[n // 2] if n % 2 else round((srt[n // 2 - 1] + srt[n // 2]) / 2, 1)
    longest_loss = 0; cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0
        longest_loss = max(longest_loss, cur)
    _, curve, _, _ = fam.run_road(formations, 'Age', 'broad', 'QUINTILE', 'annual', False)
    peak = 100.0; since = 0; longest_gap = 0
    for _, v in curve:
        if v >= peak:
            peak = v; since = 0
        else:
            since += 1; longest_gap = max(longest_gap, since)
    return {'periods': len(rets), 'positive': pos, 'share_positive_pct': round(100 * pos / len(rets), 1),
            'median_pct': med, 'best_pct': max(rets), 'worst_pct': min(rets),
            'longest_losing_streak': longest_loss, 'longest_months_between_new_highs': longest_gap,
            'year_by_year_pct': rets, 'avg_pct_secondary': round(sum(rets) / len(rets), 1)}

roads_out = {}
for rname, forms in ROADS.items():
    fin, curve, costs, maxdd = fam.run_road(forms, 'Age', 'broad', 'QUINTILE', 'annual', False)
    twins = []
    for s in range(1, 21):
        tf, _, _, _ = fam.run_road(forms, 'Age', 'broad', 'QUINTILE', 'annual', False, seed=s)
        twins.append(tf)
    roads_out[rname] = {'formations': forms, 'final': fin, 'costs': costs, 'max_dd': maxdd,
                        'spy_same_window': spy_final(forms), 'placebo_finals': twins,
                        'placebos_beaten': sum(1 for t in twins if fin > t),
                        'placebo_median': sorted(twins)[10],
                        'period_distribution_annual': period_dist(fam, forms),
                        'curve': curve}
    print(rname, fin, 'dd', maxdd, 'pb', roads_out[rname]['placebos_beaten'], 'spy', roads_out[rname]['spy_same_window'], flush=True)

res = {'family': 'catalog-hxz-firm-age', 'program': 'v13-best-rules',
       'spec': 'broad|annual|QUINTILE|no-floor', 'pool_sizes': pool_sizes, 'roads': roads_out}
json.dump(res, open(os.path.join(HERE, '..', 'results.json'), 'w'), indent=1)
print('DONE')
