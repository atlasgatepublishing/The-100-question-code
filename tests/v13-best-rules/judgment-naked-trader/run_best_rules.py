#!/usr/bin/env python3
"""V13 BEST-RULES — judgment-naked-trader (Burns checklist, JUDGMENT-CONSTRUCTED).
Spec: BEST-RULES-SPEC.md (frozen before this run). Simulation only.
Chassis: v11 _w04_broad_data engine (read-only) — 658 EDGAR candidates,
PIT annual frames, monthly Yahoo adjclose 2016-01..2026-11, vanished -> ZERO.
Habitat substitute: US small/mid pond for his UK pond (labeled in spec).
Costs: chassis tier — this universe is all <$1bn cap, so 0.75%/side.
No portfolio floor (spec). Per-position: -11% stop, get-out-quick (first 3
marks below fill), top-slice half at +50%, one average-up add at +20%.
"""
import csv, json, os, random, statistics, sys, time
sys.path.insert(0, os.path.expanduser('~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data'))
import engine_w04 as W

HERE = os.path.dirname(os.path.abspath(__file__))
END = '2026-11'
W.D = W.Data()
D = W.D
ym = W.ym

NI = {y: W.load_frame(f'NetIncomeLoss_{y}D.json') for y in range(2014, 2026)}
SH = {y: W.load_frame(f'Shares_{y}I.json') for y in range(2014, 2026)}

# ---------- insider buys (Form 4 code P), trailing-12m net value by cik ----------
INSIDER = {}  # (cik, 'YYYY-MM') -> cumulative? store list of (filing_date, value)
_ev_path = os.path.expanduser('~/workspace/stock-app/backtests/v3/insider-data/events.csv')
_buys = {}
if os.path.exists(_ev_path):
    with open(_ev_path) as f:
        for r in csv.DictReader(f):
            if r['code'] != 'P':
                continue
            try:
                cik = int(r['issuer_cik']); val = float(r['value']); fd = r['filing_date']
            except Exception:
                continue
            _buys.setdefault(cik, []).append((fd, val))

def insider_buy(cik, form_date):
    """Net open-market buy value filed in the 12 months up to form_date (PIT by filing date)."""
    lo = f'{int(form_date[:4]) - 1}-{form_date[5:]}'
    return sum(v for fd, v in _buys.get(cik, []) if lo < fd <= form_date)

# ---------- helpers ----------
def eps_series(cik, F):
    """EPS by fiscal year on the F-1 share basis (split-corrected, chassis method)."""
    raw = {}
    for y in range(2014, F):
        ni, sh = NI[y].get(cik), SH[y].get(cik)
        if ni is not None and sh:
            raw[y] = ni / sh
    if not raw:
        return {}
    yrs = sorted(raw)
    adj = {}
    for i, y in enumerate(yrs):
        f = 1.0
        for y0, y1 in zip(yrs[i:], yrs[i + 1:]):
            r = SH[y1][cik] / SH[y0][cik]
            if r >= 1.6 or r <= 0.625:
                f *= r
        adj[y] = raw[y] / f if f else raw[y]
    return adj

def price_adj(cik, month):
    """Adj price at month; last print if gap; 0.0 if series ENDED before month; None if never started."""
    s = D.px.get(cik)
    if not s:
        return None
    if month in s:
        return s[month][0]
    prev = [m for m in s if m < month]
    if not prev:
        return None
    if month > max(s):
        return 0.0
    return s[max(prev)][0]

def months_between(a, b):
    y0, m0 = int(a[:4]), int(a[5:7]); y1, m1 = int(b[:4]), int(b[5:7])
    out = []
    y, m = y0, m0
    while (y, m) <= (y1, m1):
        out.append(ym(y, m))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out

