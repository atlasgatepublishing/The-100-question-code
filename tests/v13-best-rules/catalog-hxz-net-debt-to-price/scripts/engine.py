#!/usr/bin/env python3
"""V13 Best-Rules engine — catalog-hxz-net-debt-to-price.
Frozen spec: ../BEST-RULES-SPEC.md. My form: NdpPos pool (net debt > 0),
top quintile, equal-weight, annual June formation, 12m hold, NO floor.
Twin: published form (full Ndp pool, top quintile, annual, no floor) on
identical roads. Chassis inherited from v12: W04 broad stack (read-only),
EDGAR frames, tiered costs, vanished->ZERO, PIT June lag.
Roads end with a partial formation Jun 2026 -> Nov 2026."""
import json, os, math, random
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FAM = os.path.dirname(HERE)
BASE = '/home/hatch/workspace/stock-app/backtests'
W04 = os.path.join(BASE, 'v11-native-rules', '_w04_broad_data')
EXTRA = '/tmp/slice12_frames'

def loadj(p):
    return json.load(open(p)) if os.path.exists(p) else {}

cand = {int(k): v for k, v in loadj(os.path.join(W04, 'candidates.json')).items()}
px = {}
for cik, info in cand.items():
    t = info['ticker'].replace('/', '-')
    p = os.path.join(W04, f'px_{t}.json')
    if os.path.exists(p):
        try: px[cik] = {r[0]: (r[1], r[2]) for r in loadj(p)}
        except Exception: pass
spy = {r[0]: r[1] for r in loadj(os.path.join(W04, 'px_SPY.json'))}

def frame(concept, unit):
    out = {}
    for y in range(2014, 2026):
        d = loadj(os.path.join(W04, 'frames', f'{concept}_{y}{unit}.json'))
        if not d:
            d = loadj(os.path.join(EXTRA, f'{concept}_{y}{unit}.json'))
        out[y] = {int(k): v for k, v in d.items()}
    return out

FR = {}
for c in ['CashAndCashEquivalentsAtCarryingValue', 'DebtCurrent', 'LongTermDebt',
          'LongTermDebtNoncurrent', 'Shares']:
    FR[c] = frame(c, 'I')

def g(concept, y, cik):
    return FR[concept].get(y, {}).get(cik)

sf = {}
for cik in cand:
    avail = [(y, FR['Shares'][y][cik]) for y in range(2014, 2026) if cik in FR['Shares'].get(y, {})]
    d = {}
    for F in range(2016, 2028):
        f = 1.0
        for (y0, a), (y1, b) in zip(avail, avail[1:]):
            if y1 >= F and a:
                r = b / a
                if r >= 1.6 or r <= 0.625: f *= r
        d[F] = f
    sf[cik] = d

def cap_of(cik, F):
    sh = g('Shares', F-1, cik) or g('Shares', F-2, cik)
    s = px.get(cik)
    if not sh or not s: return None
    e = s.get(f'{F:04d}-06')
    if not e or not e[1]: return None
    return sh * e[1] * sf.get(cik, {}).get(F, 1.0)

def cost_rate(cap):
    if cap is None: return 0.0075
    if cap >= 5e9: return 0.0010
    if cap >= 1e9: return 0.0025
    return 0.0075

def total_debt(y, cik):
    dc = g('DebtCurrent', y, cik); ltn = g('LongTermDebtNoncurrent', y, cik)
    lt = g('LongTermDebt', y, cik)
    if dc is not None and ltn is not None: return dc + ltn
    if lt is not None: return lt
    if dc is not None: return dc
    if ltn is not None: return ltn
    return None

def ym(y, m): return f'{y:04d}-{m:02d}'

def sig_ndp(F):
    out, pos = {}, {}
    for cik in cand:
        debt, cash = total_debt(F-1, cik), g('CashAndCashEquivalentsAtCarryingValue', F-1, cik)
        mc = cap_of(cik, F)
        if debt is None or cash is None or not mc: continue
        v = (debt - cash) / mc
        out[cik] = v
        if debt - cash > 0: pos[cik] = v
    return {'Ndp': (out, 'high'), 'NdpPos': (pos, 'high')}

