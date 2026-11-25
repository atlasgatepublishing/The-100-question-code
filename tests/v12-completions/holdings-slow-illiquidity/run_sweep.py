#!/usr/bin/env python3
"""V12 HOLDINGS-COUNT SWEEP — slow-illiquidity (Amihud) family.

Chassis = the v12 CONSTRUCTED form frozen in
../slow-illiquidity/CONSTRUCTION-SPEC.md, implemented identically to
../slow-illiquidity/run_illiquidity.py (same formation, ILLIQ, vol-tercile x
ILLIQ-quintile sort, skip-2/hold-1 monthly cadence, vanished prices to ZERO,
Corwin-Schultz name-specific costs floored 0.50%/side capped 7.5%/side
+0.10%/side, $0.01 sell fee). The ONLY variation is HOW MANY names the
portfolio holds, per the pre-registered grid:
  counts 1,2,3,5,8,10,15,20,30, NATIVE (the published quintile selection),
  ALL-ELIGIBLE (the whole post-trim eligible pool).

Ranking for a fixed count N (frozen before runs): within each volatility
tercile, names are ranked by ILLIQ descending; each name's score is its
rank-from-the-top divided by its tercile size (0 = most illiquid in tercile);
the pooled list sorts by that score ascending, ties broken by raw ILLIQ
descending. Top-N = first N of that list. This preserves the native
tercile x illiquidity structure while making the count a single knob.

Rule sets:
  native — the constructed Amihud form exactly: NO floor, no stops.
  house  — v9 protections on the same selection/costs: plain -15% floor on
           month-end marks from the episode-start balance; breach liquidates
           (the pot is already in cash at a month-end mark), 90 calendar days
           in cash, restart at the next month with a fresh floor of 85% of
           the restart balance; a second breach ends the run.

Roads (constructed spec; LONG 2010 is not honestly available on this free
PIT universe): LONGEST 2016-01-04->2026-11-20, DECADE 2016-11-21->2026-11-20,
CONT 2019-01-02->2026-11-20, VAL 2023-01-03->2026-11-20. $100 pots.
20-seed placebos per cell (same count drawn at random from the same pool,
same costs per name); ALL-ELIGIBLE has no placebo (the draw is the pool).
Simulation only."""
import json, os, math, random, statistics, bisect, datetime
HERE = os.path.dirname(os.path.abspath(__file__))
BROAD = '/home/hatch/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data'
DATA = os.path.join(HERE, 'data')
START_CASH = 100.0
COUNTS = [1, 2, 3, 5, 8, 10, 15, 20, 30, 'NATIVE', 'ALL']

# ---------- data ----------
cand = {int(k): v for k, v in json.load(open(os.path.join(BROAD, 'candidates.json'))).items()}
def load_frame(name):
    p = os.path.join(BROAD, 'frames', name)
    if not os.path.exists(p): return set()
    return {int(k) for k in json.load(open(p)).keys()}
shares_years = {y: load_frame(f'Shares_{y}I.json') for y in range(2014, 2026)}

LISTED = {'NYSE', 'NASDAQ', 'TXSE', 'CBOE'}
ticker2cik = {}
for cik, info in cand.items():
    if info.get('exchange') in LISTED and info.get('ticker'):
        ticker2cik[info['ticker'].replace('/', '-')] = cik

bars = {}
for t in ticker2cik:
    p = os.path.join(DATA, f'px_{t}.json')
    if not os.path.exists(p): continue
    rows = json.load(open(p))
    ser = []
    for r in rows:
        d, o, h, l, c, adj, v = r
        if adj is None or adj <= 0 or c is None or c <= 0: continue
        f = adj / c
        ser.append({'d': d, 'o': (o or c) * f, 'h': (h or c) * f, 'l': (l or c) * f,
                    'c': adj, 'rawc': c, 'v': v or 0})
    if len(ser) >= 60:
        bars[t] = ser
_rows = json.load(open(os.path.join(DATA, 'px_SPY.json')))
spy = [{'d': r[0], 'c': r[5]} for r in _rows if r[5]]
spy_by_date = {b['d']: b['c'] for b in spy}
ALL_DATES = sorted(spy_by_date.keys())

def month_key(d): return d[:7]
MONTHS, _seen = [], set()
for d in ALL_DATES:
    m = month_key(d)
    if m not in _seen:
        _seen.add(m); MONTHS.append(m)
