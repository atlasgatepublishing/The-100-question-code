#!/usr/bin/env python3
"""catalog-aaii-schloss v13 BEST-RULES run. Spec: ../BEST-RULES-SPEC.md (frozen).
Screen = v12 published construction EXACTLY (P/B in (0,1), near-low<=1.10,
debt<equity). Chassis = Schloss carry: ALL passers, annual June review,
sell only on P/B>=1.0 or +50% from entry, no floor, no stop, vanish->ZERO,
program tiered costs. Placebos: 20 seeds, same chassis, random pond names.
Writes only ../results.json. Simulation only."""
import json, os, math, random, statistics
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FAM = os.path.join(HERE, '..')
W04 = os.path.join(FAM, '..', '..', 'v11-native-rules', '_w04_broad_data')
XFR = os.path.join(FAM, '..', '..', 'v12-completions', 'catalog-aaii-pe-relative', 'data', 'frames')

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
months_all = sorted(spy)
LASTBAR = {c: max(s) if s else None for c, s in px.items()}

def frame(name, y, kind):
    d = loadj(os.path.join(W04, 'frames', f'{name}_{y}{kind}.json'))
    return {int(k): v for k, v in d.items()}

YEARS = range(2009, 2026)
F = {}
for name, kind in [('Assets','I'),('StockholdersEquity','I'),('Shares','I'),
                   ('LongTermDebt','I'),('DebtCurrent','I'),('NetIncomeLoss','D')]:
    F[name] = {y: frame(name, y, kind) for y in YEARS}

sf = {}
for cik in cand:
    avail = [(y, F['Shares'][y][cik]) for y in YEARS if cik in F['Shares'][y]]
    d = {}
    for Fy in range(2016, 2027):
        f = 1.0
        for (y0, a), (y1, b) in zip(avail, avail[1:]):
            if y1 >= Fy and a:
                r = b / a
                if r >= 1.6 or r <= 0.625: f *= r
        d[Fy] = f
    sf[cik] = d

def ym(y, m): return f'{y:04d}-{m:02d}'
def june_px(cik, y):
    e = px.get(cik, {}).get(ym(y, 6))
    return e[1] if e and e[1] else None
def adj_at(cik, mm):
    e = px.get(cik, {}).get(mm)
    return e[0] if e and e[0] else None

def cap_of(cik, Fy):
    sh = F['Shares'].get(Fy-1, {}).get(cik) or F['Shares'].get(Fy-2, {}).get(cik)
    s = px.get(cik)
    if not sh or not s: return None
    e = s.get(ym(Fy, 6))
    if not e or not e[1]: return None
    return sh * e[1] * sf.get(cik, {}).get(Fy, 1.0)

def cost_rate(cap):
    if cap is None: return 0.0075
    if cap >= 5e9: return 0.0010
    if cap >= 1e9: return 0.0025
    return 0.0075

def g(cik, name, y): return F[name].get(y, {}).get(cik)

def metrics(cik, Fy):
    y = Fy - 1
    m = {}
    m['eq'] = g(cik, 'StockholdersEquity', y); m['sh'] = g(cik, 'Shares', y)
    m['px'] = june_px(cik, Fy); m['cap'] = cap_of(cik, Fy)
    if not m['px'] or not m['sh']: return None
    m['pb'] = (m['cap'] / m['eq']) if (m['cap'] and m['eq']) else None
    s = px.get(cik, {})
    idx = months_all.index(ym(Fy, 6)) if ym(Fy, 6) in months_all else None
    if idx is not None:
        lo = [s[mm][0] for mm in months_all[max(0, idx-11):idx+1] if mm in s]
        cur = s.get(ym(Fy, 6), (None, None))[0]
        m['near_low'] = (cur / min(lo)) if lo and cur else None
    ltd = g(cik, 'LongTermDebt', y); dc = g(cik, 'DebtCurrent', y) or 0.0
    m['debt'] = (ltd + dc) if ltd is not None else None
    m['rate'] = cost_rate(m['cap'])
    return m