def cols_for(F):
    if F < 2026:
        return [ym(F, m) for m in range(6, 13)] + [ym(F+1, m) for m in range(1, 7)]
    return [ym(2026, m) for m in range(6, 12)]  # Jun..Nov 2026 partial

POOLS = {}; MATS = {}
for F in range(2016, 2027):
    sigs = sig_ndp(F)
    cols = cols_for(F)
    for sname, (vals, direction) in sigs.items():
        pool = {}
        for cik, v in vals.items():
            if cik not in px: continue
            e = px[cik].get(ym(F, 6))
            if not e or not e[0]: continue
            cap = cap_of(cik, F)
            pool[cik] = {'sig': v, 'dir': direction, 'cap': cap, 'rate': cost_rate(cap)}
        POOLS[(F, sname)] = pool
        ciks = sorted(pool)
        M = np.full((len(ciks), len(cols)), np.nan)
        for i, cik in enumerate(ciks):
            s = px[cik]; last = None; lastbar = max(s) if s else None
            for j, mm in enumerate(cols):
                if mm in s: last = s[mm][0]
                if lastbar is not None and mm > lastbar: M[i, j] = 0.0
                elif last is not None: M[i, j] = last
        MATS[(F, sname)] = (ciks, M)

def picks_for(F, sname):
    pool = POOLS[(F, sname)]
    items = sorted(pool.items(), key=lambda kv: kv[1]['sig'], reverse=True)
    n = max(1, math.ceil(len(items) * 0.20))
    return [c for c, _ in items[:n]]

def run_road(formations, sname, seed=None):
    cash = 100.0; curve = []; total_costs = 0.0; periods = []
    for F in formations:
        ciks_all, M = MATS[(F, sname)]
        idx = {c: i for i, c in enumerate(ciks_all)}
        pool = POOLS[(F, sname)]
        if seed is None:
            picks = picks_for(F, sname)
        else:
            rng = random.Random(seed * 100003 + F)
            keys = list(pool.keys()); rng.shuffle(keys)
            n = max(1, math.ceil(len(keys) * 0.20))
            picks = keys[:n]
        cols = cols_for(F)
        start_cash = cash
        if not picks:
            for mm in cols[1:]: curve.append([mm, round(cash, 2)])
            periods.append({'formation': F, 'ret': 0.0, 'partial': F == 2026})
            continue
        rows = np.array([idx[c] for c in picks])
        P = M[rows, :]
        rates = np.array([pool[c]['rate'] for c in picks])
        px0 = P[:, 0].copy(); px0[px0 <= 0] = np.nan
        w = cash / len(picks)
        shares = np.where(np.isnan(px0), 0.0, (w * (1 - rates)) / np.where(np.isnan(px0), 1.0, px0))
        total_costs += float(np.sum(w * rates))
        nsteps = P.shape[1] - 1
        for j in range(1, nsteps + 1):
            pj = P[:, j]
            vals = shares * np.where(np.isnan(pj), 0.0, pj)
            val = float(np.sum(vals))
            if j == nsteps:
                sell = float(np.sum(vals * rates)); total_costs += sell; cash = val - sell
            else:
                cash = val
            curve.append([cols[j], round(cash, 2)])
        periods.append({'formation': F, 'ret': round(cash / start_cash - 1, 4) if start_cash else 0.0,
                        'partial': F == 2026})
    peak2 = 100.0; maxdd = 0.0
    for _, v in curve:
        peak2 = max(peak2, v); maxdd = max(maxdd, 1 - v / peak2) if peak2 else 0.0
    return round(cash, 2), curve, round(total_costs, 2), round(maxdd, 4), periods

def spy_final(formations):
    a = spy.get(ym(formations[0], 6)); b = spy.get('2026-11') if formations[-1] == 2026 else spy.get(ym(formations[-1]+1, 6))
    return round(100 * b / a, 2) if a and b else None

def spy_window(m_start, m_end):
    a, b = spy.get(m_start), spy.get(m_end)
    return round(100 * b / a, 2) if a and b else None

