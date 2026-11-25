#!/usr/bin/env python3
"""catalog-hxz-debt-structure v13 BEST-RULES engine — frozen by BEST-RULES-SPEC.md.
Single cell: Sdd (SecuredDebt / total debt), ZERO-IF-SILENT missing-data
convention, native universe (ex-financials, SIC first digit 6), UPPER-HALF
(above formation-year median) equal-weight, annual June formations, 12-month
holds, NO floor, tiered program costs, vanished->ZERO, 20-seed placebos
sharing the chassis. Simulation only. Public data + published signal only."""
import json, os, math, random, statistics
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FAM = os.path.join(HERE, '..')
V12 = os.path.join(FAM, '..', '..', 'v12-completions', 'catalog-hxz-debt-structure')
W04 = os.path.join(FAM, '..', '..', 'v11-native-rules', '_w04_broad_data')
WFR = os.path.join(W04, 'frames')
LFR = os.path.join(V12, 'data', 'frames')

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

YEARS = list(range(2009, 2026))
def F_series(tag, suf):
    return {y: frame(tag, y, suf) for y in YEARS}
SH = F_series('Shares', 'I')
LTD = F_series('LongTermDebt', 'I')
DCUR = F_series('DebtCurrent', 'I')
SEC = F_series('SecuredDebt', 'I')

sf = {}
for cik in cand:
    avail = [(y, SH[y][cik]) for y in YEARS if cik in SH[y]]
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

# === SIGNAL: Sdd with ZERO-IF-SILENT (frozen convention) ===
def build_signals():
    """Returns {F: {cik: sdd}}, plus diagnostics per F."""
    out, diag = {}, {}
    for F in range(2016, 2026):
        y = F - 1; d = {}; n_silent = 0; n_reported = 0; n_err = 0
        for cik in cand:
            sic = str(cand[cik].get('sic') or '')
            if sic[:1] == '6': continue  # native universe: ex-financials
            td = debt(y, cik)
            if not td or td <= 0: continue
            sec = SEC[y].get(cik)
            if sec is None:
                sdd = 0.0; n_silent += 1
            else:
                sdd = sec / td; n_reported += 1
            if sdd > 1.0: n_err += 1; continue  # reporting error, frozen drop
            d[cik] = sdd
        out[F] = d
        diag[F] = {'eligible_with_debt': len(d), 'zero_if_silent': n_silent,
                   'reported_secured': n_reported, 'dropped_sdd_gt_1': n_err}
    return out, diag

SIG, DIAG = build_signals()

POOLS = {}
for F in range(2016, 2026):
    pool = {}
    for cik, sdd in SIG.get(F, {}).items():
        if cik not in px: continue
        e = px[cik].get(ym(F, 6))
        if not e or not e[0]: continue
        cap = cap_of(cik, F)
        pool[cik] = {'sdd': sdd, 'cap': cap, 'rate': cost_rate(cap), 'px0': e[0]}
    POOLS[F] = pool

MATS = {}
for F in range(2016, 2026):
    cols = [ym(F, m) for m in range(6, 13)] + [ym(F + 1, m) for m in range(1, 7)]
    pool = POOLS[F]
    ciks = sorted(pool)
    M = np.full((len(ciks), len(cols)), np.nan)
    for i, cik in enumerate(ciks):
        s = px[cik]; last = None; lastbar = max(s) if s else None
        for j, mm in enumerate(cols):
            if mm in s: last = s[mm][0]
            if lastbar is not None and mm > lastbar: M[i, j] = 0.0
            elif last is not None: M[i, j] = last
    MATS[F] = (ciks, M)

def picks_for(F):
    """Upper half: Sdd strictly above the formation-year median."""
    pool = POOLS[F]
    if not pool: return []
    med = statistics.median(v['sdd'] for v in pool.values())
    return sorted([c for c, v in pool.items() if v['sdd'] > med])

def run_road(formations, seed=None):
    cash = 100.0; curve = []; total_costs = 0.0; year_rets = []
    for F in formations:
        start_cash = cash
        ciks_all, M = MATS[F]
        idx = {c: i for i, c in enumerate(ciks_all)}
        pool = POOLS[F]
        if seed is None:
            picks = picks_for(F)
        else:
            rng = random.Random(seed * 100003 + F)
            keys = sorted(pool); rng.shuffle(keys)
            picks = keys[:len(picks_for(F))]
        cols = [ym(F, m) for m in range(6, 13)] + [ym(F + 1, m) for m in range(1, 7)]
        if not picks:
            for mm in cols[1:]: curve.append([mm, round(cash, 2)])
            year_rets.append(0.0); continue
        rows = np.array([idx[c] for c in picks])
        P = M[rows, :]
        rates = np.array([pool[c]['rate'] for c in picks])
        px0 = P[:, 0].copy(); px0[px0 <= 0] = np.nan
        w = cash / len(picks)
        shares = np.where(np.isnan(px0), 0.0, (w * (1 - rates)) / np.where(np.isnan(px0), 1.0, px0))
        total_costs += float(np.sum(w * rates))
        for j in range(1, 13):
            pj = P[:, j]
            vals = shares * np.where(np.isnan(pj), 0.0, pj)
            val = float(np.sum(vals))
            if j == 12:
                sell = float(np.sum(vals * rates)); total_costs += sell; cash = val - sell
            else:
                cash = val
            curve.append([cols[j], round(cash, 2)])
        year_rets.append(round(cash / start_cash - 1.0, 4) if start_cash else 0.0)
    peak2 = 100.0; maxdd = 0.0
    for _, v in curve:
        peak2 = max(peak2, v); maxdd = max(maxdd, 1 - v / peak2) if peak2 else 0.0
    return round(cash, 2), curve, round(total_costs, 2), round(maxdd, 4), year_rets

