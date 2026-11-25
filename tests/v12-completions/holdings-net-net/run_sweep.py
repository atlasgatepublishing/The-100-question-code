#!/usr/bin/env python3
"""HOLDINGS-COUNT SWEEP — net-net (Graham NCAV), v12 wing.

Universe/rules: the frozen v12 CONSTRUCTION-SPEC (../net-net/): EDGAR two-stage
pool (as-filed NCAV = AssetsCurrent - TOTAL Liabilities, filed <= Jun 30 of F),
qualifier = split-corrected market cap <= 2/3 x NCAV at the June formation,
p* >= $0.25 pool fence, Yahoo monthly prices, vanish-to-zero, tiered costs
(<$100M cap 2.00%/side, $100M-$1B 1.00%, >=$1B 0.50%).

NATIVE form (=ALL-ELIGIBLE count): buy every qualifier, equal-weight new buys,
exits = +50% appreciation / June-review discount-closed (cap > NCAV) /
36 months. No floor (Graham: diversification is the risk control).
HOUSE form: identical selection/exits PLUS v9 protections — plain -15% floor
on the episode start balance; first halt liquidates at that month-end, 90 days
cash, restart at the next June formation under an episode-2 floor of -15% of
the restart balance; second halt ends the run.

GRID (pre-registered, program-fixed): counts 1,2,3,5,8,10,15,20,30,
ALL-ELIGIBLE. A count caps TOTAL holdings; at each formation the portfolio
fills open slots from qualifiers not already held, ranked by discount depth
(price / p* ascending — deepest discount first). ALL-ELIGIBLE is uncapped
(the native count).
Roads (spec): FULL formations 2016-2025 (Jun 2016->Jun 2026), CONT 2019-2025,
VAL 2023-2025. 20-seed placebos per cell: per formation, same number of new
buys drawn at random from that formation's priced pool excluding qualifiers,
identical exit/cost/floor machinery.
Simulation data only. Writes results.json in this folder only.
"""
import json, os, random, statistics, datetime
HERE = os.path.dirname(os.path.abspath(__file__))
FR = os.path.join(HERE, '..', '..', 'v11-native-rules', '_w04_broad_data', 'frames')
COUNTS = [1, 2, 3, 5, 8, 10, 15, 20, 30, None]  # None = ALL-ELIGIBLE
ROADS = {'FULL': 2016, 'CONT': 2019, 'VAL': 2023}
END_YM = '2026-06'

def tier(cap):
    return 0.02 if cap < 100e6 else (0.01 if cap < 1e9 else 0.005)

def ym_iter(y0, y1=2026, m1=6):
    out, y, m = [], y0, 6
    while (y, m) <= (y1, m1):
        out.append(f'{y:04d}-{m:02d}')
        m += 1
        if m > 12: y, m = y + 1, 1
    return out

# ---------- load ----------
poolj = json.load(open(os.path.join(HERE, 'pool.json')))
POOL = {int(k): {r['cik']: r for r in v} for k, v in poolj['pool'].items()}
COUNTS_STAGE = poolj['counts']
MAP = {int(k): v['ticker'] for k, v in json.load(open(os.path.join(HERE, 'mapping.json'))).items()}

def load_px(t):
    fn = os.path.join(HERE, 'px', f"px_{t.replace('/', '-')}.json")
    if not os.path.exists(fn): return {}, None
    d = json.load(open(fn))
    px = {r[0]: r[1] for r in d['rows']}
    ft = d.get('meta', {}).get('firstTrade')
    ftym = None
    if ft:
        dt = datetime.datetime.utcfromtimestamp(ft)
        ftym = f'{dt.year:04d}-{dt.month:02d}'
    return px, ftym

PX, FT = {}, {}
for cik, t in MAP.items():
    if t not in PX:
        PX[t], FT[t] = load_px(t)
SPY, _ = load_px('SPY')

def price_at(cik, ym):
    t = MAP.get(cik)
    if t is None: return None
    return PX.get(t, {}).get(ym)

