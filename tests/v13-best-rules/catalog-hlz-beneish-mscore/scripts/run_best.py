#!/usr/bin/env python3
"""V13 best-rules run — catalog-hlz-beneish-mscore.
Spec: BEST-RULES-SPEC.md (frozen before this run).
Primary cell: native universe (SIC 4/6 dropped), ANNUAL June formation,
hold ALL names with M-score <= -1.78 (published Beneish cutoff veto),
equal weight, NO floor, tiered program costs, vanished->ZERO.
Control (pre-registered): same book with veto OFF (all eligible names).
Placebos: 20 seeds, random same-count draw from full pool per formation.
Chassis logic inherited from the family's v12 engine (read-only source).
Signals read from the v12 folder's signals.json (read-only shared input).
"""
import json, os, math, random
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); FAM = os.path.join(HERE, '..')
V12 = os.path.join(FAM, '..', '..', 'v12-completions', 'catalog-hlz-beneish-mscore')
W04 = os.path.join(FAM, '..', '..', 'v11-native-rules', '_w04_broad_data')
CUTOFF = -1.78

def loadj(p): return json.load(open(p)) if os.path.exists(p) else {}

cand = {int(k): v for k, v in loadj(os.path.join(W04, 'candidates.json')).items()}
px = {}
for cik, info in cand.items():
    t = info['ticker'].replace('/', '-'); p = os.path.join(W04, f'px_{t}.json')
    if os.path.exists(p):
        try: px[cik] = {r[0]: (r[1], r[2]) for r in loadj(p)}
        except Exception: pass
spy = {r[0]: r[1] for r in loadj(os.path.join(W04, 'px_SPY.json'))}
SIG = loadj(os.path.join(V12, 'signals.json'))['signals']['Mscore']

shares_f = {}
for y in range(2009, 2026):
    shares_f[y] = {int(k): v for k, v in loadj(os.path.join(W04, 'frames', f'Shares_{y}I.json')).items()}
sf = {}
for cik in cand:
    avail = [(y, shares_f[y][cik]) for y in range(2009, 2026) if cik in shares_f[y]]
    d = {}
    for F in range(2016, 2027):
        f = 1.0
        for (y0, a), (y1, b) in zip(avail, avail[1:]):
            if y1 >= F and a:
                r = b / a
                if r >= 1.6 or r <= 0.625: f *= r
        d[F] = f
    sf[cik] = d

def cap_of(cik, F):
    sh = shares_f.get(F - 1, {}).get(cik) or shares_f.get(F - 2, {}).get(cik)
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

def ym(y, m): return f'{y:04d}-{m:02d}'

FORMS = sorted({int(f) for f in SIG['values']})
POOLS = {}; MATS = {}
for F in FORMS:
    vals = {int(k): v for k, v in SIG['values'].get(str(F), {}).items()}
    pool = {}
    for cik, score in vals.items():
        if cik not in px: continue
        e = px[cik].get(ym(F, 6))
        if not e or not e[0]: continue
        sic = str(cand[cik].get('sic') or '')
        if sic[:1] in ('4', '6'): continue
        cap = cap_of(cik, F)
        pool[cik] = {'score': score, 'cap': cap, 'rate': cost_rate(cap)}
    POOLS[F] = pool
    cols = [ym(F, m) for m in range(6, 13)] + [ym(F + 1, m) for m in range(1, 7)]
    allciks = sorted(pool)
    M = np.full((len(allciks), 13), np.nan); idx = {c: i for i, c in enumerate(allciks)}
    for i, cik in enumerate(allciks):
        s = px[cik]; last = None; lastbar = max(s) if s else None
        for j, mm in enumerate(cols):
            if mm in s: last = s[mm][0]
            if lastbar is not None and mm > lastbar: M[i, j] = 0.0
            elif last is not None: M[i, j] = last
    MATS[F] = (idx, M)

def picks_veto(F):
    return [c for c, d in POOLS[F].items() if d['score'] <= CUTOFF]

def picks_all(F):
    return list(POOLS[F].keys())

def run_road(formations, pickfn, seed=None):
    cash = 100.0; curve = []; total_costs = 0.0
    for F in formations:
        idx, M = MATS[F]; pool = POOLS[F]
        if seed is None:
            picks = pickfn(F)
        else:
            rng = random.Random(seed * 100003 + F); keys = list(pool.keys()); rng.shuffle(keys)
            picks = keys[:len(pickfn(F))]
        cols = [ym(F, m) for m in range(6, 13)] + [ym(F + 1, m) for m in range(1, 7)]
        if not picks:
            for mm in cols[1:]: curve.append([mm, round(cash, 2)])
            continue
        rows = np.array([idx[c] for c in picks]); P = M[rows, :]
        rates = np.array([pool[c]['rate'] for c in picks])
        px0 = P[:, 0].copy(); px0[px0 <= 0] = np.nan
        w = cash / len(picks)
        shares = np.where(np.isnan(px0), 0.0, (w * (1 - rates)) / np.where(np.isnan(px0), 1.0, px0))
        total_costs += float(np.sum(w * rates))
        for j in range(1, 13):
            pj = P[:, j]; vals = shares * np.where(np.isnan(pj), 0.0, pj); val = float(np.sum(vals))
            if j == 12:
                sell = float(np.sum(vals * rates)); total_costs += sell; cash = val - sell
            else:
                cash = val
            curve.append([cols[j], round(cash, 2)])
    peak = 100.0; maxdd = 0.0
    for _, v in curve:
        peak = max(peak, v); maxdd = max(maxdd, 1 - v / peak) if peak else 0.0
    return round(cash, 2), curve, round(total_costs, 2), round(maxdd, 4)

