#!/usr/bin/env python3
"""V13 best-rules run — catalog-hxz-order-backlog (CONSTRUCTED RPO form).
Chassis frozen in BEST-RULES-SPEC.md: signal = RPO/assets (same fiscal
quarter, PIT lag ~2 months), quarterly formations Mar/Jun/Sep/Dec,
broad reporter universe (non-reporters EXCLUDED, never zero-filled),
top QUINTILE equal weight, long-only, NO floor, tiered program costs
on traded amounts, vanished->ZERO, 20-seed placebos same chassis.
Simulation only. W04 stack + v12 frames are read-only inputs."""
import json, os, math, random, statistics
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
FAM = os.path.join(HERE, '..')
FR = os.path.join(FAM, 'data', 'frames')
W04 = os.path.join(FAM, '..', '..', 'v11-native-rules', '_w04_broad_data')
def loadj(p): return json.load(open(p)) if os.path.exists(p) else {}
def frames(tag, y, q):
    return {int(k): v for k, v in loadj(os.path.join(FR, f'{tag}_CY{y}Q{q}I.json')).items()}
cand = {int(k): v for k, v in loadj(os.path.join(W04, 'candidates.json')).items()}
px = {}
for cik, info in cand.items():
    t = info['ticker'].replace('/', '-')
    p = os.path.join(W04, f'px_{t}.json')
    if os.path.exists(p):
        try: px[cik] = {r[0]: (r[1], r[2]) for r in loadj(p)}
        except Exception: pass
spy = {r[0]: r[1] for r in loadj(os.path.join(W04, 'px_SPY.json'))}
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
def cap_of(cik, F, ymkey):
    sh = shares_f.get(F - 1, {}).get(cik) or shares_f.get(F - 2, {}).get(cik)
    s = px.get(cik)
    if not sh or not s: return None
    e = s.get(ymkey)
    if not e or not e[1]: return None
    return sh * e[1] * sf.get(cik, {}).get(F, 1.0)
def cost_rate(cap):
    if cap is None: return 0.0075
    if cap >= 5e9: return 0.0010
    if cap >= 1e9: return 0.0025
    return 0.0075
def ym(y, m): return f'{y:04d}-{m:02d}'
def months_between(a, b):
    y0, m0 = int(a[:4]), int(a[5:7]); y1, m1 = int(b[:4]), int(b[5:7])
    out = []; y, m = y0, m0
    while (y, m) <= (y1, m1):
        out.append(ym(y, m)); m += 1
        if m == 13: y += 1; m = 1
    return out
# ---- formations: (form_ym, data_year, data_quarter) ----
FORMATIONS = []
for Y in range(2019, 2027):
    FORMATIONS.append((ym(Y, 3), Y - 1, 4))
    FORMATIONS.append((ym(Y, 6), Y, 1))
    FORMATIONS.append((ym(Y, 9), Y, 2))
    if Y <= 2025: FORMATIONS.append((ym(Y, 12), Y, 3))
    else: FORMATIONS.append((ym(Y, 12), Y, 3))
FORMATIONS = [f for f in FORMATIONS if f[0] <= '2026-09']
END = '2026-11'
POOLS = {}
for (fym, dy, dq) in FORMATIONS:
    rpo = frames('RevenueRemainingPerformanceObligation', dy, dq)
    ast = frames('Assets', dy, dq)
    pool = {}
    for cik in cand:
        if cik not in px or cik not in rpo or cik not in ast: continue
        if not ast[cik] or ast[cik] <= 0: continue
        e = px[cik].get(fym)
        if not e or not e[0]: continue
        cap = cap_of(cik, int(fym[:4]), fym)
        pool[cik] = {'sig': rpo[cik] / ast[cik], 'cap': cap, 'rate': cost_rate(cap)}
    POOLS[fym] = pool
def price_at(cik, mm, state):
    """last carried price; 0.0 after the name's last bar (vanished->ZERO)."""
    s = px[cik]
    if mm in s: state[cik] = s[mm][0]
    lastbar = max(s) if s else None
    if lastbar is not None and mm > lastbar: return 0.0
    return state.get(cik)
def picks_for(fym, seed=None):
    pool = POOLS[fym]
    n = max(1, math.ceil(len(pool) * 0.20))
    if seed is None:
        items = sorted(pool.items(), key=lambda kv: -kv[1]['sig'])
        return [c for c, _ in items[:n]]
    rng = random.Random(seed * 100003 + int(fym[:4]) * 100 + int(fym[5:7]))
    keys = list(pool.keys()); rng.shuffle(keys)
    return keys[:n]
def add_months(a, k):
    y, m = int(a[:4]), int(a[5:7]) + k
    while m > 12: y += 1; m -= 12
    return ym(y, m)
