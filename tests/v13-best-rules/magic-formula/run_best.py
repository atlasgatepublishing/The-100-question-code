#!/usr/bin/env python3
"""V13 BEST-RULES Magic Formula run — frozen spec in BEST-RULES-SPEC.md.
Reuses the v11 W04 broad-universe engine (read-only) for data/snapshots.
Design: gated universe (EBIT>0, CFO>0), both-legs top-60% floor, combined
rank, top 40, two staggered tranches/yr (Jun + Dec) each held exactly 1yr,
no floor, tiered habitat costs, 20-seed placebos. Simulation only."""
import json, os, sys, random, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
W04 = os.path.expanduser('~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data')
spec = importlib.util.spec_from_file_location('engine_w04', os.path.join(W04, 'engine_w04.py'))
E = importlib.util.module_from_spec(spec); spec.loader.exec_module(E)
E.D = E.Data()
D = E.D
ym = E.ym

COUNT = 40
LEG_FRAC = 0.60

def tranche_snapshot(F, month):
    """Scored/pickable pool for a tranche forming in year F at `month` (6 or 12).
    Fundamentals always from snapshot(F) (FY ended F-1). For December, cap/EV/EY
    are recomputed at December prices per the frozen spec."""
    s = E.snapshot(F)
    pool = E.eligible_magic(s)
    scored = {}
    for c, v in pool.items():
        ebit = v['opinc'] + (v['interest'] or 0)
        if ebit <= 0: continue
        if v['cfo'] is None or v['cfo'] <= 0: continue
        if month == 12:
            px_raw = D.price(c, ym(F, 12), adj=False); px_adj = D.price(c, ym(F, 12), adj=True)
            if not px_adj or not px_raw or not v['shares']: continue
            cap = v['shares'] * px_raw * D.sf.get(c, {}).get(F, 1.0)
        else:
            px_adj = v['px_adj']; cap = v['cap']
        if not cap or cap < 50e6: continue
        ev = cap + (v['ltd'] or 0) - (v['cash'] or 0)
        capital = (v['ca'] - (v['cash'] or 0)) - v['cl'] + v['ppe']
        if ev <= 0 or capital <= 0: continue
        scored[c] = dict(ey=ebit / ev, roc=ebit / capital, cap=cap, px=px_adj, ticker=v['ticker'])
    if len(scored) < COUNT: return scored, {}
    ey_order = sorted(scored, key=lambda c: -scored[c]['ey'])
    rc_order = sorted(scored, key=lambda c: -scored[c]['roc'])
    ey_rank = {c: i for i, c in enumerate(ey_order)}; rc_rank = {c: i for i, c in enumerate(rc_order)}
    lim = int(LEG_FRAC * len(scored))
    pickable = {c: v for c, v in scored.items() if ey_rank[c] < lim and rc_rank[c] < lim}
    for c in pickable: pickable[c]['combined'] = ey_rank[c] + rc_rank[c]
    return scored, pickable

def tranche_picks(F, month, seed=None):
    scored, pickable = tranche_snapshot(F, month)
    if seed is None:
        picks = sorted(pickable, key=lambda c: pickable[c]['combined'])[:COUNT]
    else:
        rng = random.Random(seed * 7919 + F * 10 + month)
        keys = list(pickable.keys()); rng.shuffle(keys); picks = keys[:COUNT]
    info = {c: (pickable[c] if c in pickable else scored[c]) for c in picks}
    return picks, info, len(scored), len(pickable)

def run_sleeve(month, form_years, seed=None):
    """One seasonal sleeve: starts $50 cash at its first formation, rolls yearly."""
    cash = 50.0; total_costs = 0.0; periods = []; marks = {}
    for F in form_years:
        picks, info, n_scored, n_pick = tranche_picks(F, month, seed)
        start = cash
        if not picks:
            periods.append({'formation': f'{F}-{month:02d}', 'ret': 0.0, 'picks': [], 'n_scored': n_scored, 'n_pickable': n_pick})
            continue
        w = cash / len(picks); pos = {}
        for c in picks:
            rate = E.cost_rate(info[c]['cap']); total_costs += w * rate
            pos[c] = (w - w * rate) / info[c]['px']
        months = [ym(F, m) for m in range(month + 1, 13)] + [ym(F + 1, m) for m in range(1, month + 1)]
        for mm in months:
            val = 0.0
            for c, sh in pos.items():
                p = D.price(c, mm, adj=True)
                if p is None: p = info[c]['px']
                val += sh * p
            marks[mm] = val
        end_val = 0.0
        for c, sh in pos.items():
            p = D.price(c, ym(F + 1, month), adj=True) or info[c]['px']
            gross = sh * p; rate = E.cost_rate(info[c]['cap']); total_costs += gross * rate
            end_val += gross - gross * rate
        cash = end_val
        periods.append({'formation': f'{F}-{month:02d}', 'ret': round(cash / start - 1, 4) if start else 0.0,
                        'picks': [info[c]['ticker'] for c in picks], 'n_scored': n_scored, 'n_pickable': n_pick})
    return cash, total_costs, periods, marks

