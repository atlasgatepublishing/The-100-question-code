#!/usr/bin/env python3
"""V13 best-rules: Zakamulin COMBI-VOTE exactly as frozen in BEST-RULES-SPEC.md.
Single cell per asset (SPY, BTC cross-run). Monthly, long/cash, NO floor.
Costs: SPY 0.10%/side, BTC 0.50%/side. 20 matched-long-share placebos.
Benchmarks: buy-hold + static 50/50 (monthly rebalanced)."""
import json, os, random, csv, statistics
FAM = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
BASE = os.path.join(FAM, '..', '..')
W04 = os.path.join(BASE, 'v11-native-rules', '_w04_broad_data')
spy = {r[0]: r[1] for r in json.load(open(os.path.join(W04, 'px_SPY.json')))}
months = sorted(spy); SP = [spy[m] for m in months]
btc = {}
with open(os.path.join(BASE, 'v4', 'crypto-trend-data', 'BTC-USD.csv')) as fh:
    rd = csv.DictReader(fh); cols = rd.fieldnames
    for row in rd:
        d = row[cols[0]]; v = row.get('Close') or row.get('close') or row[cols[1]]
        try: btc[d[:7]] = float(v)
        except Exception: pass
bm = sorted(btc); BT = [btc[m] for m in bm]

def sma(s, i, n): return sum(s[i-n+1:i+1]) / n if i >= n-1 else None
def sig_one(s, rule, n):
    out = []
    for i in range(len(s)):
        if rule == 'MOM': out.append(1 if i >= n and s[i] > s[i-n] else 0)
        elif rule == 'P-MA':
            m = sma(s, i, n); out.append(1 if m is not None and s[i] > m else 0)
        elif rule == 'MAC':
            a = sma(s, i, 5); b = sma(s, i, 10)
            out.append(1 if a is not None and b is not None and a > b else 0)
    return out
def combi(s):
    a = sig_one(s, 'MOM', 10); b = sig_one(s, 'P-MA', 10); c = sig_one(s, 'MAC', 0)
    return [1 if x + y + z >= 2 else 0 for x, y, z in zip(a, b, c)]

def run_timer(s, sig, cost, seed=None):
    cash = 100.0; curve = []; invested = False; costs = 0.0
    if seed is not None:
        rng = random.Random(seed); share = sum(sig) / max(1, len(sig))
        sig = [1 if rng.random() < share else 0 for _ in sig]
    for i in range(1, len(s)):
        want = bool(sig[i-1])
        if want != invested:
            c = cash * cost; costs += c; cash -= c; invested = want
        if invested: cash *= s[i] / s[i-1]
        curve.append(round(cash, 2))
    dd = 0.0; pk = 100.0
    for v in curve: pk = max(pk, v); dd = max(dd, 1 - v / pk)
    return round(cash, 2), curve, round(costs, 2), round(dd, 4)

def run_static(s, cost, w=0.5):
    """50/50 asset/cash, monthly rebalanced; cost on traded amount."""
    curve = []; costs = 0.0; holding = 100.0 * w; cash_amt = 100.0 * (1 - w)
    for i in range(1, len(s)):
        holding *= s[i] / s[i-1]
        tot = holding + cash_amt
        target = w * tot
        trade = abs(target - holding)
        c = trade * cost; costs += c
        # rebalance to target, paying the switch cost out of the total
        holding = target - c * w; cash_amt = tot - c - holding
        curve.append(round(holding + cash_amt, 2))
    tot = holding + cash_amt
    dd = 0.0; pk = 100.0
    for v in curve: pk = max(pk, v); dd = max(dd, 1 - v / pk)
    return round(tot, 2), curve, round(costs, 2), round(dd, 4)

def period_stats(curve):
    vals = [100.0] + curve; rets = []
    for i in range(12, len(vals), 12): rets.append(vals[i] / vals[i-12] - 1)
    if not rets: return None
    pos = sum(1 for r in rets if r > 0); run = 0; worst = 0
    for r in rets: run = run + 1 if r <= 0 else 0; worst = max(worst, run)
    pk = vals[0]; cur = 0; nohigh = 0
    for v in vals:
        if v >= pk: pk = v; cur = 0
        else: cur += 1; nohigh = max(nohigh, cur)
    return {'periods': len(rets), 'positive': pos,
            'median_pct': round(statistics.median(rets) * 100, 1),
            'mean_pct_secondary': round(statistics.mean(rets) * 100, 1),
            'best_pct': round(max(rets) * 100, 1), 'worst_pct': round(min(rets) * 100, 1),
            'longest_losing_run': worst, 'longest_months_between_highs': nohigh}

ROADS = {'DECADE': ('2017-01', '2026-06'), 'CONT': ('2019-07', '2026-06'),
         'VAL': ('2023-07', '2026-06'), 'LONGEST': ('2016-07', '2026-06')}
CHAMP = {'DECADE': 667.35, 'CONT': 544.47, 'VAL': 288.05}
res = {'family': 'catalog-taa-zakamulin-optimal-trend', 'program': 'v13-best-rules',
       'cell': 'COMBI-VOTE = majority{MOM(10), P-MA(10), MAC(5,10)}, monthly, long/cash, NO floor',
       'assets': {}}
for label, series, mlist, cost in (('SPY', SP, months, 0.0010), ('BTC', BT, bm, 0.0050)):
    idx = {m: i for i, m in enumerate(mlist)}
    sig = combi(series)
    cell = {}
    for rname, (a, b) in ROADS.items():
        i0, i1 = idx[a], idx[b]
        sub = series[i0:i1+1]; ssig = sig[i0:i1+1]
        fin, curve, costs, dd = run_timer(sub, ssig, cost)
        twins = [run_timer(sub, ssig, cost, seed=sd)[0] for sd in range(1, 21)]
        bh = round(100 * series[i1] / series[i0], 2)
        sf, scurve, scosts, sdd = run_static(sub, cost)
        cell[rname] = {'final': fin, 'costs': costs, 'max_dd': dd, 'curve': curve,
                       'months': mlist[i0:i1+1],
                       'buyhold_same_window': bh,
                       'static_50_50': {'final': sf, 'costs': scosts, 'max_dd': sdd, 'curve': scurve},
                       'placebo_finals': twins,
                       'placebos_beaten': sum(1 for t in twins if fin > t),
                       'placebo_median': round(statistics.median(twins), 2),
                       'long_share': round(sum(ssig) / len(ssig), 3),
                       'period_stats': period_stats(curve),
                       'beats_champion_vm': (fin > CHAMP[rname]) if (label == 'SPY' and rname in CHAMP) else None}
        print(label, rname, fin, 'bh', bh, 'static', sf, 'placebos', cell[rname]['placebos_beaten'], '/20 dd', dd, flush=True)
    res['assets'][label] = {'months': [mlist[0], mlist[-1]], 'cost_per_side': cost, 'roads': cell}
json.dump(res, open(os.path.join(FAM, 'results.json'), 'w'), indent=1)
print('saved results.json')
