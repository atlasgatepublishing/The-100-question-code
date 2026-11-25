#!/usr/bin/env python3
"""V13 BEST-RULES Graham Enterprising — frozen per BEST-RULES-SPEC.md.
Changes vs v12 run_judgment.py ONLY as specced: (1) cheapness = cap / 5y-avg NI <= 10
(single test, replaces trailing pair); (2) NO floor. Everything else identical
machinery. Reuses W04 broad stack read-only. Writes only in this folder."""
import json, os, sys, random
sys.path.insert(0, os.path.expanduser("~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data"))
import engine_w04 as E

HERE = os.path.dirname(os.path.abspath(__file__))

def ni_hist(cik, F):
    return {y: E.D.F('NetIncomeLoss', y, 'D').get(cik) for y in range(F - 5, F)}

def gates(snap, F):
    quals, pool = [], []
    for cik, v in snap.items():
        ca, cl = v['ca'], v['cl']
        if ca is None or cl is None or cl <= 0 or v['cap'] is None or not v['px_adj']:
            continue
        nca = ca - cl
        if ca / cl < 1.5: continue
        if v['ltd'] is None or nca <= 0 or v['ltd'] > 1.10 * nca: continue
        h = ni_hist(cik, F)
        if any(h[y] is None or h[y] <= 0 for y in range(F - 5, F)): continue
        if not (h[F - 1] > h[F - 5]): continue
        pool.append(cik)
        # v13: cheapness on 5y AVERAGE earnings, single test <= 10
        avg_ni = sum(h[y] for y in range(F - 5, F)) / 5.0
        if avg_ni <= 0 or v['cap'] / avg_ni > 10.0: continue
        if v['equity'] is None or v['equity'] <= 0 or v['cap'] > 1.20 * v['equity']: continue
        if v['liab'] is not None:
            ncav = ca - v['liab']
            if ncav > 0 and v['cap'] <= (2.0 / 3.0) * ncav: continue
        quals.append(cik)
    def rank(c):
        v = snap[c]; h = ni_hist(c, F)
        avg_ni = sum(h[y] for y in range(F - 5, F)) / 5.0
        return (v['cap'] / avg_ni) * (v['cap'] / v['equity'])
    quals.sort(key=rank)
    return quals, pool

def run(formations, seed=None):
    D = E.D
    cash = 100.0; curve = []; total_costs = 0.0; orders = 0; yearly = []
    for F in formations:
        s = E.snapshot(F)
        quals, pool = gates(s, F)
        if seed is not None:
            rng = random.Random(seed * 7919 + F)
            keys = list(pool); rng.shuffle(keys)
            picks = keys[:len(quals)]
        else:
            picks = quals
        start = cash
        if not picks:
            yearly.append({'formation': F, 'n_picks': 0, 'ret': 0.0, 'picks': []})
            for m in range(7, 13): curve.append([E.ym(F, m), round(cash, 2)])
            for m in range(1, 7): curve.append([E.ym(F + 1, m), round(cash, 2)])
            continue
        w = cash / len(picks); pos = {}
        for c in picks:
            r = E.cost_rate(s[c]['cap']); total_costs += w * r; orders += 1
            pos[c] = (w - w * r) / s[c]['px_adj']
        months = [E.ym(F, m) for m in range(7, 13)] + [E.ym(F + 1, m) for m in range(1, 7)]
        for mm in months:
            val = sum(sh * (D.price(c, mm, adj=True) or s[c]['px_adj']) for c, sh in pos.items())
            curve.append([mm, round(val, 2)])
        end = 0.0
        for c, sh in pos.items():
            if not D.has_price_month(c, E.ym(F + 1, 6)):
                continue  # vanished -> ZERO
            p = D.price(c, E.ym(F + 1, 6), adj=True)
            g = sh * p; r = E.cost_rate(s[c]['cap']); total_costs += g * r; orders += 1
            end += g - g * r
        cash = end
        yearly.append({'formation': F, 'n_picks': len(picks), 'ret': round(cash / start - 1, 4) if start else 0.0,
                       'picks': [s[c]['ticker'] for c in picks]})
    peak = 100.0; maxdd = 0.0
    for _, v in curve:
        peak = max(peak, v); maxdd = max(maxdd, 1 - v / peak)
    spy = None
    if formations and D.spy:
        a = D.spy.get(E.ym(formations[0], 6)); b = D.spy.get(E.ym(formations[-1] + 1, 6))
        if a and b: spy = round(100 * b / a, 2)
    return {'final': round(cash, 2), 'max_dd': round(maxdd, 4), 'costs': round(total_costs, 2),
            'orders': orders, 'curve': curve, 'yearly': yearly, 'spy_final_same_window': spy}

