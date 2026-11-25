#!/usr/bin/env python3
"""v12 CONSTRUCTED vm-composite run engine — frozen by CONSTRUCTION-SPEC.md.
Composite value (mean percentile rank of B/M, E/P, CF/P, as-filed EDGAR PIT,
filed-date availability, 548-day staleness) + AMP 12-1 momentum, combined 50/50
by percentile rank; long-only top quintile, equal weight, monthly formation;
W04 broad universe + monthly Yahoo prices (read-only); vanished prices -> ZERO;
tiered habitat costs + $0.01/sell order; no floor (none published); 20-seed
placebos from the same scored pools. Simulation only. Writes only in this folder."""
import bisect, calendar, json, os, random, sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
W04 = os.path.join(HERE, '..', '..', 'v11-native-rules', '_w04_broad_data')
FACTS = os.path.join(HERE, 'data', 'facts')

def pct_ranks(values):
    """Program convention (v4 percentile_ranks): sorted ascending, i/(n-1)."""
    items = sorted(values.items(), key=lambda kv: kv[1])
    n = len(items)
    if n == 1: return {items[0][0]: 0.5}
    return {t: i / (n - 1) for i, (t, _) in enumerate(items)}

def cost_rate(cap):
    if cap is None: return 0.0075
    if cap >= 5e9: return 0.0010
    if cap >= 1e9: return 0.0025
    return 0.0075

# ---------------- PIT as-filed series ----------------
class Pit:
    """Latest filing with filed <= asof (max key (filed, prio, end));
    stale if asof - filed > 548 days. Replicates the program PitFast rule."""
    def __init__(self, rows):
        # rows: (filed, end, start, val, prio)
        best = {}
        for filed, end, start, val, prio in rows:
            if filed is None or val is None: continue
            cur = best.get(filed)
            if cur is None or (prio, end) > (cur[0], cur[1]):
                best[filed] = (prio, end, val)
        self.fileds = sorted(best)
        self.best = best
        self.ords = [date(int(f[:4]), int(f[5:7]), int(f[8:10])).toordinal() for f in self.fileds]
    def value(self, asof):
        i = bisect.bisect_right(self.fileds, asof) - 1
        if i < 0: return None
        ao = date(int(asof[:4]), int(asof[5:7]), int(asof[8:10])).toordinal()
        if ao - self.ords[i] > 548: return None
        return self.best[self.fileds[i]][2]

def load_pits(cik):
    p = os.path.join(FACTS, f'{cik:010d}.json')
    if not os.path.exists(p): return None
    try:
        rec = json.load(open(p))
    except Exception:
        return None
    def rows(key, prio, annual=False):
        out = []
        for filed, end, start, val, form in rec.get(key, []):
            if annual:
                if start is None or end is None: continue
                dur = (date(int(end[:4]), int(end[5:7]), int(end[8:10])) -
                       date(int(start[:4]), int(start[5:7]), int(start[8:10]))).days
                if not (350 <= dur <= 380): continue
            out.append((filed, end, start, val, prio))
        return out
    eq = Pit(rows('us-gaap:StockholdersEquity', 2) +
             rows('us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest', 1))
    ni = Pit(rows('us-gaap:NetIncomeLoss', 1, annual=True))
    cfo = Pit(rows('us-gaap:NetCashProvidedByUsedInOperatingActivities', 1, annual=True))
    sh = Pit(rows('dei:EntityCommonStockSharesOutstanding', 3) +
             rows('us-gaap:CommonStockSharesOutstanding', 2))
    return {'eq': eq, 'ni': ni, 'cfo': cfo, 'sh': sh}