def has_later_price(cik, ym):
    t = MAP.get(cik)
    if t is None: return False
    return any(k > ym for k in PX.get(t, {}))

def reuse_blocked(cik, form_ym):
    t = MAP.get(cik)
    ft = FT.get(t) if t else None
    return ft is not None and ft > form_ym

def qualifiers(F):
    """priced, reuse-clean qualifiers at formation F + census stats."""
    fym = f'{F}-06'
    quals, priced, pool_ncav, unpriced_ncav = [], 0, 0.0, 0.0
    nonquals = []
    for cik, r in POOL.get(F, {}).items():
        pool_ncav += r['ncav']
        px = price_at(cik, fym)
        if px is None or reuse_blocked(cik, fym):
            unpriced_ncav += r['ncav']
            continue
        priced += 1
        cap = r['shares'] * r['sf'] * px
        if cap <= (2.0 / 3.0) * r['ncav']:
            quals.append({'cik': cik, 'px': px, 'cap': cap, 'ratio': px / r['pstar'], 'tier': tier(cap)})
        else:
            nonquals.append({'cik': cik, 'px': px, 'cap': cap, 'tier': tier(cap)})
    quals.sort(key=lambda q: q['ratio'])
    return quals, nonquals, {'pool': len(POOL.get(F, {})), 'priced': priced,
                             'qualifiers': len(quals), 'pool_ncav': pool_ncav,
                             'unpriced_ncav_share': (unpriced_ncav / pool_ncav) if pool_ncav else 0.0}

QUAL, NONQUAL, CENSUS = {}, {}, {}
for F in range(2016, 2026):
    QUAL[F], NONQUAL[F], CENSUS[F] = qualifiers(F)

# ---------- engine ----------
def simulate(start, cap_n, house, buys_plan=None, rng=None, form_end=2025, end_ym=END_YM):
    months = [m for m in ym_iter(start) if m <= end_ym]
    cash, pos = 100.0, {}   # cik -> {qty, entry, tier, last}
    curve, buys_made, halts, trades = [], {}, 0, 0
    ep_base, dead, halt_until_idx, pending_restart = 100.0, False, -1, False
    for idx, ym in enumerate(months):
        y, mo = int(ym[:4]), int(ym[5:7])
        is_form = (mo == 6 and start <= y <= form_end)
        # vanish-to-zero
        for cik in list(pos):
            if price_at(cik, ym) is None and not has_later_price(cik, ym):
                del pos[cik]  # written to ZERO
        # marks
        def mark(cik):
            px = price_at(cik, ym)
            if px is not None: pos[cik]['last'] = px
            return pos[cik]['last']
        # June discount-closed exit (before buys)
        if is_form and y in POOL:
            for cik in list(pos):
                r = POOL[y].get(cik)
                px = price_at(cik, ym)
                if r and px is not None and r['shares'] * r['sf'] * px > r['ncav']:
                    cash += pos[cik]['qty'] * px * (1 - pos[cik]['tier']); trades += 1
                    del pos[cik]
        # monthly exits: +50% / 36 months (only when tradeable this month)
        for cik in list(pos):
            px = price_at(cik, ym)
            if px is None: continue
            held_m = (y - pos[cik]['ey']) * 12 + (mo - pos[cik]['em'])
            if px >= 1.5 * pos[cik]['entry'] or held_m >= 36:
                cash += pos[cik]['qty'] * px * (1 - pos[cik]['tier']); trades += 1
                del pos[cik]
        # formation buys
        if is_form and not dead and idx > halt_until_idx:
            if pending_restart:
                ep_base, pending_restart = cash + sum(p['qty'] * mark(c) for c, p in pos.items()), False
            slots = None if cap_n is None else max(0, cap_n - len(pos))
            if rng is None:
                cand = [q for q in QUAL.get(y, []) if q['cik'] not in pos]
                chosen = cand if slots is None else cand[:slots]
                buys_made[y] = len(chosen)
            else:
                k = buys_plan.get(y, 0) if buys_plan else 0
                if slots is not None: k = min(k, slots)
                cand = [q for q in NONQUAL.get(y, []) if q['cik'] not in pos]
                rng.shuffle(cand)
                chosen = cand[:k]
            if chosen and cash > 0:
                per = cash / len(chosen)
                for q in chosen:
                    qty = per * (1 - q['tier']) / q['px']
                    pos[q['cik']] = {'qty': qty, 'entry': q['px'], 'tier': q['tier'],
                                     'last': q['px'], 'ey': y, 'em': mo}
                    trades += 1
                cash = 0.0
        val = cash + sum(p['qty'] * mark(c) for c, p in pos.items())
        # house floor (v9 plain -15% of episode base, month-end check)
        if house and not dead and val <= 0.85 * ep_base:
            liq = cash
            for cik, p in pos.items():
                liq += p['qty'] * p['last'] * (1 - p['tier']); trades += 1
            cash, pos, val = liq, {}, liq
            halts += 1
            if halts >= 2:
                dead = True
            else:
                halt_until_idx = idx + 3  # 90 days cash
                pending_restart = True
        curve.append([ym, round(val, 2)])
    # final liquidation at last marks less sell cost
    final = cash
    for cik, p in pos.items():
        final += p['qty'] * p['last'] * (1 - p['tier'])
    if curve: curve[-1][1] = round(final, 2)
    return {'final': round(final, 2), 'curve': curve, 'buys': buys_made,
            'halts': halts, 'trades': trades}

