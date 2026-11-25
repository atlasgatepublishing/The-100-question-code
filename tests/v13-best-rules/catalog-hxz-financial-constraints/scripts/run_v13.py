"""V13 best-rules run: catalog-hxz-financial-constraints.
Signal = mean percentile rank of KZ and WW (published coefficients, v12 construction),
long LOWEST (least constrained), nonfin universe, QUINTILE, annual, NO floor.
Spec frozen in ../BEST-RULES-SPEC.md before this run."""
import json, os, sys, math, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from engine import Family, ROADS, FOLDS, spy_final, cap_of, cand
from signals import Data, g, by_year

V12DIR = os.path.expanduser('~/workspace/stock-app/backtests/v12-completions/catalog-hxz-financial-constraints')
OUTDIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def cand_sic(cik):
    return cand.get(cik, {}).get('sic') or ''

# ---- build KZ and WW exactly as v12 (families.build_fc, minus fetch; frames already on disk) ----
D = Data(V12DIR).x(V12DIR)
ind_growth = {}
for y in range(2014, 2026):
    tot, totp = {}, {}
    for cik in D.Sales.get(y, {}):
        sic = str(cand_sic(cik))[:2]
        tot[sic] = tot.get(sic, 0) + D.Sales[y][cik]
        if cik in D.Sales.get(y - 1, {}): totp[sic] = totp.get(sic, 0) + D.Sales[y - 1][cik]
    ind_growth[y] = {k: (tot[k] / totp[k] - 1) for k in tot if totp.get(k)}

def kz(cik, F):
    t = F - 1
    ppe_l = g(D.PPE, t - 1, cik); ni = g(D.NI, t, cik); dep = g(D.Dep, t, cik) or 0.0
    at = g(D.Assets, t, cik); eq = g(D.Equity, t, cik); div = g(D.Div, t, cik) or 0.0
    cash = g(D.Cash, t, cik) or 0.0; ltd = g(D.LTD, t, cik) or 0.0; dc = g(D.DebtCur, t, cik) or 0.0
    mve = cap_of(cik, F)
    if not ppe_l or ni is None or not at or eq is None or not mve: return None
    cf_k = (ni + dep) / ppe_l; q = (mve + at - eq) / at; lev_d = ltd + dc
    lev = lev_d / (lev_d + eq) if (lev_d + eq) > 0 else 0.0
    return -1.001909 * cf_k + 0.2826389 * q + 3.139193 * lev - 39.3678 * (div / ppe_l) - 1.314759 * (cash / ppe_l)

def ww(cik, F):
    t = F - 1
    cfo = g(D.CFO, t, cik); at = g(D.Assets, t, cik); div = g(D.Div, t, cik)
    liab = g(D.Liab, t, cik); sales = g(D.Sales, t, cik); sales_l = g(D.Sales, t - 1, cik)
    if cfo is None or not at or liab is None or not sales or not sales_l: return None
    sic2 = str(cand_sic(cik))[:2]; ig = ind_growth.get(t, {}).get(sic2)
    if ig is None: return None
    return (-0.091 * (cfo / at) - 0.062 * (1.0 if div else 0.0) + 0.021 * (liab / at)
            - 0.044 * math.log(at) + 0.102 * ig - 0.035 * (sales / sales_l - 1))

KZ = by_year(kz); WW = by_year(ww)

def pct_rank(pool):
    srt = sorted(pool.items(), key=lambda kv: kv[1])
    n = len(srt)
    return {cik: (i / (n - 1) if n > 1 else 0.0) for i, (cik, _) in enumerate(srt)}

ENS = {}
for F in range(2016, 2026):
    a, b = KZ.get(F, {}), WW.get(F, {})
    common = set(a) & set(b)
    if not common: continue
    ra = pct_rank({c: a[c] for c in common}); rb = pct_rank({c: b[c] for c in common})
    ENS[F] = {c: (ra[c] + rb[c]) / 2.0 for c in common}
print('ENS pool sizes', {F: len(v) for F, v in ENS.items()}, flush=True)

fam = Family({'Ens': ENS}, {'Ens': 'low'})

