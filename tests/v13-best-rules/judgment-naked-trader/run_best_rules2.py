#!/usr/bin/env python3
"""V13 BEST-RULES — judgment-naked-trader, AMENDED STACK (Amendment 1).
Spec: BEST-RULES-SPEC.md + Amendment 1 (pond correction after degenerate
Run 1; every strategy rule unchanged). Simulation only. JUDGMENT-CONSTRUCTED.

Stack: shareholder-yield construction universe (1,559 EDGAR filers,
NYSE/Nasdaq only = main-market equivalent), monthly prices from that
folder's cache (2010..2026-11), EDGAR frames (SY folder + w04 folder +
./frames backfill 2009-2013, all read-only except ./frames), vanished -> ZERO.
DPS frame does not exist in EDGAR frames API (404 all years) -> the rising-
dividend leg stays DROPPED per the frozen conditional in Amendment 1.
Costs 0.75%/side (frozen). No portfolio floor (frozen).
"""
import csv, json, os, random, statistics, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
SY = os.path.expanduser('~/workspace/stock-app/backtests/v12-completions/shareholder-yield/data')
W04 = os.path.expanduser('~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data')
END = '2026-11'

# ---------- frames (search: mine -> SY -> w04) ----------
_frame_dirs = [os.path.join(HERE, 'frames'), os.path.join(SY, 'frames'),
               os.path.join(W04, 'frames')]
_frame_cache = {}
def load_frame(name):
    if name in _frame_cache:
        return _frame_cache[name]
    out = {}
    for d in _frame_dirs:
        p = os.path.join(d, name)
        if os.path.exists(p):
            try:
                out = {int(k): v for k, v in json.load(open(p)).items()}
            except Exception:
                out = {}
            break
    _frame_cache[name] = out
    return out

def F(concept, year, kind):
    return load_frame(f'{concept}_{year}{kind}.json')

# ---------- universe & prices ----------
CAND = {int(k): v for k, v in json.load(open(os.path.join(SY, 'candidates.json'))).items()
        if v.get('exchange') in ('NYSE', 'Nasdaq', 'AMEX')}
PX = {}
for cik, info in CAND.items():
    t = info['ticker']
    p = os.path.join(SY, f'px_{t}.json')
    if os.path.exists(p):
        try:
            PX[cik] = {r[0]: (r[1], r[2]) for r in json.load(open(p))}
        except Exception:
            pass
SPY = {}
try:
    SPY = {r[0]: r[1] for r in json.load(open(os.path.join(SY, 'px_SPY.json')))}
except Exception:
    pass

SH_YEARS = list(range(2009, 2026))
SH_SER = {y: F('Shares', y, 'I') for y in SH_YEARS}
NI = {y: F('NetIncomeLoss', y, 'D') for y in range(2009, 2026)}

def ym(y, m):
    return f'{y:04d}-{m:02d}'

def split_factor(cik, F_):
    avail = [(y, SH_SER[y].get(cik)) for y in SH_YEARS if SH_SER[y].get(cik)]
    f = 1.0
    for (y0, a), (y1, b) in zip(avail, avail[1:]):
        if y1 >= F_:
            r = b / a
            if r >= 1.6 or r <= 0.625:
                f *= r
    return f

def eps_series(cik, F_):
    raw = {}
    for y in range(2009, F_):
        ni, sh = NI[y].get(cik), SH_SER[y].get(cik)
        if ni is not None and sh:
            raw[y] = ni / sh
    if not raw:
        return {}
    yrs = sorted(raw)
    adj = {}
    for i, y in enumerate(yrs):
        f = 1.0
        for y0, y1 in zip(yrs[i:], yrs[i + 1:]):
            r = SH_SER[y1][cik] / SH_SER[y0][cik]
            if r >= 1.6 or r <= 0.625:
                f *= r
        adj[y] = raw[y] / f if f else raw[y]
    return adj

def price_adj(cik, month, adj=True):
    s = PX.get(cik)
    if not s:
        return None
    if month in s:
        return s[month][0] if adj else s[month][1]
    prev = [m for m in s if m < month]
    if not prev:
        return None
    if month > max(s):
        return 0.0
    return s[max(prev)][0] if adj else s[max(prev)][1]

# ---------- insider buys (Form 4 code P) ----------
_buys = {}
_ev = os.path.expanduser('~/workspace/stock-app/backtests/v3/insider-data/events.csv')
if os.path.exists(_ev):
    with open(_ev) as f:
        for r in csv.DictReader(f):
            if r['code'] != 'P':
                continue
            try:
                _buys.setdefault(int(r['issuer_cik']), []).append((r['filing_date'], float(r['value'])))
            except Exception:
                continue

def insider_buy(cik, form_date):
    lo = f'{int(form_date[:4]) - 1}-{form_date[5:]}'
    return sum(v for fd, v in _buys.get(cik, []) if lo < fd <= form_date)