def distribution(curve):
    vals = [v for _, v in curve]
    if len(vals) < 2: return None
    chg = [round(vals[i + 1] - vals[i], 2) for i in range(len(vals) - 1)]
    prof = sum(1 for c in chg if c > 0)
    run = longest = 0
    for c in chg:
        run = run + 1 if c < 0 else 0
        longest = max(longest, run)
    hi, since, stretch = vals[0], 0, 0
    for v in vals[1:]:
        if v > hi: hi, since = v, 0
        else:
            since += 1; stretch = max(stretch, since)
    return {'periods': len(chg), 'pct_profitable': round(100.0 * prof / len(chg), 1),
            'median_period_usd': round(statistics.median(chg), 2),
            'best_period_usd': max(chg), 'worst_period_usd': min(chg),
            'longest_losing_run': longest, 'longest_stretch_between_highs_months': stretch,
            'average_period_usd_secondary': round(statistics.mean(chg), 2)}

def spy_road(start):
    a, b = SPY.get(f'{start}-06'), SPY.get(END_YM)
    return round(100.0 * b / a, 2) if a and b else None

# ---------- split-factor verification (spec check, frames-based replication) ----------
def split_check():
    def load(name):
        p = os.path.join(FR, name)
        return {int(k): v for k, v in json.load(open(p)).items()} if os.path.exists(p) else {}
    sh = {y: load(f'Shares_{y}I.json') for y in range(2014, 2026)}
    def sf(cik, F):
        avail = [(y, sh[y][cik]) for y in range(2014, 2026) if sh[y].get(cik)]
        f = 1.0
        for (y0, a), (y1, b) in zip(avail, avail[1:]):
            if y1 >= F:
                r = b / a
                if r >= 1.6 or r <= 0.625: f *= r
        return f
    checks = []
    for name, cik, F in [('AAPL', 320193, 2021), ('TSLA', 1318605, 2021), ('AMZN', 1018724, 2023),
                         ('TSLA', 1318605, 2023), ('NVDA', 1045810, 2025)]:
        old, new = sh.get(F - 1, {}).get(cik), sh.get(F, {}).get(cik)
        if old and new:
            corrected = old * sf(cik, F)
            checks.append({'name': name, 'formation': F, 'sf': sf(cik, F),
                           'corrected_vs_own_year_shares_ratio': round(corrected / new, 3),
                           'within_25pct': abs(corrected / new - 1) <= 0.25})
    split_ciks = {320193, 1018724, 1045810, 1318605}
    sig = [F for F in range(2016, 2026) if any(q['cik'] in split_ciks for q in QUAL[F])]
    return {'checks': checks, 'known_splitter_qualifier_years': sig}

