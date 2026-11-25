#!/usr/bin/env python3
"""HOLDINGS-COUNT SWEEP — dividend-growth / Aristocrats line.

Native form (canonical v12 CONSTRUCTION-SPEC, S&P Dividend Aristocrats
methodology): PIT S&P 500 members with 25+ consecutive years of DPS
increases — qualification taken from S&P's own published rosters (frozen in
the canonical folder's rosters.py) — ALL qualifiers held equal-weight,
annual January reconstitution, quarterly EW resets, no ranking, no floor,
costs 0.10%/side + $0.01/sell. Native count = ALL-ELIGIBLE (whole roster,
43-71 names).

Sweep: the Aristocrats form itself has no ranking, so the count sweep uses
the nearest documented ranking overlay, labeled CONSTRUCTED: rank each
January's qualifiers by trailing calendar-year dividend yield (DPS paid in
Y-1 / raw close at formation) and hold the top N. GRID = 1,2,3,5,8,10,15,
20,30, ALL-ELIGIBLE (= native count). 20-seed placebos per cell: random N
from the same January roster (names with tapes), same mechanics.

Rulesets: native (no floor) and house (v9: plain -15% floor from episode
start on month-end marks; first halt -> liquidate, 90-day sit-out, restart
at next quarterly reset >= halt+90d re-buying the current roster-year picks
under an episode-2 floor; second halt ends the run). Costs identical in
both (the native spec already uses program costs). Quarterly resets trade
only the drift back to equal weight (the index's own mechanics).

Roads (January formation year Y -> held to 2026-11-20):
LONG 2010, DECADE 2016, CONT 2019, VAL 2023.
Confirmation folds if triggered: FOLD_A start 2010, FOLD_B start 2018
(same end), candidate vs ALL-ELIGIBLE under native rules.
Prices: canonical folder's px_<T>.json daily adjclose tapes (read-only).
Dividend events + raw closes: this folder's data/dg_div/ (v7 pxfull /
Yahoo). Vanished tape -> ZERO (canonical rule). Successor chaining per
canonical SUCCESSOR map.
"""
import json, os, sys, math, random, bisect, datetime as _dt
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..')
DG = os.path.expanduser('~/workspace/stock-app/backtests/v12-completions/dividend-growth')
sys.path.insert(0, DG)
from rosters import ROSTERS, SUCCESSOR
PXD = os.path.join(DG, 'data')
DIVD = os.path.join(ROOT, 'data', 'dg_div')
END = '2026-11-20'

def tape(t): return SUCCESSOR.get(t, t)

class Data:
    def __init__(self):
        self.adj = {}
        self.raw = {}
        self.dps = {}
        # adj tapes are stored under the ROSTER ticker's filename (the
        # canonical fetch saves successor tapes as px_<original>.json).
        names = sorted({t for v in ROSTERS.values() for t in v} | {'SPY'})
        for t in names:
            p = os.path.join(PXD, f'px_{t}.json')
            if os.path.exists(p):
                bars = json.load(open(p))['bars']
                self.adj[t] = ([b[0] for b in bars], [b[1] for b in bars])
        tapes = sorted({tape(t) for v in ROSTERS.values() for t in v} | {'SPY'})
        for t in tapes:
            dp = os.path.join(DIVD, f'{t}.json')
            if os.path.exists(dp):
                j = json.load(open(dp))
                self.raw[t] = {d: c for d, c in j['raw']}
                dps = {}
                for d, amt in j['divs']:
                    dps[int(d[:4])] = dps.get(int(d[:4]), 0.0) + amt
                self.dps[t] = dps
        self.cal = self.adj['SPY'][0]
        self.raw_dates = {t: sorted(r) for t, r in self.raw.items()}
        self._ltd = {}
        for d in self.cal:
            self._ltd[(int(d[:4]), int(d[5:7]))] = d
    def adj_at(self, t, date):
        if t not in self.adj: return None
        dates, vals = self.adj[t]
        i = bisect.bisect_right(dates, date) - 1
        if i < 0: return None
        return vals[i], dates[i]
    def last_bar_date(self, t):
        if t not in self.adj: return None
        return self.adj[t][0][-1]
    def raw_at(self, t, date):
        r = self.raw.get(t)
        if not r: return None
        ds = self.raw_dates[t]
        i = bisect.bisect_right(ds, date) - 1
        if i < 0: return None
        return r[ds[i]]
    def month_end_dates(self, start, end):
        seen = {}
        for d in self.cal:
            if start <= d <= end: seen[d[:7]] = d
        return [seen[k] for k in sorted(seen)]

D = None

def last_td(year, month):
    return D._ltd.get((year, month))