def distribution(curve, year_rets):
    if not year_rets: return {}
    med = statistics.median(year_rets)
    pos = sum(1 for r in year_rets if r > 0)
    streak = cur = 0
    for r in year_rets:
        cur = cur + 1 if r <= 0 else 0
        streak = max(streak, cur)
    # longest stretch between new highs, in months, from monthly curve
    peak = -1.0; last_high = 0; longest = 0
    vals = [100.0] + [v for _, v in curve]
    for i, v in enumerate(vals):
        if v >= peak: peak = v; last_high = i
        longest = max(longest, i - last_high)
    return {'n_periods': len(year_rets), 'median_period': round(med, 4),
            'share_positive': round(pos / len(year_rets), 3),
            'best_period': round(max(year_rets), 4), 'worst_period': round(min(year_rets), 4),
            'longest_losing_streak': streak, 'longest_months_between_highs': longest,
            'mean_period_secondary': round(sum(year_rets) / len(year_rets), 4),
            'year_rets': year_rets}

ROADS = {'LONG': list(range(2016, 2026)), 'DECADE': list(range(2017, 2026)),
         'CONT': list(range(2019, 2026)), 'VAL': list(range(2023, 2026))}

def spy_final(formations):
    a = spy.get(ym(formations[0], 6)); b = spy.get(ym(formations[-1] + 1, 6))
    return round(100 * b / a, 2) if a and b else None

def spy_year(F):
    a = spy.get(ym(F, 6)); b = spy.get(ym(F + 1, 6))
    return round(b / a - 1.0, 4) if a and b else None

def main():
    print('pool diagnostics', json.dumps(DIAG, indent=1), flush=True)
    print('pool sizes (priced)', {F: len(POOLS[F]) for F in POOLS},
          'holdings', {F: len(picks_for(F)) for F in POOLS}, flush=True)
    res = {'family': 'catalog-hxz-debt-structure', 'program': 'v13-best-rules',
           'spec': 'BEST-RULES-SPEC.md',
           'cell': 'Sdd | ZERO-IF-SILENT | native ex-financials | upper-half EW | annual | no floor',
           'pool_diag': DIAG,
           'pool_sizes_priced': {str(F): len(POOLS[F]) for F in POOLS},
           'holdings_per_formation': {str(F): len(picks_for(F)) for F in POOLS},
           'roads': {}}
    for rname, forms in ROADS.items():
        fin, curve, costs, maxdd, yrets = run_road(forms)
        twins = []
        for s in range(1, 21):
            tf, _, _, _, _ = run_road(forms, seed=s)
            twins.append(tf)
        res['roads'][rname] = {
            'formations': forms, 'final': fin, 'costs': costs, 'max_dd': maxdd,
            'spy_same_window': spy_final(forms),
            'placebo_finals': twins, 'placebos_beaten': sum(1 for t in twins if fin > t),
            'distribution': distribution(curve, yrets), 'curve': curve}
        print(rname, fin, 'dd', maxdd, 'spy', spy_final(forms), 'pb',
              res['roads'][rname]['placebos_beaten'], '/20', flush=True)
    # Confirmation machinery (frozen bars in spec) — computed for every road,
    # CLAIM only counts if a road first beats the champion print.
    conf = {}
    for rname, forms in ROADS.items():
        folds = {}
        for F in forms:
            f_fin, _, _, _, f_yrets = run_road([F])
            folds[str(F)] = {'final': f_fin, 'ret': f_yrets[0], 'spy_ret': spy_year(F),
                             'beats_spy': (f_yrets[0] > (spy_year(F) or 0))}
        half = len(forms) // 2
        h1, h2 = forms[:half], forms[half:]
        h1_fin, _, _, _, _ = run_road(h1); h2_fin, _, _, _, _ = run_road(h2)
        conf[rname] = {'year_folds': folds,
                       'years_beating_spy': sum(1 for v in folds.values() if v['beats_spy']),
                       'n_years': len(folds),
                       'half1': {'formations': h1, 'final': h1_fin, 'spy_same_window': spy_final(h1)},
                       'half2': {'formations': h2, 'final': h2_fin, 'spy_same_window': spy_final(h2)},
                       'halves_summed': round(h1_fin + h2_fin - 100.0, 2)}
        print(rname, 'CONF folds beat SPY', conf[rname]['years_beating_spy'], '/', len(folds),
              'halves', h1_fin, h2_fin, 'summed', conf[rname]['halves_summed'], flush=True)
    res['confirmation'] = conf
    with open(os.path.join(FAM, 'results.json'), 'w') as fh:
        json.dump(res, fh, indent=1)
    print('saved results.json')

if __name__ == '__main__':
    main()