def main():
    out = {'family': 'net-net', 'native_count': 'ALL-ELIGIBLE',
           'fences': 'UPPER BOUND: unpriced fence (Yahoo-blind delisted/distressed names excluded) FLATTERS every number; p*<$0.25 fence HURTS; vanish-to-zero HURTS vs takeover premia. Universe is delisting-blind on free data (v11 UNBUILDABLE-NATIVE; v12 CONSTRUCTED form).',
           'census': {str(F): CENSUS[F] for F in range(2016, 2026)},
           'stageb_counts': COUNTS_STAGE, 'split_check': split_check(),
           'spy': {r: spy_road(s) for r, s in ROADS.items()}, 'cells': {}}
    winners = {}
    for form, house in [('native', False), ('house', True)]:
        for road, start in ROADS.items():
            finals, curves = {}, {}
            plans = {}
            for cn in COUNTS:
                key = 'ALL' if cn is None else str(cn)
                r = simulate(start, cn, house)
                finals[key] = r['final']; curves[key] = r['curve']; plans[key] = r['buys']
                out['cells'][f'{form}|{road}|{key}'] = {'final': r['final'], 'halts': r['halts'], 'trades': r['trades']}
            # placebos 20 seeds per cell
            for cn in COUNTS:
                key = 'ALL' if cn is None else str(cn)
                beats = 0; pfin = []
                for seed in range(20):
                    rng = random.Random(1000 + seed)
                    pr = simulate(start, cn, house, buys_plan=plans[key], rng=rng)
                    pfin.append(pr['final'])
                    if finals[key] > pr['final']: beats += 1
                out['cells'][f'{form}|{road}|{key}']['placebo_beats_of_20'] = beats
                out['cells'][f'{form}|{road}|{key}']['placebo_median'] = round(statistics.median(pfin), 2)
            best_key = max(finals, key=lambda k: finals[k])
            winners[f'{form}|{road}'] = best_key
            # curves saved for winning + native counts
            for key in {best_key, 'ALL'}:
                cn = None if key == 'ALL' else int(key)
                r = simulate(start, cn, house)
                out['cells'][f'{form}|{road}|{key}']['curve'] = r['curve']
                out['cells'][f'{form}|{road}|{key}']['distribution_monthly'] = distribution(r['curve'])
    out['winners'] = winners
    # CONFIRMATION: any non-native count beating ALL on >=2 roads in a form ->
    # disjoint sub-windows (formations 2016-2020 end Jun 2023 / 2021-2025)
    conf = {}
    for form, house in [('native', False), ('house', True)]:
        beat_roads = {}
        for cn in COUNTS:
            if cn is None: continue
            n = sum(1 for road in ROADS if out['cells'][f'{form}|{road}|{cn}']['final'] > out['cells'][f'{form}|{road}|ALL']['final'])
            if n >= 2: beat_roads[str(cn)] = n
        for key in beat_roads:
            cn = int(key)
            a = simulate(2016, cn, house, form_end=2020, end_ym='2023-06')
            aN = simulate(2016, None, house, form_end=2020, end_ym='2023-06')
            b = simulate(2021, cn, house)
            bN = simulate(2021, None, house)
            conf[f'{form}|{key}'] = {'roads_beaten': beat_roads[key],
                                     'subA_2016_2020': {'count': a['final'], 'ALL': aN['final']},
                                     'subB_2021_2025': {'count': b['final'], 'ALL': bN['final']},
                                     'confirmed': a['final'] > aN['final'] and b['final'] > bN['final']}
    out['confirmation'] = conf
    json.dump(out, open(os.path.join(HERE, 'results.json'), 'w'), indent=1)
    print(json.dumps({'winners': winners, 'confirmation': conf,
                      'finals': {k: v['final'] for k, v in out['cells'].items()}}, indent=1), flush=True)

if __name__ == '__main__':
    main()
