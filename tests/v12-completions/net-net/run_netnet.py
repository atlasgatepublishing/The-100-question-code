#!/usr/bin/env python3
"""v12 net-net engine — frozen rules per CONSTRUCTION-SPEC.md.
Monthly marks (Yahoo adjclose). Formations June 2016-2025. Exits: +50%,
June-review cap>NCAV, 36 months, vanish-to-zero. Costs by formation cap
(<100M 2.0%, <1B 1.0%, >=1B 0.5% per side). 20-seed placebos from the same
priced possible-qualifier pool. Roads FULL/CONT/VAL + folds. Simulation only.
"""
import json, os, random, statistics, datetime
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, 'concept_cache')
PXD = os.path.join(HERE, 'px')

def ym(y, m): return f'{y:04d}-{m:02d}'
def months_between(a, b):
    out = []
    y, m = int(a[:4]), int(a[5:7])
    while ym(y, m) <= b:
        out.append(ym(y, m))
        m += 1
        if m == 13: y, m = y + 1, 1
    return out

def pick_asfiled(d, unit, year, form_date):
    best = None
    for r in d.get('units', {}).get(unit, []):
        end = r.get('end', '')
        if not end.startswith(str(year)): continue
        if r.get('filed', '9999') > form_date: continue
        key = (end, r.get('filed', ''))
        if best is None or key > best[0]: best = (key, r['val'])
    return best[1] if best else None

def load_concept(cik, name):
    p = os.path.join(CACHE, f'{cik:010d}_{name}.json')
    if not os.path.exists(p): return {'units': {}}
    return json.load(open(p))

class Data:
    def __init__(self):
        poolj = json.load(open(os.path.join(HERE, 'pool.json')))
        self.pool = {int(k): v for k, v in poolj['pool'].items()}
        self.counts = poolj['counts']
        self.mapping = {int(k): v for k, v in json.load(open(os.path.join(HERE, 'mapping.json'))).items()}
        self.px = {}
        self.first_trade = {}
        for cik, mv in self.mapping.items():
            t = mv['ticker'].replace('/', '-')
            p = os.path.join(PXD, f'px_{t}.json')
            if not os.path.exists(p): continue
            d = json.load(open(p))
            self.px[cik] = {r[0]: (r[1], r[2]) for r in d['rows']}
            ft = d.get('meta', {}).get('firstTrade')
            if ft: self.first_trade[cik] = datetime.datetime.utcfromtimestamp(ft).strftime('%Y-%m')
        sp = json.load(open(os.path.join(PXD, 'px_SPY.json')))
        self.spy = {r[0]: r[1] for r in sp['rows']}
        self._ncav_cache = {}
        FR = os.path.join(HERE, '..', '..', 'v11-native-rules', '_w04_broad_data', 'frames')
        self._sh_series = {}
        for y in range(2014, 2027):
            p = os.path.join(FR, f'Shares_{y}I.json')
            self._sh_series[y] = {int(k): v for k, v in json.load(open(p)).items()} if os.path.exists(p) else {}
    def sf(self, cik, F):
        avail = [(y, self._sh_series[y][cik]) for y in range(2014, 2027) if self._sh_series[y].get(cik)]
        f = 1.0
        for (y0, a), (y1, b) in zip(avail, avail[1:]):
            if y1 >= F:
                r = b / a
                if r >= 1.6 or r <= 0.625: f *= r
        return f
    def price(self, cik, month):
        s = self.px.get(cik)
        return s.get(month) if s else None
    def adj(self, cik, month):
        p = self.price(cik, month)
        return p[0] if p else None
    def last_month(self, cik):
        s = self.px.get(cik)
        return max(s) if s else None
    def priced_ok(self, cik, F):
        """Price exists at formation June and reuse guard passes."""
        if cik not in self.px: return False
        if self.adj(cik, ym(F, 6)) is None: return False
        ft = self.first_trade.get(cik)
        if ft and ft > ym(F, 6): return False
        return True
    def cap(self, cik, F, row=None):
        p = self.price(cik, ym(F, 6))
        if not p: return None
        if row is None:
            row = next((r for r in self.pool.get(F, []) if r['cik'] == cik), None)
        if row is None: return None
        return row['shares'] * p[1] * row['sf']
    def ncav_now(self, cik, F):
        """As-filed NCAV for June review of year F (YE F-1, filed <= Jun 30 F)."""
        key = (cik, F)
        if key in self._ncav_cache: return self._ncav_cache[key]
        fd = f'{F}-06-30'
        ca = pick_asfiled(load_concept(cik, 'AssetsCurrent'), 'USD', F - 1, fd)
        li = pick_asfiled(load_concept(cik, 'Liabilities'), 'USD', F - 1, fd)
        sh = pick_asfiled(load_concept(cik, 'EntityCommonStockSharesOutstanding'), 'shares', F - 1, fd)
        out = (ca - li, sh) if (ca is not None and li is not None) else (None, None)
        self._ncav_cache[key] = out
        return out

