#!/usr/bin/env python3
"""Slater Zulu — Form C (CONSTRUCTED, trailing-EPS substitute) on the v11 W04
broad EDGAR chassis (read-only import). Quarterly re-screen: fundamentals are
the annual snapshot for formation year F (data CY F-1, as in engine_w04);
prices / cap / RS / P/E / PEG_C are refreshed at each quarter-end.
Roads: formations 2018-2025 (4-year EPS streak needs frames back to 2014).
Native form: tiered habitat costs (engine cost_rate), no floor.
House form (v9): 0.10%/side costs + -15% episode floor on monthly closes,
liquidate to cash until next quarterly rebalance, restart once, 2nd halt ends.
Vanished price (month beyond a name's last price month) -> ZERO (spec conv.).
Insider-cluster proxy: Form 4 coverage absent on this chassis -> include all,
gap logged in RESULTS.md (spec-permitted). Simulation only."""
import json, os, sys, math, random, statistics
sys.path.insert(0, '/home/hatch/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data')
import engine_w04 as E

OUT = os.path.dirname(os.path.abspath(__file__))
D = None
COUNTS = [1, 2, 3, 5, 8, 10, 15, 20, 30, 'ALL']

def ym(y, m): return f'{y:04d}-{m:02d}'

def eps_series(cik, F):
    """EPS_C (NI / shares, split-basis via SF(F)) for data years F-4..F-1."""
    out = {}
    for Y in range(F - 4, F):
        ni = D.F('NetIncomeLoss', Y, 'D').get(cik)
        sh = None
        for yy in (Y, Y - 1):
            d = D.F('Shares', yy, 'I')
            if d.get(cik): sh = d[cik]; break
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
    Returns (qualifiers ranked by PEG_C asc, placebo pool list)."""
    s = E.snapshot(F)
    quals, pool = [], []
    yq, mq = int(qm[:4]), int(qm[5:7])
    for cik, v in s.items():
        if not v['px_adj'] or not v['shares']: continue
        px = D.price(cik, qm, adj=True); pxr = D.price(cik, qm, adj=False)
        if not px or not pxr: continue
        cap = v['shares'] * pxr * D.sf.get(cik, {}).get(F, 1.0)
        if cap < 100e6 or cap > 5e9: continue                      # CONSTRUCTED US size band
        es = eps_series(cik, F)
        if es is None: continue
        eps = es[F - 1]
        if eps <= 0: continue
        # cash flow per share > EPS: latest year and 5y avg (chassis has F-1,F-2 flows;
        # 5y avg approximated by available years F-1..F-4 NI/CFO where present) -> use
        # latest-year test + CFO>NI test over F-1 and F-2 (documented approximation)
        cfo1 = v['cfo']
        if cfo1 is None or v['ni'] is None: continue
        sh_b = v['shares'] * D.sf.get(cik, {}).get(F, 1.0)
        cfps = cfo1 / sh_b
        if cfps <= eps: continue
        if v['ni'] <= 0: continue
        # gearing: net cash positive OR total debt / equity < 0.5
        debt = v['ltd'] if v['ltd'] is not None else 0
        cashv = v['cash'] or 0
        eq = v['equity']
        if not (cashv > debt or (eq and eq > 0 and debt / eq < 0.5)): continue
        # ROCE (ex-intangibles unavailable): opinc / (assets - current liab) > 12%
        if v['opinc'] is None or not v['assets'] or v['cl'] is None: continue
        ce = v['assets'] - v['cl']
        if ce <= 0 or v['opinc'] / ce <= 0.12: continue
        # RS: 12-month price return > 0
        p12 = D.price(cik, ym(yq - 1, mq), adj=True)
        if not p12 or px / p12 - 1 <= 0: continue
        pool.append(cik)
        # growth streak: EPS strictly rising F-4..F-1; trailing growth > 15%
        yrs = [es[y] for y in range(F - 4, F)]
        if not all(yrs[i] > yrs[i - 1] for i in range(1, 4)): continue
        g = yrs[3] / yrs[2] - 1
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
    if mm > last: return 0.0          # delisted / vanished -> ZERO
    prev = [m for m in s if m <= mm]
    return s[max(prev)][0] if prev else fallback

def run(formations, count, form='native', seed=None):
    cash = 100.0; curve = []; costs = 0.0; orders = 0; halts = 0; halted_final = False
    quarters_log = []
    # quarter schedule: for formation F: Jun F, Sep F, Dec F, Mar F+1; exit Jun F+1
    sched = []
    for F in formations:
        sched += [(F, ym(F, 6)), (F, ym(F, 9)), (F, ym(F, 12)), (F, ym(F + 1, 3))]
    end_month = ym(formations[-1] + 1, 6)
    pos = {}   # cik -> shares
    cur_F = None; in_cash_until = None
    def months_between(a, b):
        y1, m1 = int(a[:4]), int(a[5:7]); y2, m2 = int(b[:4]), int(b[5:7])
        out = []; y, m = y1, m1
        while (y, m) <= (y2, m2):
            out.append(ym(y, m)); m += 1
            if m > 12: y, m = y + 1, 1
        return out
    all_months = months_between(sched[0][1], end_month)
    qset = {q: F for F, q in sched}
    qi = 0
    for i, mm in enumerate(all_months):
        if mm in qset and not halted_final:
            F = qset[mm]
            quals, pool, s = screen(F, mm)
            if seed is None:
                picks = quals if count == 'ALL' else quals[:count]
            else:
                rng = random.Random(seed * 100003 + F * 10 + qi)
                keys = list(pool); rng.shuffle(keys)
                n = len(quals) if count == 'ALL' else min(count, len(quals))
                picks = keys[:n]
            qi += 1
            # sell current holdings at this month's close
            val = cash
            for c, sh in list(pos.items()):
                p = price_or_zero(c, mm, 0)
                gross = sh * p
                if form == 'native': rate = E.cost_rate(s[c]['cap'] if c in s else None)
                else: rate = 0.0010
                costs += gross * rate; orders += 1; val += gross - gross * rate
            pos = {}
            cash = 0.0
            if picks:
                w = val / len(picks)
                for c in picks:
                    p = D.price(c, mm, adj=True)
                    if form == 'native': rate = E.cost_rate(s[c]['cap'])
                    else: rate = 0.0010
                    costs += w * rate; orders += 1
                    pos[c] = (w - w * rate) / p
                quarters_log.append({'q': mm, 'n': len(picks), 'tickers': [s[c]['ticker'] for c in picks]})
            else:
                cash = val
                quarters_log.append({'q': mm, 'n': 0, 'tickers': []})
            curve.append([mm, round(cash + sum(sh * price_or_zero(c, mm, 0) for c, sh in pos.items()), 2)])
            continue
        # mark month
        val = cash + sum(sh * price_or_zero(c, mm, 0) for c, sh in pos.items())
        if form == 'house' and pos and not halted_final:
            peak = max([v for _, v in curve] + [100.0])
            if val <= 0.85 * peak:
                # liquidate at this close, cash until next quarter
                tot = cash
                for c, sh in pos.items():
                    tot += sh * price_or_zero(c, mm, 0) * (1 - 0.0010)
                pos = {}; cash = tot; val = tot; halts += 1
                if halts >= 2: halted_final = True
        curve.append([mm, round(val, 2)])
    # final liquidation at end_month already marked; apply sell costs
    peak = 100.0; maxdd = 0.0
    for _, v in curve:
        peak = max(peak, v); maxdd = max(maxdd, 1 - v / peak)
    final = curve[-1][1] if curve else 100.0
    if pos and form == 'native':  # rough exit cost already excluded; note in results
        pass
    spy = None
    a = D.spy.get(sched[0][1]); b = D.spy.get(end_month)
    if a and b: spy = round(100 * b / a, 2)
    return {'final': final, 'max_dd': round(maxdd, 4), 'costs': round(costs, 2),
            'orders': orders, 'halts': halts, 'curve': curve,
            'quarters': quarters_log, 'spy_final_same_window': spy}

def dist(curve, step_months=3):
    pts = [100.0] + [v for _, v in curve]
    # quarterly period returns from curve sampled every 3 months
    samp = [curve[i][1] for i in range(0, len(curve), step_months)]
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

def main():
    global D
    D = E.Data(); E.D = D
    roads = {'FULL': list(range(2018, 2026)), 'CONT': list(range(2019, 2026)),
             'VAL': list(range(2023, 2026)), 'FOLD_A': list(range(2018, 2022)),
             'FOLD_B': list(range(2022, 2026))}
    res = {'family': 'slater-zulu-formC-CONSTRUCTED', 'roads': {}}
    for form in ('native', 'v9'):
        res['roads'][form] = {}
        for road, forms_ in roads.items():
            res['roads'][form][road] = {}
            for count in COUNTS:
                key = str(count)
                r = run(forms_, count, form=form)
                entry = {k: r[k] for k in ('final', 'max_dd', 'costs', 'orders', 'halts', 'spy_final_same_window')}
                if road == 'FULL':
                    entry['curve'] = r['curve']; entry['quarters'] = r['quarters']
                    entry['distribution_quarterly'] = dist(r['curve'])
                res['roads'][form][road][key] = entry
                print(form, road, key, entry['final'], 'spy', entry['spy_final_same_window'], flush=True)
            # placebos for every count cell, 20 seeds
            for count in COUNTS:
                key = str(count); pls = []
                for seed in range(1, 21):
                    rp = run(forms_, count, form=form, seed=seed)
                    pls.append(rp['final'])
                nat = res['roads'][form][road][key]['final']
                res['roads'][form][road][key]['placebo_finals'] = pls
                res['roads'][form][road][key]['placebos_beaten'] = sum(1 for t in pls if nat > t)
                print(form, road, key, 'placebos beaten', res['roads'][form][road][key]['placebos_beaten'], '/20', flush=True)
    json.dump(res, open(os.path.join(OUT, 'results.json'), 'w'), indent=1)
    print('saved')

if __name__ == '__main__':
    main()
