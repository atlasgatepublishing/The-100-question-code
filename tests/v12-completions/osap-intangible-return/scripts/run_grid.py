#!/usr/bin/env python3
"""Grid engine for osap-intangible-return (CONSTRUCTED rebuild).
Frozen design: SPEC-FROZEN.md + SPEC-ADDENDUM.md. Long LOWEST Intan
(Sign -1), equal weight, full sell+buy at each formation, tiered
program costs, ZERO-on-vanish baked into the panel return matrix,
v9 house rulebook = -15% peak floor / 90-day sit-out / one restart /
second halt ends. 20-seed placebos per cell. Writes results.json."""
import json, os, pickle, math, random
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MY = os.path.join(HERE, '..', 'data')
P = pickle.load(open(os.path.join(MY, 'panel.pkl'), 'rb'))
MONTHS = P['months']; MIDX = {s: i for i, s in enumerate(MONTHS)}
RET = P['ret']; CAP = P['cap']; NF = len(P['ciks'])
SIGNALS = P['signals']

spy = {r[0]: r[1] for r in json.load(open(os.path.join(MY, 'spy_monthly.json')))}

def cost_rate(cap):
    if cap is None or not np.isfinite(cap): return 0.0075
    if cap >= 5e9: return 0.0010
    if cap >= 1e9: return 0.0025
    return 0.0075

# composite: firms present in all four signals; score = mean pct rank
def build_composite():
    comp = {}
    names = ['IntanBM', 'IntanCFP', 'IntanEP', 'IntanSP']
    months = set(SIGNALS['IntanBM'])
    for s in names[1:]: months &= set(SIGNALS[s])
    for m in months:
        per = []
        base = None
        for s in names:
            idx, val = SIGNALS[s][m]
            d = dict(zip(idx.tolist(), val.tolist()))
            per.append(d)
            base = set(d) if base is None else base & set(d)
        firms = sorted(base)
        if len(firms) < 100: continue
        score = {}
        for d in per:
            order = sorted(firms, key=lambda f: d[f])
            for r, f in enumerate(order):
                score[f] = score.get(f, 0.0) + (r / (len(firms) - 1) if len(firms) > 1 else 0.5)
        idx = np.array(firms, dtype=np.int32)
        val = np.array([score[f] / 4.0 for f in firms])
        comp[m] = (idx, val)
    return comp

SIGNALS['COMPOSITE'] = build_composite()

def picks_for(sig, mstr, count, rng=None):
    if mstr not in SIGNALS[sig]: return None, 0
    idx, val = SIGNALS[sig][mstr]
    n_elig = len(idx)
    k = max(1, math.ceil(0.10 * n_elig)) if count == 'ALL' else min(count, n_elig)
    if rng is not None:
        sel = rng.choice(idx, size=k, replace=False)
        return np.sort(sel), n_elig
    order = np.argsort(val, kind='stable')[:k]
    return np.sort(idx[order]), n_elig

def simulate(sig, cadence, count, rulebook, start_m, end_form_m, seed=None):
    """Formations at months start_m, +cadence, ... <= end_form_m.
    Buy at formation close; curve monthly to last formation + cadence
    (capped at final panel month). Returns dict or None if no data."""
    rng = random.Random(seed) if seed is not None else None
    np_rng = np.random.default_rng(seed) if seed is not None else None
    forms = []
    j = MIDX[start_m]
    while j <= MIDX[end_form_m]:
        forms.append(j); j += cadence
    if not forms: return None
    end_j = min(forms[-1] + cadence, len(MONTHS) - 1)
    equity = 100.0; peak = 100.0; total_costs = 0.0; n_orders = 0
    curve = [[start_m, 100.0]]
    weights = None  # (firm_idx array, weight array)
    in_cash = False; restarts = 0; sitout_until = -1; halted = False
    form_set = set(forms)
    for t in range(MIDX[start_m] + 1, end_j + 1):
        if (t - 1) in form_set and not halted:
            fm = MONTHS[t - 1]
            if in_cash and (t - 1) < sitout_until:
                pass  # still sitting out; skip formation
            else:
                if seed is None:
                    picks, n_elig = picks_for(sig, fm, count)
                else:
                    picks, n_elig = picks_for(sig, fm, count, rng=np_rng)
                if picks is not None and len(picks) > 0:
                    if weights is not None:
                        sell_frac = float(np.sum(weights[1] * np.array(
                            [cost_rate(CAP[f, t - 1]) for f in weights[0]])))
                        c = equity * sell_frac; total_costs += c; equity -= c
                        n_orders += len(weights[0])
                    w = np.full(len(picks), 1.0 / len(picks))
                    buy_frac = float(np.sum(w * np.array(
                        [cost_rate(CAP[f, t - 1]) for f in picks])))
                    c = equity * buy_frac; total_costs += c; equity -= c
                    n_orders += len(picks)
                    weights = (picks, w); in_cash = False
        if weights is not None and not in_cash:
            r = float(np.sum(weights[1] * RET[weights[0], t]))
            equity *= (1.0 + r)
        curve.append([MONTHS[t], round(equity, 4)])
        peak = max(peak, equity)
        if rulebook == 'house' and not in_cash and weights is not None and equity <= 0.85 * peak:
            sell_frac = float(np.sum(weights[1] * np.array(
                [cost_rate(CAP[f, t]) for f in weights[0]])))
            c = equity * sell_frac; total_costs += c; equity -= c
            n_orders += len(weights[0])
            curve[-1] = [MONTHS[t], round(equity, 4)]
            weights = None; in_cash = True
            if restarts >= 1:
                halted = True
            else:
                restarts += 1; sitout_until = t + 3
    if weights is not None:
        sell_frac = float(np.sum(weights[1] * np.array(
            [cost_rate(CAP[f, end_j]) for f in weights[0]])))
        c = equity * sell_frac; total_costs += c; equity -= c
        n_orders += len(weights[0])
        curve[-1] = [MONTHS[end_j], round(equity, 4)]
    peak = 100.0; maxdd = 0.0
    for _, v in curve:
        peak = max(peak, v); maxdd = max(maxdd, 1 - v / peak)
    spy_f = None
    a, b = spy.get(start_m), spy.get(MONTHS[end_j])
    if a and b: spy_f = round(100 * b / a, 2)
    return {'final': round(equity, 2), 'max_dd': round(maxdd, 4),
            'costs': round(total_costs, 2), 'orders': n_orders,
            'curve': curve, 'spy_final_same_window': spy_f,
            'floor_halts': restarts + (1 if halted else 0) if rulebook == 'house' else 0}

