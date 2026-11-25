#!/usr/bin/env python3
"""V13 BEST RULES — catalog-aronson-ma-bands.
Frozen design (BEST-RULES-SPEC.md): SPY long/flat MA-band trend filter,
SMA span 205, bands +/-5%, stateful hold between bands, daily evaluation,
signal on close i applied to return i+1, cost 0.10% per unit position
change, NO floor, cash 0%. Placebos: 20 circular phase-shifts of the
position series (v12 chassis convention, seeds 777+s).
Also re-runs the v12 published representative (ma205b3 long/short) on the
SAME plumbing/windows as a plumbing check, labeled as such.
Simulation only."""
import json, os, random, datetime
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FAM = os.path.dirname(HERE)
SPYJ = os.path.expanduser('~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json')

d = json.load(open(SPYJ))['chart']['result'][0]
ts = d['timestamp']; q = d['indicators']['quote'][0]
dates, C = [], []
for i, t in enumerate(ts):
    if q['close'][i] is None: continue
    dates.append(datetime.datetime.utcfromtimestamp(t).date()); C.append(q['close'][i])
C = np.array(C, dtype=float); N = len(C)
ret = np.zeros(N); ret[1:] = C[1:] / C[:-1] - 1

def sma(x, n):
    out = np.full(len(x), np.nan)
    cs = np.cumsum(x)
    for i in range(len(x)):
        if i >= n - 1: out[i] = (cs[i] - (cs[i - n] if i - n >= 0 else 0.0)) / n
    return out

def band_positions(price, span, width, long_short):
    m = sma(price, span); pos = np.zeros(N); cur = 0.0
    for i in range(N):
        if not np.isnan(m[i]):
            if price[i] > m[i] * (1 + width / 100.0): cur = 1.0
            elif price[i] < m[i] * (1 - width / 100.0): cur = -1.0 if long_short else 0.0
        pos[i] = cur
    return pos

POS_MINE = band_positions(C, 205, 5.0, long_short=False)   # frozen best-rules
POS_PUB = band_positions(C, 205, 3.0, long_short=True)     # v12 representative, plumbing check only

ROADS = {'LONG': ('2010-01-04', '2026-11-20'), 'DECADE': ('2016-11-21', '2026-11-20'),
         'CONT': ('2019-01-02', '2026-11-20'), 'VAL': ('2023-01-03', '2026-11-20')}
CHAMP = {'LONG': 1415.62, 'DECADE': 667.35, 'CONT': 544.47, 'VAL': 288.05}

def road_idx(a, b):
    i0 = next(i for i, dt in enumerate(dates) if dt >= datetime.date.fromisoformat(a))
    i1 = max(i for i, dt in enumerate(dates) if dt <= datetime.date.fromisoformat(b))
    return i0, i1

def run(pos, i0, i1):
    eq = 100.0; prev = 0.0; costs = 0.0; trades = 0
    curve = [[str(dates[i0]), 100.0]]
    for i in range(i0 + 1, i1 + 1):
        p = pos[i - 1]
        chg = abs(p - prev)
        if chg > 0:
            c = eq * chg * 0.001; eq -= c; costs += c; trades += 1
        eq *= (1 + p * ret[i]); prev = p
        curve.append([str(dates[i]), round(eq, 2)])
    peak = 100.0; mdd = 0.0
    for _, v in curve:
        peak = max(peak, v); mdd = max(mdd, 1 - v / peak)
    return round(eq, 2), curve, round(costs, 2), round(mdd, 4), trades

def spy_final(i0, i1): return round(100 * C[i1] / C[i0], 2)

