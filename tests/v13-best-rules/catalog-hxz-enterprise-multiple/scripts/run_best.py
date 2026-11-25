"""V13 best-rules run for catalog-hxz-enterprise-multiple.
Chassis frozen in ../BEST-RULES-SPEC.md BEFORE this run:
Em exactly as catalogued (v12 construction, reused read-only), nonfin
universe, top 20 equal weight, annual June formation, NO floor.
"""
import json, os, sys, math
V12 = os.path.expanduser('~/workspace/stock-app/backtests/v12-completions/catalog-hxz-enterprise-multiple')
sys.path.insert(0, os.path.join(V12, 'scripts'))
import engine as E            # v12 engine (read-only reuse)
from signals import Data, g, by_year   # v12 signals module (inserts slice11-work; engine already loaded)

OUT = os.path.expanduser('~/workspace/stock-app/backtests/v13-best-rules/catalog-hxz-enterprise-multiple')

# ---- Build Em EXACTLY as the v12 build_em (families.py) ----
D = Data(V12).x(V12)
def em(cik, F):
    oi = g(D.OI, F-1, cik); dep = g(D.Dep, F-1, cik) or 0.0
    dc = g(D.DebtCur, F-1, cik) or 0.0; ltd = g(D.LTD, F-1, cik) or 0.0; cash = g(D.Cash, F-1, cik) or 0.0
    mve = E.cap_of(cik, F)
    if oi is None or not mve: return None
    ebitda = oi + dep
    if ebitda <= 0: return None
    return (mve + dc + ltd - cash) / ebitda

signals = {'Em': by_year(em)}
fam = E.Family(signals, {'Em': 'low'})
UNI, COUNT, CAD = 'nonfin', 20, 'annual'

def run(forms, seed=None):
    return fam.run_road(forms, 'Em', UNI, COUNT, CAD, False, seed=seed)

ROADS = E.ROADS  # LONGEST_2016_2025, DECADE_2017_2025, CONT_2019_2025, VAL_2023_2025
res = {'family': 'catalog-hxz-enterprise-multiple', 'chassis': 'Em|nonfin|native(no floor)|annual|20',
       'roads': {}, 'folds': {}, 'half_windows': {}, 'per_year': {}, 'pool_sizes': {}}
for F in range(2016, 2026):
    res['pool_sizes'][str(F)] = len(fam.POOLS.get(('Em', F, UNI), {}))

for rname, forms in ROADS.items():
    fin, curve, costs, maxdd = run(forms)
    twins = []
    for s in range(1, 21):
        tf, _, _, _ = run(forms, seed=s); twins.append(tf)
    res['roads'][rname] = {'final': fin, 'costs': costs, 'max_dd': maxdd,
                           'spy_same_window': E.spy_final(forms),
                           'placebo_finals': twins,
                           'placebos_beaten': sum(1 for t in twins if fin > t),
                           'curve': curve}
    print(rname, fin, 'spy', E.spy_final(forms), 'pb', res['roads'][rname]['placebos_beaten'], flush=True)

# folds (combined windows)
for fname, forms in E.FOLDS.items():
    fin, curve, costs, maxdd = run(forms)
    res['folds'][fname] = {'final': fin, 'costs': costs, 'max_dd': maxdd, 'spy_same_window': E.spy_final(forms), 'curve': curve}
    print(fname, fin, 'spy', E.spy_final(forms), flush=True)

# per-year cohorts (for the frozen >=6/10 yearly-fold bar) + annual period stats
per_year = {}
for F in range(2016, 2026):
    fin, _, _, _ = run([F])
    spy1 = E.spy_final([F])
    per_year[str(F)] = {'final': fin, 'spy_same_window': spy1, 'beat_spy': bool(spy1 and fin > spy1)}
res['per_year'] = per_year
print('per-year beats SPY:', sum(1 for v in per_year.values() if v['beat_spy']), '/10', flush=True)

# half-windows per road
for rname, forms in ROADS.items():
    h = len(forms) // 2
    hw = {}
    for label, sub in (('H1', forms[:h] if h else forms[:1]), ('H2', forms[h:])):
        if not sub: continue
        fin, curve, costs, maxdd = run(sub)
        hw[label] = {'formations': sub, 'final': fin, 'max_dd': maxdd, 'spy_same_window': E.spy_final(sub), 'curve': curve}
    res['half_windows'][rname] = hw

# per-period distribution: annual (formation-year) + monthly, LONGEST
def dist_from_curve(curve):
    vals = [100.0] + [v for _, v in curve]
    rets = [round((vals[i+1]/vals[i]-1)*100, 2) for i in range(len(vals)-1) if vals[i] > 0]
    return rets
def summarize(rets):
    if not rets: return {}
    srt = sorted(rets); n = len(rets)
    med = srt[n//2] if n % 2 else round((srt[n//2-1]+srt[n//2])/2, 2)
    longest_loss = 0; cur = 0
    for r in rets:
        cur = cur+1 if r <= 0 else 0; longest_loss = max(longest_loss, cur)
    return {'periods': n, 'positive': sum(1 for r in rets if r > 0), 'median_pct': med,
            'best_pct': max(rets), 'worst_pct': min(rets), 'longest_losing_streak': longest_loss,
            'avg_pct_secondary': round(sum(rets)/n, 2), 'period_rets_pct': rets}
curve = res['roads']['LONGEST_2016_2025']['curve']
peak = 100.0; since = 0; longest_gap = 0
for _, v in curve:
    if v >= peak: peak = v; since = 0
    else: since += 1; longest_gap = max(longest_gap, since)
annual_rets = [round(per_year[str(F)]['final']-100.0, 2) for F in range(2016, 2026)]
res['distribution'] = {'annual_LONGEST': summarize(annual_rets),
                       'monthly_LONGEST': summarize(dist_from_curve(curve)),
                       'longest_months_between_highs_LONGEST': longest_gap}
for rname in ROADS:
    c = res['roads'][rname]['curve']
    res.setdefault('distribution_monthly_by_road', {})[rname] = summarize(dist_from_curve(c))

json.dump(res, open(os.path.join(OUT, 'results.json'), 'w'), indent=1)
print('DONE', flush=True)
