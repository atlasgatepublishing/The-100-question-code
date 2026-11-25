#!/usr/bin/env python3
"""SACEVS v13 BEST RULES — implements BEST-RULES-SPEC.md exactly (frozen
before this run). Monthly chassis replicating v12 engine_common.simulate
semantics: signal at month t decides weights held t->t+1, cost 0.10%/side
on turnover, cash return = BIL monthly pct change, falling back to
DGS3MO/100/12 (v12 cash_ret). Premiums: term=DGS10-DGS3MO,
credit=DBAA-DGS10, equity = earnings yield - DGS10. z-scores vs ITD
(from 1989-03) mean/SD of observations strictly before t (v12 semantics).
Validation: published Best Value (trailing GAAP EY lag4, winner-take-all)
must land near v12 LONG $569.84. Best-rules: Weighted dial with equity
premium = (100/CAPE) lagged 4 months - DGS10. Public data only:
Yahoo monthly adjclose, FRED CSVs in program stack, Shiller xls in
program stack (current vintage, named in spec). Simulation only."""
import json, os, sys, time, urllib.request
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
FRED = '/home/hatch/workspace/stock-app/backtests/v12-completions/catalog-aronson-cn-extremes-debt/data'
XLS = '/home/hatch/workspace/stock-app/backtests/v12-completions/cape-timing/data/ie_data_live_shillerdata.xls'
SHCSV = '/home/hatch/workspace/stock-app/backtests/v10-retest/cape-timing/data/shiller_monthly_reference.csv'
ROADS = {'LONG': ('2010-01-01', '2026-10-31'), 'DECADE': ('2016-01-01', '2026-10-31'),
         'CONT': ('2019-01-01', '2026-10-31'), 'VAL': ('2023-01-01', '2026-10-31')}
CHAMP = {'LONG': 1415.62, 'CONT': 544.47, 'VAL': 288.05, 'DECADE': 667.35}
SPYREF = {'LONG': 822.94, 'CONT': 313.62, 'VAL': 187.77, 'DECADE': 367.80}
V12_BEST = {'LONG': 569.84, 'DECADE': 276.63, 'CONT': 190.90, 'VAL': 127.93}
ASSET = {'term': 'TLT', 'credit': 'LQD', 'equity': 'SPY'}
COST = 0.001

def fetch_monthly(tk):
    cache = f'{HERE}/px_{tk}.json'
    if os.path.exists(cache):
        j = json.load(open(cache))
    else:
        url = f'https://query1.finance.yahoo.com/v8/finance/chart/{tk}?range=25y&interval=1mo'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        j = json.loads(urllib.request.urlopen(req, timeout=30).read())
        json.dump(j, open(cache, 'w'))
    r = j['chart']['result'][0]; ts = r['timestamp']
    adj = r['indicators']['adjclose'][0]['adjclose']
    q = r['indicators']['quote'][0]['close']
    out = {}
    for i, t in enumerate(ts):
        v = adj[i] if adj[i] is not None else q[i]
        if v is None: continue
        d = pd.Timestamp(time.strftime('%Y-%m-%d', time.gmtime(t)))
        out[d.to_period('M').to_timestamp('M')] = float(v)
    return pd.Series(out).sort_index()

def fred_monthly(name):
    d = pd.read_csv(f'{FRED}/{name}.csv', parse_dates=[0]); d.columns = ['date', 'v']
    d = d.set_index('date')['v']; m = d.resample('M').last()
    m.index = m.index.to_period('M').to_timestamp('M'); return m

def load_all():
    P = {tk: fetch_monthly(tk) for tk in ('SPY', 'TLT', 'LQD', 'BIL')}
    D10, D3 = fred_monthly('DGS10'), fred_monthly('DGS3MO')
    DBAA = fred_monthly('DBAA')
    sh = pd.read_csv(SHCSV)
    sh['date'] = pd.PeriodIndex(sh['month'], freq='M').to_timestamp('M')
    sh = sh.set_index('date')
    ey_trail = (sh['earnings_trailing'] / sh['price'] * 100).shift(4)
    import xlrd
    wb = xlrd.open_workbook(XLS); ws = wb.sheet_by_name('Data')
    cape = {}
    for r in range(8, ws.nrows):
        d = ws.cell_value(r, 0); c = ws.cell_value(r, 12)
        if isinstance(d, (int, float)) and d > 0 and isinstance(c, (int, float)) and c > 0:
            y = int(d); m = int(round((d - y) * 100))
            cape[pd.Period(f'{y}-{m:02d}', freq='M').to_timestamp('M')] = float(c)
    cape = pd.Series(cape).sort_index()
    ey_cape = (100.0 / cape).shift(4)
    prem_pub = {'term': D10 - D3, 'credit': DBAA - D10, 'equity': ey_trail - D10}
    prem_new = {'term': D10 - D3, 'credit': DBAA - D10, 'equity': ey_cape - D10}
    cr_bil = P['BIL'].pct_change()
    cr_yield = D3 / 100 / 12
    cr = cr_bil.combine_first(cr_yield)
    return P, prem_pub, prem_new, cr