# ---------- snapshot / eligibility ----------
def rev_of(y):
    a, b, c = F('Revenues', y, 'D'), F('SalesRevenueNet', y, 'D'), \
        F('RevenueFromContractWithCustomerExcludingAssessedTax', y, 'D')
    return a, b, c

def snapshot(F_):
    out = {}
    ltdc, dc, ltdn, ltd = F('LongTermDebtCurrent', F_ - 1, 'I'), F('DebtCurrent', F_ - 1, 'I'), \
        F('LongTermDebtNoncurrent', F_ - 1, 'I'), F('LongTermDebt', F_ - 1, 'I')
    cashf = F('CashAndCashEquivalentsAtCarryingValue', F_ - 1, 'I')
    opinc = F('OperatingIncomeLoss', F_ - 1, 'D')
    r1a, r1b, r1c = rev_of(F_ - 1)
    r0a, r0b, r0c = rev_of(F_ - 2)
    for cik in CAND:
        if cik not in PX:
            continue
        shares = None
        for yy in (F_ - 1, F_ - 2, F_ - 3):
            if yy in SH_SER and SH_SER[yy].get(cik):
                shares = SH_SER[yy][cik]
                break
        px_raw = price_adj(cik, ym(F_, 6), adj=False)
        cap = (shares * px_raw * split_factor(cik, F_)) if (shares and px_raw) else None
        has_debt = any(cik in d for d in (ltdc, dc, ltdn, ltd))
        debt = (ltdc.get(cik) or dc.get(cik) or 0) + (ltdn.get(cik) or ltd.get(cik) or 0) \
            if has_debt else None
        rev1 = r1a.get(cik) or r1b.get(cik) or r1c.get(cik)
        rev0 = r0a.get(cik) or r0b.get(cik) or r0c.get(cik)
        out[cik] = dict(cap=cap, shares=shares, px_raw=px_raw, debt=debt,
                        cash=cashf.get(cik), opinc=opinc.get(cik),
                        rev=rev1, rev0=rev0, ticker=CAND[cik]['ticker'])
    return out

_snap = {}
def eligible(F_):
    if F_ in _snap:
        return _snap[F_]
    s = snapshot(F_)
    out = {}
    for cik, v in s.items():
        cap = v['cap']
        if not cap or cap < 20e6 or cap > 1e9:
            continue
        if v['opinc'] is None or v['opinc'] <= 0:
            continue
        debt = v['debt'] if v['debt'] is not None else 0.0
        if (debt - (v['cash'] or 0.0)) > 3.0 * v['opinc']:
            continue
        if v['rev'] is None or v['rev0'] is None or not (v['rev'] > v['rev0']):
            continue
        eps = eps_series(cik, F_)
        if (F_ - 1) not in eps or (F_ - 2) not in eps:
            continue
        if not (eps[F_ - 1] > eps[F_ - 2]) or eps[F_ - 1] <= 0:
            continue
        px_raw = v['px_raw']
        if not px_raw:
            continue
        pe = px_raw / eps[F_ - 1]
        if not (12.0 <= pe < 20.0):
            continue
        if not v['shares']:
            continue
        op_ps = v['opinc'] / v['shares']
        if op_ps <= 0 or not (px_raw / op_ps < 15.0):
            continue
        p_now = price_adj(cik, ym(F_, 6)); p_yr = price_adj(cik, ym(F_ - 1, 6))
        if not p_now or not p_yr or not (p_now > p_yr):
            continue
        lows = [price_adj(cik, ym(F_ - 1, m)) for m in range(7, 13)] + \
               [price_adj(cik, ym(F_, m)) for m in range(1, 7)]
        lows = [x for x in lows if x]
        if not lows or p_now < 1.05 * min(lows):
            continue
        out[cik] = dict(cap=cap, mom=p_now / p_yr - 1.0, ticker=v['ticker'],
                        insider=insider_buy(cik, f'{F_}-06-30'))
    _snap[F_] = out
    return out

def ranked(F_):
    e = eligible(F_)
    return sorted(e, key=lambda c: (-round(e[c]['mom'], 4),
                                    0 if e[c]['insider'] > 0 else 1,
                                    e[c]['ticker']))

# ---------- run machinery (identical rules to Run 1) ----------
MAXPOS = 10
RATE = 0.0075

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

