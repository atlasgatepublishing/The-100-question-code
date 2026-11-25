#!/usr/bin/env python3
"""Fetch EDGAR frames needed by the Intan rebuild into this family's
data/frames/. Instant: CY{y}Q4I. Duration: CY{y}. Years 2009..2025.
Mirrors the shareholder-yield fetch conventions. Free SEC API."""
import urllib.request, json, os, time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', 'data', 'frames')
os.makedirs(OUT, exist_ok=True)
H = {'User-Agent': 'AtlasGate research atlasgatepublishing@gmail.com'}

def frame(concept, per):
    u = f'https://data.sec.gov/api/xbrl/frames/us-gaap/{concept}/USD/{per}.json'
    r = urllib.request.Request(u, headers=H)
    raw = urllib.request.urlopen(r, timeout=90).read()
    d = json.loads(raw)
    return {row['cik']: row['val'] for row in d['data']}

def main():
    jobs = []
    for y in range(2009, 2026):
        jobs.append(('StockholdersEquity', f'CY{y}Q4I', f'StockholdersEquity_{y}I.json'))
        for c in ('NetIncomeLoss', 'DepreciationDepletionAndAmortization',
                  'Revenues', 'SalesRevenueNet',
                  'RevenueFromContractWithCustomerExcludingAssessedTax'):
            jobs.append((c, f'CY{y}', f'{c}_{y}D.json'))
    ok = miss = 0
    for concept, per, fn in jobs:
        p = os.path.join(OUT, fn)
        if os.path.exists(p):
            ok += 1; continue
        try:
            json.dump(frame(concept, per), open(p, 'w'))
            ok += 1
        except Exception as e:
            miss += 1
            print('MISS', concept, per, type(e).__name__)
        time.sleep(0.15)
    print(f'done ok={ok} miss={miss}')

if __name__ == '__main__':
    main()