ALLM, POOLS = {}, {}
for Fy in range(2016, 2026):
    ms, passed = {}, {}
    for cik in cand:
        if cik not in px: continue
        mm = metrics(cik, Fy)
        if mm: ms[cik] = mm
    for cik, m in ms.items():
        if m['pb'] and 0 < m['pb'] < 1.0 and m['near_low'] and m['near_low'] <= 1.10:
            if m['debt'] is not None and m['eq'] and m['debt'] < m['eq']:
                passed[cik] = m
    ALLM[Fy] = ms; POOLS[Fy] = passed
    print('formation', Fy, 'pond', len(ms), 'passed', len(passed), flush=True)

def price_series(cik, start_mm, end_mm):
    """adj price per month, last-carried; 0.0 after series end (vanish->ZERO)."""
    s = px.get(cik, {})
    out = {}
    last = None
    mm = start_mm
    while mm <= end_mm:
        if mm in s: last = s[mm][0]
        if LASTBAR.get(cik) is not None and mm > LASTBAR[cik]: out[mm] = 0.0
        elif last is not None: out[mm] = last
        # advance
        y, mo = int(mm[:4]), int(mm[5:7])
        mo += 1
        if mo > 12: y, mo = y + 1, 1
        mm = ym(y, mo)
    return out

def month_list(a, b):
    out = []; y, mo = int(a[:4]), int(a[5:7])
    while ym(y, mo) <= b:
        out.append(ym(y, mo)); mo += 1
        if mo > 12: y, mo = y + 1, 1
    return out

def run_road(start_y, end_y, seed=None):
    """Formations June start_y..end_y-1; marks Jun start_y -> Jun end_y."""
    cash = 100.0; pos = {}  # cik -> [shares, entry_adj_px, rate]
    curve = []; total_costs = 0.0; n_buys = 0; n_sells = 0; vanish = 0
    series_cache = {}
    def series(cik):
        if cik not in series_cache:
            series_cache[cik] = price_series(cik, ym(start_y, 6), ym(end_y, 6))
        return series_cache[cik]
    months = month_list(ym(start_y, 6), ym(end_y, 6))
    for mi, mm in enumerate(months):
        y, mo = int(mm[:4]), int(mm[5:7])
        # vanish check (not at formation month 0)
        for cik in list(pos):
            if series(cik).get(mm, None) == 0.0:
                del pos[cik]; vanish += 1
        if mo == 6 and start_y <= y < end_y:
            Fy = y
            ms = ALLM[Fy]; passed = POOLS[Fy]
            jpx = {c: adj_at(c, mm) for c in pos}
            # exits: P/B discipline or +50% bank
            for cik in list(pos):
                p = jpx.get(cik)
                if p is None or p <= 0: continue
                m = ms.get(cik)
                exit_now = False
                if m is not None and m['pb'] is not None and m['pb'] >= 1.0: exit_now = True
                if pos[cik][1] and p / pos[cik][1] >= 1.50: exit_now = True
                if exit_now:
                    val = pos[cik][0] * p; cst = val * pos[cik][2]
                    cash += val - cst; total_costs += cst; n_sells += 1
                    del pos[cik]
            # entries
            if seed is None:
                new = [c for c in passed if c not in pos]
            else:
                rng = random.Random(seed * 100003 + Fy)
                pond = [c for c in ms if c not in passed and c not in pos and adj_at(c, mm)]
                want = len([c for c in passed if c not in pos])
                rng.shuffle(pond); new = pond[:want]
            for c in new:
                pos[c] = [0.0, adj_at(c, mm), ms[c]['rate'] if c in ms else 0.0075]
                n_buys += 1
            # equal-weight rebalance across whole book
            live = {}
            for c in pos:
                p = adj_at(c, mm)
                if p and p > 0: live[c] = p
            for c in list(pos):
                if c not in live: del pos[c]
            if live:
                total = cash + sum(pos[c][0] * live[c] for c in live)
                tgt0 = total / len(live)
                cst = sum(abs(tgt0 - pos[c][0] * live[c]) * pos[c][2] for c in live)
                total_costs += cst
                tgt = (total - cst) / len(live)
                for c in live:
                    pos[c][0] = tgt / live[c]
                    if pos[c][1] is None: pos[c][1] = live[c]
                cash = 0.0
        val = cash + sum(sh[0] * (series(c).get(mm) or 0.0) for c, sh in pos.items())
        curve.append([mm, round(val, 2)])
    final = curve[-1][1] if curve else cash
    vals = [100.0] + [v for _, v in curve[1:]] if curve else [100.0]
    # curve[0] is formation month at 100 pre-trade approx; use full curve values
    allv = [v for _, v in curve]
    pk = 100.0; maxdd = 0.0
    for v in [100.0] + allv:
        pk = max(pk, v); maxdd = min(maxdd, v / pk - 1) if pk else 0.0
    return {'final': round(final, 2), 'curve': curve, 'costs': round(total_costs, 2),
            'maxdd_pct': round(maxdd * 100, 1), 'buys': n_buys, 'sells': n_sells, 'vanish_zero': vanish}