D = None

def cost_rate(cap):
    if cap is None: return 0.02
    if cap >= 1e9: return 0.005
    if cap >= 1e8: return 0.01
    return 0.02

def qualifiers(F):
    out = []
    for r in D.pool.get(F, []):
        cik = r['cik']
        if not D.priced_ok(cik, F): continue
        cap = D.cap(cik, F, r)
        if cap is not None and cap <= (2.0 / 3.0) * r['ncav']:
            out.append(cik)
    return out

def placebo_pool(F):
    q = set(qualifiers(F))
    return [r['cik'] for r in D.pool.get(F, []) if D.priced_ok(r['cik'], F) and r['cik'] not in q]

def simulate(formations, end_ym, seed=None, stats=None):
    """Returns dict with final, curve, trades summary. seed=None -> strategy."""
    start = ym(formations[0], 6)
    timeline = months_between(start, end_ym)
    cash = 100.0
    pos = {}  # cik -> dict(shares, entry_ym, entry_adj, rate)
    curve = []
    n_buys = n_sells = n_zeroed = 0
    total_costs = 0.0
    bought = {}
    for month in timeline:
        y, m = int(month[:4]), int(month[5:7])
        # vanish-to-zero: series ended before this month
        for cik in list(pos):
            lm = D.last_month(cik)
            if lm is not None and month > lm:
                del pos[cik]; n_zeroed += 1
        if m == 6 and y in formations:
            # June review exits (cap > NCAV) for held names
            for cik in list(pos):
                ncav, sh = D.ncav_now(cik, y)
                p = D.price(cik, month)
                if ncav is not None and sh and p:
                    cap_now = sh * p[1] * D.sf(cik, y)
                    if cap_now > ncav:
                        gross = pos[cik]['shares'] * p[0]
                        c = gross * pos[cik]['rate']; total_costs += c
                        cash += gross - c; del pos[cik]; n_sells += 1
            # new buys
            if seed is None:
                picks = [c for c in qualifiers(y) if c not in pos]
            else:
                n_nat = len([c for c in qualifiers(y) if c not in pos])
                poolp = [c for c in placebo_pool(y) if c not in pos]
                rng = random.Random(seed * 100003 + y)
                rng.shuffle(poolp)
                picks = poolp[:n_nat]
            bought[y] = [D.mapping[c]['ticker'] if c in D.mapping else str(c) for c in picks]
            if picks and cash > 0:
                w = cash / len(picks)
                for cik in picks:
                    row = next(r for r in D.pool[y] if r['cik'] == cik)
                    cap = D.cap(cik, y, row)
                    rate = cost_rate(cap)
                    cost = w * rate; total_costs += cost
                    adj = D.adj(cik, month)
                    pos[cik] = {'shares': (w - cost) / adj, 'entry': month,
                                'entry_adj': adj, 'rate': rate}
                    n_buys += 1
                cash = 0.0
        # month-end exits: +50% and 36-month
        for cik in list(pos):
            p = D.price(cik, month)
            if not p: continue
            age = (y - int(pos[cik]['entry'][:4])) * 12 + (m - int(pos[cik]['entry'][5:7]))
            if p[0] >= 1.5 * pos[cik]['entry_adj'] or age >= 36:
                gross = pos[cik]['shares'] * p[0]
                c = gross * pos[cik]['rate']; total_costs += c
                cash += gross - c; del pos[cik]; n_sells += 1
        # mark
        val = cash
        for cik, pp in pos.items():
            a = D.adj(cik, month)
            if a is None:
                # temporary gap: last known adj
                s = D.px[cik]
                prev = [k for k in s if k < month]
                a = s[max(prev)][0] if prev else pp['entry_adj']
            val += pp['shares'] * a
        curve.append([month, round(val, 2)])
    # final liquidation at end_ym
    final = cash
    for cik, pp in pos.items():
        lm = D.last_month(cik)
        if lm is None or lm < pp['entry']: continue
        a = D.adj(cik, lm)
        gross = pp['shares'] * a
        final += gross - gross * pp['rate']
        total_costs += gross * pp['rate']
    spy_a = D.spy.get(start); spy_b = D.spy.get(end_ym)
    spy_final = round(100 * spy_b / spy_a, 2) if spy_a and spy_b else None
    return {'final': round(final, 2), 'curve': curve, 'buys': n_buys, 'sells': n_sells,
            'zeroed': n_zeroed, 'costs': round(total_costs, 2), 'bought': bought,
            'spy_final_same_window': spy_final}