def zscores(prem, t):
    zs = {}
    for k, s in prem.items():
        s = s.dropna()
        if t not in s.index: return None
        hist = s[(s.index >= pd.Timestamp('1989-03-31')) & (s.index <= t)]
        if len(hist) < 24: return None
        mu, sd = hist.iloc[:-1].mean(), hist.iloc[:-1].std()
        if sd == 0 or np.isnan(sd): return None
        zs[k] = (s[t] - mu) / sd
    return zs

def fn_best(prem):
    def f(t, P, cr):
        zs = zscores(prem, t)
        if not zs: return {}
        pos = {k: v for k, v in zs.items() if v > 0}
        if not pos: return {}
        return {ASSET[max(pos, key=pos.get)]: 1.0}
    return f

def fn_weighted(prem):
    def f(t, P, cr):
        zs = zscores(prem, t)
        if not zs: return {}
        pos = {k: v for k, v in zs.items() if v > 0}
        if not pos: return {}
        tot = sum(pos.values())
        return {ASSET[k]: v / tot for k, v in pos.items()}
    return f

def fn_static(t, P, cr):
    return {'SPY': 0.60, 'TLT': 0.25, 'LQD': 0.15}

def fn_spy(t, P, cr):
    return {'SPY': 1.0}

def period_stats(eq):
    r = eq.pct_change().dropna()
    if len(r) == 0: return {}
    ls = cur = 0
    for x in r:
        cur = cur + 1 if x <= 0 else 0; ls = max(ls, cur)
    run_max = eq.cummax(); below = (eq < run_max - 1e-9)
    lb = cur = 0
    for x in below:
        cur = cur + 1 if x else 0; lb = max(lb, cur)
    dd = (eq / run_max - 1).min()
    return {'n_periods': int(len(r)), 'share_positive': round(float((r > 0).mean()), 3),
            'median_period': round(float(r.median()), 4), 'mean_period_secondary': round(float(r.mean()), 4),
            'best': round(float(r.max()), 4), 'worst': round(float(r.min()), 4),
            'longest_losing_streak': int(ls), 'longest_below_high_months': int(lb),
            'max_dd': round(float(dd), 4)}

def simulate(P, cr, signal_fn, start, end, placebo_seed=None):
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    idx = P['SPY'].index; idx = idx[(idx >= start) & (idx <= end)]
    rng = np.random.default_rng(placebo_seed) if placebo_seed is not None else None
    eq = 100.0; curve = {}; weights = {}; total_cost = 0.0
    months = list(idx)
    for i, t in enumerate(months):
        curve[t] = eq
        if i == len(months) - 1: break
        t1 = months[i + 1]
        if rng is not None:
            assets = ['TLT', 'LQD', 'SPY']; k = int(rng.integers(1, len(assets) + 1))
            pick = rng.choice(assets, size=k, replace=False); w = rng.dirichlet(np.ones(k))
            new_w = {a: float(x) for a, x in zip(pick, w)}
        else:
            new_w = {k: float(v) for k, v in signal_fn(t, P, cr).items() if abs(v) > 1e-9}
        allk = set(weights) | set(new_w)
        turn = sum(abs(new_w.get(k, 0) - weights.get(k, 0)) for k in allk)
        c = eq * turn * COST; total_cost += c; eq -= c
        crv = cr.get(t1, 0.0) if t1 in cr.index else 0.0
        if crv is None or pd.isna(crv): crv = 0.0
        ret = (1 - sum(new_w.values())) * crv
        for k, w in new_w.items():
            s = P[k]
            ret += w * (s[t1] / s[t] - 1) if (t in s.index and t1 in s.index) else w * crv
        eq *= (1 + ret); weights = new_w
    return pd.Series(curve), total_cost

