#!/usr/bin/env python3
"""Fetch Yahoo monthly bars (adjclose + raw close) 2010-01..2026-12 for the
shareholder-yield candidate tickers + SPY into THIS folder's data/sy_px/.
Same method as the canonical family's fetch_prices.py (read-only source);
the canonical fetch was incomplete (~88/1559) when this sweep started, so
the sweep keeps its own copy. Existing canonical px files are copied first
(identical format) to avoid re-hitting Yahoo."""
import urllib.request, urllib.parse, json, os, time, datetime, shutil
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', 'data', 'sy_px'); os.makedirs(OUT, exist_ok=True)
CANON = os.path.expanduser('~/workspace/stock-app/backtests/v12-completions/shareholder-yield/data')
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
        out.append([datetime.datetime.fromtimestamp(t_, datetime.UTC).strftime('%Y-%m'), adj[i], close[i]])
    return out

def main():
    cand = json.load(open(os.path.join(CANON, 'candidates.json')))
    ticks = sorted({v['ticker'] for v in cand.values()}) + ['SPY']
    fails = []; done = 0; copied = 0
    for i, t in enumerate(ticks):
        p = os.path.join(OUT, 'px_%s.json' % t.replace('/', '-'))
        if os.path.exists(p): continue
        cp = os.path.join(CANON, 'px_%s.json' % t.replace('/', '-'))
        if os.path.exists(cp):
            ok = False
            for attempt in range(6):
                try:
                    shutil.copyfile(cp, p); ok = True; break
                except OSError:
                    time.sleep(3)
            if ok:
                copied += 1; continue
            print('copy failed, will fetch', t, flush=True)
        try:
            rows = fetch(t)
            if len(rows) < 6: raise ValueError('too few bars')
            json.dump(rows, open(p, 'w')); done += 1
        except Exception as e:
            fails.append({'ticker': t, 'error': str(e)})
        if i % 100 == 0: print(i, t, 'fetched', done, 'copied', copied, 'fails', len(fails), flush=True)
        time.sleep(0.15)
    json.dump(fails, open(os.path.join(OUT, 'price_failures.json'), 'w'), indent=1)
    print('DONE fetched', done, 'copied', copied, 'failures', len(fails), flush=True)

if __name__ == '__main__':
    main()