def period_stats(curve):
    rets = []
    for (m0, v0), (m1, v1) in zip(curve, curve[1:]):
        if v0 > 0: rets.append((m1, v1 / v0 - 1))
    if not rets: return {}
    vals = [r for _, r in rets]
    pos_n = sum(1 for r in vals if r > 0)
    # longest losing streak
    streak = mx = 0
    for r in vals:
        streak = streak + 1 if r < 0 else 0
        mx = max(mx, streak)
    # longest stretch between new highs (months)
    peak = curve[0][1]; peak_i = 0; longest = 0
    for i, (_, v) in enumerate(curve):
        if v >= peak: peak, peak_i = v, i
        longest = max(longest, i - peak_i)
    peak_v = curve[0][1]; maxdd = 0.0
    for _, v in curve:
        peak_v = max(peak_v, v); maxdd = max(maxdd, 1 - v / peak_v) if peak_v else 0
    return {'n_periods': len(vals), 'pct_positive': round(100 * pos_n / len(vals), 1),
            'median_period': round(statistics.median(vals), 4),
            'mean_period_secondary': round(statistics.mean(vals), 4),
            'best_period': [max(rets, key=lambda t: t[1])[0], round(max(vals), 4)],
            'worst_period': [min(rets, key=lambda t: t[1])[0], round(min(vals), 4)],
            'longest_losing_streak_months': mx,
            'longest_stretch_between_new_highs_months': longest,
            'max_dd': round(maxdd, 4)}

def main():
    global D
    D = Data()
    census = {}
    for F in range(2016, 2026):
        poolF = D.pool.get(F, [])
        priced = [r['cik'] for r in poolF if D.priced_ok(r['cik'], F)]
        q = qualifiers(F)
        census[F] = {'pool_possible_qualifiers': len(poolF), 'priced': len(priced),
                     'unpriced': len(poolF) - len(priced), 'qualifiers': len(q),
                     'qualifier_tickers': [D.mapping[c]['ticker'] for c in q if c in D.mapping],
                     'pool_ncav': sum(r['ncav'] for r in poolF),
                     'unpriced_ncav': sum(r['ncav'] for r in poolF if not D.priced_ok(r['cik'], F))}
        print('census', F, census[F]['qualifiers'], 'of priced', len(priced), 'pool', len(poolF), flush=True)
    roads = {'FULL': (list(range(2016, 2026)), '2026-06'),
             'CONT': (list(range(2019, 2026)), '2026-06'),
             'VAL': (list(range(2023, 2026)), '2026-06'),
             'FOLD1_2016_2020': (list(range(2016, 2021)), '2021-06'),
             'FOLD2_2021_2025': (list(range(2021, 2026)), '2026-06')}
    res = {'family': 'net-net', 'constructed': True, 'census': census, 'stageb_counts': D.counts}
    for name, (forms, end) in roads.items():
        r = simulate(forms, end)
        r['period_stats'] = period_stats(r['curve'])
        twins = []
        for seed in range(1, 21):
            t = simulate(forms, end, seed=seed)
            twins.append(t['final'])
        r['placebo_finals'] = twins
        r['placebos_beaten'] = sum(1 for t in twins if r['final'] > t)
        res[name] = r
        print(name, 'final', r['final'], 'spy', r['spy_final_same_window'],
              'placebos beaten', r['placebos_beaten'], '/20', flush=True)
    json.dump(res, open(os.path.join(HERE, 'results.json'), 'w'), indent=1)
    print('saved results.json', flush=True)

if __name__ == '__main__':
    main()
