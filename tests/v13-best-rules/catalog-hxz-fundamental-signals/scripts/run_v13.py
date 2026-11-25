"""V13 best-rules run: dSi alone, broad, native (no floor), annual, QUINTILE.
Signal construction EXACTLY as v12 (slice11 families.build_fs dSi component).
Engine reused read-only from v12 (copied into this folder's scripts/)."""
import json, os, sys, math, statistics
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.expanduser('~/workspace/slice11-work'))
from engine import Family, ROADS, FOLDS, spy_final
from signals import Data, g, by_year

V12 = os.path.expanduser('~/workspace/stock-app/backtests/v12-completions/catalog-hxz-fundamental-signals')
OUT = os.path.dirname(HERE)

def build_dsi():
    D = Data(V12).x(V12)
    def growth(S, cik, t):
        a = g(S, t, cik); b = g(S, t-1, cik)
        if a is None or not b: return None
        return a / b - 1
    def dsi(cik, F):
        t = F - 1
        gs = growth(D.Sales, cik, t)
        if gs is None: return None
        gi = growth(D.Inv, cik, t)
        return None if gi is None else gs - gi
    return {'dSi': by_year(dsi)}, {'dSi': 'high'}

def dist_from_curve(curve):
    # monthly period returns from equity curve (prepend $100 start)
    vals = [100.0] + [v for _, v in curve]
    rets = [vals[i] / vals[i-1] - 1 for i in range(1, len(vals)) if vals[i-1] > 0]
    return period_stats(rets, curve)

def annual_stats(fam, formations):
    rets = []
    for F in formations:
        fin, _, _, _ = fam.run_road([F], 'dSi', 'broad', 'QUINTILE', 'annual', False)
        rets.append(round(fin - 100.0, 2))
    return rets

def period_stats(rets, curve):
    if not rets: return {}
    srt = sorted(rets); n = len(rets)
    med = srt[n // 2] if n % 2 else (srt[n//2 - 1] + srt[n//2]) / 2
    longest_loss = 0; cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; longest_loss = max(longest_loss, cur)
    peak = 100.0; since = 0; longest_gap = 0
    for _, v in curve:
        if v >= peak: peak = v; since = 0
        else: since += 1; longest_gap = max(longest_gap, since)
    return {'periods': n, 'positive': sum(1 for r in rets if r > 0),
            'share_positive': round(sum(1 for r in rets if r > 0) / n, 3),
            'median_pct': round(med * 100, 2), 'best_pct': round(max(rets) * 100, 2),
            'worst_pct': round(min(rets) * 100, 2), 'longest_losing_streak': longest_loss,
            'longest_months_between_highs': longest_gap,
            'avg_pct_secondary': round(sum(rets) / n * 100, 2)}

def main():
    signals, dirs = build_dsi()
    fam = Family(signals, dirs)
    pools = {f'dSi|{F}|broad': len(fam.POOLS.get(('dSi', F, 'broad'), {})) for F in range(2016, 2026)}
    print('pools', pools, flush=True)
    roads = {}
    for rname, forms in ROADS.items():
        fin, curve, costs, maxdd = fam.run_road(forms, 'dSi', 'broad', 'QUINTILE', 'annual', False)
        twins = []
        for s in range(1, 21):
            tf, _, _, _ = fam.run_road(forms, 'dSi', 'broad', 'QUINTILE', 'annual', False, seed=s)
            twins.append(tf)
        ann = annual_stats(fam, forms)
        roads[rname] = {'final': fin, 'costs': costs, 'max_dd': maxdd,
                        'spy_same_window': spy_final(forms),
                        'placebo_finals': twins, 'placebos_beaten': sum(1 for t in twins if fin > t),
                        'curve': curve, 'monthly_distribution': dist_from_curve(curve),
                        'annual_returns_pct': ann,
                        'annual_distribution': period_stats([r / 100 for r in ann], curve)}
        print(rname, fin, 'dd', maxdd, 'pb', roads[rname]['placebos_beaten'], flush=True)
    res = {'family': 'catalog-hxz-fundamental-signals', 'program': 'v13-best-rules',
           'spec': 'BEST-RULES-SPEC.md', 'chassis': 'dSi|broad|native(no floor)|annual|QUINTILE',
           'pool_sizes': pools, 'roads': roads}
    # Confirmation trigger: any road beats champion V+M comparable print
    champ = {'LONGEST_2016_2025': 1415.62, 'DECADE_2017_2025': 667.35,
             'CONT_2019_2025': 544.47, 'VAL_2023_2025': 288.05}
    beaten = [r for r in ROADS if roads[r]['final'] > champ[r]]
    res['champion_roads_beaten_pre_confirmation'] = beaten
    if beaten:
        conf = {}
        for rname, forms in FOLDS.items():
            fin, curve, costs, maxdd = fam.run_road(forms, 'dSi', 'broad', 'QUINTILE', 'annual', False)
            twins = []
            for s in range(1, 21):
                tf, _, _, _ = fam.run_road(forms, 'dSi', 'broad', 'QUINTILE', 'annual', False, seed=s)
                twins.append(tf)
            conf[rname] = {'final': fin, 'costs': costs, 'max_dd': maxdd, 'spy_same_window': spy_final(forms),
                           'placebos_beaten': sum(1 for t in twins if fin > t), 'curve': curve}
            print('FOLD', rname, fin, flush=True)
        # half-windows of each beaten road
        halves = {}
        for r in beaten:
            forms = ROADS[r]; mid = len(forms) // 2
            for label, sub in (('H1', forms[:mid]), ('H2', forms[mid:])):
                fin, curve, costs, maxdd = fam.run_road(sub, 'dSi', 'broad', 'QUINTILE', 'annual', False)
                twins = []
                for s in range(1, 21):
                    tf, _, _, _ = fam.run_road(sub, 'dSi', 'broad', 'QUINTILE', 'annual', False, seed=s)
                    twins.append(tf)
                halves[f'{r}|{label}'] = {'final': fin, 'max_dd': maxdd, 'spy_same_window': spy_final(sub),
                                          'placebos_beaten': sum(1 for t in twins if fin > t), 'curve': curve}
                print('HALF', r, label, fin, flush=True)
        res['confirmation'] = {'folds': conf, 'half_windows': halves}
    json.dump(res, open(os.path.join(OUT, 'results.json'), 'w'), indent=1)
    print('DONE beaten=', beaten, flush=True)

if __name__ == '__main__':
    main()
