#!/usr/bin/env python3
"""V13 Best-Rules engine — HLZ labor-unionization (Chen-Kacperczyk-Ortiz-Molina).
Frozen by BEST-RULES-SPEC.md in this folder BEFORE this run.

Design: annual FEBRUARY formation; signal = prior-year BLS CPS Table 42
union membership rate of the firm's SIC-mapped industry; eligible =
industries at/below that year's median rate across the 25 mapped
industries; hold ALL priced names in eligible industries, equal weight,
12-month hold; NO floor. Costs: W04 tiered program costs by market cap
(0.10% >=$5B / 0.25% $1-5B / 0.75% <$1B or unknown, per side).
Chassis conventions identical to the v13 Dreman pass on the same W04
stack: return series = px[ym][0] (adjusted close); a name whose series
has ended marks 0.0 after its last bar (vanished -> ZERO); missing month
before the last bar carries the last price. Placebos: 20 seeds, same
count per formation drawn at random from ALL mapped priced candidates.
"""
import json, os, random, statistics
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.dirname(HERE)
W04 = os.path.expanduser('~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data')
RATES = json.load(open(os.path.join(OUT, 'data', 'union_rates.json')))['rates']

def loadj(p): return json.load(open(p)) if os.path.exists(p) else {}
cand = {int(k): v for k, v in loadj(os.path.join(W04, 'candidates.json')).items()}
px = {}
for cik, info in cand.items():
    t = info['ticker'].replace('/', '-')
    p = os.path.join(W04, f'px_{t}.json')
    if os.path.exists(p):
        try: px[cik] = {r[0]: (r[1], r[2]) for r in loadj(p)}
        except Exception: pass
spy = {r[0]: r[1] for r in loadj(os.path.join(W04, 'px_SPY.json'))}
SHARES = {y: {int(k): v for k, v in loadj(os.path.join(W04, 'frames', f'Shares_{y}I.json')).items()}
          for y in range(2014, 2026)}

NONDUR = {'20','21','22','23','26','27','28','29','30','31'}
def industry_of(sic):
    if not sic: return None
    s = str(sic).zfill(4); s2, s3 = s[:2], s[:3]
    n = int(s)
    if s2 in ('01','02','07','08','09'): return 'agri'
    if s2 in ('10','11','12','13','14'): return 'mining'
    if s2 in ('15','16','17'): return 'construction'
    if s3 in ('271','272','273','274','277'): return 'publishing'
    if 2000 <= n <= 3999: return 'nondurable' if s2 in NONDUR else 'durable'
    if 4000 <= n <= 4799: return 'transp_ware'
    if s3 in ('481','482','489'): return 'telecom'
    if s3 in ('483','484'): return 'broadcasting'
    if s2 == '49': return 'utilities'
    if s2 in ('50','51'): return 'wholesale'
    if 5200 <= n <= 5999: return 'retail'
    if s2 in ('60','61','62','67'): return 'finance'
    if s2 in ('63','64'): return 'insurance'
    if s2 == '65': return 'realestate'
    if s2 == '70': return 'accommodation'
    if s2 in ('72','75','76','86','88'): return 'other_exhh'
    if s3 == '737': return 'prof_tech'
    if s2 == '73': return 'mgmt_admin'
    if s2 == '78': return 'motionpic'
    if s2 in ('79','84'): return 'arts'
    if s2 in ('80','83'): return 'health'
    if s2 in ('81','87','89'): return 'prof_tech'
    if s2 == '82': return 'education'
    if 9100 <= n <= 9799: return 'public'
    return None

IND = {cik: industry_of(info.get('sic')) for cik, info in cand.items()}

def ym(y, m): return f'{y:04d}-{m:02d}'
def months_between(a, b):
    y, m = int(a[:4]), int(a[5:7]); out = []
    while ym(y, m) <= b:
        out.append(ym(y, m)); m += 1
        if m == 13: y, m = y + 1, 1
    return out