def run_road(form_yms, seed=None):
    cash = 100.0; shares = {}; state = {}; total_costs = 0.0
    curve = []; form_marks = []
    end = min(add_months(form_yms[-1], 3), END)
    all_months = months_between(form_yms[0], end)
    fset = set(form_yms)
    for mm in all_months:
        if mm in fset:
            pool = POOLS[mm]
            picks = picks_for(mm, seed)
            vals = {}
            for c, sh in shares.items():
                p = price_at(c, mm, state)
                vals[c] = sh * p if (sh and p) else 0.0
            V = cash + sum(vals.values())
            if picks and V > 0:
                tgt_pre = V / len(picks)
                C = 0.0
                for c in picks:
                    C += abs(tgt_pre - vals.get(c, 0.0)) * pool[c]['rate']
                for c in vals:
                    if c not in picks: C += vals[c] * (pool.get(c, {}).get('rate') or cost_rate(cap_of(c, int(mm[:4]), mm)))
                total_costs += C; V2 = V - C; tgt = V2 / len(picks)
                newshares = {}
                for c in picks:
                    p = price_at(c, mm, state)
                    if p and p > 0: newshares[c] = tgt / p
                shares = newshares; cash = V2 - sum(newshares[c] * price_at(c, mm, state) for c in newshares)
            form_marks.append([mm, round(cash + sum((sh * (price_at(c, mm, state) or 0.0)) for c, sh in shares.items()), 2)])
        val = cash
        for c, sh in shares.items():
            p = price_at(c, mm, state)
            if sh and p: val += sh * p
        curve.append([mm, round(val, 2)])
    # final liquidation at end mark with sell costs
    final = cash; lastf = form_yms[-1]
    for c, sh in shares.items():
        p = price_at(c, end, state)
        if sh and p:
            r = POOLS[lastf].get(c, {}).get('rate')
            if r is None: r = cost_rate(cap_of(c, int(end[:4]), end))
            final += sh * p * (1 - r); total_costs += sh * p * r
    curve[-1] = [end, round(final, 2)]
    peak = 100.0; maxdd = 0.0
    for _, v in curve:
        peak = max(peak, v); maxdd = max(maxdd, 1 - v / peak) if peak else 0.0
    return round(final, 2), curve, form_marks, round(total_costs, 2), round(maxdd, 4)
def spy_final(a, b):
    x, y = spy.get(a), spy.get(b)
    return round(100 * y / x, 2) if x and y else None
def dist(form_marks, final, curve):
    pts = [100.0] + [v for _, v in form_marks[1:]] + [final]
    # period boundaries: start 100, then each formation mark after the first, then final
    rets = [pts[i] / pts[i - 1] - 1 for i in range(1, len(pts)) if pts[i - 1] > 0]
    pos = sum(1 for r in rets if r > 0); run = 0; worst_run = 0
    for r in rets:
        run = run + 1 if r <= 0 else 0; worst_run = max(worst_run, run)
    vals = [100.0] + [v for _, v in curve]
    peak = vals[0]; longest = 0; cur = 0
    for v in vals:
        if v >= peak: peak = v; cur = 0
        else: cur += 1; longest = max(longest, cur)
    return {'periods': len(rets), 'positive': pos,
            'median_pct': round(statistics.median(rets) * 100, 1) if rets else None,
            'mean_pct_secondary': round(statistics.mean(rets) * 100, 1) if rets else None,
            'best_pct': round(max(rets) * 100, 1) if rets else None,
            'worst_pct': round(min(rets) * 100, 1) if rets else None,
            'quarterly_pct': [round(r * 100, 1) for r in rets],
            'longest_losing_streak_periods': worst_run,
            'longest_months_between_highs': longest}
def main():
    all_f = [f for f, _, _ in FORMATIONS]
    roads = {'MAIN_2019_2026': all_f, 'VAL': [f for f in all_f if f >= '2023-03']}
    out = {'family': 'catalog-hxz-order-backlog', 'spec': 'BEST-RULES-SPEC.md',
           'label': 'CONSTRUCTED (ASC-606 RPO proxy for Compustat OB)',
           'formations': all_f,
           'pool_sizes': {f: len(POOLS[f]) for f in all_f},
           'quintile_counts': {f: max(1, math.ceil(len(POOLS[f]) * 0.20)) for f in all_f},
           'roads': {}}
    for rname, forms in roads.items():
        fin, curve, fmarks, costs, maxdd = run_road(forms)
        twins = []
        for s in range(1, 21):
            tf, _, _, _, _ = run_road(forms, seed=s); twins.append(tf)
        out['roads'][rname] = {'final': fin, 'costs': costs, 'max_dd': maxdd,
                               'spy_same_window': spy_final(forms[0], END),
                               'placebo_finals': twins,
                               'placebos_beaten': sum(1 for t in twins if fin > t),
                               'curve': curve, 'formation_marks': fmarks,
                               'distribution': dist(fmarks, fin, curve)}
        print(rname, fin, 'costs', costs, 'maxdd', maxdd, 'spy', out['roads'][rname]['spy_same_window'],
              'pb', out['roads'][rname]['placebos_beaten'], flush=True)
    # confirmation machinery (runs regardless; verdict logic reads it)
    conf = {'year_folds': {}, 'half_windows': {}}
    for Y in range(2019, 2027):
        forms = [f for f in all_f if f[:4] == str(Y)]
        if len(forms) < 4: continue
        fin, curve, fmarks, costs, maxdd = run_road(forms)
        endm = curve[-1][0]
        conf['year_folds'][str(Y)] = {'final': fin, 'max_dd': maxdd,
                                      'spy_same_window': spy_final(forms[0], endm)}
    half = len(all_f) // 2
    for nm, forms in (('FIRST_HALF', all_f[:half]), ('SECOND_HALF', all_f[half:])):
        fin, curve, fmarks, costs, maxdd = run_road(forms)
        conf['half_windows'][nm] = {'final': fin, 'max_dd': maxdd, 'formations': forms,
                                    'spy_same_window': spy_final(forms[0], curve[-1][0])}
    out['confirmation'] = conf
    print('folds', {k: (v['final'], v['spy_same_window']) for k, v in conf['year_folds'].items()}, flush=True)
    print('halves', {k: (v['final'], v['spy_same_window']) for k, v in conf['half_windows'].items()}, flush=True)
    with open(os.path.join(FAM, 'results.json'), 'w') as fh: json.dump(out, fh, indent=1)
    print('saved results.json')
if __name__ == '__main__': main()
