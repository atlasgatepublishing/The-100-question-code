#!/usr/bin/env python3
"""Yahoo monthly bars (adjclose + raw close) 2010-01..2026-12 for candidate
tickers + SPY. Failures recorded in price_failures.json (counted fence #2,
never patched)."""
import urllib.request, urllib.parse, json, os, time, datetime
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')
UA = {'User-Agent': 'Mozilla/5.0'}

def fetch(t):
    u = 'https://query1.finance.yahoo.com/v8/finance/chart/%s?period1=1262304000&period2=1796000000&interval=1mo&events=div,split' % urllib.parse.quote(t)
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
    cand = json.load(open(os.path.join(DATA, 'candidates.json')))
    ticks = sorted({v['ticker'] for v in cand.values()}) + ['SPY']
    fails = []
    done = 0
    for i, t in enumerate(ticks):
        p = os.path.join(DATA, 'px_%s.json' % t.replace('/', '-'))
        if os.path.exists(p): continue
        try:
            rows = fetch(t)
            if len(rows) < 6: raise ValueError('too few bars')
            json.dump(rows, open(p, 'w')); done += 1
        except Exception as e:
            fails.append({'ticker': t, 'error': str(e)})
        if i % 100 == 0: print(i, t, 'fetched so far', done, flush=True)
        time.sleep(0.15)
    json.dump(fails, open(os.path.join(DATA, 'price_failures.json'), 'w'), indent=1)
    print('DONE fetched', done, 'failures', len(fails), flush=True)

if __name__ == '__main__':
    main()