def cap_of(cik, F):
    sh = SHARES.get(F - 1, {}).get(cik) or SHARES.get(F - 2, {}).get(cik)
    e = px.get(cik, {}).get(ym(F, 2))
    if not sh or not e or not e[1]: return None
    return sh * e[1]
def cost_rate(cap):
    if cap is None: return 0.0075
    if cap >= 5e9: return 0.0010
    if cap >= 1e9: return 0.0025
    return 0.0075

FORM = {}
for F in range(2016, 2027):
    rates = RATES[str(F - 1)]
    med = statistics.median(rates.values())
    elig_ind = sorted([k for k, v in rates.items() if v <= med])
    allc, elc = [], []
    gated = 0
    for cik in cand:
        ind = IND.get(cik)
        if ind is None or cik not in px: continue
        e = px[cik].get(ym(F, 2))
        if not e or not e[0]: continue
        # DATA-INTEGRITY GATE (post-spec, disclosed in RESULTS): the shared
        # W04 cache contains broken bars (e.g. AMCCF: negative adjusted
        # prices, a $0.05 raw bar between $57 bars). A name is priced at a
        # formation only if adjusted price > 0 and raw close >= $1.00.
        # Applied identically to the signal book and every placebo draw.
        if e[0] <= 0 or not e[1] or e[1] < 1.00:
            gated += 1; continue
        allc.append(cik)
        if ind in elig_ind: elc.append(cik)
    FORM[F] = {'eligible': sorted(elc), 'all': sorted(allc), 'gated_out': gated,
               'median_rate': med, 'eligible_industries': elig_ind,
               'rates': {cik: cost_rate(cap_of(cik, F)) for cik in allc}}

def price_series(cik, cols):
    s = px[cik]; last = None; lastbar = max(s) if s else None
    out = []
    for mm in cols:
        if mm in s: last = s[mm][0]
        if lastbar is not None and mm > lastbar: out.append(0.0)
        elif last is not None: out.append(last)
        else: out.append(np.nan)
    return np.array(out, dtype=float)

def run_road(formations, start_month, seed=None):
    cash = 100.0; total_costs = 0.0; curve = []; periods = []
    period_start_val = 100.0
    all_months = months_between(start_month, '2026-11')
    form_set = {ym(F, 2): F for F in formations}
    held = None  # (ciks, shares, P matrix, cols, rates)
    for mm in all_months:
        if mm in form_set:
            F = form_set[mm]
            info = FORM[F]
            if seed is None: picks = list(info['eligible'])
            else:
                rng = random.Random(seed * 100003 + F)
                keys = list(info['all']); rng.shuffle(keys)
                picks = sorted(keys[:len(info['eligible'])])
            if held is not None:
                # value old book at formation prices; sell EXITS in full;
                # continuing names trade only |target - drifted| (spec rule 8)
                ociks, oshares, _, _, orates = held
                ovals = {}
                for ci, c in enumerate(ociks):
                    v = price_series(c, [mm])[0]
                    ovals[c] = 0.0 if np.isnan(v) else float(oshares[ci] * v)
                pickset = set(picks)
                post = cash
                for ci, c in enumerate(ociks):
                    if c in pickset: post += ovals[c]
                    else:
                        sc = ovals[c] * orates[ci]; total_costs += sc
                        post += ovals[c] - sc
                periods.append(post / period_start_val - 1.0)
                period_start_val = post
                held = None
                cash = post
                old_shares = {c: oshares[ci] for ci, c in enumerate(ociks)}
                old_vals = ovals
            else:
                old_shares, old_vals = {}, {}
            if picks:
                cols = [c for c in months_between(ym(F, 2), ym(F + 1, 1)) if c <= '2026-11']
                P = np.array([price_series(c, cols) for c in picks])
                rates = np.array([info['rates'][c] for c in picks])
                px0 = P[:, 0].copy(); px0[px0 <= 0] = np.nan
                t = cash / len(picks)
                shares = np.zeros(len(picks))
                for i, c in enumerate(picks):
                    if np.isnan(px0[i]): continue
                    v0 = old_vals.get(c, 0.0)
                    ci_cost = rates[i] * (abs(t - v0) if c in old_shares else t)
                    total_costs += ci_cost
                    shares[i] = max(t - ci_cost, 0.0) / px0[i]
                held = (picks, shares, P, cols, rates)
                cash = 0.0
        if held is not None:
            ciks, shares, P, cols, rates = held
            j = cols.index(mm)
            col = np.where(np.isnan(P[:, j]), 0.0, P[:, j])
            val = float(np.sum(shares * col))
        else:
            val = cash
        curve.append([mm, round(val, 2)])
    final = curve[-1][1]
    periods.append(final / period_start_val - 1.0)
    peak = 100.0; maxdd = 0.0
    for _, v in curve:
        peak = max(peak, v); maxdd = max(maxdd, 1 - v / peak) if peak else 0.0
    return round(final, 2), curve, round(total_costs, 2), round(maxdd, 4), periods

