#!/usr/bin/env python3
"""Yahoo monthly bars (adjclose + raw close) 2016-01..2026-12 for candidate
tickers + SPY. Delisted tickers Yahoo no longer serves fail and are recorded
in price_failures.json (counted, never patched)."""
import urllib.request, urllib.parse, json, os, time, datetime
HERE = os.path.dirname(os.path.abspath(__file__))
UA = {'User-Agent': 'Mozilla/5.0'}
def fetch(t):
    u = 'https://query1.finance.yahoo.com/v8/finance/chart/%s?period1=1451606400&period2=1796000000&interval=1mo&events=div,split' % urllib.parse.quote(t)
    r = urllib.request.Request(u, headers=UA)
    d = json.loads(urllib.request.urlopen(r, timeout=60).read())
    res = d['chart']['result'][0]
    ts = res['timestamp']; adj = res['indicators']['adjclose'][0]['adjclose']; close = res['indicators']['quote'][0]['close']
    out = []
    for i, t_ in enumerate(ts):
        if adj[i] is None: continue
        out.append([datetime.datetime.utcfromtimestamp(t_).strftime('%Y-%m'), adj[i], close[i]])
    return out
def main():
    cand = json.load(open(os.path.join(HERE, 'candidates.json')))
    ticks = sorted({v['ticker'] for v in cand.values()}) + ['SPY']
    fails = []
    for i, t in enumerate(ticks):
        p = os.path.join(HERE, 'px_%s.json' % t.replace('/', '-'))
        if os.path.exists(p): continue
        try:
            rows = fetch(t)
            if len(rows) < 6: raise ValueError('too few bars')
            json.dump(rows, open(p, 'w'))
        except Exception as e:
            fails.append({'ticker': t, 'error': str(e)})
        if i % 50 == 0: print(i, t, flush=True)
        time.sleep(0.2)
    json.dump(fails, open(os.path.join(HERE, 'price_failures.json'), 'w'), indent=1)
    print('failures', len(fails), flush=True)
if __name__ == '__main__': main()