def period_stats(curve):
    months = {}
    for ds, v in curve: months[ds[:7]] = v
    ks = sorted(months); vals = [months[k] for k in ks]
    rets = [vals[i] / vals[i - 1] - 1 for i in range(1, len(vals)) if vals[i - 1] > 0]
    los = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0; los = max(los, cur)
    peak = -1; since = 0; longest = 0
    for v in vals:
        if v >= peak: peak = v; since = 0
        else: since += 1; longest = max(longest, since)
    return {'n_months': len(rets), 'share_positive': round(sum(1 for r in rets if r > 0) / len(rets), 3),
            'median_month_pct': round(100 * float(np.median(rets)), 2),
            'best_month_pct': round(100 * max(rets), 2), 'worst_month_pct': round(100 * min(rets), 2),
            'longest_losing_streak_months': los, 'longest_between_highs_months': longest,
            'avg_month_pct_secondary': round(100 * float(np.mean(rets)), 2)}

def main():
    out = {'family': 'catalog-aronson-ma-bands', 'program': 'v13-best-rules',
           'design': 'SPY long/flat, SMA205 bands +/-5%, stateful, daily, 0.10%/unit-change, no floor',
           'roads': {}}
    for rname, (a, b) in ROADS.items():
        i0, i1 = road_idx(a, b)
        fin, curve, costs, mdd, trades = run(POS_MINE, i0, i1)
        twins = []
        for s in range(1, 21):
            rng = random.Random(777 + s)
            off = rng.randint(60, N - 60)
            tf, _, _, _, _ = run(np.roll(POS_MINE, off), i0, i1)
            twins.append(tf)
        pfin, _, pcosts, pmdd, _ = run(POS_PUB, i0, i1)
        out['roads'][rname] = {
            'window': [a, b], 'final': fin, 'costs': costs, 'max_dd': mdd, 'trades': trades,
            'spy_same_window': spy_final(i0, i1), 'champion_VM': CHAMP[rname],
            'beats_champion': bool(fin > CHAMP[rname]),
            'placebos_beaten': sum(1 for t in twins if fin > t), 'placebo_finals': twins,
            'placebo_median': round(float(np.median(twins)), 2),
            'period_stats_monthly': period_stats(curve),
            'published_rep_same_plumbing': {'cell': 'ma205b3 long/short', 'final': pfin,
                                            'costs': pcosts, 'max_dd': pmdd},
            'curve': curve}
        print(rname, 'mine', fin, 'dd', mdd, 'spy', spy_final(i0, i1), 'pb', out['roads'][rname]['placebos_beaten'],
              'pub-rep-same-plumbing', pfin, flush=True)
    # Confirmation machinery (frozen bar in spec) — computed for any road beating champion;
    # also stored unconditionally for the record.
    conf = {}
    for rname, (a, b) in ROADS.items():
        i0, i1 = road_idx(a, b); mid = (i0 + i1) // 2
        halves = []
        for (h0, h1) in ((i0, mid), (mid, i1)):
            hf, _, _, hmdd, _ = run(POS_MINE, h0, h1)
            halves.append({'window': [str(dates[h0]), str(dates[h1])], 'final': hf,
                           'spy_same_window': spy_final(h0, h1), 'max_dd': hmdd,
                           'beats_spy': bool(hf > spy_final(h0, h1))})
        conf[rname] = {'half_windows': halves}
    fresh = {}
    for nm, (a, b) in {'FRESH_2010_2018': ('2010-01-04', '2018-12-31'),
                       'FRESH_2019_2026': ('2019-01-02', '2026-11-20')}.items():
        i0, i1 = road_idx(a, b)
        ff, _, _, fmdd, _ = run(POS_MINE, i0, i1)
        fresh[nm] = {'window': [a, b], 'final': ff, 'spy_same_window': spy_final(i0, i1),
                     'max_dd': fmdd, 'beats_spy': bool(ff > spy_final(i0, i1))}
    out['confirmation'] = {'half_windows': conf, 'fresh_windows': fresh}
    json.dump(out, open(os.path.join(FAM, 'results.json'), 'w'), indent=1)
    print('CONF', json.dumps(conf, indent=1)[:600]); print('FRESH', json.dumps(fresh, indent=1))

if __name__ == '__main__': main()
