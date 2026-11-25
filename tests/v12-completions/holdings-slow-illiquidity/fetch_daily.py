#!/usr/bin/env python3
"""Holdings-sweep data fill: Yahoo daily bars 2015-01-01..2026-12-31 for the
EDGAR/broad candidate tickers + SPY, into THIS folder's data/ (skips files
already copied from the sibling v12 slow-illiquidity folder, read-only source).
Delisted tickers Yahoo no longer serves fail and are recorded, never patched."""
import urllib.request, urllib.parse, json, os, time, datetime
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = '/home/hatch/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data/candidates.json'
OUT = os.path.join(HERE, 'data')
os.makedirs(OUT, exist_ok=True)
UA = {'User-Agent': 'Mozilla/5.0'}
P1, P2 = 1420070400, 1798761600

def fetch(t):
    u = ('https://query1.finance.yahoo.com/v8/finance/chart/%s?period1=%d&period2=%d'
         '&interval=1d&events=div,split') % (urllib.parse.quote(t), P1, P2)
    d = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60).read())
    res = d['chart']['result'][0]
    ts = res['timestamp']; q = res['indicators']['quote'][0]
    adj = res['indicators']['adjclose'][0]['adjclose']
    out = []
    for i, t_ in enumerate(ts):
        if adj[i] is None or q['close'][i] is None:
            continue
        out.append([datetime.datetime.fromtimestamp(t_, datetime.UTC).strftime('%Y-%m-%d'),
                    q['open'][i], q['high'][i], q['low'][i], q['close'][i], adj[i],
                    q['volume'][i] or 0])
    return out

def main():
    cand = json.load(open(SRC))
    ticks = sorted({v['ticker'] for v in cand.values()}) + ['SPY']
    fails = []
    for i, t in enumerate(ticks):
        p = os.path.join(OUT, 'px_%s.json' % t.replace('/', '-'))
        if os.path.exists(p):
            continue
        try:
            rows = fetch(t)
            if len(rows) < 30:
                raise ValueError('too few bars: %d' % len(rows))
            json.dump(rows, open(p, 'w'))
        except Exception as e:
            fails.append({'ticker': t, 'error': str(e)[:120]})
        if i % 50 == 0:
            print(i, t, flush=True)
        time.sleep(0.15)
    json.dump(fails, open(os.path.join(HERE, 'fetch_failures.json'), 'w'), indent=1)
    print('DONE failures', len(fails), flush=True)

if __name__ == '__main__':
    main()