def spy_final(a, b):
    x, yv = spy.get(a), spy.get(b)
    return round(100.0 * yv / x, 2) if x and yv else None

def period_stats(curve):
    vals = [v for _, v in curve]
    months = [m for m, _ in curve]
    rets = []
    for i in range(12, len(vals), 12):
        if vals[i - 12] > 0: rets.append(vals[i] / vals[i - 12] - 1)
    if not rets: return None
    pos_n = sum(1 for r in rets if r > 0)
    run = worst = 0
    for r in rets:
        run = run + 1 if r <= 0 else 0; worst = max(worst, run)
    peak = vals[0]; cur = longest = 0
    for v in vals:
        if v >= peak: peak = v; cur = 0
        else: cur += 1; longest = max(longest, cur)
    return {'periods': len(rets), 'positive': pos_n,
            'median_pct': round(statistics.median(rets) * 100, 1),
            'mean_pct_secondary': round(statistics.mean(rets) * 100, 1),
            'best_pct': round(max(rets) * 100, 1), 'worst_pct': round(min(rets) * 100, 1),
            'yearly_pct': [round(r * 100, 1) for r in rets],
            'longest_losing_run': worst, 'longest_months_between_highs': longest}

ROADS = {'LONGEST': (2016, 2026), 'DECADE': (2017, 2026), 'CONT': (2019, 2026), 'VAL': (2023, 2026),
         'FOLD1': (2016, 2021), 'FOLD2': (2021, 2026)}
out = {'family': 'catalog-aaii-schloss', 'program': 'v13-best-rules', 'roads': {}, 'pool_sizes': {str(k): len(v) for k, v in POOLS.items()}}
for name, (a, b) in ROADS.items():
    r = run_road(a, b)
    beaten = 0; pfin = []
    for s in range(1, 21):
        pr = run_road(a, b, seed=s); pfin.append(pr['final'])
        if r['final'] > pr['final']: beaten += 1
    r['placebos_beaten'] = beaten
    r['placebo_median_final'] = round(statistics.median(pfin), 2)
    r['spy_same_window'] = spy_final(ym(a, 6), ym(b, 6))
    r['period_stats'] = period_stats(r['curve'])
    out['roads'][name] = r
    print(name, r['final'], 'dd', r['maxdd_pct'], 'pb', beaten, 'spy', r['spy_same_window'], flush=True)

# half-windows for LONGEST and any champion-beating road (confirmation bars)
def halves(a, b):
    forms = list(range(a, b)); mid = forms[len(forms) // 2]
    return [(a, mid), (mid, b)]
out['half_windows'] = {}
for name in ('LONGEST', 'DECADE', 'CONT', 'VAL'):
    a, b = ROADS[name]
    hw = []
    for (x, y) in halves(a, b):
        rr = run_road(x, y)
        hw.append({'window': f'{x}-{y}', 'final': rr['final'], 'maxdd_pct': rr['maxdd_pct'],
                   'spy_same_window': spy_final(ym(x, 6), ym(y, 6))})
    out['half_windows'][name] = hw
    print('halves', name, hw, flush=True)

json.dump(out, open(os.path.join(FAM, 'results.json'), 'w'), indent=1)
print('WROTE results.json')
