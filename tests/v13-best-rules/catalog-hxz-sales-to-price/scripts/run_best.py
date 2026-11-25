"""V13 best-rules run for catalog-hxz-sales-to-price.
Chassis frozen in ../BEST-RULES-SPEC.md BEFORE this run:
Sp exactly as catalogued (v12 construction, reused read-only),
broad universe, top 20 equal weight, annual June formation, NO floor.
"""
import json, os, sys, statistics
V12 = os.path.expanduser('~/workspace/stock-app/backtests/v12-completions/catalog-hxz-sales-to-price')
sys.path.insert(0, os.path.join(V12, 'scripts'))
import importlib.util
spec = importlib.util.spec_from_file_location('v12engine', os.path.join(V12, 'scripts', 'engine.py'))
E = importlib.util.module_from_spec(spec); spec.loader.exec_module(E)

OUT = os.path.expanduser('~/workspace/stock-app/backtests/v13-best-rules/catalog-hxz-sales-to-price')
UNI, COUNT, CAD, HOUSE = 'broad', 20, 'annual', False
SNAME = 'Sp'

def run(forms, seed=None):
    return E.run_road(forms, SNAME, UNI, COUNT, CAD, HOUSE, seed=seed)

R = E.roads()
ROADS = {k: R[k] for k in ('LONGEST', 'DECADE', 'CONT', 'VAL')}
res = {'family': 'catalog-hxz-sales-to-price',
       'chassis': 'Sp|broad|native(no floor)|annual|20',
       'spec': 'BEST-RULES-SPEC.md',
       'formations_all': E.FORMATIONS,
       'roads': {}, 'folds': {}, 'half_windows': {}, 'per_year': {},
       'pool_sizes': {f'{SNAME}|{F}|{UNI}': len(E.POOLS[(SNAME, F, UNI)]) for F in E.FORMATIONS}}

for rname, forms in ROADS.items():
    fin, curve, costs, maxdd = run(forms)
    twins = []
    for s in range(1, 21):
        tf, _, _, _ = run(forms, seed=s); twins.append(tf)
    res['roads'][rname] = {'formations': forms, 'final': fin, 'costs': costs, 'max_dd': maxdd,
                           'spy_same_window': E.spy_final(forms),
                           'placebo_finals': twins,
                           'placebos_beaten': sum(1 for t in twins if fin > t),
                           'curve': curve}
    print(rname, fin, 'spy', E.spy_final(forms), 'pb', res['roads'][rname]['placebos_beaten'], flush=True)

for fname in ('FOLD_A', 'FOLD_B'):
    forms = R[fname]
    fin, curve, costs, maxdd = run(forms)
    res['folds'][fname] = {'formations': forms, 'final': fin, 'costs': costs, 'max_dd': maxdd,
                           'spy_same_window': E.spy_final(forms), 'curve': curve}
    print(fname, forms, fin, 'spy', E.spy_final(forms), flush=True)

per_year = {}
for F in range(2016, 2026):
    fin, _, _, _ = run([F])
    spy1 = E.spy_final([F])
    per_year[str(F)] = {'final': fin, 'spy_same_window': spy1, 'beat_spy': bool(spy1 and fin > spy1)}
res['per_year'] = per_year
print('per-year beats SPY:', sum(1 for v in per_year.values() if v['beat_spy']), '/10', flush=True)

for rname, forms in ROADS.items():
    h = len(forms) // 2
    hw = {}
    for label, sub in (('H1', forms[:h] if h else forms[:1]), ('H2', forms[h:])):
        if not sub: continue
        fin, curve, costs, maxdd = run(sub)
        hw[label] = {'formations': sub, 'final': fin, 'costs': costs, 'max_dd': maxdd,
                     'spy_same_window': E.spy_final(sub), 'curve': curve}
    res['half_windows'][rname] = hw

def summarize(rets):
    if not rets: return {}
    longest_loss = 0; cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; longest_loss = max(longest_loss, cur)
    return {'periods': len(rets), 'positive': sum(1 for r in rets if r > 0),
            'median_pct': round(statistics.median(rets), 2),
            'mean_pct_secondary': round(statistics.mean(rets), 2),
            'best_pct': round(max(rets), 2), 'worst_pct': round(min(rets), 2),
            'longest_losing_streak': longest_loss, 'period_rets_pct': [round(r, 2) for r in rets]}

def monthly_dist(curve):
    vals = [100.0] + [v for _, v in curve]
    rets = [(vals[i] / vals[i-1] - 1) * 100 for i in range(1, len(vals)) if vals[i-1] > 0]
    peak = 100.0; since = 0; longest_gap = 0
    for _, v in curve:
        if v >= peak: peak = v; since = 0
        else: since += 1; longest_gap = max(longest_gap, since)
    d = summarize(rets); d['longest_months_between_highs'] = longest_gap
    return d

def annual_dist(forms):
    # chained annual returns from the road curve (12-month blocks)
    curve = res['roads'][{2016:'LONGEST',2017:'DECADE',2019:'CONT',2023:'VAL'}[forms[0]]]['curve'] if False else None
    return None

res['distribution'] = {}
for rname in ROADS:
    res['distribution'][rname] = {'monthly': monthly_dist(res['roads'][rname]['curve'])}
# annual distribution on LONGEST from per-formation-year single-year runs chained in order:
annual_rets = [per_year[str(F)]['final'] - 100.0 for F in range(2016, 2026)]
ad = summarize(annual_rets)
curve = res['roads']['LONGEST']['curve']
peak = 100.0; since = 0; longest_gap = 0
for _, v in curve:
    if v >= peak: peak = v; since = 0
    else: since += 1; longest_gap = max(longest_gap, since)
ad['longest_months_between_highs'] = longest_gap
res['distribution']['LONGEST']['annual_single_year_cohorts'] = ad
# also chained annual blocks from LONGEST curve
vals = [100.0] + [v for _, v in curve]
blocks = [(vals[i] / vals[i-12] - 1) * 100 for i in range(12, len(vals)+1, 12) if vals[i-12] > 0]
bd = summarize(blocks); bd['longest_months_between_highs'] = longest_gap
res['distribution']['LONGEST']['annual_chained_blocks'] = bd

json.dump(res, open(os.path.join(OUT, 'results.json'), 'w'), indent=1)
print('DONE', flush=True)
