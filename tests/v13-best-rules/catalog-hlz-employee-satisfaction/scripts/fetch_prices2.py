#!/usr/bin/env python3
"""Retry failed tickers: Yahoo query1 first, then Stooq daily CSV
(converted into the same px JSON shape; Stooq closes are split/dividend
adjusted). Logs which source filled each ticker. Simulation only."""
import csv, io, json, os, time, urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')
PX = os.path.join(DATA, 'prices')
UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AtlasGateResearch'}
log = json.load(open(os.path.join(DATA, 'price_fetch_log.json')))
fails = [t for t, _ in log['fail']]
filled = {}

for t in fails:
    dst = os.path.join(PX, f'px_{t}.json')
    if os.path.exists(dst): filled[t] = 'already'; continue
    got = False
    for host in ('query1', 'query2'):
        url = (f'https://{host}.finance.yahoo.com/v8/finance/chart/{t}'
               f'?period1=1230768000&period2=1796000000&interval=1d&events=div,split')
        try:
            req = urllib.request.Request(url, headers=UA)
            raw = urllib.request.urlopen(req, timeout=40).read().decode('utf-8', 'ignore')
            d = json.loads(raw)
            if d.get('chart', {}).get('result'):
                open(dst, 'w').write(raw); filled[t] = f'yahoo-{host}'; got = True; break
        except Exception:
            pass
    if got: continue
    try:
        req = urllib.request.Request(f'https://stooq.com/q/d/l/?s={t.lower()}.us&i=d', headers=UA)
        txt = urllib.request.urlopen(req, timeout=40).read().decode('utf-8', 'ignore')
        rows = list(csv.DictReader(io.StringIO(txt)))
        ts, adj = [], []
        for r in rows:
            try:
                dt = datetime.strptime(r['Date'], '%Y-%m-%d').replace(tzinfo=timezone.utc)
                c = float(r['Close'])
            except Exception:
                continue
            ts.append(int(dt.timestamp())); adj.append(c)
        if len(ts) > 50:
            out = {'chart': {'result': [{'timestamp': ts, 'indicators': {
                'quote': [{'close': adj}], 'adjclose': [{'adjclose': adj}]}}]}}
            json.dump(out, open(dst, 'w')); filled[t] = f'stooq({len(ts)} bars)'
    except Exception as e:
        print('stooq fail', t, e)
    time.sleep(0.3)

print('filled:', filled)
still = [t for t in fails if t not in filled]
print('still missing:', still)
json.dump({'filled': filled, 'still_missing': still},
          open(os.path.join(DATA, 'price_fetch_log2.json'), 'w'), indent=1)