# ---------------- data ----------------
class Data:
    def __init__(self):
        cand = json.load(open(os.path.join(W04, 'candidates.json')))
        self.cand = {int(k): v for k, v in cand.items()}
        self.px = {}   # cik -> {ym: (adj, raw)}
        for cik, info in self.cand.items():
            t = info['ticker'].replace('/', '-')
            p = os.path.join(W04, f'px_{t}.json')
            if os.path.exists(p):
                self.px[cik] = {r[0]: (r[1], r[2]) for r in json.load(open(p))}
        self.spy = {r[0]: r[1] for r in json.load(open(os.path.join(W04, 'px_SPY.json')))}
        # W04 split factors from Shares frames (read-only)
        sh_series = {}
        for y in range(2014, 2026):
            fp = os.path.join(W04, 'frames', f'Shares_{y}I.json')
            sh_series[y] = {int(k): v for k, v in json.load(open(fp)).items()} if os.path.exists(fp) else {}
        self.sf = {}
        for cik in self.cand:
            avail = [(y, sh_series[y][cik]) for y in range(2014, 2026) if cik in sh_series[y]]
            sf = {}
            for F in range(2016, 2027):
                f = 1.0
                for (y0, a), (y1, b) in zip(avail, avail[1:]):
                    if y1 >= F and a:
                        r = b / a
                        if r >= 1.6 or r <= 0.625: f *= r
                sf[F] = f
            self.sf[cik] = sf
        self.pits = {}
        for cik in self.px:
            pit = load_pits(cik)
            if pit: self.pits[cik] = pit
        months = sorted(self.spy)
        self.months = months
        self.midx = {m: i for i, m in enumerate(months)}

    def score_pool(self, ym_date, ym):
        """ym: formation month 'YYYY-MM'; ym_date: last calendar day of ym.
        Returns dict cik -> dict(bm, ep, cfp, mom, cap). Cached per month:
        pools are identical across windows and placebo seeds."""
        if not hasattr(self, '_poolcache'): self._poolcache = {}
        if ym in self._poolcache: return self._poolcache[ym]
        out = self._score_pool(ym_date, ym)
        self._poolcache[ym] = out
        return out

    def _score_pool(self, ym_date, ym):
        F = int(ym[:4])
        i = self.midx.get(ym)
        if i is None or i < 12: return {}
        m_prev = self.months[i - 1]; m_12 = self.months[i - 12]
        out = {}
        for cik, pit in self.pits.items():
            px = self.px.get(cik)
            if not px or ym not in px: continue
            adj, raw = px[ym]
            if not adj or not raw: continue
            if m_prev not in px or m_12 not in px: continue
            a1, a12 = px[m_prev][0], px[m_12][0]
            if not a1 or not a12: continue
            eq = pit['eq'].value(ym_date); ni = pit['ni'].value(ym_date)
            cfo = pit['cfo'].value(ym_date); sh = pit['sh'].value(ym_date)
            if eq is None or ni is None or cfo is None or sh is None or sh <= 0: continue
            cap = sh * raw * self.sf.get(cik, {}).get(F, 1.0)
            if cap <= 0: continue
            out[cik] = {'bm': eq / cap, 'ep': ni / cap, 'cfp': cfo / cap,
                        'mom': a1 / a12 - 1.0, 'cap': cap, 'adj': adj}
        return out

    def picks_for(self, pool):
        if len(pool) < 5: return [], {}
        rb = pct_ranks({c: v['bm'] for c, v in pool.items()})
        re_ = pct_ranks({c: v['ep'] for c, v in pool.items()})
        rc = pct_ranks({c: v['cfp'] for c, v in pool.items()})
        rm = pct_ranks({c: v['mom'] for c, v in pool.items()})
        comb = {c: ((rb[c] + re_[c] + rc[c]) / 3.0 + rm[c]) / 2.0 for c in pool}
        n = max(1, len(pool) // 5)
        picks = sorted(comb, key=lambda c: -comb[c])[:n]
        return picks, comb

# ---------------- simulation ----------------
def run_window(D, start_ym, end_ym, seed=None):
    """Formations in [start_ym, end_ym); marks start_ym..end_ym. $100 start."""
    months = [m for m in D.months if start_ym <= m <= end_ym]
    cash = 100.0; pos = {}  # cik -> qty (adj-price units)
    curve = []; total_costs = 0.0; n_orders = 0; zero_events = []
    formations_log = []
    for mi, ym in enumerate(months):
        # mark / zero-out vanished
        val = cash
        for c in list(pos):
            row = D.px.get(c, {}).get(ym)
            if row is None or not row[0]:
                if pos[c] > 0: zero_events.append({'cik': c, 'ticker': D.cand[c]['ticker'], 'month': ym})
                del pos[c]
            else:
                val += pos[c] * row[0]
        if mi == 0:
            curve.append([ym, round(val, 2)])
        if ym == end_ym: break
        # formation at close of ym
        last_day = f'{ym}-{calendar.monthrange(int(ym[:4]), int(ym[5:7]))[1]:02d}'
        pool = D.score_pool(last_day, ym)
        picks_nat, _ = D.picks_for(pool)
        if seed is None:
            picks = picks_nat
        else:
            rng = random.Random(seed * 100003 + mi)
            keys = list(pool.keys()); rng.shuffle(keys)
            picks = keys[:len(picks_nat)]
        formations_log.append([ym, len(pool), len(picks)])
        if picks:
            target = val / len(picks)
            pickset = set(picks)
            # sells first
            for c in list(pos):
                row = D.px[c][ym]; adj = row[0]
                cur = pos[c] * adj
                tgt = target if c in pickset else 0.0
                if cur > tgt + 0.005:
                    sv = cur - tgt
                    cost = sv * cost_rate(pool.get(c, {}).get('cap')) + 0.01
                    cash += sv - cost; total_costs += cost; n_orders += 1
                    pos[c] = tgt / adj if tgt > 0 else 0.0
                    if pos[c] <= 0: del pos[c]
            for c in picks:
                adj = D.px[c][ym][0]
                cur = pos.get(c, 0.0) * adj
                bv = target - cur
                if bv > 0.005:
                    bv = min(bv, cash / 1.0075)
                    if bv <= 0.005: continue
                    cost = bv * cost_rate(pool[c]['cap'])
                    cash -= bv + cost; total_costs += cost; n_orders += 1
                    pos[c] = pos.get(c, 0.0) + bv / adj
        # mark after rebalance (same month close) only for first month handled above;
        # subsequent months marked at loop top of next iteration -> append here:
        v2 = cash
        for c, q in pos.items():
            row = D.px.get(c, {}).get(ym)
            if row and row[0]: v2 += q * row[0]
        if mi == 0:
            curve[-1] = [ym, round(v2, 2)]
        else:
            curve.append([ym, round(v2, 2)])
    # final mark at end_ym already appended at loop top? ensure last point:
    if curve[-1][0] != end_ym:
        val = cash
        for c in list(pos):
            row = D.px.get(c, {}).get(end_ym)
            if row and row[0]: val += pos[c] * row[0]
        curve.append([end_ym, round(val, 2)])
    # liquidate at end (sell costs) for final cash figure
    final = cash
    for c, q in pos.items():
        row = D.px.get(c, {}).get(end_ym)
        if row and row[0]:
            g = q * row[0]; cost = g * 0.0025 + 0.01
            total_costs += cost; n_orders += 1; final += g - cost
    peak = 100.0; maxdd = 0.0
    for _, v in curve:
        peak = max(peak, v); maxdd = max(maxdd, 1 - v / peak if peak else 0)
    spy_final = round(100 * D.spy[end_ym] / D.spy[start_ym], 2) if start_ym in D.spy and end_ym in D.spy else None
    return {'final': round(final, 2), 'mark_final': curve[-1][1], 'max_dd_pct': round(maxdd * 100, 2),
            'costs': round(total_costs, 2), 'orders': n_orders, 'curve': curve,
            'spy_final_same_window': spy_final, 'zero_events': zero_events,
            'formations': formations_log}

def period_stats(curve):
    """ACTUAL period-by-period record at the strategy's native tempo (monthly),
    from the saved equity curve. Averages, if any, are secondary only."""
    rets = []
    for (m0, v0), (m1, v1) in zip(curve, curve[1:]):
        if v0 > 0: rets.append((m1, v1 / v0 - 1.0))
    if not rets: return {}
    vals = sorted(r for _, r in rets)
    n = len(vals)
    median = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2.0
    best = max(rets, key=lambda kv: kv[1]); worst = min(rets, key=lambda kv: kv[1])
    streak = longest = 0
    for _, r in rets:
        streak = streak + 1 if r < 0 else 0
        longest = max(longest, streak)
    peak = -1.0; peak_m = None; longest_under = 0; cur_under = 0
    for m, v in curve:
        if v >= peak:
            peak = v; peak_m = m; cur_under = 0
        else:
            cur_under += 1; longest_under = max(longest_under, cur_under)
    return {'n_periods': n,
            'pct_periods_positive': round(100.0 * sum(1 for _, r in rets if r > 0) / n, 1),
            'median_period_pct': round(median * 100, 2),
            'best_period': {'month': best[0], 'pct': round(best[1] * 100, 2)},
            'worst_period': {'month': worst[0], 'pct': round(worst[1] * 100, 2)},
            'longest_losing_streak_months': longest,
            'longest_months_between_new_highs': longest_under,
            'mean_period_pct_secondary_average_only': round(sum(r for _, r in rets) / n * 100, 2)}

def main():
    D = Data()
    print('universe with prices+pits:', len(D.pits), 'months', D.months[0], D.months[-1], flush=True)
    windows = {
        'LONGEST_2017_2026': ('2017-01', '2026-11'),
        'CONTanalog_2019_2026': ('2019-01', '2026-11'),
        'VALanalog_2023_2026': ('2023-01', '2026-11'),
    }
    res = {'family': 'vm-composite', 'constructed': True,
           'universe_names_with_prices_and_facts': len(D.pits),
           'champions_program': {'champion_vm': {'LONG': 1415.62, 'CONT': 544.47, 'VAL': 288.05, 'DECADE': 667.35},
                                 'spy_program': {'LONG': 822.94, 'CONT': 313.62, 'VAL': 187.77, 'DECADE': 367.80}},
           'windows': {}}
    for name, (s, e) in windows.items():
        r = run_window(D, s, e)
        twins = []
        for seed in range(1, 21):
            rt = run_window(D, s, e, seed=seed)
            twins.append(rt['final'])
        r['placebo_finals'] = twins
        r['placebos_beaten'] = sum(1 for t in twins if r['final'] > t)
        r['period_stats_monthly'] = period_stats(r['curve'])
        res['windows'][name] = r
        print(name, 'final', r['final'], 'spy', r['spy_final_same_window'], 'maxDD', r['max_dd_pct'],
              'costs', r['costs'], 'orders', r['orders'], 'placebos_beaten', r['placebos_beaten'], '/20',
              'zero_events', len(r['zero_events']), flush=True)
    # per-year folds (confirmation material; formations within each calendar year)
    folds = {}
    for y in range(2017, 2026):
        r = run_window(D, f'{y}-01', f'{y+1}-01')
        folds[str(y)] = {'final': r['final'], 'spy': r['spy_final_same_window'], 'max_dd_pct': r['max_dd_pct']}
        print('fold', y, r['final'], 'spy', r['spy_final_same_window'], flush=True)
    r = run_window(D, '2026-01', '2026-11'); folds['2026_partial'] = {'final': r['final'], 'spy': r['spy_final_same_window'], 'max_dd_pct': r['max_dd_pct']}
    res['year_folds'] = folds
    # NOTE: this sandbox intermittently blocks large python file writes (EPERM);
    # results are emitted on stdout and persisted by the caller via the file tool.
    print('RESULTS_JSON_BEGIN')
    print(json.dumps(res))
    print('RESULTS_JSON_END', flush=True)

if __name__ == '__main__':
    main()