# ---------- eligibility at June formation F ----------
_snap = {}
def eligible(F):
    if F in _snap:
        return _snap[F]
    s = W.snapshot(F)
    out = {}
    for cik, v in s.items():
        cap = v['cap']
        if not cap or cap < 20e6 or cap > 1e9:
            continue
        if v['opinc'] is None or v['opinc'] <= 0:
            continue
        debt = v['ltd'] if v['ltd'] is not None else 0.0
        cash = v['cash'] or 0.0
        if (debt - cash) > 3.0 * v['opinc']:
            continue
        if v['rev'] is None or v['rev0'] is None or not (v['rev'] > v['rev0']):
            continue
        eps = eps_series(cik, F)
        if (F - 1) not in eps or (F - 2) not in eps:
            continue
        if not (eps[F - 1] > eps[F - 2]) or eps[F - 1] <= 0:
            continue
        px_raw = D.price(cik, ym(F, 6), adj=False)
        if not px_raw:
            continue
        pe = px_raw / eps[F - 1]
        if not (12.0 <= pe < 20.0):
            continue
        sh = v['shares']
        if not sh:
            continue
        op_ps = v['opinc'] / sh  # opinc/shares on filed basis vs raw price: labeled proxy
        if op_ps <= 0 or not (px_raw / op_ps < 15.0):
            continue
        p_now = price_adj(cik, ym(F, 6)); p_yr = price_adj(cik, ym(F - 1, 6))
        if not p_now or not p_yr or not (p_now > p_yr):
            continue
        lows = [price_adj(cik, ym(F - 1, m)) for m in range(7, 13)] + \
               [price_adj(cik, ym(F, m)) for m in range(1, 7)]
        lows = [x for x in lows if x]
        if not lows or p_now < 1.05 * min(lows):
            continue
        mom = p_now / p_yr - 1.0
        out[cik] = dict(cap=cap, mom=mom, ticker=v['ticker'],
                        insider=insider_buy(cik, f'{F}-06-30'))
    _snap[F] = out
    return out

def ranked(F):
    e = eligible(F)
    return sorted(e, key=lambda c: (-round(e[c]['mom'], 4),
                                    0 if e[c]['insider'] > 0 else 1,
                                    e[c]['ticker']))

# ---------- the run ----------
MAXPOS = 10

def run_road(start_month, first_form, last_form, seed=None, end=END):
    cash = 100.0
    pos = {}   # cik -> dict(sh, fill, age_marks, added, sliced, cap)
    curve = []
    total_costs = 0.0; n_orders = 0; n_trades_closed = 0
    months = months_between(start_month, end)
    forms = set(range(first_form, last_form + 1))

    def equity(month):
        tot = cash
        for c, p in pos.items():
            pr = price_adj(c, month)
            if pr:
                tot += p['sh'] * pr
        return tot

    for month in months:
        y, m = int(month[:4]), int(month[5:7])
        # --- exits / adds on monthly marks (not in the entry month) ---
        for c in list(pos):
            p = pos[c]
            if p['entry_month'] == month:
                continue
            pr = price_adj(c, month)
            p['age'] += 1
            if pr is None:
                continue
            rate = W.cost_rate(p['cap'])
            if pr == 0.0:  # vanished -> ZERO, exit at zero
                del pos[c]; n_trades_closed += 1
                continue
            if p['age'] <= 3 and pr < p['fill']:  # get-out-quick
                gross = p['sh'] * pr; cost = gross * rate
                cash += gross - cost; total_costs += cost; n_orders += 1
                del pos[c]; n_trades_closed += 1
                continue
            if pr <= 0.89 * p['fill']:  # emergency stop -11%
                gross = p['sh'] * pr; cost = gross * rate
                cash += gross - cost; total_costs += cost; n_orders += 1
                del pos[c]; n_trades_closed += 1
                continue
            if not p['sliced'] and pr >= 1.50 * p['fill']:  # top-slice half
                gross = 0.5 * p['sh'] * pr; cost = gross * rate
                cash += gross - cost; total_costs += cost; n_orders += 1
                p['sh'] *= 0.5; p['sliced'] = True
                continue
            if not p['added'] and pr >= 1.20 * p['fill']:  # average up
                amt = 0.10 * equity(month)
                if cash > 0 and amt > 0:
                    spend = min(amt, cash / (1 + rate))
                    if spend > 1.0:
                        cost = spend * rate; total_costs += cost; n_orders += 1
                        new_sh = spend / pr
                        p['fill'] = (p['fill'] * p['sh'] + pr * new_sh) / (p['sh'] + new_sh)
                        p['sh'] += new_sh; cash -= spend + cost
                        p['added'] = True
        # --- formation entries (June) or initial entry at road start ---
        is_form = (m == 6 and y in forms)
        is_start = (month == start_month)
        if is_form or is_start:
            F = y if is_form else first_form
            e = eligible(F)
            if seed is not None:
                rng = random.Random(seed * 100003 + F)
                keys = list(e.keys()); rng.shuffle(keys)
                cand = keys
            else:
                cand = ranked(F)
            slots = MAXPOS - len(pos)
            if slots > 0 and cand:
                eq_now = equity(month)
                target_amt = 0.10 * eq_now
                for c in cand:
                    if slots <= 0 or cash <= 1.0:
                        break
                    if c in pos:
                        continue
                    pr = price_adj(c, month)
                    if not pr or pr == 0.0:
                        continue
                    rate = W.cost_rate(e[c]['cap'])
                    spend = min(target_amt, cash / (1 + rate))
                    if spend <= 1.0:
                        continue
                    cost = spend * rate; total_costs += cost; n_orders += 1
                    pos[c] = dict(sh=spend / pr, fill=pr, age=0, added=False,
                                  sliced=False, cap=e[c]['cap'], entry_month=month)
                    cash -= spend + cost; slots -= 1
        curve.append([month, round(equity(month), 4)])
    # end-of-road liquidation
    if pos:
        liq = 0.0
        for c, p in pos.items():
            pr = price_adj(c, end) or 0.0
            liq += p['sh'] * pr * W.cost_rate(p['cap'])
        final = equity(end) - liq
        total_costs += liq
        curve[-1] = [end, round(final, 4)]
    else:
        final = cash
    peak = 100.0; maxdd = 0.0; dd_date = None
    for d, v in curve:
        if v > peak:
            peak = v
        dd = 1 - v / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, dd_date = dd, d
    return dict(final=round(final, 2), max_dd_pct=round(100 * maxdd, 1),
                max_dd_date=dd_date, costs=round(total_costs, 2), orders=n_orders,
                trades_closed=n_trades_closed, curve=curve)

