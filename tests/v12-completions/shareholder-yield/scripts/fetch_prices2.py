#!/usr/bin/env python3
"""Threaded resume of fetch_prices.py (the sequential pass stalled on
hanging requests). 4 workers, 25s timeout, skips files already present.
Aborts if HTTP 429 dominates (provider hard stop). Failures appended to
price_failures.json."""
import urllib.request, urllib.parse, json, os, time, datetime, threading
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')
UA = {'User-Agent': 'Mozilla/5.0'}
lock = threading.Lock()
stats = {'done': 0, 'fail': 0, 'r429': 0, 'seen': 0}
fails = []

def fetch(t):
    u = 'https://query1.finance.yahoo.com/v8/finance/chart/%s?period1=1262304000&period2=1796000000&interval=1mo&events=div,split' % urllib.parse.quote(t)
    r = urllib.request.Request(u, headers=UA)
    d = json.loads(urllib.request.urlopen(r, timeout=25).read())
    res = d['chart']['result'][0]
    ts = res['timestamp']; adj = res['indicators']['adjclose'][0]['adjclose']; close = res['indicators']['quote'][0]['close']
    out = []
    for i, t_ in enumerate(ts):
        if adj[i] is None: continue
        out.append([datetime.datetime.fromtimestamp(t_, datetime.UTC).strftime('%Y-%m'), adj[i], close[i]])
    return out

def work(t):
    p = os.path.join(DATA, 'px_%s.json' % t.replace('/', '-'))
    if os.path.exists(p): return
    try:
        rows = fetch(t)
        if len(rows) < 6: raise ValueError('too few bars')
        json.dump(rows, open(p, 'w'))
        with lock: stats['done'] += 1
    except Exception as e:
        with lock:
            stats['fail'] += 1
            if '429' in str(e): stats['r429'] += 1
            fails.append({'ticker': t, 'error': str(e)})
    with lock:
        stats['seen'] += 1
        if stats['seen'] % 100 == 0:
            print('seen', stats['seen'], 'done', stats['done'], 'fail', stats['fail'], '429', stats['r429'], flush=True)

def main():
    cand = json.load(open(os.path.join(DATA, 'candidates.json')))
    ticks = sorted({v['ticker'] for v in cand.values()}) + ['SPY']
    todo = [t for t in ticks if not os.path.exists(os.path.join(DATA, 'px_%s.json' % t.replace('/', '-')))]
    print('todo', len(todo), flush=True)
    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(work, todo))
    old = []
    pf = os.path.join(DATA, 'price_failures.json')
    if os.path.exists(pf): old = json.load(open(pf))
    json.dump(old + fails, open(pf, 'w'), indent=1)
    print('DONE', stats, flush=True)

if __name__ == '__main__':
    main()
