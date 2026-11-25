#!/usr/bin/env python3
"""Fetch EDGAR frames needed by the shareholder-yield construction into
this family's data/frames/. Instant concepts: CY{y}Q4I. Duration (flows):
CY{y}. Years 2009..2025. Read-only toward everything else."""
import urllib.request, json, os, time
H = {'User-Agent': 'AtlasGate v12 research research@atlasgate.example'}
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', 'data', 'frames')
os.makedirs(OUT, exist_ok=True)

def get(u, tries=3):
    for i in range(tries):
        try:
            r = urllib.request.Request(u, headers=H)
            return urllib.request.urlopen(r, timeout=90).read()
        except Exception:
            if i == tries - 1: raise
            time.sleep(2 * (i + 1))

INSTANT = ['Assets', 'LongTermDebtCurrent', 'DebtCurrent',
           'LongTermDebtNoncurrent', 'LongTermDebt']
DURATION = ['PaymentsOfDividendsCommonStock', 'PaymentsOfDividends',
            'PaymentsForRepurchaseOfCommonStock',
            'ProceedsFromIssuanceOfCommonStock']
YEARS = list(range(2009, 2026))

def frame(tax, concept, unit, per):
    u = f'https://data.sec.gov/api/xbrl/frames/{tax}/{concept}/{unit}/{per}.json'
    d = json.loads(get(u))
    return {int(r['cik']): r['val'] for r in d['data']}

def main():
    for c in INSTANT:
        for y in YEARS:
            p = os.path.join(OUT, f'{c}_{y}I.json')
            if os.path.exists(p): continue
            try: json.dump(frame('us-gaap', c, 'USD', f'CY{y}Q4I'), open(p, 'w'))
            except Exception as e: print('MISS', c, y, e, flush=True)
            time.sleep(0.12)
        print('instant done', c, flush=True)
    for c in DURATION:
        for y in YEARS:
            p = os.path.join(OUT, f'{c}_{y}D.json')
            if os.path.exists(p): continue
            try: json.dump(frame('us-gaap', c, 'USD', f'CY{y}'), open(p, 'w'))
            except Exception as e: print('MISS', c, y, e, flush=True)
            time.sleep(0.12)
        print('duration done', c, flush=True)
    for y in YEARS:
        p = os.path.join(OUT, f'Shares_{y}I.json')
        if os.path.exists(p): continue
        try: json.dump(frame('dei', 'EntityCommonStockSharesOutstanding', 'shares', f'CY{y}Q4I'), open(p, 'w'))
        except Exception as e: print('MISS Shares', y, e, flush=True)
        time.sleep(0.12)
    print('shares done', flush=True)
    # current CIK->ticker mapping snapshot
    p = os.path.join(HERE, '..', 'data', 'company_tickers_exchange.json')
    if not os.path.exists(p):
        open(p, 'wb').write(get('https://www.sec.gov/files/company_tickers_exchange.json'))
    print('ALL DONE', flush=True)

if __name__ == '__main__':
    main()