def dist_stats(forms, uni='nonfin'):
    """Per-period (formation-year) distribution + monthly-curve gap stats for my-rules cell."""
    rets = []
    for F in forms:
        fin, _, _, _ = fam.run_road([F], 'Ens', uni, 'QUINTILE', 'annual', False)
        rets.append(round(fin - 100.0, 1))
    _, curve, _, _ = fam.run_road(forms, 'Ens', uni, 'QUINTILE', 'annual', False)
    peak = 100.0; since = 0; gap = 0
    for _, v in curve:
        if v >= peak: peak = v; since = 0
        else: since += 1; gap = max(gap, since)
    srt = sorted(rets); n = len(rets)
    med = srt[n // 2] if n % 2 else round((srt[n // 2 - 1] + srt[n // 2]) / 2, 1)
    cur = 0; streak = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; streak = max(streak, cur)
    return {'periods': n, 'positive': sum(1 for r in rets if r > 0), 'median_pct': med,
            'best_pct': max(rets), 'worst_pct': min(rets), 'longest_losing_streak': streak,
            'longest_months_between_highs': gap, 'year_by_year_pct': rets,
            'avg_pct_secondary': round(sum(rets) / n, 1)}

def diagnostic():
    """Size-in-a-trench-coat diagnostic: picks vs pool caps per formation (nonfin)."""
    out = {}
    for F in range(2016, 2026):
        pool = fam.POOLS.get(('Ens', F, 'nonfin'), {})
        if not pool: continue
        picks = fam.picks_for('Ens', F, 'nonfin', 'QUINTILE')
        caps = {c: pool[c]['cap'] for c in pool if pool[c]['cap']}
        if not caps or not picks: continue
        srt = sorted(caps.values()); thr = srt[int(0.8 * (len(srt) - 1))]
        pcaps = [caps[c] for c in picks if c in caps]
        out[F] = {'pool_n': len(pool), 'picks_n': len(picks),
                  'pool_median_cap_bn': round(statistics.median(caps.values()) / 1e9, 2),
                  'picks_median_cap_bn': round(statistics.median(pcaps) / 1e9, 2) if pcaps else None,
                  'share_picks_in_largest_quintile': round(sum(1 for v in pcaps if v >= thr) / len(pcaps), 3) if pcaps else None}
    return out

results = {'family': 'catalog-hxz-financial-constraints', 'program': 'v13-best-rules',
           'spec': 'BEST-RULES-SPEC.md', 'cell': 'Ens(KZ+WW rank-avg)|nonfin|native(no floor)|annual|QUINTILE',
           'roads': {}, 'diagnostic_size': diagnostic()}
for rname, forms in ROADS.items():
    fin, curve, costs, maxdd = fam.run_road(forms, 'Ens', 'nonfin', 'QUINTILE', 'annual', False)
    twins = []
    for s in range(1, 21):
        tf, _, _, _ = fam.run_road(forms, 'Ens', 'nonfin', 'QUINTILE', 'annual', False, seed=s)
        twins.append(tf)
    results['roads'][rname] = {'final': fin, 'costs': costs, 'max_dd': maxdd,
                               'spy_same_window': spy_final(forms),
                               'placebo_finals': twins, 'placebos_beaten': sum(1 for t in twins if fin > t),
                               'curve': curve, 'distribution': dist_stats(forms)}
    print(rname, fin, 'spy', spy_final(forms), 'pb', results['roads'][rname]['placebos_beaten'], 'dd', maxdd, flush=True)

# Confirmation trigger check vs champion prints (frozen bars in spec)
CHAMP = {'LONGEST_2016_2025': 1415.62, 'DECADE_2017_2025': 667.35, 'CONT_2019_2025': 544.47, 'VAL_2023_2025': 288.05}
triggered = [r for r in ROADS if results['roads'][r]['final'] > CHAMP[r]]
results['champion_trigger_roads'] = triggered
if triggered:
    conf = {}
    for rname in triggered:
        forms = ROADS[rname]
        half = len(forms) // 2
        halves = {'H1': forms[:half], 'H2': forms[half:]}
        entry = {}
        for fname, fforms in list(FOLDS.items()) + list(halves.items()):
            fin, _, _, dd = fam.run_road(fforms, 'Ens', 'nonfin', 'QUINTILE', 'annual', False)
            twins = [fam.run_road(fforms, 'Ens', 'nonfin', 'QUINTILE', 'annual', False, seed=s)[0] for s in range(1, 21)]
            entry[fname] = {'final': fin, 'spy_same_window': spy_final(fforms),
                            'placebos_beaten': sum(1 for t in twins if fin > t), 'max_dd': dd}
        conf[rname] = entry
    results['confirmation'] = conf
    print('CONFIRMATION RUN', json.dumps(conf), flush=True)

json.dump(results, open(os.path.join(OUTDIR, 'results.json'), 'w'), indent=1)
print('DONE', flush=True)
