#!/usr/bin/env python3
"""V12 JUDGMENT-CONSTRUCTED Graham Enterprising — frozen per JUDGMENT-SPEC.md.
Reuses the W04 broad EDGAR-frames Data/snapshot (read-only shared input).
Exit rule: a held name with no price in its exit June is written to ZERO.
Simulation only. Writes only in this folder."""
import json, os, sys, random
sys.path.insert(0, os.path.expanduser("~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data"))
import engine_w04 as E

HERE = os.path.dirname(os.path.abspath(__file__))
FLOOR = 85.0

def ni_hist(cik, F):
    """Net income for calendar years F-5..F-1 from duration frames."""
    out = {}
    for y in range(F - 5, F):
        out[y] = E.D.F('NetIncomeLoss', y, 'D').get(cik)
    return out

def gates(snap, F):
    """Returns (qualifiers ranked list, jpool list) of ciks."""
    quals, pool = [], []
    for cik, v in snap.items():
        ca, cl = v['ca'], v['cl']
        if ca is None or cl is None or cl <= 0 or v['cap'] is None or not v['px_adj']:
            continue
        nca = ca - cl
        # J1
        if ca / cl < 1.5: continue
        if v['ltd'] is None or nca <= 0 or v['ltd'] > 1.10 * nca: continue
        # J2/J3 need 5y NI
        h = ni_hist(cik, F)
        if any(h[y] is None or h[y] <= 0 for y in range(F - 5, F)): continue
        if not (h[F - 1] > h[F - 5]): continue
        pool.append(cik)
        # J5 price tests
        ni1 = h[F - 1]; ni_avg2 = (h[F - 1] + h[F - 2]) / 2.0
        if v['cap'] / ni1 > 10.0: continue
        if ni_avg2 <= 0 or v['cap'] / ni_avg2 > 12.0: continue
        if v['equity'] is None or v['equity'] <= 0 or v['cap'] > 1.20 * v['equity']: continue
        # J6 net-net exclusion
        if v['liab'] is not None:
            ncav = ca - v['liab']
            if ncav > 0 and v['cap'] <= (2.0 / 3.0) * ncav: continue
        quals.append(cik)
    def rank(c):
        v = snap[c]
        pe = v['cap'] / ni_hist(c, F)[F - 1]
        pb = v['cap'] / v['equity']
        return pe * pb
    quals.sort(key=rank)
    return quals, pool

def run(formations, mode='native', count=None, seed=None):
    D = E.D
    cash = 100.0; curve = []; total_costs = 0.0; orders = 0; yearly = []
    floored = False
    for F in formations:
        if floored: break
        s = E.snapshot(F)
        quals, pool = gates(s, F)
        if seed is not None:
            rng = random.Random(seed * 7919 + F)
            keys = list(pool); rng.shuffle(keys)
            picks = keys[:len(quals)]
        elif mode == 'grid':
            picks = quals[:count] if count else quals
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
        hit_floor = False
        for mm in months:
            val = sum(sh * (D.price(c, mm, adj=True) or s[c]['px_adj']) for c, sh in pos.items())
            curve.append([mm, round(val, 2)])
            if val < FLOOR:
                # liquidate at marks less sell costs
                cash = 0.0
                for c, sh in pos.items():
                    p = D.price(c, mm, adj=True) or s[c]['px_adj']
                    g = sh * p; cash += g - g * E.cost_rate(s[c]['cap']); total_costs += g * E.cost_rate(s[c]['cap']); orders += 1
                floored = True; hit_floor = True
                yearly.append({'formation': F, 'n_picks': len(picks), 'ret': round(cash / start - 1, 4) if start else 0.0,
                               'picks': [s[c]['ticker'] for c in picks], 'floored': True})
                break
        if hit_floor: break
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
            'orders': orders, 'floored': floored, 'curve': curve, 'yearly': yearly,
            'spy_final_same_window': spy}

def main():
    E.D = E.Data()
    res = {'family': 'judgment-graham-enterprising', 'label': 'JUDGMENT-CONSTRUCTED'}
    roads = {'FULL_DECADE_PROXY_2017_2025': list(range(2017, 2026)),
             'CONT_2019_2025': list(range(2019, 2026)),
             'VAL_2023_2025': list(range(2023, 2026))}
    for name, forms in roads.items():
        r = run(forms)
        res[name] = r
        print(name, 'final', r['final'], 'maxdd', r['max_dd'], 'spy', r['spy_final_same_window'], 'floored', r['floored'], flush=True)
    # qualifiers census
    census = []
    for F in range(2017, 2026):
        s = E.snapshot(F); q, p = gates(s, F)
        census.append({'formation': F, 'qualifiers': len(q), 'jpool': len(p),
                       'tickers': [s[c]['ticker'] for c in q]})
        print('census', F, len(q), 'pool', len(p), flush=True)
    res['census'] = census
    # placebos on FULL road
    twins = []
    for seed in range(1, 21):
        r = run(roads['FULL_DECADE_PROXY_2017_2025'], seed=seed)
        twins.append(r['final']); print('twin', seed, r['final'], flush=True)
    res['placebo_finals_full'] = twins
    res['placebos_beaten_full'] = sum(1 for t in twins if res['FULL_DECADE_PROXY_2017_2025']['final'] > t)
    # holdings grid on FULL road
    grid = {}
    for n in [1, 2, 3, 5, 8, 10, 15, 20, 30]:
        r = run(roads['FULL_DECADE_PROXY_2017_2025'], mode='grid', count=n)
        grid[str(n)] = {'final': r['final'], 'max_dd': r['max_dd']}
        print('grid', n, r['final'], flush=True)
    grid['ALL'] = {'final': res['FULL_DECADE_PROXY_2017_2025']['final'], 'max_dd': res['FULL_DECADE_PROXY_2017_2025']['max_dd']}
    res['holdings_grid_full'] = grid
    if os.environ.get('PRINT_JSON'):
        print('JSON_BEGIN')
        print(json.dumps(res))
        print('JSON_END')
    else:
        json.dump(res, open(os.path.join(HERE, 'results.json'), 'w'), indent=1)
    print('saved', flush=True)

if __name__ == '__main__':
    main()