def roster_with_tapes(Y):
    out = []
    fd = last_td(Y, 1)
    for t in ROSTERS[Y]:
        r = D.adj_at(t, fd)
        if r is not None and r[1][:10] >= f'{Y-1:04d}-06-01':
            out.append(t)
    return out

def ranked(Y, names):
    fd = last_td(Y, 1)
    def yld(t):
        tt = tape(t)
        dps = D.dps.get(tt, {}).get(Y - 1, 0.0)
        rc = D.raw_at(tt, fd)
        if not rc: return -1.0
        return dps / rc
    return sorted(names, key=lambda t: (-yld(t), t))

def run(start_year, count, rules, seed=None):
    events = []
    for Y in range(start_year, 2027):
        for m in (1, 4, 7, 10):
            d = last_td(Y, m)
            if d and d <= END: events.append((d, Y, m == 1))
    events.sort()
    me_dates = D.month_end_dates(last_td(start_year, 1), END)
    timeline = sorted([(d, 'ev', (Y, f)) for d, Y, f in events] +
                      [(d, 'me', None) for d in me_dates])
    st = {'cash': 100.0, 'pos': {}, 'costs': 0.0, 'orders': 0, 'vanished': set()}
    halts = []; episode_start = 100.0; ended = False
    sit_out_until = None; cur_picks = []

    def price_of(t, date):
        lb = D.last_bar_date(t)
        # vanished -> ZERO, except tapes ending within 45 days of END
        # (dataset end, not a delisting) are valued at their last bar.
        if lb is not None and date > lb[:10] and lb[:10] < '2026-10-06': return None
        r = D.adj_at(t, date)
        return r[0] if r else None

    def value_at(date):
        tot = st['cash']
        for t, sh in st['pos'].items():
            p = price_of(t, date)
            if p: tot += sh * p
        return tot

    def sell_all(date):
        tot = st['cash']
        for t, sh in list(st['pos'].items()):
            p = price_of(t, date)
            if p is None:
                st['vanished'].add(t); continue
            gross = sh * p; cst = gross * 0.0010 + 0.01
            st['costs'] += cst; st['orders'] += 1; tot += gross - cst
        st['pos'] = {}
        return tot

    def rebalance(date, picks):
        # drop vanished / non-pick names at market (non-picks sold in full)
        for t in list(st['pos'].keys()):
            p = price_of(t, date)
            if p is None:
                st['vanished'].add(t); del st['pos'][t]
            elif t not in picks:
                gross = st['pos'][t] * p; cst = gross * 0.0010 + 0.01
                st['costs'] += cst; st['orders'] += 1; st['cash'] += gross - cst
                del st['pos'][t]
        total = value_at(date)
        if not picks: return
        target = total / len(picks)
        # sells first (drift only)
        for t in picks:
            p = price_of(t, date)
            if p is None: continue
            cur = st['pos'].get(t, 0.0) * p
            if cur > target:
                sell_val = cur - target
                cst = sell_val * 0.0010 + 0.01
                st['costs'] += cst; st['orders'] += 1
                st['pos'][t] -= sell_val / p
                st['cash'] += sell_val - cst
        # buys
        for t in picks:
            p = price_of(t, date)
            if p is None: continue
            cur = st['pos'].get(t, 0.0) * p
            if cur < target:
                buy_val = min(target - cur, st['cash'] / 1.001)
                if buy_val <= 0: continue
                cst = buy_val * 0.0010
                st['costs'] += cst; st['orders'] += 1
                st['pos'][t] = st['pos'].get(t, 0.0) + buy_val / p
                st['cash'] -= buy_val + cst

    curve_m = []
    for date, kind, payload in timeline:
        if kind == 'ev':
            Y, isform = payload
            if ended: continue
            if sit_out_until is not None and date < sit_out_until: continue
            if isform:
                names = roster_with_tapes(Y)
                n = len(names) if count == 'ALL' else min(count, len(names))
                if seed is None:
                    cur_picks = list(names) if count == 'ALL' else ranked(Y, names)[:n]
                else:
                    rng = random.Random(seed * 10000 + Y)
                    pool = list(names); rng.shuffle(pool)
                    cur_picks = pool[:n]
            restarting = sit_out_until is not None and date >= sit_out_until
            if restarting: sit_out_until = None
            if isform or restarting:
                st['cash'] = sell_all(date)
                episode_start = st['cash']
            rebalance(date, cur_picks)
        else:
            v = value_at(date)
            curve_m.append([date, round(v, 2)])
            if rules == 'house' and not ended and st['pos'] and v <= 0.85 * episode_start:
                st['cash'] = sell_all(date)
                halts.append(date)
                curve_m[-1] = [date, round(st['cash'], 2)]
                if len(halts) >= 2:
                    ended = True
                else:
                    hd = _dt.date(int(date[:4]), int(date[5:7]), int(date[8:10])) + _dt.timedelta(days=90)
                    sit_out_until = hd.isoformat()
    if st['pos']:
        st['cash'] = sell_all(END)
    peak = 100.0; maxdd = 0.0
    for _, v in curve_m:
        peak = max(peak, v); maxdd = max(maxdd, 1 - v / peak)
    spy_final = None
    a = D.adj_at('SPY', last_td(start_year, 1)); b = D.adj_at('SPY', END)
    if a and b: spy_final = round(100 * b[0] / a[0], 2)
    return {'final': round(st['cash'], 2), 'max_dd': round(maxdd, 4),
            'costs': round(st['costs'], 2), 'orders': st['orders'],
            'vanished_zeroed': sorted(st['vanished']), 'halts': halts,
            'curve_monthly': curve_m, 'spy_final_same_window': spy_final}