def distribution(periods, curve):
    rets = [p['ret'] for p in periods]
    if not rets: return {}
    srt = sorted(rets); n = len(srt)
    med = srt[n//2] if n % 2 else (srt[n//2-1] + srt[n//2]) / 2
    longest_loss = 0; run = 0
    for r in rets:
        run = run + 1 if r < 0 else 0
        longest_loss = max(longest_loss, run)
    # longest stretch between new highs (months), from monthly curve incl. start
    peak = 100.0; stretch = 0; cur = 0
    for _, v in curve:
        if v >= peak: peak = v; cur = 0
        else: cur += 1; stretch = max(stretch, cur)
    return {'n_periods': n, 'median_period_ret': round(med, 4),
            'share_positive': round(sum(1 for r in rets if r > 0) / n, 3),
            'best_period_ret': round(max(rets), 4), 'worst_period_ret': round(min(rets), 4),
            'longest_losing_streak_periods': longest_loss,
            'longest_months_between_new_highs': stretch,
            'mean_period_ret_secondary': round(sum(rets) / n, 4),
            'period_rets': [round(r, 4) for r in rets]}

ROADS = {'LONGEST': list(range(2016, 2027)), 'DECADE': list(range(2017, 2027)),
         'CONT': list(range(2019, 2027)), 'VAL': list(range(2023, 2027))}

def main():
    fences = {f'{F}|{s}': len(POOLS[(F, s)]) for (F, s) in sorted(POOLS.keys())}
    print('pools', fences, flush=True)
    out = {'family': 'catalog-hxz-net-debt-to-price', 'spec': 'BEST-RULES-SPEC.md',
           'pool_sizes_eligible': fences, 'roads': {}}
    for form_name, sname in (('my_rules', 'NdpPos'), ('published_twin', 'Ndp')):
        out['roads'][form_name] = {}
        for rname, forms in ROADS.items():
            fin, curve, costs, maxdd, periods = run_road(forms, sname)
            twins = []
            for sd in range(1, 21):
                tf, _, _, _, _ = run_road(forms, sname, seed=sd)
                twins.append(tf)
            entry = {'final': fin, 'costs': costs, 'max_dd': maxdd,
                     'spy_same_window': spy_final(forms),
                     'placebo_finals': twins,
                     'placebos_beaten': sum(1 for t in twins if fin > t),
                     'distribution_annual': distribution(periods, curve),
                     'curve': curve}
            out['roads'][form_name][rname] = entry
            print(form_name, rname, fin, 'dd', maxdd, 'spy', entry['spy_same_window'],
                  'pb', entry['placebos_beaten'], flush=True)
    # confirmation pack for my form: yearly folds + half windows (all roads; used per spec bars)
    conf = {}
    for rname, forms in ROADS.items():
        folds = {}
        for F in forms:
            fin, _, _, _, _ = run_road([F], 'NdpPos')
            end = '2026-11' if F == 2026 else ym(F+1, 6)
            folds[str(F)] = {'final': fin, 'spy_same_window': spy_window(ym(F, 6), end)}
        half = len(forms) // 2
        halves = {}
        for label, fs in (('first_half', forms[:half]), ('second_half', forms[half:])):
            fin, _, _, _, _ = run_road(fs, 'NdpPos')
            end = '2026-11' if fs[-1] == 2026 else ym(fs[-1]+1, 6)
            halves[label] = {'formations': fs, 'final': fin,
                             'spy_same_window': spy_window(ym(fs[0], 6), end)}
        conf[rname] = {'yearly_folds': folds, 'half_windows': halves,
                       'folds_beating_spy': sum(1 for v in folds.values() if v['final'] > v['spy_same_window']),
                       'n_folds': len(folds)}
        print('conf', rname, 'folds beat SPY', conf[rname]['folds_beating_spy'], '/', len(folds),
              'halves', halves['first_half']['final'], halves['second_half']['final'], flush=True)
    out['confirmation_my_rules'] = conf
    with open(os.path.join(FAM, 'results.json'), 'w') as fh:
        json.dump(out, fh, indent=1)
    print('saved results.json')

if __name__ == '__main__':
    main()
