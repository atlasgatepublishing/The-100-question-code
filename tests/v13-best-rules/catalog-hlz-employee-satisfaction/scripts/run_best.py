#!/usr/bin/env python3
"""V13 best-rules run: catalog-hlz-employee-satisfaction.
Spec: ../BEST-RULES-SPEC.md (frozen before this run).
Annual formation (first trading day of May; June for the 2021 list),
equal-weight ALL buyable list members, no floor, 0.25%/side costs.
Data amendment (disclosed, made before any returns were seen): the
2012 and 2015 lists could not be recovered from any free contemporaneous
source, and 2014 is a documented reconstruction (81 names); years with
no recovered list simply have no formation — the prior basket holds.
Simulation only."""
import json, os, random, sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
FAM = os.path.join(HERE, '..')
DATA = os.path.join(FAM, 'data')
sys.path.insert(0, HERE)
from mapping import ticker_for

COST = 0.0025
END = '2026-11-20'

def load_px(t):
    p = os.path.join(DATA, 'prices', f'px_{t}.json')
    if not os.path.exists(p): return None
    d = json.load(open(p))
    try:
        r = d['chart']['result'][0]
        ts = r['timestamp']
        adj = r['indicators'].get('adjclose', [{}])[0].get('adjclose')
        if adj is None: adj = r['indicators']['quote'][0]['close']
    except Exception:
        return None
    out = {}
    for tstamp, v in zip(ts, adj):
        if v is None: continue
        day = datetime.fromtimestamp(tstamp, tz=timezone.utc).strftime('%Y-%m-%d')
        out[day] = float(v)
    return out

panel = json.load(open(os.path.join(DATA, 'panel_raw.json')))
SPY = load_px('SPY')
CAL = sorted(d for d in SPY if d <= END)
CALSET = set(CAL)

def first_td(year, month):
    for d in CAL:
        if d >= f'{year:04d}-{month:02d}-01': return d
    return None

SKIP_YEARS = {2012, 2015}  # 2012: list unrecovered. 2015: only a 24-name
# page fragment recovered (3 buyable) — a fragment is not a list, so no
# formation. 2014 (81 names) is kept: it comes from the complete PTAB
# exhibit of the full list, with matching losses, documented in RESULTS.md.
FORMATIONS = []  # (date, year)
for y in range(2010, 2027):
    if y in SKIP_YEARS or not panel.get(str(y)): continue
    d = first_td(y, 6 if y == 2021 else 5)
    if d and d <= END: FORMATIONS.append((d, y))
FORMATIONS.sort()

PX = {}
ALL_TICKERS = set()
for y, names in panel.items():
    for n in names:
        t = ticker_for(n, int(y))
        if t: ALL_TICKERS.add(t)
for t in sorted(ALL_TICKERS | {'SPY'}):
    px = load_px(t)
    if px: PX[t] = px

def basket(year, rng=None, count=None):
    names = panel[str(year)]
    ticks = []
    for n in names:
        t = ticker_for(n, year)
        if t and t in PX: ticks.append(t)
    ticks = sorted(set(ticks))
    if rng is not None:
        pool = [t for t in sorted(ALL_TICKERS) if t in PX]
        return rng.sample(pool, min(count or len(ticks), len(pool)))
    return ticks

def price_on(t, day, cal_idx):
    px = PX[t]
    if day in px: return px[day]
    i = cal_idx
    while i >= 0:
        if CAL[i] in px: return px[CAL[i]]
        i -= 1
    return None