def dist(curve):
    """Per-period (monthly) distribution from marks; start = 100 baseline."""
    vals = [100.0] + [v for _, v in curve]
    rets = [vals[i] / vals[i - 1] - 1 for i in range(1, len(vals))]
    pos = sum(1 for r in rets if r > 1e-9); neg = sum(1 for r in rets if r < -1e-9)
    srt = sorted(rets); n = len(rets)
    median = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2
    best_i = max(range(n), key=lambda i: rets[i]); worst_i = min(range(n), key=lambda i: rets[i])
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r < -1e-9 else 0; streak = max(streak, cur)
    peak = vals[0]; since = 0; longest = 0
    for v in vals[1:]:
        if v >= peak: peak = v; longest = max(longest, since); since = 0
        else: since += 1
    longest = max(longest, since)
    labels = [m for m, _ in curve]
    return {'periods': n, 'positive': pos, 'negative': neg, 'flat': n - pos - neg,
            'median_pct': round(median * 100, 2), 'mean_pct_secondary': round(sum(rets) / n * 100, 2) if n else 0.0,
            'best': {'month': labels[best_i], 'pct': round(rets[best_i] * 100, 2)},
            'worst': {'month': labels[worst_i], 'pct': round(rets[worst_i] * 100, 2)},
            'longest_losing_streak_months': streak, 'longest_months_between_new_highs': longest}

def main():
    E.D = E.Data()
    res = {'family': 'judgment-graham-enterprising', 'program': 'v13-best-rules', 'label': 'JUDGMENT-CONSTRUCTED'}
    roads = {'DECADE_PROXY_2017_2025': list(range(2017, 2026)),
             'CONT_2019_2025': list(range(2019, 2026)),
             'VAL_2023_2025': list(range(2023, 2026))}
    for name, forms in roads.items():
        r = run(forms); r['distribution_monthly'] = dist(r['curve'])
        res[name] = r
        print(name, 'final', r['final'], 'maxdd', r['max_dd'], 'spy', r['spy_final_same_window'], flush=True)
    census = []
    for F in range(2017, 2026):
        s = E.snapshot(F); q, p = gates(s, F)
        census.append({'formation': F, 'qualifiers': len(q), 'jpool': len(p),
                       'tickers': [s[c]['ticker'] for c in q]})
        print('census', F, len(q), 'pool', len(p), [s[c]['ticker'] for c in q], flush=True)
    res['census'] = census
    twins = []
    for seed in range(1, 21):
        r = run(roads['DECADE_PROXY_2017_2025'], seed=seed)
        twins.append(r['final']); print('twin', seed, r['final'], flush=True)
    res['placebo_finals_decade'] = twins
    med = sorted(twins)[10]
    res['placebo_median_decade'] = med
    res['placebos_beaten_decade'] = sum(1 for t in twins if res['DECADE_PROXY_2017_2025']['final'] > t)
    json.dump(res, open(os.path.join(HERE, 'results.json'), 'w'), indent=1)
    print('saved', flush=True)

if __name__ == '__main__':
    main()
