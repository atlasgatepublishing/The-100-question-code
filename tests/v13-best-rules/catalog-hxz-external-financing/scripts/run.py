"""V13 best-rules run: catalog-hxz-external-financing.
Chassis frozen in BEST-RULES-SPEC.md: Nxf (exact v12/catalog construction),
nonfin universe, annual June formation, QUINTILE, no floor, program costs.
Reuses the v12 engine/signals/families code read-only; v12 data frames are
read from the v12 folder (all frame files already exist there, so the
fetcher writes nothing)."""
import json, os, sys, math
sys.path.insert(0, os.path.expanduser('~/workspace/slice11-work'))
from engine import Family, ROADS, FOLDS, spy_final
from families import build_xf

V12 = os.path.expanduser('~/workspace/stock-app/backtests/v12-completions/catalog-hxz-external-financing')
OUT = os.path.expanduser('~/workspace/stock-app/backtests/v13-best-rules/catalog-hxz-external-financing')

signals, directions, primary, _sec = build_xf(V12)
assert primary == 'Nxf'
fam = Family(signals, directions)

def run(forms, uni, count='QUINTILE', seed=None):
    fin, curve, costs, maxdd = fam.run_road(forms, 'Nxf', uni, count, 'annual', False, seed=seed)
    return fin, curve, costs, maxdd

def monthly_dist(curve):
    vals = [100.0] + [v for _, v in curve]
    rets = [(vals[i+1]/vals[i]-1)*100 if vals[i] else 0.0 for i in range(len(vals)-1)]
    srt = sorted(rets); n = len(rets)
    med = srt[n//2] if n % 2 else (srt[n//2-1]+srt[n//2])/2
    longest_loss = cur = 0
    for r in rets:
        cur = cur+1 if r <= 0 else 0; longest_loss = max(longest_loss, cur)
    peak = 100.0; since = 0; gap = 0
    for v in vals[1:]:
        if v >= peak: peak = v; since = 0
        else: since += 1; gap = max(gap, since)
    return {'months': n, 'median_pct': round(med, 2), 'share_positive': round(sum(1 for r in rets if r > 0)/n, 3),
            'best_pct': round(max(rets), 2), 'worst_pct': round(min(rets), 2),
            'longest_losing_streak_months': longest_loss, 'longest_months_between_highs': gap,
            'avg_pct_secondary': round(sum(rets)/n, 2)}

def annual_dist(forms, uni):
    rets = []
    for F in forms:
        fin, _, _, _ = run([F], uni)
        rets.append(round(fin-100.0, 1))
    srt = sorted(rets); n = len(rets)
    med = srt[n//2] if n % 2 else round((srt[n//2-1]+srt[n//2])/2, 1)
    longest_loss = cur = 0
    for r in rets:
        cur = cur+1 if r <= 0 else 0; longest_loss = max(longest_loss, cur)
    return {'periods': n, 'positive': sum(1 for r in rets if r > 0), 'median_pct': med,
            'best_pct': max(rets), 'worst_pct': min(rets), 'longest_losing_streak': longest_loss,
            'year_by_year_pct': rets, 'avg_pct_secondary': round(sum(rets)/n, 1)}

res = {'family': 'catalog-hxz-external-financing', 'spec': 'BEST-RULES-SPEC.md',
       'chassis': 'Nxf | nonfin | native (no floor) | annual | QUINTILE',
       'roads': {}, 'published_form_v12': {}, 'pool_sizes': {}}
for F in range(2016, 2026):
    res['pool_sizes'][str(F)] = len(fam.POOLS[('Nxf', F, 'nonfin')])

# integrity gate: reproduce v12 published form (broad quintile) exactly
gate = {}
for rname, forms in ROADS.items():
    fin, curve, costs, maxdd = run(forms, 'broad')
    gate[rname] = {'final': fin, 'max_dd': maxdd, 'costs': costs, 'curve': curve}
    res['published_form_v12'][rname] = {'final': fin, 'max_dd': maxdd, 'costs': costs,
                                       'spy_same_window': spy_final(forms)}
print('GATE broad quintile:', {r: gate[r]['final'] for r in ROADS}, flush=True)

for rname, forms in ROADS.items():
    fin, curve, costs, maxdd = run(forms, 'nonfin')
    twins = []
    for s in range(1, 21):
        tf, _, _, _ = run(forms, 'nonfin', seed=s); twins.append(tf)
    res['roads'][rname] = {'final': fin, 'costs': costs, 'max_dd': maxdd,
                           'spy_same_window': spy_final(forms),
                           'placebo_finals': twins,
                           'placebos_beaten': sum(1 for t in twins if fin > t),
                           'curve': curve,
                           'monthly_distribution': monthly_dist(curve),
                           'annual_distribution': annual_dist(forms, 'nonfin')}
    print(rname, fin, 'dd', maxdd, 'pb', res['roads'][rname]['placebos_beaten'], flush=True)

json.dump(res, open(os.path.join(OUT, 'results.json'), 'w'), indent=1)
print('DONE', flush=True)
