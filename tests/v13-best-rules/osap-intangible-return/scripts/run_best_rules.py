#!/usr/bin/env python3
"""V13 best-rules engine for osap-intangible-return.

Rules (BEST-RULES-SPEC.md, frozen before this run): QUARTERLY formation,
long the LOWEST Intan names, full bottom DECILE of the eligible
cross-section, equal weight, full sell+buy at each formation, program
tiered costs per side, NO floor/stop, $100 pots, ZERO-on-vanish in the
panel returns. Signals: IntanBM/CFP/EP/SP separately + COMPOSITE
(mean percentile rank). 20-seed placebos sharing the chassis.
Confirmation (frozen bars): any road beating its champion is re-run on
DECADE folds 2016-2020 / 2021-2025 and on the road's own half-windows,
fresh $100 each; every fold/half must beat SPY on its window and the
road placebo score must be >= 15/20.
Writes ../results.json with equity curves.
"""
import json, os, math
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MYDATA = os.path.join(HERE, '..', 'data')
OUT = os.path.join(HERE, '..', 'results.json')

P = np.load(os.path.join(MYDATA, 'panel.npz'), allow_pickle=False)
MONTHS = [str(m) for m in P['months']]
MIDX = {s: i for i, s in enumerate(MONTHS)}
RET = P['ret']; CAP = P['cap']
SIG = json.load(open(os.path.join(MYDATA, 'signals.json')))
SIGNALS = {k: {m: (np.array(v[0]), np.array(v[1])) for m, v in d.items()}
           for k, d in SIG['signals'].items()}
spy = {r[0]: r[1] for r in json.load(open(os.path.join(MYDATA, 'spy_monthly.json')))}

def build_composite():
    names = ['IntanBM', 'IntanCFP', 'IntanEP', 'IntanSP']
    months = set(SIGNALS[names[0]])
    for s in names[1:]:
        months &= set(SIGNALS[s])
    comp = {}
    for m in months:
        per = []
        base = None
        for s in names:
            idx, val = SIGNALS[s][m]
            d = dict(zip(idx.tolist(), val.tolist()))
            per.append(d)
            base = set(d) if base is None else base & set(d)
        firms = sorted(base)
        if len(firms) < 100:
            continue
        score = {f: 0.0 for f in firms}
        for d in per:
            order = sorted(firms, key=lambda f: d[f])
            for r, f in enumerate(order):
                score[f] += r / (len(firms) - 1) if len(firms) > 1 else 0.5
        comp[m] = (np.array(firms, dtype=np.int64),
                   np.array([score[f] / 4.0 for f in firms]))
    return comp

SIGNALS['COMPOSITE'] = build_composite()

def cost_rate(cap):
    if cap is None or not np.isfinite(cap):
        return 0.0075
    if cap >= 5e9:
        return 0.0010
    if cap >= 1e9:
        return 0.0025
    return 0.0075

CADENCE = 3  # quarterly, frozen in spec

def picks_for(sig, mstr, rng=None):
    if mstr not in SIGNALS[sig]:
        return None, 0
    idx, val = SIGNALS[sig][mstr]
    n_elig = len(idx)
    k = max(1, math.ceil(0.10 * n_elig))  # bottom decile
    if rng is not None:
        sel = rng.choice(idx, size=k, replace=False)
        return np.sort(sel), n_elig
    order = np.argsort(val, kind='stable')[:k]
    return np.sort(idx[order]), n_elig

def simulate(sig, start_m, end_form_m, seed=None):
    rng = np.random.default_rng(seed) if seed is not None else None
    forms = []
    j = MIDX[start_m]
    while j <= MIDX[end_form_m]:
        forms.append(j); j += CADENCE
    if not forms:
        return None
    end_j = min(forms[-1] + CADENCE, len(MONTHS) - 1)
    form_set = set(forms)
    equity = 100.0; total_costs = 0.0; n_orders = 0
    curve = [[start_m, 100.0]]
    weights = None
    for t in range(MIDX[start_m] + 1, end_j + 1):
        if (t - 1) in form_set:
            fm = MONTHS[t - 1]
            picks, _ = picks_for(sig, fm, rng=rng)
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
                weights = (picks, w)
        if weights is not None:
            r = float(np.sum(weights[1] * RET[weights[0], t]))
            equity *= (1.0 + r)
        curve.append([MONTHS[t], round(equity, 4)])
    if weights is not None:
        sell_frac = float(np.sum(weights[1] * np.array(
            [cost_rate(CAP[f, end_j]) for f in weights[0]])))
        c = equity * sell_frac; total_costs += c; equity -= c
        n_orders += len(weights[0])
        curve[-1] = [MONTHS[end_j], round(equity, 4)]
    peak = 100.0; maxdd = 0.0
    for _, v in curve:
        peak = max(peak, v); maxdd = max(maxdd, 1 - v / peak)
    a, b = spy.get(start_m), spy.get(MONTHS[end_j])
    spy_f = round(100 * b / a, 2) if a and b else None
    return {'final': round(equity, 2), 'max_dd': round(maxdd, 4),
            'costs': round(total_costs, 2), 'orders': n_orders,
            'curve': curve, 'spy_final_same_window': spy_f}

