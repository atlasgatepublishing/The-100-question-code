#!/usr/bin/env python3
"""catalog-hxz-debt-to-market v13 engine — frozen by BEST-RULES-SPEC.md.
My-rules form: Dm = debt/(debt+market equity), long HIGH, top HALF of the
ex-financials pool, equal-weight, annual June formation, 12m hold, NO floor.
Published-form twin (top QUINTILE, same chassis) run on identical roads.
Formations 2016-2026; the 2026 formation is partial (Jun->Nov 2026).
Tiered program costs, vanished->ZERO, 20-seed placebos sharing the chassis.
Simulation only. Public data only."""
import json, os, math, random, statistics
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FAM = os.path.join(HERE, '..')
W04 = os.path.join(FAM, '..', '..', 'v11-native-rules', '_w04_broad_data')
WFR = os.path.join(W04, 'frames')
LFR = os.path.join(FAM, '..', '..', 'v12-completions', 'catalog-hxz-debt-to-market', 'data', 'frames')

def loadj(p):
    return json.load(open(p)) if os.path.exists(p) else {}

def frame(tag, y, suf):
    for base in (LFR, WFR):
        d = loadj(os.path.join(base, f'{tag}_{y}{suf}.json'))
        if d: return {int(k): v for k, v in d.items()}
    return {}

cand = {int(k): v for k, v in loadj(os.path.join(W04, 'candidates.json')).items()}
px = {}
for cik, info in cand.items():
    t = info['ticker'].replace('/', '-')
    p = os.path.join(W04, f'px_{t}.json')
    if os.path.exists(p):
        try: px[cik] = {r[0]: (r[1], r[2]) for r in loadj(p)}
        except Exception: pass
spy = {r[0]: r[1] for r in loadj(os.path.join(W04, 'px_SPY.json'))}

YEARS = list(range(2009, 2027))
def F_series(tag, suf): return {y: frame(tag, y, suf) for y in YEARS}
LT = F_series('Liabilities', 'I'); LTD = F_series('LongTermDebt', 'I')
DCUR = F_series('DebtCurrent', 'I'); SH = F_series('Shares', 'I')

sf = {}
for cik in cand:
    avail = [(y, SH[y][cik]) for y in YEARS if cik in SH[y]]
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
    sh = SH.get(F - 1, {}).get(cik) or SH.get(F - 2, {}).get(cik)
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

def debt(y, cik):
    a = LTD[y].get(cik); b = DCUR[y].get(cik)
    if a is None and b is None: return None
    return (a or 0) + (b or 0)

def ym(y, m): return f'{y:04d}-{m:02d}'

SIG = {}
for F in range(2016, 2027):
    y = F - 1; d = {}
    for cik in cand:
        db = debt(y, cik); cap = cap_of(cik, F)
        if db is None or not cap or (db + cap) <= 0: continue
        d[cik] = db / (db + cap)
    SIG[F] = d

POOLS = {}
for F in range(2016, 2027):
    pool = {}
    for cik, v in SIG.get(F, {}).items():
        if cik not in px: continue
        e = px[cik].get(ym(F, 6))
        if not e or not e[0]: continue
        sic = str(cand[cik].get('sic') or '')
        if sic[:1] == '6': continue  # ex-financials (native/HXZ convention)
        cap = cap_of(cik, F)
        pool[cik] = {'sig': v, 'cap': cap, 'rate': cost_rate(cap), 'px0': e[0]}
    POOLS[F] = pool

def cols_for(F):
    if F < 2026:
        return [ym(F, m) for m in range(6, 13)] + [ym(F + 1, m) for m in range(1, 7)]
    return [ym(2026, m) for m in range(6, 12)]  # Jun..Nov 2026 partial

MATS = {}
for F in range(2016, 2027):
    cols = cols_for(F); pool = POOLS[F]; ciks = sorted(pool)
    M = np.full((len(ciks), len(cols)), np.nan)
    for i, cik in enumerate(ciks):
        s = px[cik]; last = None; lastbar = max(s) if s else None
        for j, mm in enumerate(cols):
            if mm in s: last = s[mm][0]
            if lastbar is not None and mm > lastbar: M[i, j] = 0.0
            elif last is not None: M[i, j] = last
    MATS[F] = (ciks, M)

def n_for(count, npool):
    if count == 'HALF': return max(1, math.ceil(npool * 0.50))
    if count == 'QUINTILE': return max(1, math.ceil(npool * 0.20))
    raise ValueError(count)

def picks_for(F, count):
    items = sorted(POOLS[F].items(), key=lambda kv: -kv[1]['sig'])
    return [c for c, _ in items[:n_for(count, len(items))]]

