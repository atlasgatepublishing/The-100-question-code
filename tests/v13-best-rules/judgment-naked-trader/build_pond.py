#!/usr/bin/env python3
"""Amendment-2 pond build: v3 insider-bars tickers (daily Yahoo chart JSON,
read-only) -> monthly bars (last trading day of month: adjclose, raw close),
mapped to CIK via the SEC current company_tickers_exchange file, NYSE/Nasdaq
only. Writes universe.json + monthly_px.json into THIS folder."""
import glob, json, os
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
BARS = os.path.expanduser('~/workspace/stock-app/backtests/v3/insider-data/bars')
SY = os.path.expanduser('~/workspace/stock-app/backtests/v12-completions/shareholder-yield/data')

tick = json.load(open(os.path.join(SY, 'company_tickers_exchange.json')))
f = tick['fields']
ci, ti, ei = f.index('cik'), f.index('ticker'), f.index('exchange')
t2c = {}
for row in tick['data']:
    if row[ei] in ('NYSE', 'Nasdaq'):
        t2c.setdefault(row[ti], int(row[ci]))

universe = {}
monthly = {}
n_files = 0
for p in glob.glob(os.path.join(BARS, '*.json')):
    t = os.path.basename(p)[:-5]
    if t not in t2c:
        continue
    try:
        d = json.load(open(p))['chart']['result'][0]
        ts = d['timestamp']
        adj = d['indicators']['adjclose'][0]['adjclose']
        raw = d['indicators']['quote'][0]['close']
    except Exception:
        continue
    m = {}
    for i, x in enumerate(ts):
        if adj[i] is None or raw[i] is None:
            continue
        dt = datetime.fromtimestamp(x, tz=timezone.utc)
        key = f'{dt.year:04d}-{dt.month:02d}'
        m[key] = [round(adj[i], 6), round(raw[i], 6)]  # last day wins (series is chronological)
    if len(m) < 24:
        continue
    cik = t2c[t]
    if cik in monthly:
        continue
    monthly[cik] = m
    universe[cik] = t
    n_files += 1

json.dump({str(k): v for k, v in universe.items()},
          open(os.path.join(HERE, 'universe.json'), 'w'))
json.dump({str(k): v for k, v in monthly.items()},
          open(os.path.join(HERE, 'monthly_px.json'), 'w'))
starts = {}
for m in monthly.values():
    starts[min(m)[:4]] = starts.get(min(m)[:4], 0) + 1
print('pond names:', len(universe), 'price-start years:', sorted(starts.items()))
