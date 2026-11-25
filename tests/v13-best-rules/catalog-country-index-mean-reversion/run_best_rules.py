#!/usr/bin/env python3
"""V13 best-rules: country-index mean reversion, MY form (see BEST-RULES-SPEC.md).
Long-only bottom-7 of 21 country ETFs by trailing 36m return, annual January
rebalance, equal weight, 0.10%/side on turnover, NO floor.
Data: Yahoo monthly adjusted close, cached in ./data_cache (this folder only).
Simulation only. Writes only in this folder."""
import json, os, sys, time, urllib.request, statistics
import pandas as pd, numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, 'data_cache'); os.makedirs(CACHE, exist_ok=True)
POND = ['EWA','EWC','EWD','EWG','EWH','EWI','EWJ','EWK','EWL','EWN','EWO',
        'EWP','EWQ','EWS','EWU','EWW','EWY','EWZ','EWT','EZA','FXI']
COST = 0.001; TOPN = 7; LOOKBACK = 36

def fetch(t):
    p = os.path.join(CACHE, f'{t}.json')
    if os.path.exists(p): return json.load(open(p))
    url = (f'https://query1.finance.yahoo.com/v8/finance/chart/{t}'
           f'?period1=0&period2=1796000000&interval=1mo&events=div,split')
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=30) as r: raw = json.load(r)
    res = raw['chart']['result'][0]
    ts = res['timestamp']; adj = res['indicators']['adjclose'][0]['adjclose']
    out = {pd.Timestamp.utcfromtimestamp(t_).strftime('%Y-%m-%d'): float(v)
           for t_, v in zip(ts, adj) if v is not None}
    json.dump(out, open(p, 'w')); time.sleep(0.3); return out

def load(t):
    d = fetch(t)
    s = pd.Series({pd.Timestamp(k): v for k, v in d.items()}).sort_index()
    s.index = s.index.to_period('M').to_timestamp('M')
    return s[~s.index.duplicated(keep='last')]

PRICES = {t: load(t) for t in POND + ['SPY']}
ALLIDX = PRICES['SPY'].index

ROADS = {'LONG': ('2010-01-04', '2026-11-20'), 'DECADE': ('2016-11-21', '2026-11-20'),
         'CONT': ('2019-01-02', '2026-11-20'), 'VAL': ('2023-01-03', '2026-11-20')}

def eligible(t_sig):
    out = []
    for t in POND:
        s = PRICES[t]
        hist = s[s.index <= t_sig]
        if len(hist) >= LOOKBACK + 1: out.append(t)
    return out

def signal_weights(t_sig):
    """Rank at signal month-end t_sig (data <= t_sig only)."""
    pool = eligible(t_sig); rets = {}
    for t in pool:
        s = PRICES[t]; h = s[s.index <= t_sig]
        rets[t] = h.iloc[-1] / h.iloc[-LOOKBACK - 1] - 1.0
    picks = sorted(pool, key=lambda t: rets[t])[:TOPN]
    if not picks: return {}, picks, pool
    return {t: 1.0 / len(picks) for t in picks}, picks, pool