def dist_stats(periods, curve):
    rets = periods
    los = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0; los = max(los, cur)
    vals = [100.0] + [v for _, v in curve]
    peak = -1; since = 0; longest = 0
    for v in vals:
        if v >= peak: peak = v; since = 0
        else: since += 1; longest = max(longest, since)
    return {'n_periods': len(rets),
            'median_period_pct': round(100 * float(np.median(rets)), 2),
            'share_positive': round(sum(1 for r in rets if r > 0) / len(rets), 3),
            'best_period_pct': round(100 * max(rets), 2),
            'worst_period_pct': round(100 * min(rets), 2),
            'longest_losing_streak_periods': los,
            'longest_between_highs_months': longest,
            'avg_period_pct_secondary': round(100 * float(np.mean(rets)), 2),
            'period_returns_pct': [round(100 * r, 2) for r in rets]}

ROADS = {'LONG':   (list(range(2016, 2027)), '2016-02', '2016-01'),
         'DECADE': (list(range(2017, 2027)), '2016-11', '2016-10'),
         'CONT':   (list(range(2019, 2027)), '2019-01', '2018-12'),
         'VAL':    (list(range(2023, 2027)), '2023-01', '2022-12')}

def spy_final(base_month):
    a = spy.get(base_month); b = spy.get('2026-11')
    return round(100 * b / a, 2) if a and b else None

def main():
    out = {'family': 'catalog-hlz-labor-unionization', 'program': 'v13-best-rules',
           'spec': 'BEST-RULES-SPEC.md (frozen before run)',
           'formations': {str(F): {'n_eligible': len(FORM[F]['eligible']),
                                   'n_all_mapped_priced': len(FORM[F]['all']),
                                   'n_gated_out_integrity': FORM[F]['gated_out'],
                                   'median_rate': FORM[F]['median_rate'],
                                   'eligible_industries': FORM[F]['eligible_industries']}
                          for F in sorted(FORM)},
           'roads': {}}
    for rname, (forms, start_month, spy_base) in ROADS.items():
        fin, curve, costs, maxdd, periods = run_road(forms, start_month)
        twins = [run_road(forms, start_month, seed=s)[0] for s in range(1, 21)]
        out['roads'][rname] = {'final': fin, 'costs': costs, 'max_dd': maxdd,
                               'spy_same_window': spy_final(spy_base),
                               'placebos_beaten': sum(1 for t in twins if fin > t),
                               'placebo_median': float(np.median(twins)),
                               'placebo_finals': twins,
                               'distribution': dist_stats(periods, curve),
                               'curve': curve}
        print(rname, fin, 'dd', maxdd, 'costs', costs, 'spy', spy_final(spy_base),
              'pb', sum(1 for t in twins if fin > t), '/20', flush=True)
    json.dump(out, open(os.path.join(OUT, 'results.json'), 'w'), indent=1)
    print('saved')

if __name__ == '__main__':
    main()
