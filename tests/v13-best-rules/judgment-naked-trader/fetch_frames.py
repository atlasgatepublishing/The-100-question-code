#!/usr/bin/env python3
"""Fetch the EDGAR frames the amended stack still lacks, into ./frames/.
Public SEC data only. Existing program frames (w04 2014-2025, shareholder-
yield 2009-2025) are read in place; this fills 2009-2013 for the flow/cash
concepts and attempts the per-share dividend frame for all years."""
import urllib.request, json, os, time
H = {'User-Agent': 'AtlasGate v13 research research@atlasgate.example'}
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'frames')
os.makedirs(OUT, exist_ok=True)

def get(u, tries=3):
    for i in range(tries):
        try:
            r = urllib.request.Request(u, headers=H)
            return urllib.request.urlopen(r, timeout=90).read()
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))

def frame(tax, concept, unit, per):
    u = f'https://data.sec.gov/api/xbrl/frames/{tax}/{concept}/{unit}/{per}.json'
    d = json.loads(get(u))
    return {int(r['cik']): r['val'] for r in d['data']}

DURATION = ['Revenues', 'SalesRevenueNet',
            'RevenueFromContractWithCustomerExcludingAssessedTax',
            'NetIncomeLoss', 'OperatingIncomeLoss']
INSTANT = ['CashAndCashEquivalentsAtCarryingValue']
YEARS_BACKFILL = list(range(2009, 2014))

def main():
    for c in DURATION:
        for y in YEARS_BACKFILL:
            p = os.path.join(OUT, f'{c}_{y}D.json')
            if os.path.exists(p):
                continue
            try:
                json.dump(frame('us-gaap', c, 'USD', f'CY{y}'), open(p, 'w'))
            except Exception as e:
                print('MISS', c, y, e, flush=True)
            time.sleep(0.12)
        print('duration done', c, flush=True)
    for c in INSTANT:
        for y in YEARS_BACKFILL:
            p = os.path.join(OUT, f'{c}_{y}I.json')
            if os.path.exists(p):
                continue
            try:
                json.dump(frame('us-gaap', c, 'USD', f'CY{y}Q4I'), open(p, 'w'))
            except Exception as e:
                print('MISS', c, y, e, flush=True)
            time.sleep(0.12)
        print('instant done', c, flush=True)
    # DPS per share attempt, all years (Amendment 1 conditional)
    ok = 0
    for y in range(2009, 2026):
        p = os.path.join(OUT, f'DPS_{y}D.json')
        if os.path.exists(p):
            ok += 1
            continue
        try:
            json.dump(frame('us-gaap', 'CommonStockDividendsPerShareCashPaid',
                            'USD/shares', f'CY{y}'), open(p, 'w'))
            ok += 1
        except Exception as e:
            print('MISS DPS', y, e, flush=True)
        time.sleep(0.12)
    print('DPS years fetched:', ok, flush=True)
    print('ALL DONE', flush=True)

if __name__ == '__main__':
    main()