def run_road(start_year):
    jun_years = list(range(start_year, 2026))          # Jun tranches mature by Jun 2026
    dec_years = list(range(start_year, 2025))          # Dec tranches mature by Dec 2025
    fj, cj, pj, mj = run_sleeve(6, jun_years)
    fd, cd, pd_, md = run_sleeve(12, dec_years)
    # combined monthly curve Jun(start)..Jun 2026; Dec sleeve = $50 cash before Dec start_year, then its marks, then final cash after Dec 2025
    curve = []
    y, m = start_year, 6
    while (y, m) <= (2026, 6):
        key = ym(y, m)
        jv = mj.get(key, fj if (y, m) >= (2025, 6) else None)
        if jv is None:  # before/at first June formation month: sleeve at $50 pre-investment handled by marks from Jul; June itself = 50
            jv = 50.0
        if (y, m) < (start_year, 12): dv = 50.0
        elif key in md: dv = md[key]
        else: dv = fd
        curve.append([key, round(jv + dv, 2)])
        m += 1
        if m == 13: y, m = y + 1, 1
    final = round(curve[-1][1], 2)
    peak = 100.0; maxdd = 0.0
    for _, v in curve: peak = max(peak, v); maxdd = max(maxdd, 1 - v / peak)
    a = D.spy.get(ym(start_year, 6)); b = D.spy.get(ym(2026, 6))
    spy = round(100 * b / a, 2) if a and b else None
    return {'final': final, 'max_dd': round(maxdd, 4), 'costs': round(cj + cd, 2),
            'spy_final_same_window': spy, 'curve': curve, 'periods': pj + pd_}

def placebo_final(start_year, seed):
    tot = 0.0
    for month, years in ((6, list(range(start_year, 2026))), (12, list(range(start_year, 2025)))):
        f, _, _, _ = run_sleeve(month, years, seed=seed)
        tot += f
    return round(tot, 2)

def period_stats(periods):
    rets = sorted(p['ret'] for p in periods)
    if not rets: return {}
    n = len(rets); med = rets[n // 2] if n % 2 else (rets[n // 2 - 1] + rets[n // 2]) / 2
    streak = cur = 0
    for p in periods:
        cur = cur + 1 if p['ret'] <= 0 else 0; streak = max(streak, cur)
    return {'n_periods': n, 'median_ret': round(med, 4), 'share_positive': round(sum(1 for r in rets if r > 0) / n, 3),
            'best': round(rets[-1], 4), 'worst': round(rets[0], 4), 'longest_losing_streak': streak,
            'mean_ret_secondary': round(sum(rets) / n, 4)}

def main():
    res = {'family': 'magic-formula', 'spec': 'v13-best-rules (see BEST-RULES-SPEC.md)', 'count': COUNT}
    for name, sy in (('full_2017', 2017), ('cont_2019', 2019), ('val_2023', 2023),
                     ('fold_2017_2020', None), ('fold_2021_2025', None)):
        if sy is not None:
            r = run_road(sy); res[name] = r
            print(name, r['final'], 'spy', r['spy_final_same_window'], 'dd', r['max_dd'], flush=True)
    # folds: independent pots restricted to formations in the fold window
    for name, yrs in (('fold_2017_2020', (2017, 2020)), ('fold_2021_2025', (2021, 2025))):
        tot = 0.0; costs = 0.0; pers = []
        for month, yrange in ((6, range(yrs[0], yrs[1] + 1)), (12, range(yrs[0], min(yrs[1], 2024) + 1))):
            f, cst, p, _ = run_sleeve(month, list(yrange)); tot += f; costs += cst; pers += p
        res[name] = {'final': round(tot, 2), 'costs': round(costs, 2), 'periods': pers}
        print(name, res[name]['final'], flush=True)
    res['full_2017']['period_stats'] = period_stats(res['full_2017']['periods'])
    twins = []
    for seed in range(1, 21):
        t = placebo_final(2017, seed); twins.append(t); print(' twin', seed, t, flush=True)
    res['placebo_finals_full'] = twins
    res['placebos_beaten_full'] = sum(1 for t in twins if res['full_2017']['final'] > t)
    json.dump(res, open(os.path.join(HERE, 'results.json'), 'w'), indent=1)
    print('saved. full final', res['full_2017']['final'], 'placebos beaten', res['placebos_beaten_full'], '/20')

if __name__ == '__main__':
    main()
