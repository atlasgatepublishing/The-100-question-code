#!/usr/bin/env python3
"""Slater Zulu — V13 BEST RULES (CONSTRUCTED, trailing-EPS substitute) on the
v11 W04 broad EDGAR chassis (read-only import). Spec: BEST-RULES-SPEC.md
(frozen before this run). Differences from v12 Form C, per spec:
- growth history: 3 reported years, EPS>0 each, EPS(F-1)>EPS(F-3),
  latest-year growth >15% (was: 4 strictly-rising years);
- size band $50m-$5bn (was $100m-$5bn);
- EPS history extended to CY2013 via v12 graham frames_ext (NI/Shares);
- split factors extended to formation 2016 by the engine's own method;
- NO floor; tiered habitat costs; final liquidation charged.
Quarterly re-screen on annual snapshot(F) fundamentals (data CY F-1);
prices/cap/RS/P-E/PEG_C refreshed quarterly. Vanished price -> ZERO.
Insider-cluster proxy: Form 4 coverage absent on this chassis -> include
all, gap logged in RESULTS.md. Simulation only."""
import json, os, sys, math, random, statistics
sys.path.insert(0, '/home/hatch/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data')
import engine_w04 as E

OUT = os.path.dirname(os.path.abspath(__file__))
EXT = os.path.expanduser('~/workspace/stock-app/backtests/v12-completions/hunt-graham-defensive/data/frames_ext')
D = None

def load_ext(name, year, kind):
    p = os.path.join(EXT, f'{name}_{year}{kind}.json')
    if not os.path.exists(p): return {}
    return {int(k): v for k, v in json.load(open(p)).items()}

NI_EXT = {y: load_ext('NetIncomeLoss', y, 'D') for y in range(2010, 2014)}
SH_EXT = {y: load_ext('Shares', y, 'I') for y in range(2010, 2014)}

def ni_of(cik, Y):
    if Y >= 2014: return D.F('NetIncomeLoss', Y, 'D').get(cik)
    return NI_EXT.get(Y, {}).get(cik)

def shares_of(cik, Y):
    if Y >= 2014: return D.F('Shares', Y, 'I').get(cik)
    return SH_EXT.get(Y, {}).get(cik)

def ym(y, m): return f'{y:04d}-{m:02d}'

def eps_series(cik, F):
    """EPS_C (NI / shares, split-basis via SF(F)) for data years F-3..F-1."""
    out = {}
    for Y in range(F - 3, F):
        ni = ni_of(cik, Y)
        sh = None
        for yy in (Y, Y - 1):
            v = shares_of(cik, yy)
            if v: sh = v; break
        if ni is None or not sh: return None
        out[Y] = ni / (sh * D.sf.get(cik, {}).get(F, 1.0))
    return out

_SNAP = {}
_orig_snapshot = E.snapshot
def _snap(F):
    if F not in _SNAP: _SNAP[F] = _orig_snapshot(F)
    return _SNAP[F]
E.snapshot = _snap

_SCR = {}
def screen(F, qm):
    if (F, qm) in _SCR: return _SCR[(F, qm)]
    r = _screen(F, qm); _SCR[(F, qm)] = r; return r

def _screen(F, qm):
    """Screen at quarter-end month qm (YYYY-MM) using snapshot(F) fundamentals.
    Returns (qualifiers ranked by PEG_C asc, placebo pool list, snapshot)."""
    s = E.snapshot(F)
    quals, pool = [], []
    yq, mq = int(qm[:4]), int(qm[5:7])
    for cik, v in s.items():
        if not v['px_adj'] or not v['shares']: continue
        px = D.price(cik, qm, adj=True); pxr = D.price(cik, qm, adj=False)
        if not px or not pxr: continue
        cap = v['shares'] * pxr * D.sf.get(cik, {}).get(F, 1.0)
        if cap < 50e6 or cap > 5e9: continue                      # spec section 4 size band
        es = eps_series(cik, F)
        if es is None: continue
        eps = es[F - 1]
        if eps <= 0: continue
        cfo1 = v['cfo']
        if cfo1 is None or v['ni'] is None: continue
        sh_b = v['shares'] * D.sf.get(cik, {}).get(F, 1.0)
        cfps = cfo1 / sh_b
        if cfps <= eps: continue
        if v['ni'] <= 0: continue
        debt = v['ltd'] if v['ltd'] is not None else 0
        cashv = v['cash'] or 0
        eq = v['equity']
        if not (cashv > debt or (eq and eq > 0 and debt / eq < 0.5)): continue
        if v['opinc'] is None or not v['assets'] or v['cl'] is None: continue
        ce = v['assets'] - v['cl']
        if ce <= 0 or v['opinc'] / ce <= 0.12: continue
        p12 = D.price(cik, ym(yq - 1, mq), adj=True)
        if not p12 or px / p12 - 1 <= 0: continue
        pool.append(cik)
        # spec section 1 growth-history test (replaces v12 4-yr strict streak)
        yrs = [es[y] for y in range(F - 3, F)]
        if not all(e > 0 for e in yrs): continue
        if not yrs[2] > yrs[0]: continue
        g = yrs[2] / yrs[1] - 1
        if g <= 0.15: continue
        pe = px / eps
        if pe >= 20 or pe <= 0: continue
        peg = pe / (g * 100)
        if peg >= 0.75: continue
        quals.append((peg, cik))
    quals.sort()
    return [c for _, c in quals], pool, s

