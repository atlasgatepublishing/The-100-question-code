#!/usr/bin/env python3
"""Fetch quarterly RPO + Assets frames from SEC EDGAR frames API (public)."""
import urllib.request, json, os, time
H = {'User-Agent': 'AtlasGate v13 research research@atlasgate.example'}
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'frames')
os.makedirs(OUT, exist_ok=True)
quarters = [(2018, 4)] + [(y, q) for y in range(2019, 2027) for q in (1, 2, 3, 4) if not (y == 2026 and q == 4)] + []
quarters = [(2018, 4)] + [(y, q) for y in range(2019, 2026) for q in (1, 2, 3, 4)] + [(2026, q) for q in (1, 2, 3)]
for tag in ('RevenueRemainingPerformanceObligation', 'Assets'):
    for (y, q) in quarters:
        frame = f'CY{y}Q{q}I'
        p = os.path.join(OUT, f'{tag}_{frame}.json')
        if os.path.exists(p):
            continue
        u = f'https://data.sec.gov/api/xbrl/frames/us-gaap/{tag}/USD/{frame}.json'
        try:
            req = urllib.request.Request(u, headers=H)
            d = json.loads(urllib.request.urlopen(req, timeout=90).read())
            json.dump({int(r['cik']): r['val'] for r in d['data']}, open(p, 'w'))
            print(tag, frame, 'ok', len(d['data']), flush=True)
        except Exception as e:
            json.dump({}, open(p, 'w')); print(tag, frame, 'MISS', e, flush=True)
        time.sleep(0.12)
print('done')