def spy_final(formations):
    if not formations: return None
    a = spy.get(ym(formations[0], 6)); b = spy.get(ym(formations[-1] + 1, 6))
    return round(100 * b / a, 2) if a and b else None

def period_stats(curve, n_formations):
    """Per formation-year period distribution from the monthly curve."""
    rets = []; prev = 100.0
    for i in range(n_formations):
        end = curve[(i + 1) * 12 - 1][1]
        rets.append(end / prev - 1.0); prev = end
    if not rets: return {}
    srt = sorted(rets); n = len(rets)
    med = srt[n // 2] if n % 2 else 0.5 * (srt[n // 2 - 1] + srt[n // 2])
    streak = worst_streak = 0
    for r in rets:
        streak = streak + 1 if r < 0 else 0
        worst_streak = max(worst_streak, streak)
    peak = 100.0; since_high = longest = 0
    for _, v in curve:
        if v >= peak: peak = v; since_high = 0
        else:
            since_high += 1; longest = max(longest, since_high)
    return {'periods': n, 'median_period_return': round(med, 4),
            'share_positive': round(sum(1 for r in rets if r > 0) / n, 3),
            'best_period': round(max(rets), 4), 'worst_period': round(min(rets), 4),
            'mean_period_return_secondary': round(sum(rets) / n, 4),
            'longest_losing_streak_periods': worst_streak,
            'longest_months_between_new_highs': longest,
            'period_returns': [round(r, 4) for r in rets]}

ROADS = {'LONGEST': FORMS,
         'DECADE': [f for f in FORMS if f >= 2017],
         'CONT': [f for f in FORMS if f >= 2019],
         'VAL': [f for f in FORMS if f >= 2023]}
FOLDS = {'FOLD_A': [f for f in FORMS if f <= 2020], 'FOLD_B': [f for f in FORMS if f >= 2021]}

def main():
    out = {'family': 'catalog-hlz-beneish-mscore',
           'spec': 'BEST-RULES-SPEC.md (frozen 2026-11-22)',
           'cell': 'native universe | ANNUAL June | hold ALL M<=-1.78 (veto) | EW | no floor',
           'control': 'same book, veto OFF (all eligible names)',
           'pool_sizes': {str(F): {'eligible': len(POOLS[F]),
                                   'flagged_vetoed': sum(1 for d in POOLS[F].values() if d['score'] > CUTOFF),
                                   'held': len(picks_veto(F))} for F in FORMS},
           'roads': {}, 'folds': {}, 'half_windows': {}}
    for name, forms in list(ROADS.items()) + list(FOLDS.items()):
        fin, curve, costs, maxdd = run_road(forms, picks_veto)
        cfin, ccurve, ccosts, cmaxdd = run_road(forms, picks_all)
        twins = []
        for sd in range(1, 21):
            tf, _, _, _ = run_road(forms, picks_veto, seed=sd); twins.append(tf)
        entry = {'formations': forms, 'final': fin, 'costs': costs, 'max_dd': maxdd,
                 'spy_same_window': spy_final(forms),
                 'placebo_finals': twins, 'placebos_beaten': sum(1 for t in twins if fin > t),
                 'control_final': cfin, 'control_costs': ccosts, 'control_max_dd': cmaxdd,
                 'curve': curve, 'control_curve': ccurve,
                 'period_stats': period_stats(curve, len(forms)),
                 'control_period_stats': period_stats(ccurve, len(forms))}
        (out['roads'] if name in ROADS else out['folds'])[name] = entry
        print(name, 'veto', fin, 'control', cfin, 'spy', entry['spy_same_window'],
              'pb', entry['placebos_beaten'], 'maxdd', maxdd, flush=True)
        if name in ROADS:
            h = max(1, len(forms) // 2)
            hw = {}
            for lbl, sub in (('first_half', forms[:h]), ('second_half', forms[h:])):
                hf, _, _, hdd = run_road(sub, picks_veto)
                hw[lbl] = {'formations': sub, 'final': hf, 'max_dd': hdd, 'spy_same_window': spy_final(sub)}
            out['half_windows'][name] = hw
            print(' ', name, 'halves', hw, flush=True)
    with open(os.path.join(FAM, 'results.json'), 'w') as fh:
        json.dump(out, fh, indent=1)
    print('saved results.json')

if __name__ == '__main__':
    main()