def run_road(formations, count, seed=None):
    cash = 100.0; curve = []; total_costs = 0.0; periods = []
    for F in formations:
        ciks_all, M = MATS[F]; idx = {c: i for i, c in enumerate(ciks_all)}
        pool = POOLS[F]; cols = cols_for(F); start_cash = cash
        if seed is None:
            picks = picks_for(F, count)
        else:
            rng = random.Random(seed * 100003 + F)
            keys = sorted(pool); rng.shuffle(keys)
            picks = keys[:n_for(count, len(keys))]
        if not picks:
            for mm in cols[1:]: curve.append([mm, round(cash, 2)])
            periods.append({'formation': F, 'ret': 0.0}); continue
        rows = np.array([idx[c] for c in picks])
        P = M[rows, :]
        rates = np.array([pool[c]['rate'] for c in picks])
        px0 = P[:, 0].copy(); px0[px0 <= 0] = np.nan
        w = cash / len(picks)
        shares = np.where(np.isnan(px0), 0.0, (w * (1 - rates)) / np.where(np.isnan(px0), 1.0, px0))
        total_costs += float(np.sum(w * rates))
        last_j = len(cols) - 1
        for j in range(1, len(cols)):
            pj = P[:, j]
            vals = shares * np.where(np.isnan(pj), 0.0, pj)
            val = float(np.sum(vals))
            if j == last_j:
                sell = float(np.sum(vals * rates)); total_costs += sell; cash = val - sell
            else:
                cash = val
            curve.append([cols[j], round(cash, 2)])
        periods.append({'formation': F, 'ret': round(cash / start_cash - 1, 4) if start_cash else 0.0})
    peak = 100.0; maxdd = 0.0; last_high_i = 0; longest_gap = 0
    for i, (_, v) in enumerate(curve):
        if v >= peak: peak = v; last_high_i = i
        longest_gap = max(longest_gap, i - last_high_i)
        if peak: maxdd = max(maxdd, 1 - v / peak)
    return {'final': round(cash, 2), 'curve': curve, 'costs': round(total_costs, 2),
            'max_dd': round(maxdd, 4), 'periods': periods, 'months_between_highs_max': longest_gap}

def spy_final(formations):
    a = spy.get(ym(formations[0], 6)); b = spy.get('2026-11')
    return round(100 * b / a, 2) if a and b else None

def spy_window(f0, f1):
    a = spy.get(ym(f0, 6)); b = spy.get(ym(f1, 6)) if f1 <= 2026 else spy.get('2026-11')
    return round(100 * b / a, 2) if a and b else None

def distribution(res):
    rets = [p['ret'] for p in res['periods']]
    pos = sum(1 for r in rets if r > 0)
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; streak = max(streak, cur)
    return {'n_periods': len(rets), 'median_period': round(statistics.median(rets), 4) if rets else None,
            'share_positive': round(pos / len(rets), 3) if rets else None,
            'best_period': round(max(rets), 4) if rets else None,
            'worst_period': round(min(rets), 4) if rets else None,
            'longest_losing_streak_periods': streak,
            'longest_months_between_new_highs': res['months_between_highs_max'],
            'period_rets': rets,
            'mean_period_secondary': round(statistics.mean(rets), 4) if rets else None}

ROADS = {'LONGEST': list(range(2016, 2027)), 'DECADE': list(range(2017, 2027)),
         'CONT': list(range(2019, 2027)), 'VAL': list(range(2023, 2027))}

def main():
    out = {'family': 'catalog-hxz-debt-to-market', 'program': 'v13-best-rules',
           'spec': 'BEST-RULES-SPEC.md',
           'pool_sizes': {str(F): len(POOLS[F]) for F in range(2016, 2027)}, 'roads': {}}
    for form_name, count in (('my_rules_HALF', 'HALF'), ('published_twin_QUINTILE', 'QUINTILE')):
        for rname, forms in ROADS.items():
            res = run_road(forms, count)
            twins = []
            for s in range(1, 21):
                twins.append(run_road(forms, count, seed=s)['final'])
            res['placebo_finals'] = twins
            res['placebos_beaten'] = sum(1 for t in twins if res['final'] > t)
            res['spy_same_window'] = spy_final(forms)
            res['distribution'] = distribution(res)
            out['roads'][f'{form_name}|{rname}'] = res
            print(form_name, rname, res['final'], 'dd', res['max_dd'], 'pb', res['placebos_beaten'], 'spy', res['spy_same_window'], flush=True)
    # yearly folds + half-windows for my form (confirmation inputs / transparency)
    folds = {}
    for F in range(2016, 2027):
        r = run_road([F], 'HALF')
        folds[str(F)] = {'final': r['final'], 'max_dd': r['max_dd'],
                         'spy_same_window': round(100 * spy.get(cols_for(F)[-1], 0) / spy.get(ym(F, 6), 1), 2) if spy.get(ym(F, 6)) else None}
    out['yearly_folds_my_rules'] = folds
    print('folds', folds, flush=True)
    with open(os.path.join(FAM, 'results.json'), 'w') as fh: json.dump(out, fh, indent=1)
    print('saved results.json')

if __name__ == '__main__': main()
