#!/usr/bin/env python3
"""Fetch EDGAR frames 2009-2013 for the concepts W04 (2014-2025) lacks,
into ./data/frames using the exact W04 file convention.
Concepts: Revenues/SalesRevenueNet/RevContract (D), OperatingIncomeLoss (D),
Assets (I), Liabilities (I). NetIncomeLoss (D) and Shares (I) 2009-2013 are
copied from the v13 weiss folder (same convention, already fetched)."""
import urllib.request, json, os, shutil, time
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', 'data', 'frames')
os.makedirs(OUT, exist_ok=True)
H = {'User-Agent': 'AtlasGateResearch terry@example.com'}
def frame(tax, concept, unit, per):
    u = f'https://data.sec.gov/api/xbrl/frames/{tax}/{concept}/{unit}/{per}.json'
    r = urllib.request.Request(u, headers=H)
    raw = urllib.request.urlopen(r, timeout=90).read()
    d = json.loads(raw)
    return {row['cik']: row['val'] for row in d['data']}
jobs = []
for y in range(2009, 2014):
    for c in ['Revenues', 'SalesRevenueNet', 'RevenueFromContractWithCustomerExcludingAssessedTax', 'OperatingIncomeLoss']:
        jobs.append((c, y, 'D', f'CY{y}'))
    for c in ['Assets', 'Liabilities']:
        jobs.append((c, y, 'I', f'CY{y}Q4I'))
for c, y, kind, per in jobs:
    p = os.path.join(OUT, f'{c}_{y}{kind}.json')
    if os.path.exists(p):
        print('skip', p, flush=True); continue
    try:
        json.dump(frame('us-gaap', c, 'USD', per), open(p, 'w'))
        print('ok', c, y, kind, flush=True)
    except Exception as e:
        print('FAIL', c, y, kind, e, flush=True)
    time.sleep(0.15)
# copy NetIncomeLoss + Shares 2009-2013 from weiss v13 (identical convention)
SRC = '/home/hatch/workspace/stock-app/backtests/v13-best-rules/catalog-aaii-weiss-blue-chip-yield/data/frames'
for y in range(2009, 2014):
    for name in [f'NetIncomeLoss_{y}D.json', f'Shares_{y}I.json']:
        s = os.path.join(SRC, name); d = os.path.join(OUT, name)
        if os.path.exists(s) and not os.path.exists(d):
            shutil.copy(s, d); print('copied', name, flush=True)
print('done', flush=True)