MONTH_LAST, MONTH_FIRST = {}, {}
for d in ALL_DATES:
    MONTH_LAST[month_key(d)] = d
    MONTH_FIRST.setdefault(month_key(d), d)
DATES_BY_T = {t: [b['d'] for b in ser] for t, ser in bars.items()}

def trailing(t, end_date, n=63):
    ser = bars[t]; ds = DATES_BY_T[t]
    end = bisect.bisect_right(ds, end_date)
    return ser[max(0, end - n):end]

def cs_spread(win):
    ests = []
    for a, b in zip(win, win[1:]):
        if a['h'] <= 0 or a['l'] <= 0 or b['h'] <= 0 or b['l'] <= 0: continue
        beta = (math.log(a['h'] / a['l'])) ** 2 + (math.log(b['h'] / b['l'])) ** 2
        h2 = max(a['h'], b['h']); l2 = min(a['l'], b['l'])
        if l2 <= 0: continue
        gamma = (math.log(h2 / l2)) ** 2
        denom = 3 - 2 * math.sqrt(2)
        alpha = (math.sqrt(2 * beta) - math.sqrt(beta)) / denom - math.sqrt(gamma / denom)
        s = 2 * (math.exp(alpha) - 1) / (1 + math.exp(alpha))
        ests.append(max(0.0, s))
    return statistics.mean(ests) if ests else 0.01