GRID = [1, 2, 3, 5, 8, 10, 15, 20, 30, 'ALL']
ROADS = {'LONG': 2010, 'DECADE': 2016, 'CONT': 2019, 'VAL': 2023}

def save_json(obj, path):
    import time as _t
    tmp = path + '.tmp'
    for attempt in range(5):
        try:
            with open(tmp, 'w') as f:
                json.dump(obj, f, indent=1)
            os.replace(tmp, path)
            return
        except OSError as e:
            print('save retry', attempt, e, flush=True); _t.sleep(3)
    raise RuntimeError('could not save ' + path)

def main():
    global D
    D = Data()
    print('tapes loaded:', len(D.adj), 'div files:', len(D.dps), flush=True)
    res = {'family': 'dividend-growth', 'line': 'holdings-count sweep',
           'form_swept': 'Aristocrats published rosters; native count = ALL qualifiers; '
                         'top-N ranking overlay (trailing DPS yield) is CONSTRUCTED',
           'roster_sizes': {Y: len(ROSTERS[Y]) for Y in sorted(ROSTERS)},
           'roads': {}}
    for rname, sy_ in ROADS.items():
        res['roads'][rname] = {}
        for rules in ('native', 'house'):
            res['roads'][rname][rules] = {}
            for count in GRID:
                r = run(sy_, count, rules)
                cell = {k: r[k] for k in ('final', 'max_dd', 'costs', 'orders', 'vanished_zeroed', 'halts', 'spy_final_same_window')}
                cell['detail'] = {'curve_monthly': r['curve_monthly']}
                if count != 'ALL':
                    twins = [run(sy_, count, rules, seed=s)['final'] for s in range(1, 21)]
                    cell['placebo_finals'] = twins
                    cell['placebos_beaten'] = sum(1 for t in twins if r['final'] > t)
                res['roads'][rname][rules][str(count)] = cell
                print(rname, rules, count, 'final', cell['final'], 'beat',
                      cell.get('placebos_beaten'), '/20', 'halts', cell['halts'], flush=True)
        save_json(res, os.path.join(ROOT, 'results_dg_partial.json'))
    wins = {}
    totals = {}
    for count in GRID:
        if count == 'ALL': continue
        w = sum(1 for rname in ROADS
                if res['roads'][rname]['native'][str(count)]['final'] > res['roads'][rname]['native']['ALL']['final'])
        wins[count] = w
        totals[count] = sum(res['roads'][rname]['native'][str(count)]['final'] for rname in ROADS)
    print('non-native road wins vs ALL (native rules):', wins, flush=True)
    print('non-native total finals (native rules):', totals, flush=True)
    # CONFIRMATION RULE: every count beating native on >=3 roads is folded;
    # the money-winner (highest total) is the headline candidate.
    res['confirmation'] = {}
    for count in GRID:
        if count == 'ALL' or wins.get(count, 0) < 3: continue
        folds = {
            'FOLD_A_start2010': {'candidate': run(2010, count, 'native')['final'],
                                 'native_ALL': run(2010, 'ALL', 'native')['final']},
            'FOLD_B_start2018': {'candidate': run(2018, count, 'native')['final'],
                                 'native_ALL': run(2018, 'ALL', 'native')['final']}}
        res['confirmation'][str(count)] = folds
        print('CONFIRMATION count', count, folds, flush=True)
    res['curves'] = {}
    for rules in ('native', 'house'):
        res['curves'][rules] = {rname: {'ALL': run(sy_, 'ALL', rules)} for rname, sy_ in ROADS.items()}
    save_json(res, os.path.join(ROOT, 'results_dg.json'))
    print('saved results_dg.json', flush=True)

if __name__ == '__main__':
    main()