def run_road(start_month, first_form, last_form, seed=None, end=END):
    cash = 100.0
    pos = {}
    curve = []
    total_costs = 0.0; n_orders = 0; n_closed = 0
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
        for c in list(pos):
            p = pos[c]
            if p['entry_month'] == month:
                continue
            pr = price_adj(c, month)
            p['age'] += 1
            if pr is None:
                continue
            if pr == 0.0:
                del pos[c]; n_closed += 1
                continue
            if p['age'] <= 3 and pr < p['fill']:
                gross = p['sh'] * pr; cost = gross * RATE
                cash += gross - cost; total_costs += cost; n_orders += 1
                del pos[c]; n_closed += 1
                continue
            if pr <= 0.89 * p['fill']:
                gross = p['sh'] * pr; cost = gross * RATE
                cash += gross - cost; total_costs += cost; n_orders += 1
                del pos[c]; n_closed += 1
                continue
            if not p['sliced'] and pr >= 1.50 * p['fill']:
                gross = 0.5 * p['sh'] * pr; cost = gross * RATE
                cash += gross - cost; total_costs += cost; n_orders += 1
                p['sh'] *= 0.5; p['sliced'] = True
                continue
            if not p['added'] and pr >= 1.20 * p['fill']:
                amt = 0.10 * equity(month)
                if cash > 0 and amt > 0:
                    spend = min(amt, cash / (1 + RATE))
                    if spend > 1.0:
                        cost = spend * RATE; total_costs += cost; n_orders += 1
                        new_sh = spend / pr
                        p['fill'] = (p['fill'] * p['sh'] + pr * new_sh) / (p['sh'] + new_sh)
                        p['sh'] += new_sh; cash -= spend + cost
                        p['added'] = True
        is_form = (m == 6 and y in forms)
        is_start = (month == start_month)
        if is_form or is_start:
            F_ = y if is_form else first_form
            e = eligible(F_)
            if seed is not None:
                rng = random.Random(seed * 100003 + F_)
                cand = list(e.keys()); rng.shuffle(cand)
            else:
                cand = ranked(F_)
            slots = MAXPOS - len(pos)
            if slots > 0 and cand:
                target_amt = 0.10 * equity(month)
                for c in cand:
                    if slots <= 0 or cash <= 1.0:
                        break
                    if c in pos:
                        continue
                    pr = price_adj(c, month)
                    if not pr or pr == 0.0:
                        continue
                    spend = min(target_amt, cash / (1 + RATE))
                    if spend <= 1.0:
                        continue
                    cost = spend * RATE; total_costs += cost; n_orders += 1
                    pos[c] = dict(sh=spend / pr, fill=pr, age=0, added=False,
                                  sliced=False, entry_month=month)
                    cash -= spend + cost; slots -= 1
        curve.append([month, round(equity(month), 4)])
    if pos:
        liq = sum(p['sh'] * (price_adj(c, end) or 0.0) * RATE for c, p in pos.items())
        final = equity(end) - liq
        total_costs += liq
        curve[-1] = [end, round(final, 4)]
    else:
        final = cash
    peak = 100.0; maxdd = 0.0; dd_date = None
    for d, v in curve:
        peak = max(peak, v)
        dd = 1 - v / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, dd_date = dd, d
    return dict(final=round(final, 2), max_dd_pct=round(100 * maxdd, 1),
                max_dd_date=dd_date, costs=round(total_costs, 2), orders=n_orders,
                trades_closed=n_closed, curve=curve)

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
    x, yv = SPY.get(a), SPY.get(b)
    return round(100 * yv / x, 2) if x and yv else None

ROADS = {
    'LONG':   dict(start='2011-06', first=2011, last=2026, champion=1415.62, spy_ref=822.94),
    'DECADE': dict(start='2016-11', first=2016, last=2026, champion=667.35, spy_ref=367.80),
    'CONT':   dict(start='2019-01', first=2018, last=2026, champion=544.47, spy_ref=313.62),
    'VAL':    dict(start='2023-01', first=2022, last=2026, champion=288.05, spy_ref=187.77),
}
SEEDS = list(range(1, 21))

def main():
    t0 = time.time()
    results = {'program': 'v13-best-rules', 'family': 'judgment-naked-trader',
               'label': 'JUDGMENT-CONSTRUCTED', 'verdict_ceiling': 'CANDIDATE',
               'spec': 'BEST-RULES-SPEC.md + Amendment 1 (frozen before substantive run)',
               'run1_degenerate': 'w04 pond: 0 eligible every formation, all roads $100.00 cash (results-run1-degenerate.json)',
               'habitat': 'US substitute pond (shareholder-yield construction, NYSE/Nasdaq) — UK pond unbuildable on free data (v12)',
               'universe_size': len(CAND), 'priced': len(PX),
               'dps_leg': 'DROPPED — EDGAR frames API 404 for CommonStockDividendsPerShareCashPaid all years (Amendment 1 conditional)',
               'my_rules': {'count': MAXPOS, 'floor': None,
                            'cadence': 'annual June formation, monthly exit marks',
                            'costs': '0.75%/side flat (frozen; universe entirely <$1bn cap)',
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
        for Fy in range(2018, 2027):
            a, b = ym(Fy, 6), ym(Fy + 1, 6) if Fy < 2026 else END
            rr = run_road(a, Fy, Fy, end=b)
            sv = spy_window(a, b)
            folds[f'{Fy}-{Fy + 1}'] = {'final': rr['final'], 'spy': sv,
                                       'max_dd_pct': rr['max_dd_pct'],
                                       'win_vs_spy': (sv is not None and rr['final'] > sv)}
        halves = {}
        for hn, (a, ff, lf, b) in {'H1': ('2016-11', 2016, 2021, '2021-11'),
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