def period_stats(curve):
    vals = [v for _, v in curve]
    rets = [vals[i] / vals[i - 1] - 1.0 for i in range(1, len(vals))]
    if not rets:
        return {}
    med = float(np.median(rets))
    pos = sum(1 for r in rets if r > 0) / len(rets)
    longest_loss = 0; run = 0
    for r in rets:
        run = run + 1 if r < 0 else 0
        longest_loss = max(longest_loss, run)
    # longest stretch between new highs (months)
    peak = vals[0]; last_high = 0; longest_uw = 0
    for i, v in enumerate(vals):
        if v >= peak:
            peak = v; last_high = i
        longest_uw = max(longest_uw, i - last_high)
    return {'n_periods': len(rets), 'median_period': round(med, 4),
            'share_positive': round(pos, 3),
            'best_period': round(max(rets), 4), 'worst_period': round(min(rets), 4),
            'mean_period_secondary': round(float(np.mean(rets)), 4),
            'longest_losing_streak': longest_loss,
            'longest_between_new_highs_months': longest_uw}

ROADS = {'LONGEST': ('2015-01', '2025-12'), 'DECADE': ('2016-01', '2025-12'),
         'CONT': ('2019-01', '2025-12'), 'VAL': ('2023-01', '2025-12')}
CHAMP = {'LONGEST': 1415.62, 'DECADE': 667.35, 'CONT': 544.47, 'VAL': 288.05}

def half_windows(start_m, end_form_m):
    forms = []
    j = MIDX[start_m]
    while j <= MIDX[end_form_m]:
        forms.append(j); j += CADENCE
    mid = forms[len(forms) // 2]
    return (start_m, MONTHS[forms[len(forms) // 2 - 1]]), (MONTHS[mid], end_form_m)

def run_cell(sig, start_m, end_form_m, with_placebos=True):
    base = simulate(sig, start_m, end_form_m)
    if base is None:
        return None
    base['period_stats'] = period_stats(base['curve'])
    if with_placebos:
        beaten = 0; pfin = []
        for seed in range(20):
            ps = simulate(sig, start_m, end_form_m, seed=2000 + seed)
            if ps is None:
                continue
            pfin.append(ps['final'])
            if base['final'] > ps['final']:
                beaten += 1
        base['placebo_beaten'] = beaten
        base['placebo_finals'] = [round(x, 2) for x in pfin]
    return base

def main():
    results = {'family': 'osap-intangible-return', 'program': 'v13-best-rules',
               'grade': 'CONSTRUCTED', 'verdict_ceiling': 'CANDIDATE',
               'rules': 'quarterly formation, bottom decile EW, no floor, tiered costs',
               'champions_VM': {'LONG': 1415.62, 'DECADE': 667.35, 'CONT': 544.47, 'VAL': 288.05},
               'spy_program': {'LONG': 822.94, 'DECADE': 367.80, 'CONT': 313.62, 'VAL': 187.77},
               'signals': {}, 'confirmation': {}}
    for sig in ['IntanBM', 'IntanCFP', 'IntanEP', 'IntanSP', 'COMPOSITE']:
        results['signals'][sig] = {}
        for road, (s, e) in ROADS.items():
            r = run_cell(sig, s, e)
            if r:
                results['signals'][sig][road] = r
            print(sig, road, r['final'] if r else None,
                  'placebo', r.get('placebo_beaten') if r else None, flush=True)
        # confirmation for any champion-beating road
        for road, (s, e) in ROADS.items():
            r = results['signals'][sig].get(road)
            if not r or r['final'] <= CHAMP[road]:
                continue
            conf = {'champion_bar': CHAMP[road], 'road_final': r['final'],
                    'placebo_beaten': r.get('placebo_beaten'), 'checks': {}}
            windows = {}
            if road == 'DECADE':
                windows['FOLD16_20'] = ('2016-01', '2020-12')
                windows['FOLD21_25'] = ('2021-01', '2025-12')
            else:
                h1, h2 = half_windows(s, e)
                windows['HALF1'] = h1; windows['HALF2'] = h2
                windows['FOLD16_20'] = ('2016-01', '2020-12')
                windows['FOLD21_25'] = ('2021-01', '2025-12')
            allpass = r.get('placebo_beaten', 0) >= 15
            for wname, (ws, we) in windows.items():
                if MIDX[ws] < MIDX[s] or MIDX[we] > MIDX[e]:
                    # folds are defined on DECADE span; only apply where inside road
                    if road != 'DECADE' and wname.startswith('FOLD'):
                        continue
                wr = simulate(sig, ws, we)
                if wr is None:
                    continue
                ok = wr['spy_final_same_window'] is not None and wr['final'] > wr['spy_final_same_window']
                conf['checks'][wname] = {'window': [ws, we], 'final': wr['final'],
                                         'spy': wr['spy_final_same_window'],
                                         'max_dd': wr['max_dd'], 'beats_spy': ok}
                allpass = allpass and ok
            conf['confirmed'] = bool(allpass)
            results['confirmation'][f'{sig}_{road}'] = conf
            print('CONFIRMATION', sig, road, conf, flush=True)
    with open(OUT, 'w') as f:
        json.dump(results, f)
    print('results.json written')

if __name__ == '__main__':
    main()
