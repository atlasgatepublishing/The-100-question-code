#!/usr/bin/env python3
"""Dividend events + raw daily close for every Aristocrat tape ticker.
Source order: v7 long-hold pxfull payloads (read-only) -> fresh Yahoo pull.
Writes data/dg_div/<T>.json = {"raw":[[date,close]...], "divs":[[date,amt]...], "src":...}
Tape ticker = successor-mapped per canonical rosters.py SUCCESSOR."""
import json, os, sys, time, urllib.request, calendar
sys.path.insert(0, os.path.expanduser('~/workspace/stock-app/backtests/v12-completions/dividend-growth'))
from rosters import ROSTERS, SUCCESSOR
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', 'data', 'dg_div'); os.makedirs(OUT, exist_ok=True)
V7 = os.path.expanduser('~/workspace/stock-app/backtests/v7/long-hold/data')

def from_payload(payload):
    res = payload['chart']['result'][0]
    ts = res['timestamp']; q = res['indicators']['quote'][0]
    raw = []
    for i, t in enumerate(ts):
        c = q['close'][i]
        if c is None: continue
        raw.append([time.strftime('%Y-%m-%d', time.gmtime(t)), round(float(c), 4)])
    divs = []
    ev = (res.get('events') or {}).get('dividends') or {}
    for k, v in ev.items():
        divs.append([time.strftime('%Y-%m-%d', time.gmtime(v['date'])), float(v['amount'])])
    return sorted(raw), sorted(divs)

def main():
    tapes = sorted({SUCCESSOR.get(t, t) for v in ROSTERS.values() for t in v} | {'SPY'})
    report = {}
    for t in tapes:
        p = os.path.join(OUT, f'{t}.json')
        if os.path.exists(p):
            report[t] = 'cached'; continue
        got = None
        vp = os.path.join(V7, f'pxfull_{t}.json')
        if os.path.exists(vp) and os.path.getsize(vp) > 100:
            try:
                raw, divs = from_payload(json.load(open(vp)))
                if len(raw) > 50: got = (raw, divs, 'v7cache')
            except Exception as e:
                print(t, 'v7 fail', e, flush=True)
        if got is None:
            try:
                t1 = calendar.timegm(time.strptime('2007-01-01', '%Y-%m-%d'))
                t2 = calendar.timegm(time.strptime('2026-11-22', '%Y-%m-%d'))
                url = f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(t)}?period1={t1}&period2={t2}&interval=1d&events=div,split'
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=60) as r:
                    raw, divs = from_payload(json.loads(r.read()))
                if len(raw) > 50: got = (raw, divs, 'yahoo')
            except Exception as e:
                print(t, 'yahoo fail', e, flush=True)
        if got is None:
            report[t] = 'FAILED'; continue
        raw, divs, src = got
        json.dump({'raw': raw, 'divs': divs, 'src': src}, open(p, 'w'))
        report[t] = f'{src} raw={len(raw)} divs={len(divs)}'
        print(t, report[t], flush=True)
    json.dump(report, open(os.path.join(OUT, 'report.json'), 'w'), indent=1)
    print('DONE', sum(1 for v in report.values() if v != 'FAILED'), '/', len(report), flush=True)

if __name__ == '__main__':
    import urllib.parse
    main()
