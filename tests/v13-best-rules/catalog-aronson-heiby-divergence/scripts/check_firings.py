#!/usr/bin/env python3
"""Diagnostic (post-run, printed in RESULTS.md): on which days did the
frozen veto condition div<=-50 (CN91 SPY - CN91 cumOBV, LMA4) actually
occur, and how many fall inside each program road? Reproduces the
firing census behind the headline finding. Simulation only."""
import json, datetime
import numpy as np

SPYJ = '/home/hatch/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json'
d = json.load(open(SPYJ))['chart']['result'][0]
ts = d['timestamp']; q = d['indicators']['quote'][0]
dates, C, V = [], [], []
for i, t in enumerate(ts):
    if q['close'][i] is None: continue
    dates.append(datetime.datetime.utcfromtimestamp(t).date())
    C.append(q['close'][i]); V.append(q['volume'][i] or 0)
C = np.array(C, float); V = np.array(V, float)

def cn(x, n):
    out = np.full(len(x), np.nan)
    for i in range(len(x)):
        if i < n - 1: continue
        w = x[i - n + 1:i + 1]; w = w[~np.isnan(w)]
        if len(w) < n // 2: continue
        lo, hi = w.min(), w.max()
        out[i] = 100.0 * (x[i] - lo) / (hi - lo) if hi > lo else 50.0
    return out

def lma4(x):
    out = np.full(len(x), np.nan); w = np.array([1., 2., 3., 4.])
    for i in range(3, len(x)):
        seg = x[i - 3:i + 1]
        if np.isnan(seg).any(): continue
        out[i] = float(np.dot(w, seg) / 10.0)
    return out

obv = np.cumsum(np.sign(np.diff(C, prepend=C[0])) * V)
div = lma4(cn(C, 91)) - lma4(cn(obv, 91))
fire = [dates[i] for i in range(len(dates)) if not np.isnan(div[i]) and div[i] <= -50]
print('all div<=-50 days:', len(fire), [str(x) for x in fire])
for a, b in [('2010-01-04', '2026-11-20'), ('2016-11-21', '2026-11-20'),
             ('2019-01-02', '2026-11-20'), ('2023-01-03', '2026-11-20')]:
    print(a, '->', b, 'firings:', sum(1 for x in fire if a <= str(x) <= b))
for span in (41, 205):
    dv = lma4(cn(C, span)) - lma4(cn(obv, span))
    print('span', span, 'min div', round(float(np.nanmin(dv)), 1),
          'count<=-50', int(np.sum(dv <= -50)))