def price_or_zero(cik, mm, fallback):
    s = D.px.get(cik)
    if not s: return 0.0
    if mm in s: return s[mm][0]
    last = max(s)
    if mm > last: return 0.0
    prev = [m for m in s if m <= mm]
    return s[max(prev)][0] if prev else fallback

def months_between(a, b):
    y1, m1 = int(a[:4]), int(a[5:7]); y2, m2 = int(b[:4]), int(b[5:7])
    out = []; y, m = y1, m1
    while (y, m) <= (y2, m2):
        out.append(ym(y, m)); m += 1
        if m > 12: y, m = y + 1, 1
    return out

def run(formations, seed=None):
    cash = 100.0; curve = []; costs = 0.0; orders = 0
    quarters_log = []
    sched = []
    for F in formations:
        sched += [(F, ym(F, 6)), (F, ym(F, 9)), (F, ym(F, 12)), (F, ym(F + 1, 3))]
    end_month = ym(formations[-1] + 1, 6)
    pos = {}
    all_months = months_between(sched[0][1], end_month)
    qset = {q: F for F, q in sched}
    qi = 0
    last_s = None
    for mm in all_months:
        if mm in qset:
            F = qset[mm]
            quals, pool, s = screen(F, mm)
            last_s = s
            if seed is None:
                picks = quals
            else:
                rng = random.Random(seed * 100003 + F * 10 + qi)
                keys = list(pool); rng.shuffle(keys)
                picks = keys[:len(quals)]
            qi += 1
            val = cash
            for c, sh in list(pos.items()):
                p = price_or_zero(c, mm, 0)
                gross = sh * p
                rate = E.cost_rate(s[c]['cap'] if c in s else None)
                costs += gross * rate; orders += 1; val += gross - gross * rate
            pos = {}
            cash = 0.0
            if picks:
                w = val / len(picks)
                for c in picks:
                    p = D.price(c, mm, adj=True)
                    rate = E.cost_rate(s[c]['cap'])
                    costs += w * rate; orders += 1
                    pos[c] = (w - w * rate) / p
                quarters_log.append({'q': mm, 'n': len(picks), 'tickers': [s[c]['ticker'] for c in picks]})
            else:
                cash = val
                quarters_log.append({'q': mm, 'n': 0, 'tickers': []})
            curve.append([mm, round(cash + sum(sh * price_or_zero(c, mm, 0) for c, sh in pos.items()), 2)])
            continue
        val = cash + sum(sh * price_or_zero(c, mm, 0) for c, sh in pos.items())
        curve.append([mm, round(val, 2)])
    # final liquidation at end_month, per-name tier cost (spec section 7)
    if pos:
        tot = cash
        for c, sh in pos.items():
            p = price_or_zero(c, end_month, 0)
            gross = sh * p
            rate = E.cost_rate(last_s[c]['cap'] if last_s and c in last_s else None)
            costs += gross * rate; orders += 1; tot += gross - gross * rate
        curve[-1] = [end_month, round(tot, 2)]
        pos = {}
    peak = 100.0; maxdd = 0.0
    for _, v in curve:
        peak = max(peak, v); maxdd = max(maxdd, 1 - v / peak)
    final = curve[-1][1] if curve else 100.0
    spy = None
    a = D.spy.get(sched[0][1]); b = D.spy.get(end_month)
    if a and b: spy = round(100 * b / a, 2)
    return {'final': final, 'max_dd': round(maxdd, 4), 'costs': round(costs, 2),
            'orders': orders, 'curve': curve, 'quarters': quarters_log,
            'spy_final_same_window': spy}