def simulate(start, seed=None):
    rng = random.Random(seed) if seed is not None else None
    cash = 100.0; shares = {}
    costs = 0.0; curve = []
    forms = [(d, y) for d, y in FORMATIONS if d <= END]
    # in-force formation at start
    inforce = None
    for d, y in forms:
        if d <= start: inforce = (d, y)
    fi = 0
    started = False
    period_marks = []  # (label, equity at formation after trades)
    for ci, day in enumerate(CAL):
        if day < start: continue
        due = [f for f in forms if f[0] == day]
        if not started and inforce and day == start:
            due = [inforce]; started = True
        if day >= (forms[0][0] if forms else END) and not started and due:
            started = True
        for d, y in due:
            # sell all
            val = cash
            for t, sh in shares.items():
                p = price_on(t, day, ci)
                if p: val += sh * p * (1 - COST); costs += sh * p * COST
            shares = {}
            b = basket(y) if rng is None else basket(y, rng=rng)
            usable = []
            for t in b:
                p = price_on(t, day, ci)
                if p and p > 0: usable.append((t, p))
            if usable:
                w = val / len(usable)
                for t, p in usable:
                    shares[t] = w * (1 - COST) / p; costs += w * COST
                cash = 0.0
            else:
                cash = val
            period_marks.append((f'{y} list', round(val if not usable else
                sum(sh * price_on(t, day, ci) for t, sh in shares.items()) + cash, 2)))
        if shares or cash:
            eq = cash + sum(sh * (price_on(t, day, ci) or 0) for t, sh in shares.items())
        else:
            eq = cash
        curve.append((day, round(eq, 4)))
    return curve, costs, period_marks

def stats(curve):
    peak = -1; maxdd = 0.0; last_high_i = 0; longest_gap = 0
    for i, (d, v) in enumerate(curve):
        if v >= peak: peak = v; last_high_i = i
        longest_gap = max(longest_gap, i - last_high_i)
        if peak > 0: maxdd = max(maxdd, 1 - v / peak)
    return round(curve[-1][1], 2), round(maxdd, 4), longest_gap

def period_stats(marks, curve):
    # periods = consecutive formation marks (equity sampled at formations)
    vals = [v for _, v in marks]
    rets = []
    for a, b in zip(vals, vals[1:]):
        if a > 0: rets.append(b / a - 1)
    if not rets: return {}
    srt = sorted(rets); n = len(rets)
    med = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0; streak = max(streak, cur)
    return {'n_periods': n, 'median_period_return': round(med, 4),
            'share_positive': round(sum(1 for r in rets if r > 0) / n, 3),
            'best_period': round(max(rets), 4), 'worst_period': round(min(rets), 4),
            'longest_losing_streak_periods': streak,
            'period_returns': [round(r, 4) for r in rets]}

ROADS = {'LONG': '2010-01-04', 'DECADE': '2016-11-21',
         'CONT': '2019-01-02', 'VAL': '2023-01-03'}
CHAMP = {'LONG': 1415.62, 'DECADE': 667.35, 'CONT': 544.47, 'VAL': 288.05}
SPYREF = {'LONG': 822.94, 'DECADE': 367.80, 'CONT': 313.62, 'VAL': 187.77}

results = {'spec': 'BEST-RULES-SPEC.md', 'formations': FORMATIONS,
           'basket_sizes': {}, 'roads': {}}
for d, y in FORMATIONS:
    results['basket_sizes'][str(y)] = len(basket(y))

for road, start in ROADS.items():
    curve, costs, marks = simulate(start)
    fin, maxdd, gap = stats(curve)
    si = next(i for i, d in enumerate(CAL) if d >= start)
    spy_fin = round(100 * SPY[CAL[-1] if CAL[-1] <= END else END] / SPY[CAL[si]], 2) \
        if CAL[si] in SPY else None
    twins = []
    for s in range(1, 21):
        tc, _, _ = simulate(start, seed=s * 7919)
        twins.append(round(tc[-1][1], 2))
    beaten = sum(1 for t in twins if fin > t)
    results['roads'][road] = {
        'start': start, 'end': END, 'final': fin, 'max_dd': maxdd,
        'costs_total': round(costs, 2), 'spy_same_window': spy_fin,
        'spy_program_reference': SPYREF[road], 'champion_vm': CHAMP[road],
        'placebo_finals': twins, 'placebos_beaten': beaten,
        'longest_stretch_between_new_highs_days': gap,
        'period_distribution': period_stats(marks, curve),
        'formation_marks': marks, 'curve': curve}
    print(road, 'final', fin, 'maxdd', maxdd, 'spy', spy_fin,
          'placebos beaten', beaten, '/20', flush=True)

json.dump(results, open(os.path.join(FAM, 'results.json'), 'w'), indent=1)
print('saved results.json')
