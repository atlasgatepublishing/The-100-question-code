"""V13 best-rules run — catalog-hxz-equity-duration.
Chassis frozen in ../BEST-RULES-SPEC.md: signal EXACTLY the v12 catalog
build (build_dur copied verbatim from slice11-work/families.py);
universe=nonfin, QUINTILE, annual, NO floor. Integrity gate: same engine
at (broad, native, annual, QUINTILE) must reproduce v12 published finals.
"""
import json, os, sys, math
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np
from engine import Family, ROADS, spy_final, cap_of, cand, w04_frame

V12DIV = os.path.expanduser('~/workspace/stock-app/backtests/v12-completions/catalog-hxz-equity-duration/data/frames')

def series(concept, suffix, famdir_frames=None, years=range(2013, 2026)):
    out = {}
    for y in years:
        if famdir_frames:
            p = os.path.join(famdir_frames, f'{concept}_{y}{suffix}.json')
            if os.path.exists(p):
                out[y] = {int(k): v for k, v in json.load(open(p)).items()}
                continue
        out[y] = w04_frame(concept, y, suffix)
    return out

NI = series('NetIncomeLoss', 'D')
EQ = series('StockholdersEquity', 'I')
DIV = series('PaymentsOfDividendsCommonStock', 'D', V12DIV)

def g(d, y, cik):
    return d.get(y, {}).get(cik)

# --- signal: verbatim copy of v12 build_dur's dur() ---
def dur(cik, F):
    roes = []
    for y in (F-3, F-2, F-1):
        ni = g(NI, y, cik); eq = g(EQ, y, cik)
        if ni is not None and eq and eq > 0: roes.append(ni/eq)
    eq0 = g(EQ, F-1, cik); mve = cap_of(cik, F)
    if not roes or not eq0 or eq0 <= 0 or not mve: return None
    roe0 = sum(roes)/len(roes)
    divs = []
    for y in (F-3, F-2, F-1):
        dv = g(DIV, y, cik); ni = g(NI, y, cik)
        if dv is not None and ni and ni > 0: divs.append(min(max(dv/ni, 0.0), 1.0))
    payout = sum(divs)/len(divs) if divs else 0.3
    r = 0.10; book = eq0; pv = 0.0; wpv = 0.0
    for t in range(1, 21):
        roe_t = r + (roe0-r)*(0.85**(t-1))
        earn = roe_t*book; div = payout*earn
        df = (1+r)**-t; pv += div*df; wpv += t*div*df
        book += earn-div
    if pv <= 0: return None
    return wpv/pv