def pack(eq, cost):
    return {'final': round(float(eq.iloc[-1]), 2), 'cost': round(float(cost), 2),
            'stats': period_stats(eq),
            'curve': {str(k.date()): round(float(v), 4) for k, v in eq.items()}}

def main():
    P, prem_pub, prem_new, cr = load_all()
    out = {'champions': CHAMP, 'spy_reference': SPYREF, 'v12_published_best': V12_BEST}
    # validation: published Best Value on this plumbing
    out['validation_published_best'] = {}
    for road, (s, e) in ROADS.items():
        eq, c = simulate(P, cr, fn_best(prem_pub), s, e)
        out['validation_published_best'][road] = pack(eq, c)
    # best rules
    out['roads'] = {}
    for road, (s, e) in ROADS.items():
        eq, c = simulate(P, cr, fn_weighted(prem_new), s, e)
        out['roads'][road] = pack(eq, c)
    # controls
    out['static_mix'] = {}; out['spy_buyhold_same_plumbing'] = {}
    for road, (s, e) in ROADS.items():
        eq, c = simulate(P, cr, fn_static, s, e); out['static_mix'][road] = pack(eq, c)
        eq, c = simulate(P, cr, fn_spy, s, e); out['spy_buyhold_same_plumbing'][road] = pack(eq, c)
    # exposure diagnostics for best rules (LONG)
    # placebos
    out['placebos'] = {}
    for road in ('LONG', 'CONT'):
        s, e = ROADS[road]; beats = 0; finals = []
        for seed in range(20):
            eqp, _ = simulate(P, cr, fn_weighted(prem_new), s, e, placebo_seed=seed)
            finals.append(float(eqp.iloc[-1]))
            if out['roads'][road]['final'] > finals[-1]: beats += 1
        out['placebos'][road] = {'beats': beats, 'median_placebo': round(float(np.median(finals)), 2),
                                 'finals': [round(f, 2) for f in finals]}
    # yearly folds + half windows (confirmation machinery, computed regardless)
    out['confirmation'] = {}
    for road, (s, e) in ROADS.items():
        months = P['SPY'].index; months = months[(months >= pd.Timestamp(s)) & (months <= pd.Timestamp(e))]
        mid = months[len(months) // 2]
        halves = {}
        for name, (hs, he) in {'first_half': (s, str(mid.date())), 'second_half': (str(mid.date()), e)}.items():
            eqm, _ = simulate(P, cr, fn_weighted(prem_new), hs, he)
            eqs, _ = simulate(P, cr, fn_spy, hs, he)
            eqx, _ = simulate(P, cr, fn_static, hs, he)
            halves[name] = {'mine': round(float(eqm.iloc[-1]), 2), 'spy': round(float(eqs.iloc[-1]), 2),
                            'static': round(float(eqx.iloc[-1]), 2)}
        folds = {}; wins = 0; tot = 0
        for y in range(int(s[:4]), 2027):
            ys, ye = f'{y}-01-01', f'{y}-12-31'
            if pd.Timestamp(ys) > pd.Timestamp(e): break
            if pd.Timestamp(ye) < pd.Timestamp(s): continue
            ys2 = max(ys, s); ye2 = min(ye, e)
            eqm, _ = simulate(P, cr, fn_weighted(prem_new), ys2, ye2)
            eqs, _ = simulate(P, cr, fn_spy, ys2, ye2)
            if len(eqm) < 3: continue
            folds[str(y)] = {'mine': round(float(eqm.iloc[-1]), 2), 'spy': round(float(eqs.iloc[-1]), 2)}
            tot += 1; wins += 1 if eqm.iloc[-1] > eqs.iloc[-1] else 0
        out['confirmation'][road] = {'halves': halves, 'yearly_folds': folds,
                                     'folds_beat_spy': f'{wins}/{tot}'}
    json.dump(out, open(f'{HERE}/results.json', 'w'), indent=1)
    print('VALIDATION published Best Value:', {r: out['validation_published_best'][r]['final'] for r in ROADS},
          'vs v12', V12_BEST)
    print('BEST RULES:', {r: out['roads'][r]['final'] for r in ROADS})
    print('STATIC:', {r: out['static_mix'][r]['final'] for r in ROADS})
    print('SPY same plumbing:', {r: out['spy_buyhold_same_plumbing'][r]['final'] for r in ROADS}, 'ref', SPYREF)
    print('PLACEBOS:', out['placebos'])

if __name__ == '__main__':
    main()