def dist(curve):
    samp = [curve[i][1] for i in range(0, len(curve), 3)]
    rets = []
    prev = 100.0
    for v in samp:
        rets.append(v / prev - 1 if prev else 0.0); prev = v
    if not rets: return {}
    prof = sum(1 for r in rets if r > 0)
    longest_loss = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; longest_loss = max(longest_loss, cur)
    peak = 100.0; last_high = 0; longest_gap = 0
    for i, (_, v) in enumerate(curve):
        if v >= peak: peak = v; longest_gap = max(longest_gap, i - last_high); last_high = i
    longest_gap = max(longest_gap, len(curve) - 1 - last_high)
    return {'periods': len(rets), 'pct_profitable': round(100 * prof / len(rets), 1),
            'median': round(statistics.median(rets) * 100, 2),
            'best': round(max(rets) * 100, 2), 'worst': round(min(rets) * 100, 2),
            'avg_secondary': round(statistics.mean(rets) * 100, 2),
            'longest_losing_run': longest_loss, 'longest_between_highs_months': longest_gap}

def extend_sf_2016():
    """Engine computes split factors only for formations >= 2017; add 2016
    by the identical method (product of split-like YoY share ratios in
    frame years >= F)."""
    for cik in D.cand:
        series = D.sh_series
        avail = [(y, series[y].get(cik)) for y in range(2014, 2026) if series[y].get(cik)]
        f = 1.0
        for (y0, a), (y1, b) in zip(avail, avail[1:]):
            if y1 >= 2016:
                r = b / a
                if r >= 1.6 or r <= 0.625: f *= r
        D.sf.setdefault(cik, {})[2016] = f

CHAMP = {'LONG': 1415.62, 'DECADE': 667.35, 'CONT': 544.47, 'VAL': 288.05}

def main():
    global D
    D = E.Data(); E.D = D
    extend_sf_2016()
    roads = {'DECADE': list(range(2016, 2026)), 'CONT': list(range(2019, 2026)),
             'VAL': list(range(2023, 2026))}
    res = {'family': 'slater-zulu-v13-best-rules-CONSTRUCTED', 'roads': {}}
    for road, forms_ in roads.items():
        r = run(forms_)
        entry = {k: r[k] for k in ('final', 'max_dd', 'costs', 'orders', 'spy_final_same_window')}
        entry['curve'] = r['curve']; entry['quarters'] = r['quarters']
        entry['distribution_quarterly'] = dist(r['curve'])
        pls = []
        for seed in range(1, 21):
            rp = run(forms_, seed=seed)
            pls.append(rp['final'])
        entry['placebo_finals'] = pls
        entry['placebos_beaten'] = sum(1 for t in pls if r['final'] > t)
        entry['placebo_median'] = round(statistics.median(pls), 2)
        res['roads'][road] = entry
        print(road, 'final', entry['final'], 'maxdd', entry['max_dd'], 'spy', entry['spy_final_same_window'],
              'placebos beaten', entry['placebos_beaten'], '/20', flush=True)
    # LONG collapses into DECADE (spec section 7 closure)
    res['roads']['LONG'] = dict(res['roads']['DECADE'])
    res['roads']['LONG']['note'] = 'LONG collapses into DECADE window: earliest supported formation is 2016 (BS frames begin CY2014).'
    # Confirmation (spec section 8), only if a road beats the champion
    conf = {}
    for road in ('LONG', 'DECADE', 'CONT', 'VAL'):
        if res['roads'][road]['final'] > CHAMP[road]:
            forms_ = roads['DECADE'] if road in ('LONG', 'DECADE') else roads[road]
            folds = []
            for F in forms_:
                rf = run([F])
                spyf = rf['spy_final_same_window']
                folds.append({'formation': F, 'final': rf['final'], 'spy': spyf})
            med = statistics.median([f['final'] for f in folds])
            share = sum(1 for f in folds if f['final'] > 100) / len(folds)
            spymed = statistics.median([f['spy'] for f in folds if f['spy'] is not None])
            mid = forms_[len(forms_) // 2]
            h1 = run([F for F in forms_ if F < mid]); h2 = run([F for F in forms_ if F >= mid])
            folds_ok = med > 100 and share >= 0.6 and med > spymed
            halves_ok = (h1['final'] > 100 and h2['final'] > 100
                         and h1['spy_final_same_window'] is not None and h1['final'] > h1['spy_final_same_window']
                         and h2['spy_final_same_window'] is not None and h2['final'] > h2['spy_final_same_window'])
            conf[road] = {'folds': folds, 'median_fold': round(med, 2), 'share_folds_above_100': round(share, 3),
                          'spy_median_fold': round(spymed, 2), 'folds_ok': folds_ok,
                          'half1': {'final': h1['final'], 'spy': h1['spy_final_same_window']},
                          'half2': {'final': h2['final'], 'spy': h2['spy_final_same_window']},
                          'halves_ok': halves_ok, 'confirmed': bool(folds_ok and halves_ok)}
            print('CONFIRMATION', road, conf[road]['confirmed'], flush=True)
    res['confirmation'] = conf
    json.dump(res, open(os.path.join(OUT, 'results.json'), 'w'), indent=1)
    print('saved')

if __name__ == '__main__':
    main()