def formation_raw(form_month):
    """Returns (pool, ranked, native_picks) exactly per the constructed spec,
    plus the pooled top-N ranking frozen in this script's header."""
    end_date = MONTH_LAST[form_month]
    year = int(form_month[:4])
    members = shares_years.get(year, set()) | shares_years.get(year - 1, set())
    pool = {}
    for t, cik in ticker2cik.items():
        if cik not in members or t not in bars: continue
        win = trailing(t, end_date)
        if len(win) < 40: continue
        if win[-1]['c'] < 1.00: continue
        rets, dv, ok = [], [], True
        for a, b in zip(win, win[1:]):
            if a['c'] <= 0: ok = False; break
            r = b['c'] / a['c'] - 1.0
            rets.append(r)
            if b['v'] > 0 and b['rawc'] > 0:
                dv.append(abs(r) / (b['rawc'] * b['v']))
        if not ok or len(dv) < 40 or len(rets) < 40: continue
        pool[t] = {'illiq': statistics.mean(dv) * 1e6,
                   'vol': statistics.pstdev(rets),
                   'cost': min(0.075, max(0.005, cs_spread(win) / 2.0)) + 0.001}
    if len(pool) < 30: return pool, [], []
    srt = sorted(pool.items(), key=lambda kv: kv[1]['illiq'])
    pool = dict(srt[:max(1, int(len(srt) * 0.99))])
    items = sorted(pool.items(), key=lambda kv: kv[1]['vol'])
    n = len(items); native, scored = [], []
    for k in range(3):
        terc = items[k * n // 3:(k + 1) * n // 3]
        terc.sort(key=lambda kv: kv[1]['illiq'], reverse=True)
        native += [t for t, _ in terc[:max(1, len(terc) // 5)]]
        for rank, (t, info) in enumerate(terc):
            scored.append((rank / max(1, len(terc)), -info['illiq'], t))
    scored.sort()
    ranked = [t for _, _, t in scored]
    return pool, ranked, native

# ---------- formation cache ----------
FCACHE = os.path.join(HERE, 'formations.json')
if os.path.exists(FCACHE):
    FORM = json.load(open(FCACHE))
else:
    FORM = {}
    for fm in MONTHS:
        if fm < '2015-09' or fm > '2026-08': continue
        pool, ranked, native = formation_raw(fm)
        FORM[fm] = {'pool': pool, 'ranked': ranked, 'native': native}
        print('formation', fm, 'pool', len(pool), 'native', len(native), flush=True)
    json.dump(FORM, open(FCACHE, 'w'))

# ---------- per-name hold outcomes, cached per (form_month, ticker) ----------
def hold_outcome(t, hold_month):
    """(entry_open, exit_close_or_None, dead) for ticker t in hold_month.
    ZERO rule per the constructed spec, with one sample-end convention,
    documented in RESULTS.md: a name counts as vanished only if the tape
    demonstrably continued without it — its series ends in a month BEFORE
    the dataset's final month (2026-11). A series ending inside the final
    data month is marked at its last close in the hold month, because at
    the sample edge a delisting cannot be told apart from the sample
    simply ending (the un-fixed rule zeroes EVERY name in the last hold
    month, live ones included, and destroys every road's final value)."""
    ser = bars[t]; ds = DATES_BY_T[t]
    i = bisect.bisect_left(ds, MONTH_FIRST[hold_month])
    if i >= len(ser) or ds[i][:7] != hold_month or ser[i]['o'] <= 0:
        return None
    entry = ser[i]['o']
    last_in, j = None, i
    while j < len(ser) and ds[j][:7] == hold_month:
        last_in = ser[j]; j += 1
    last_month = ser[-1]['d'][:7]
    dead = last_month <= hold_month and last_month < ALL_DATES[-1][:7]
    if last_in is None or dead:
        return (entry, None, True)
    return (entry, last_in['c'], False)

OUTC = {}
def outcome(form_month, t):
    key = (form_month, t)
    if key not in OUTC:
        hi = MONTHS.index(form_month) + 3
        OUTC[key] = hold_outcome(t, MONTHS[hi]) if hi < len(MONTHS) else None
    return OUTC[key]

# ---------- runner ----------
def run_road(start, end, count, ruleset, placebo_seed=None):
    cash = START_CASH
    curve = []
    trades = 0; zeroed = 0; total_cost = 0.0
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    floor = 0.85 * START_CASH
    halts = 0; halt_until_idx = -1
    mi_start = MONTHS.index(month_key(start)); mi_end = MONTHS.index(month_key(end))
    for mi in range(mi_start, mi_end + 1):
        hold_month = MONTHS[mi]
        last_d = MONTH_LAST[hold_month]
        if ruleset == 'house' and halts >= 2:
            curve.append([last_d, round(cash, 4)]); continue
        if ruleset == 'house' and mi <= halt_until_idx:
            curve.append([last_d, round(cash, 4)]); continue
        if mi - 3 < 0:
            curve.append([last_d, round(cash, 4)]); continue
        f = FORM.get(MONTHS[mi - 3])
        if not f or not f['ranked']:
            curve.append([last_d, round(cash, 4)]); continue
        pool, ranked, native = f['pool'], f['ranked'], f['native']
        if count == 'NATIVE': picks = list(native)
        elif count == 'ALL': picks = list(ranked)
        else: picks = ranked[:count]
        if rng is not None:
            k = min(len(picks), len(pool))
            picks = rng.sample(sorted(pool.keys()), k)
        if not picks:
            curve.append([last_d, round(cash, 4)]); continue
        per = cash / len(picks)
        spent = 0.0; proceeds = 0.0
        for t in picks:
            oc = outcome(MONTHS[mi - 3], t)
            if oc is None: continue
            entry, exit_c, dead = oc
            cs = pool[t]['cost']
            amt = per * (1 - cs)
            sh = amt / entry
            spent += per; total_cost += per * cs
            trades += 1
            if dead:
                zeroed += 1; continue
            val = sh * exit_c
            proceeds += val * (1 - cs) - 0.01
            total_cost += val * cs + 0.01
        cash = cash - spent + proceeds
        curve.append([last_d, round(cash, 4)])
        if ruleset == 'house' and cash <= floor:
            halts += 1
            if halts == 1:
                # 90 calendar days in cash, restart next month after that
                hd = datetime.date.fromisoformat(last_d)
                j = mi + 1
                while j < len(MONTHS) and (datetime.date.fromisoformat(MONTH_LAST[MONTHS[j]]) - hd).days < 90:
                    j += 1
                halt_until_idx = j - 1
                floor = 0.85 * cash
    return {'final': round(cash, 2), 'curve': curve, 'trades': trades,
            'zeroed': zeroed, 'total_cost': round(total_cost, 2), 'halts': halts}

def max_dd(curve):
    peak, dd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0: dd = min(dd, v / peak - 1)
    return round(dd * 100, 1)

def spy_road(start, end):
    s = next(b['c'] for b in spy if b['d'] >= start)
    e = [b['c'] for b in spy if b['d'] <= end][-1]
    return round(START_CASH * e / s, 2)

def period_distribution(curve):
    """Monthly period distribution from month-end marks (Terry's reporting
    standard). Periods are month-to-month changes in pot value."""
    vals = [START_CASH] + [v for _, v in curve]
    rets = [(vals[i + 1] - vals[i]) for i in range(len(vals) - 1)]
    pcts = [(vals[i + 1] / vals[i] - 1) * 100 if vals[i] > 0 else 0.0 for i in range(len(vals) - 1)]
    prof = sum(1 for r in rets if r > 0)
    longest_loss = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0
        longest_loss = max(longest_loss, cur)
    peak_i, longest_h2h, last_high = 0, 0, 0
    peak = vals[0]
    for i, v in enumerate(vals):
        if v >= peak:
            peak = v; longest_h2h = max(longest_h2h, i - last_high); last_high = i
    longest_h2h = max(longest_h2h, len(vals) - 1 - last_high)
    return {'periods': len(rets), 'pct_profitable': round(100.0 * prof / len(rets), 1) if rets else 0.0,
            'median_period_usd': round(statistics.median(rets), 2) if rets else 0.0,
            'median_period_pct': round(statistics.median(pcts), 2) if pcts else 0.0,
            'best_period_usd': round(max(rets), 2) if rets else 0.0,
            'worst_period_usd': round(min(rets), 2) if rets else 0.0,
            'longest_losing_run_periods': longest_loss,
            'longest_stretch_between_new_highs_periods': longest_h2h,
            'average_period_usd_secondary': round(statistics.mean(rets), 2) if rets else 0.0}

ROADS = {
    'LONGEST': ('2016-01-04', '2026-11-20'),
    'DECADE': ('2016-11-21', '2026-11-20'),
    'CONT': ('2019-01-02', '2026-11-20'),
    'VAL': ('2023-01-03', '2026-11-20'),
}
CHAMP = {'LONGEST': 1415.62, 'DECADE': 667.35, 'CONT': 544.47, 'VAL': 288.05}

def main():
    out = {'universe': {'candidates': len(cand), 'listed_with_prices': len(bars)},
           'native_count_stats': {}, 'roads': {}}
    nat_counts = [len(f['native']) for f in FORM.values() if f['native']]
    pool_sizes = [len(f['pool']) for f in FORM.values() if f['pool']]
    out['native_count_stats'] = {
        'formations': len(nat_counts),
        'native_picks_min': min(nat_counts), 'native_picks_median': statistics.median(nat_counts),
        'native_picks_max': max(nat_counts),
        'pool_median': statistics.median(pool_sizes)}
    for rname, (s, e) in ROADS.items():
        out['roads'][rname] = {'window': [s, e], 'spy_final': spy_road(s, e),
                               'champion_vm': CHAMP[rname], 'cells': {}}
        for ruleset in ('native', 'house'):
            for count in COUNTS:
                key = f'{ruleset}|{count}'
                r = run_road(s, e, count, ruleset)
                cell = {'final': r['final'], 'max_dd_pct': max_dd(r['curve']),
                        'trades': r['trades'], 'zeroed': r['zeroed'],
                        'total_cost': r['total_cost'], 'halts': r['halts']}
                if count != 'ALL':
                    pls = sorted(run_road(s, e, count, ruleset, placebo_seed=2000 + sd)['final']
                                 for sd in range(20))
                    cell['placebos'] = {'finals': pls, 'median': pls[10],
                                        'beat_count_of_20': sum(1 for x in pls if r['final'] > x)}
                out['roads'][rname]['cells'][key] = cell
                print(rname, key, r['final'], 'dd', cell['max_dd_pct'],
                      'plmed', cell.get('placebos', {}).get('median'), flush=True)
        json.dump(out, open(os.path.join(HERE, 'results.json'), 'w'), indent=1)
    # curves + distributions for NATIVE and every count on LONGEST (both rulesets)
    curves = {}
    for ruleset in ('native', 'house'):
        for count in COUNTS:
            r = run_road(*ROADS['LONGEST'], count, ruleset)
            curves[f'{ruleset}|{count}'] = {'curve': r['curve'],
                                            'distribution_monthly': period_distribution(r['curve'])}
    out['longest_curves'] = curves
    json.dump(out, open(os.path.join(HERE, 'results.json'), 'w'), indent=1)
    print('DONE')

if __name__ == '__main__':
    main()
