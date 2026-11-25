#!/usr/bin/env python3
"""Single-threaded refetch of missing tickers; writes via temp file +
os.replace so a killed/denied run never leaves a half file. Retries each
write up to 5 times (workspace writes are intermittently denied)."""
import urllib.request, urllib.parse, json, os, time, datetime
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')
UA = {'User-Agent': 'Mozilla/5.0'}

def fetch(t):
    u = 'https://query1.finance.yahoo.com/v8/finance/chart/%s?period1=1262304000&period2=1796000000&interval=1mo&events=div,split' % urllib.parse.quote(t)
    r = urllib.request.Request(u, headers=UA)
    d = json.loads(urllib.request.urlopen(r, timeout=15).read())
    res = d['chart']['result'][0]
    ts = res['timestamp']; adj = res['indicators']['adjclose'][0]['adjclose']; close = res['indicators']['quote'][0]['close']
    out = []
    for i, t_ in enumerate(ts):
        if adj[i] is None: continue
        out.append([datetime.datetime.fromtimestamp(t_, datetime.UTC).strftime('%Y-%m'), adj[i], close[i]])
    return out

def main():
    cand = json.load(open(os.path.join(DATA, 'candidates.json')))
    ticks = sorted({v['ticker'] for v in cand.values()}) + ['SPY']
    todo = [t for t in ticks if not os.path.exists(os.path.join(DATA, 'px_%s.json' % t.replace('/', '-')))]
    todo.reverse()  # live names (Z->A) first; dead/odd tickers hang longest and sort first A->Z
    print('todo', len(todo), flush=True)
    fails = []
    for i, t in enumerate(todo):
        p = os.path.join(DATA, 'px_%s.json' % t.replace('/', '-'))
        try:
            rows = fetch(t)
            if len(rows) < 6: raise ValueError('too few bars')
            tmp = p + '.tmp'
            for attempt in range(5):
                try:
                    with open(tmp, 'w') as fh: json.dump(rows, fh)
                    os.replace(tmp, p); break
                except PermissionError:
                    time.sleep(3 * (attempt + 1))
            else:
                raise PermissionError('write denied after retries')
        except Exception as e:
            fails.append({'ticker': t, 'error': str(e)})
        if i % 50 == 0: print(i, t, 'fails', len(fails), flush=True)
        time.sleep(0.1)
    print('DONE fails', len(fails), [f['ticker'] for f in fails], flush=True)

if __name__ == '__main__':
    main()