def by_year(fn, years=range(2016, 2026)):
    out = {}
    for F in years:
        pool = {}
        for cik in cand:
            try: v = fn(cik, F)
            except Exception: v = None
            if v is not None and not (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
                pool[cik] = v
        if pool: out[F] = pool
    return out

signals = {'Dur': by_year(dur)}
fam = Family(signals, {'Dur': 'low'})

ROADMAP = {'LONGEST_2016_2025': 'LONG', 'DECADE_2017_2025': 'DECADE',
           'CONT_2019_2025': 'CONT', 'VAL_2023_2025': 'VAL'}
V12_PUBLISHED = {'LONG': 285.18, 'DECADE': 244.18, 'CONT': 200.64, 'VAL': 144.13}
CHAMP = {'LONG': 1415.62, 'DECADE': 667.35, 'CONT': 544.47, 'VAL': 288.05}

def dist_stats(curve):
    vals = [100.0] + [v for _, v in curve]
    rets = [(vals[i]/vals[i-1]-1)*100 if vals[i-1] else 0.0 for i in range(1, len(vals))]
    srt = sorted(rets); n = len(rets)
    med = srt[n//2] if n % 2 else (srt[n//2-1]+srt[n//2])/2
    longest_loss = 0; cur = 0
    for r in rets:
        cur = cur+1 if r <= 0 else 0; longest_loss = max(longest_loss, cur)
    peak = 100.0; since = 0; gap = 0
    for v in vals[1:]:
        if v >= peak: peak = v; since = 0
        else: since += 1; gap = max(gap, since)
    return {'months': n, 'median_pct': round(med, 2),
            'share_positive_pct': round(100*sum(1 for r in rets if r > 0)/n, 1),
            'best_pct': round(max(rets), 2), 'worst_pct': round(min(rets), 2),
            'longest_losing_streak_months': longest_loss,
            'longest_months_between_highs': gap,
            'avg_pct_secondary': round(sum(rets)/n, 2)}

def annual_stats(forms, uni):
    rets = []
    for F in forms:
        fin, _, _, _ = fam.run_road([F], 'Dur', uni, 'QUINTILE', 'annual', False)
        rets.append(round(fin-100.0, 1))
    srt = sorted(rets); n = len(rets)
    med = srt[n//2] if n % 2 else (srt[n//2-1]+srt[n//2])/2
    ll = 0; cur = 0
    for r in rets:
        cur = cur+1 if r <= 0 else 0; ll = max(ll, cur)
    return {'periods': n, 'positive': sum(1 for r in rets if r > 0),
            'median_pct': med, 'best_pct': max(rets), 'worst_pct': min(rets),
            'longest_losing_streak': ll, 'year_by_year_pct': rets}

out = {'family': 'catalog-hxz-equity-duration', 'spec': 'BEST-RULES-SPEC.md'}

# Integrity gate: published form must reproduce v12 to the cent
gate = {}
for rname, forms in ROADS.items():
    fin, _, _, dd = fam.run_road(forms, 'Dur', 'broad', 'QUINTILE', 'annual', False)
    gate[ROADMAP[rname]] = {'final': fin, 'v12': V12_PUBLISHED[ROADMAP[rname]],
                            'match': fin == V12_PUBLISHED[ROADMAP[rname]], 'max_dd': dd}
out['integrity_gate_broad_native_annual_quintile'] = gate
print('GATE', gate, flush=True)
assert all(v['match'] for v in gate.values()), 'INTEGRITY GATE FAILED'

# My rules: nonfin, annual, QUINTILE, no floor (house=False)
mine = {}
for rname, forms in ROADS.items():
    fin, curve, costs, dd = fam.run_road(forms, 'Dur', 'nonfin', 'QUINTILE', 'annual', False)
    twins = []
    for s in range(1, 21):
        tf, _, _, _ = fam.run_road(forms, 'Dur', 'nonfin', 'QUINTILE', 'annual', False, seed=s)
        twins.append(tf)
    mine[ROADMAP[rname]] = {'final': fin, 'costs': costs, 'max_dd': dd,
                            'spy_same_window': spy_final(forms),
                            'placebo_finals': twins,
                            'placebos_beaten': sum(1 for t in twins if fin > t),
                            'placebo_median': sorted(twins)[10],
                            'curve': curve, 'distribution_monthly': dist_stats(curve),
                            'distribution_annual': annual_stats(forms, 'nonfin')}
    print('MINE', ROADMAP[rname], fin, 'dd', dd, 'pb', mine[ROADMAP[rname]]['placebos_beaten'], flush=True)
out['my_rules_nonfin_native_annual_quintile'] = mine
out['pool_sizes'] = {f'{F}': {'broad': len(fam.POOLS.get(('Dur', F, 'broad'), {})),
                              'nonfin': len(fam.POOLS.get(('Dur', F, 'nonfin'), {})),
                              'nonfin_picks': len(fam.picks_for('Dur', F, 'nonfin', 'QUINTILE'))}
                     for F in range(2016, 2026)}
out['picks'] = {str(F): [cand[c]['ticker'] for c in fam.picks_for('Dur', F, 'nonfin', 'QUINTILE')]
                for F in range(2016, 2026)}

# Confirmation (frozen bars): only if a road beats its champion figure
conf = {}
for road, m in mine.items():
    if m['final'] > CHAMP[road]:
        forms = [k for k, v in ROADMAP.items() if v == road]
        fl = ROADS[forms[0]]
        yearly = {}
        for F in fl:
            fin, _, _, _ = fam.run_road([F], 'Dur', 'nonfin', 'QUINTILE', 'annual', False)
            yearly[str(F)] = fin
        half = len(fl)//2
        hw = {}
        for nm, sub in (('first_half', fl[:half]), ('second_half', fl[half:])):
            fin, _, _, _ = fam.run_road(sub, 'Dur', 'nonfin', 'QUINTILE', 'annual', False)
            hw[nm] = fin
        conf[road] = {'yearly_folds': yearly, 'half_windows': hw,
                      'bars': 'road final above champion on majority of yearly folds AND both half-windows (literal frozen bars)'}
out['confirmation'] = conf
json.dump(out, open(os.path.join(HERE, '..', 'results.json'), 'w'), indent=1)
print('DONE', flush=True)