ROADS = {'LONGEST': ('2015-01', '2025-12'), 'DECADE': ('2016-01', '2025-12'),
         'CONT': ('2019-01', '2025-12'), 'VAL': ('2023-01', '2025-12')}
FOLDS = {'FOLD16_20': ('2016-01', '2020-12'), 'FOLD21_25': ('2021-01', '2025-12')}
COUNTS_M = [1, 2, 3, 5, 8, 10, 15, 20, 30, 'ALL']
COUNTS_S = [5, 10, 30, 'ALL']

def run_cell(sig, cadence, count, rulebook, road, s, e):
    base = simulate(sig, cadence, count, rulebook, s, e)
    if base is None: return None
    beaten = 0; pfin = []
    for seed in range(20):
        ps = simulate(sig, cadence, count, rulebook, s, e, seed=1000 + seed)
        if ps is None: continue
        pfin.append(ps['final'])
        if base['final'] > ps['final']: beaten += 1
    base['placebo_beaten'] = beaten
    base['placebo_finals'] = [round(x, 2) for x in pfin]
    return base

def main():
    results = {'family': 'osap-intangible-return', 'grade': 'CONSTRUCTED',
               'signals': {}, 'folds': {},
               'champions': {'VM': {'LONG': 1415.62, 'DECADE': 667.35, 'CONT': 544.47, 'VAL': 288.05},
                             'SPY_program': {'LONG': 822.94, 'DECADE': 367.80, 'CONT': 313.62, 'VAL': 187.77}},
               'cross_section': {s: P['sig_stats'][s] for s in
                                 ['IntanBM', 'IntanCFP', 'IntanEP', 'IntanSP']}}
    for sig in ['IntanBM', 'IntanCFP', 'IntanEP', 'IntanSP', 'COMPOSITE']:
        results['signals'][sig] = {}
        for cadence, counts, books in ((1, COUNTS_M, ('native', 'house')),
                                       (3, COUNTS_S, ('native',)),
                                       (6, COUNTS_S, ('native',)),
                                       (12, COUNTS_S, ('native',))):
            for count in counts:
                for book in books:
                    key = f'cad{cadence}_n{count}_{book}'
                    cell = {}
                    for road, (s, e) in ROADS.items():
                        r = run_cell(sig, cadence, count, book, road, s, e)
                        if r: cell[road] = r
                    results['signals'][sig][key] = cell
                    print(sig, key, {k: v['final'] for k, v in cell.items()}, flush=True)
        # folds for monthly native cells (confirmation machinery)
        results['folds'][sig] = {}
        for count in COUNTS_M:
            key = f'cad1_n{count}_native'
            fc = {}
            for fold, (s, e) in FOLDS.items():
                r = run_cell(sig, 1, count, 'native', fold, s, e)
                if r: fc[fold] = r
            results['folds'][sig][key] = fc
    with open(os.path.join(MY, '..', 'results.json'), 'w') as f:
        json.dump(results, f)
    print('results.json written')

if __name__ == '__main__':
    main()
