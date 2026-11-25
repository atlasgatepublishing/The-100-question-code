#!/usr/bin/env python3
"""Fetch daily prices for every ticker the panel needs.
Reuse the program's read-only pxfull cache (v7 long-hold) where present;
otherwise pull Yahoo chart JSON (same source/format as the cache) into
this family's data/prices/. Also SPY. Simulation only."""
import json, os, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')
PX = os.path.join(DATA, 'prices')
os.makedirs(PX, exist_ok=True)
sys.path.insert(0, HERE)
from mapping import ticker_for

CACHE = os.path.expanduser('~/workspace/stock-app/backtests/v7/long-hold/data')
panel = json.load(open(os.path.join(DATA, 'panel_raw.json')))
need = set(['SPY'])
for y, names in panel.items():
    for n in names:
        t = ticker_for(n, int(y))
        if t: need.add(t)
print('tickers needed:', len(need))

UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AtlasGateResearch'}
ok, fail = [], []
for t in sorted(need):
    dst = os.path.join(PX, f'px_{t}.json')
    if os.path.exists(dst): ok.append(t); continue
    src = os.path.join(CACHE, f'pxfull_{t}.json')
    if os.path.exists(src):
        with open(src) as f: raw = f.read()
        open(dst, 'w').write(raw); ok.append(t); continue
    url = (f'https://query2.finance.yahoo.com/v8/finance/chart/{t}'
           f'?period1=1230768000&period2=1796000000&interval=1d&events=div,split')
    try:
        req = urllib.request.Request(url, headers=UA)
        raw = urllib.request.urlopen(req, timeout=40).read().decode('utf-8', 'ignore')
        d = json.loads(raw)
        if not d.get('chart', {}).get('result'): raise ValueError('empty result')
        open(dst, 'w').write(raw); ok.append(t)
    except Exception as e:
        fail.append((t, str(e)[:80])); print('FAIL', t, e, flush=True)
    time.sleep(0.4)
print('ok', len(ok), 'fail', fail)
json.dump({'ok': ok, 'fail': fail}, open(os.path.join(DATA, 'price_fetch_log.json'), 'w'), indent=1)