def period_distribution(curve):
    vals = [100.0] + [v for _, v in curve]
    rets = [vals[i + 1] / vals[i] - 1 for i in range(len(vals) - 1) if vals[i] > 0]
    if not rets:
        return {}
    streak = mx = 0
    for r in rets:
        streak = streak + 1 if r < 0 else 0
        mx = max(mx, streak)
    peak = vals[0]; since = mx_since = 0
    for v in vals[1:]:
        if v >= peak:
            peak = v; since = 0
        else:
            since += 1; mx_since = max(mx_since, since)
    return dict(periods=len(rets),
                median_period_pct=round(100 * statistics.median(rets), 2),
                share_positive_pct=round(100 * sum(1 for r in rets if r > 0) / len(rets), 1),
                best_period_pct=round(100 * max(rets), 2),
                worst_period_pct=round(100 * min(rets), 2),
                longest_losing_streak=mx,
                longest_below_high_months=mx_since,
                mean_period_pct_labeled_average=round(100 * statistics.mean(rets), 2))

def spy_window(a, b):
    x, yv = D.spy.get(a), D.spy.get(b)
    return round(100 * yv / x, 2) if x and yv else None

ROADS = {
    'DECADE': dict(start='2017-06', first=2017, last=2026, champion=667.35, spy_ref=367.80),
    'CONT':   dict(start='2019-01', first=2018, last=2026, champion=544.47, spy_ref=313.62),
    'VAL':    dict(start='2023-01', first=2022, last=2026, champion=288.05, spy_ref=187.77),
}
SEEDS = list(range(1, 21))

