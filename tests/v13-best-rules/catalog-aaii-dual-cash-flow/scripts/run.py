#!/usr/bin/env python3
"""V13 best-rules run for catalog-aaii-dual-cash-flow.
Spec: ../BEST-RULES-SPEC.md (frozen before this run).
Primary: S_dualcf (annual adaptation, criteria as published), native
universe, ANNUAL June formations, ALL passing equal-weight, NO floor,
cash in zero-passer years. Control: plain cash-flow yield top-10, same
chassis. Placebos: 20 seeds — primary draws same count from the full
base pool; control draws random 10 from its cf>0 pool.
Reuses the v12 engine's data layer (copied alongside, paths repointed
to the read-only v12 frames). Simulation only."""
import json, os, sys, random
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E

HERE = os.path.dirname(os.path.abspath(__file__))
FAM = os.path.join(HERE, '..')
HOLD = 12
NS = 21  # arm 0 = strategy, 1..20 = placebos

def simulate(forms, picker):
    """picker(F, fi) -> list of 21 pick-arrays (positions into F arrays)."""
    cash = np.full(NS, 100.0); costs = 0.0; curve = []
    period_rets = []  # strategy annual period returns
    pool_sizes = []
    for fi, ym in enumerate(forms):
        F = E.features(ym)
        picks, npool = picker(F, fi)
        pool_sizes.append(int(npool))
        start = cash.copy()
        if len(picks[0]) == 0:
            for j in range(1, HOLD + 1):
                curve.append([E.ym_add(ym, j), round(float(cash[0]), 2)])
            period_rets.append(0.0)
            continue
        M = E.price_matrix(F['idx'], ym, HOLD)
        rates = F['rate']
        vals_end = cash.copy()
        for s in range(NS):
            pk = picks[s]
            P = M[pk, :]; r = rates[pk]
            p0 = P[:, 0].copy(); p0[p0 <= 0] = np.nan
            w = cash[s] / len(pk)
            sh = np.where(np.isnan(p0), 0.0, w * (1 - r) / np.where(np.isnan(p0), 1.0, p0))
            if s == 0: costs += float(np.sum(w * r))
            live = sh[:, None] * np.where(np.isnan(P), 0.0, P)
            v = live[:, HOLD].sum()
            sell = (live[:, HOLD] * r).sum()
            v -= sell
            if s == 0: costs += float(sell)
            vals_end[s] = v
        # monthly curve for strategy arm
        pk = picks[0]; P = M[pk, :]; r = rates[pk]
        p0 = P[:, 0].copy(); p0[p0 <= 0] = np.nan
        w = cash[0] / len(pk)
        sh = np.where(np.isnan(p0), 0.0, w * (1 - r) / np.where(np.isnan(p0), 1.0, p0))
        live = sh[:, None] * np.where(np.isnan(P), 0.0, P)
        for j in range(1, HOLD + 1):
            v = live[:, j].sum()
            if j == HOLD: v -= (live[:, j] * r).sum()
            curve.append([E.ym_add(ym, j), round(float(v), 2)])
        period_rets.append(float(vals_end[0] / start[0] - 1) if start[0] > 0 else 0.0)
        cash = vals_end
    peak = 100.0; maxdd = 0.0; high = 100.0; since_high = 0; longest_gap = 0
    for _, v in curve:
        peak = max(peak, v); maxdd = max(maxdd, 1 - v / peak) if peak else 0.0
        if v >= high: high = v; since_high = 0
        else: since_high += 1; longest_gap = max(longest_gap, since_high)
    los = 0; longest_los = 0
    for r_ in period_rets:
        los = los + 1 if r_ < 0 else 0; longest_los = max(longest_los, los)
    pos = [r_ for r_ in period_rets]
    spyfin = None
    if forms:
        a = E.spy.get(forms[0]); b = E.spy.get(E.ym_add(forms[-1], HOLD))
        spyfin = round(100 * b / a, 2) if a and b else None
    return {'final': round(float(cash[0]), 2), 'costs': round(costs, 2),
            'max_dd': round(maxdd, 4), 'spy_same_window': spyfin,
            'placebo_finals': [round(float(x), 2) for x in cash[1:]],
            'placebos_beaten': int(sum(1 for x in cash[1:] if cash[0] > x)),
            'curve': curve, 'pool_sizes': pool_sizes,
            'distribution': {
                'n_periods': len(pos),
                'share_positive': round(float(np.mean([1 if r_ > 0 else 0 for r_ in pos])), 4) if pos else None,
                'median_period': round(float(np.median(pos)), 4) if pos else None,
                'mean_period_secondary': round(float(np.mean(pos)), 4) if pos else None,
                'best_period': round(float(max(pos)), 4) if pos else None,
                'worst_period': round(float(min(pos)), 4) if pos else None,
                'longest_losing_streak_periods': longest_los,
                'longest_stretch_between_new_highs_months': longest_gap,
                'period_returns': [round(float(r_), 4) for r_ in pos]}}

def primary_picker(F, fi):
    mask, rank = E.S_dualcf(F, 'native')
    pool_pos = np.where(mask)[0]
    n = len(pool_pos)
    base = np.where(F['otc'] == 0)[0]
    picks = [pool_pos]
    for s in range(1, NS):
        rng = random.Random(s * 100003 + fi * 131 + E.MIDX[F['ym']])
        picks.append(np.array(rng.sample(list(base), n)) if 0 < n <= len(base) else np.array([], dtype=int))
    return picks, n

def control_picker(F, fi):
    with np.errstate(invalid='ignore', divide='ignore'):
        cfy = np.where(F['cf'] > 0, F['cf'] / np.where(F['cap'] > 0, F['cap'], np.nan), np.nan)
    elig = np.where(~np.isnan(cfy) & (F['otc'] == 0))[0]
    order = elig[np.argsort(-cfy[elig])]
    top = order[:10]
    picks = [top]
    for s in range(1, NS):
        rng = random.Random(s * 777001 + fi * 131 + E.MIDX[F['ym']])
        picks.append(np.array(rng.sample(list(elig), min(10, len(elig)))))
    return picks, len(elig)

def main():
    out = {'family': 'catalog-aaii-dual-cash-flow', 'spec': 'BEST-RULES-SPEC.md',
           'arms': {}}
    for arm, picker in (('primary_dualcf_all_annual_nofloor', primary_picker),
                        ('control_plain_cfyield_top10', control_picker)):
        out['arms'][arm] = {}
        for road in ('LONGEST', 'DECADE', 'CONT', 'VAL', 'FOLD1', 'FOLD2'):
            forms = E.formation_months('annual', *E.ROADS[road])
            res = simulate(forms, picker)
            res['road_label'] = {'LONGEST': 'LONG', 'DECADE': 'DECADE', 'CONT': 'CONT',
                                 'VAL': 'VAL', 'FOLD1': 'FOLD1', 'FOLD2': 'FOLD2'}[road]
            res['formations'] = forms
            out['arms'][arm][road] = res
            print(arm, road, res['final'], 'spy', res['spy_same_window'],
                  'pb', res['placebos_beaten'], 'dd', res['max_dd'],
                  'pools', res['pool_sizes'], flush=True)
    json.dump(out, open(os.path.join(FAM, 'results.json'), 'w'), indent=1)
    print('saved results.json')

if __name__ == '__main__':
    main()