def simulate(road, seed=None):
    start, end = pd.Timestamp(ROADS[road][0]), pd.Timestamp(ROADS[road][1])
    months = [m for m in ALLIDX if start <= m <= end]
    rng = np.random.default_rng(seed) if seed is not None else None
    eq = 100.0; curve = {}; weights = {}; total_cost = 0.0; picks_log = []
    for i, t in enumerate(months):
        curve[t] = eq
        if i == len(months) - 1: break
        t1 = months[i + 1]
        # Annual rebalance: decision at January month-end t, using data <= t,
        # applied to the t -> t1 month. Also initial entry at road start:
        # signal from the month-end just before the road start.
        new_w = weights
        if t.month == 1 or i == 0:
            if i == 0:
                prior = [m for m in ALLIDX if m < months[0]]
                sig_t = prior[-1] if prior else t
            else:
                sig_t = t
            if rng is not None:
                pool = eligible(sig_t)
                k = min(TOPN, len(pool))
                pick = list(rng.choice(pool, size=k, replace=False)) if k else []
                new_w = {x: 1.0 / k for x in pick} if k else {}
                picks_log.append([str(sig_t.date()), sorted(pick)])
            else:
                new_w, picks, pool = signal_weights(sig_t)
                picks_log.append([str(sig_t.date()), picks])
        allk = set(weights) | set(new_w)
        turn = sum(abs(new_w.get(k, 0) - weights.get(k, 0)) for k in allk)
        c = eq * turn * COST; total_cost += c; eq -= c
        ret = 0.0
        for k, w in new_w.items():
            s = PRICES[k]
            if t in s.index and t1 in s.index: ret += w * (s[t1] / s[t] - 1)
            # else: series gap -> 0 for that month (conservative, no phantom gain)
        eq *= (1 + ret); weights = new_w
    return pd.Series(curve), round(total_cost, 2), picks_log

def spy_final(road):
    start, end = pd.Timestamp(ROADS[road][0]), pd.Timestamp(ROADS[road][1])
    s = PRICES['SPY']; m = [x for x in s.index if start <= x <= end]
    return round(100 * s[m[-1]] / s[m[0]], 2)

def stats(eq):
    r = eq.pct_change().dropna()
    ls = cur = 0
    for x in r: cur = cur + 1 if x <= 0 else 0; ls = max(ls, cur)
    peak = eq.cummax(); below = eq < peak - 1e-9
    lb = cur = 0
    for x in below: cur = cur + 1 if x else 0; lb = max(lb, cur)
    return {'n_periods': int(len(r)), 'share_positive': round(float((r > 0).mean()), 3),
            'median_period': round(float(r.median()), 4),
            'mean_period_secondary': round(float(r.mean()), 4),
            'best': round(float(r.max()), 4), 'worst': round(float(r.min()), 4),
            'longest_losing_streak': int(ls), 'longest_below_high_months': int(lb),
            'max_dd': round(float((eq / peak - 1).min()), 4)}

def main():
    log = open(os.path.join(HERE, 'run.log'), 'w')
    def say(*a): print(*a, flush=True); print(*a, file=log, flush=True)
    say('first months:', {t: str(PRICES[t].index.min().date()) for t in POND})
    out = {'family': 'catalog-country-index-mean-reversion', 'program': 'v13-best-rules',
           'my_rules': {'side': 'long-only', 'topn': TOPN, 'lookback_months': LOOKBACK,
                        'cadence': 'annual January', 'cost_rate_per_side': COST, 'floor': None,
                        'pond': POND},
           'survivorship_fence': 'Pond = 21 still-existing iShares country funds (v12 pond); delisted country ETFs absent -> finals are UPPER BOUNDS. PIT 36m-history eligibility enforced.',
           'roads': {}}
    for road in ROADS:
        eq, cost, picks = simulate(road)
        st = stats(eq); fin = round(float(eq.iloc[-1]), 2)
        beats = 0; finals = []
        for seed in range(20):
            ep, _, _ = simulate(road, seed=seed); finals.append(round(float(ep.iloc[-1]), 2))
            if fin > finals[-1]: beats += 1
        out['roads'][road] = {'final': fin, 'cost': cost, 'stats': st,
                              'spy_same_data': spy_final(road),
                              'placebos': {'beats': beats, 'median_placebo': round(float(np.median(finals)), 2),
                                           'finals': finals},
                              'picks_log': picks,
                              'curve': {str(k.date()): round(float(v), 4) for k, v in eq.items()}}
        say(f"{road}: final {fin} maxDD {st['max_dd']} cost {cost} spy {spy_final(road)} "
            f"placebos {beats}/20 median {out['roads'][road]['placebos']['median_placebo']} stats {st}")
    json.dump(out, open(os.path.join(HERE, 'results.json'), 'w'), indent=1)
    say('saved results.json'); log.close()

if __name__ == '__main__': main()
