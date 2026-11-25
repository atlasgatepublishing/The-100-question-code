import sys, os, json, math
HERE = os.path.dirname(os.path.abspath(__file__)); FAM = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from engine import Family, ROADS, FOLDS, spy_final
from signals import Data, g, by_year
from engine import cap_of

D = Data(FAM)
def ebp(cik, F):
    eq = g(D.Equity, F-1, cik); liab = g(D.Liab, F-1, cik); cash = g(D.Cash, F-1, cik) or 0.0
    mve = cap_of(cik, F)
    if not eq or liab is None or not mve: return None
    nd = liab - cash; den = mve + nd
    return (eq + nd) / den if den > 0 else None

signals = {'Ebp': by_year(ebp)}
fam = Family(signals, {'Ebp': 'high'})

def road(forms, uni, count, seed=None):
    return fam.run_road(forms, 'Ebp', uni, count, 'annual', False, seed=seed)

def block(forms):
    fin, curve, costs, dd = road(forms, 'nonfin', 10)
    twins = [road(forms, 'nonfin', 10, seed=s)[0] for s in range(1, 21)]
    pub, pcurve, pcosts, pdd = road(forms, 'broad', 'QUINTILE')
    ptwins = [road(forms, 'broad', 'QUINTILE', seed=s)[0] for s in range(1, 21)]
    return {'my': {'final': fin, 'costs': costs, 'max_dd': dd, 'curve': curve,
                   'placebo_finals': twins, 'placebos_beaten': sum(1 for t in twins if fin > t)},
            'published': {'final': pub, 'costs': pcosts, 'max_dd': pdd, 'curve': pcurve,
                          'placebo_finals': ptwins, 'placebos_beaten': sum(1 for t in ptwins if pub > t)},
            'spy_same_window': spy_final(forms)}

out = {'family': 'catalog-hxz-enterprise-book-to-price',
       'chassis': 'Ebp | nonfin | annual June, FY<=F-1 | top10 equal-weight buy-and-hold drift | NO floor | tiered program costs',
       'published_form': 'Ebp | broad | annual | QUINTILE | native (no floor)',
       'roads': {}}
for name, forms in ROADS.items():
    out['roads'][name] = block(forms)
    print(name, 'my', out['roads'][name]['my']['final'], 'pub', out['roads'][name]['published']['final'],
          'spy', out['roads'][name]['spy_same_window'], flush=True)

# per-period distribution on LONGEST, my chassis (annual formation years)
rets = []
for F in ROADS['LONGEST_2016_2025']:
    f, _, _, _ = road([F], 'nonfin', 10); rets.append(round(f - 100.0, 1))
srt = sorted(rets); n = len(rets)
med = srt[n//2] if n % 2 else round((srt[n//2-1] + srt[n//2]) / 2, 1)
cur = ll = 0
for r in rets:
    cur = cur + 1 if r <= 0 else 0; ll = max(ll, cur)
curve = out['roads']['LONGEST_2016_2025']['my']['curve']
peak = 100.0; since = gap = 0
for _, v in curve:
    if v >= peak: peak = v; since = 0
    else: since += 1; gap = max(gap, since)
out['period_stats_my_LONGEST'] = {'periods': n, 'positive': sum(1 for r in rets if r > 0), 'median_pct': med,
    'best_pct': max(rets), 'worst_pct': min(rets), 'longest_losing_streak': ll,
    'longest_months_between_highs': gap, 'year_by_year_pct': rets,
    'avg_pct_secondary': round(sum(rets) / len(rets), 1)}

# confirmation (only meaningful if a road beats champion V+M for that road)
CHAMP = {'LONGEST_2016_2025': 1415.62, 'DECADE_2017_2025': 667.35, 'CONT_2019_2025': 544.47, 'VAL_2023_2025': 288.05}
beats = [r for r in ROADS if out['roads'][r]['my']['final'] > CHAMP[r]]
out['champion_beats'] = beats
if beats:
    conf = {}
    for nm, forms in FOLDS.items():
        f, _, _, _ = road(forms, 'nonfin', 10)
        tw = [road(forms, 'nonfin', 10, seed=s)[0] for s in range(1, 21)]
        conf[nm] = {'final': f, 'spy_same_window': spy_final(forms), 'placebos_beaten': sum(1 for t in tw if f > t)}
    for r in beats:
        forms = ROADS[r]; mid = forms[len(forms)//2]
        halves = {}
        for hn, hf in {'H1': forms[:len(forms)//2], 'H2': forms[len(forms)//2:]}.items():
            f, _, _, _ = road(hf, 'nonfin', 10)
            halves[hn] = {'formations': hf, 'final': f, 'spy_same_window': spy_final(hf)}
        conf[r + '_halves'] = halves
    out['confirmation'] = conf
json.dump(out, open(os.path.join(FAM, 'results.json'), 'w'), indent=1)
print('DONE beats:', beats)