def main():
    t0 = time.time()
    results = {'program': 'v13-best-rules', 'family': 'judgment-naked-trader',
               'label': 'JUDGMENT-CONSTRUCTED', 'verdict_ceiling': 'CANDIDATE',
               'spec': 'BEST-RULES-SPEC.md (frozen before run)',
               'habitat': 'US substitute pond (w04 broad EDGAR chassis) — UK pond unbuildable on free data (v12)',
               'long_road': 'NOT RUNNABLE on this stack (prices begin 2016-01, frames 2014)',
               'my_rules': {'count': MAXPOS, 'floor': None, 'cadence': 'annual June formation, monthly exit marks',
                            'costs': '0.75%/side (chassis small-cap tier; entire universe <$1bn cap)',
                            'start_cash': 100.0},
               'champions_vm': {'LONG': 1415.62, 'DECADE': 667.35, 'CONT': 544.47, 'VAL': 288.05},
               'spy_program_ref': {'LONG': 822.94, 'DECADE': 367.80, 'CONT': 313.62, 'VAL': 187.77},
               'roads': {}, 'confirmation': None}
    beat_any = False
    for name, rs in ROADS.items():
        r = run_road(rs['start'], rs['first'], rs['last'])
        pfin = []
        for sd in SEEDS:
            pr = run_road(rs['start'], rs['first'], rs['last'], seed=sd)
            pfin.append(pr['final'])
        beaten = sum(1 for f in pfin if f < r['final'])
        elig_counts = {F: len(eligible(F)) for F in range(rs['first'], rs['last'] + 1)}
        beat = r['final'] > rs['champion']
        beat_any = beat_any or beat
        results['roads'][name] = {
            'window_marks': [rs['start'], END], 'formations': [rs['first'], rs['last']],
            'eligible_per_formation': elig_counts,
            'spy_chassis_window': spy_window(rs['start'], END),
            'spy_program_ref': rs['spy_ref'], 'champion_vm': rs['champion'],
            'my_rules': {'final': r['final'], 'max_dd_pct': r['max_dd_pct'],
                         'max_dd_date': r['max_dd_date'], 'costs': r['costs'],
                         'orders': r['orders'], 'trades_closed': r['trades_closed'],
                         'beats_champion': beat,
                         'placebo_beaten': beaten, 'placebo_finals': pfin,
                         'placebo_median': round(statistics.median(pfin), 2),
                         'period_distribution': period_distribution(r['curve']),
                         'curve': r['curve']}}
        print(f"{name}: final ${r['final']:,.2f} maxDD {r['max_dd_pct']}% "
              f"champion ${rs['champion']} spy(win) ${spy_window(rs['start'], END)} "
              f"placebos beaten {beaten}/20 (med ${statistics.median(pfin):,.2f}) "
              f"orders={r['orders']} costs=${r['costs']} elig={elig_counts}", flush=True)

    if beat_any:
        folds = {}
        for F in range(2018, 2027):
            a, b = ym(F, 6), ym(F + 1, 6) if F < 2026 else END
            rr = run_road(a, F, F, end=b)
            sv = spy_window(a, b)
            folds[f'{F}-{F + 1}'] = {'final': rr['final'], 'spy': sv,
                                     'max_dd_pct': rr['max_dd_pct'],
                                     'win_vs_spy': (sv is not None and rr['final'] > sv)}
        halves = {}
        for hn, (a, ff, lf, b) in {'H1': ('2017-06', 2017, 2021, '2021-11'),
                                   'H2': ('2021-12', 2021, 2026, END)}.items():
            rr = run_road(a, ff, lf, end=b)
            sv = spy_window(a, b)
            halves[hn] = {'final': rr['final'], 'spy': sv, 'max_dd_pct': rr['max_dd_pct'],
                          'win_vs_spy': (sv is not None and rr['final'] > sv)}
        fw = sum(1 for v in folds.values() if v['win_vs_spy'])
        hw = sum(1 for v in halves.values() if v['win_vs_spy'])
        results['confirmation'] = {'design': 'fresh-$100 June-to-June folds 2018..2026 + DECADE halves; win = beats chassis SPY same span; bars frozen in spec: >=6/9 folds AND 2/2 halves',
                                   'folds': folds, 'fold_wins': f'{fw}/9',
                                   'half_windows': halves, 'half_wins': f'{hw}/2',
                                   'confirmed': fw >= 6 and hw == 2}
        print(f"CONFIRMATION: folds {fw}/9 halves {hw}/2 confirmed={results['confirmation']['confirmed']}", flush=True)

    results['elapsed_sec'] = round(time.time() - t0, 1)
    with open(os.path.join(HERE, 'results.json'), 'w') as f:
        json.dump(results, f, indent=1)
    print('DONE', results['elapsed_sec'], flush=True)

if __name__ == '__main__':
    main()
