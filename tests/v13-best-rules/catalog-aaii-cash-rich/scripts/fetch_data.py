#!/usr/bin/env python3
"""Fetch public SEC EDGAR data for the v13 cash-rich pond into this folder:
frames for Cash, ShortTermInvestments, Liabilities, LiabilitiesCurrent,
StockholdersEquity (instant CY{y}Q4I) and NetIncomeLoss (duration CY{y}),
years 2009..2025; plus SIC per CIK from data.sec.gov/submissions for every
CIK in the shareholder-yield stack's candidates.json (read-only input).
Public data only. Polite rate."""
import urllib.request, json, os, time, sys
H = {'User-Agent': 'AtlasGate v13 research research@atlasgate.example'}
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', 'data', 'frames')
os.makedirs(OUT, exist_ok=True)
SY = os.path.expanduser('~/workspace/stock-app/backtests/v12-completions/shareholder-yield/data')

def get(u, tries=3):
    for i in range(tries):
        try:
            r = urllib.request.Request(u, headers=H)
            return urllib.request.urlopen(r, timeout=90).read()
        except Exception:
            if i == tries - 1: raise
            time.sleep(2 * (i + 1))

def frame(concept, unit, per):
    u = f'https://data.sec.gov/api/xbrl/frames/us-gaap/{concept}/{unit}/{per}.json'
    d = json.loads(get(u))
    return {int(r['cik']): r['val'] for r in d['data']}

INSTANT = ['CashAndCashEquivalentsAtCarryingValue', 'ShortTermInvestments',
           'Liabilities', 'LiabilitiesCurrent', 'StockholdersEquity']
for c in INSTANT:
    for y in range(2009, 2026):
        p = os.path.join(OUT, f'{c}_{y}I.json')
        if os.path.exists(p): continue
        try: json.dump(frame(c, 'USD', f'CY{y}Q4I'), open(p, 'w'))
        except Exception as e: print('MISS', c, y, e, flush=True)
        time.sleep(0.12)
    print('instant done', c, flush=True)
for y in range(2009, 2026):
    p = os.path.join(OUT, f'NetIncomeLoss_{y}D.json')
    if os.path.exists(p): continue
    try: json.dump(frame('NetIncomeLoss', 'USD', f'CY{y}'), open(p, 'w'))
    except Exception as e: print('MISS NetIncomeLoss', y, e, flush=True)
    time.sleep(0.12)
print('duration done NetIncomeLoss', flush=True)

cand = {int(k): v for k, v in json.load(open(os.path.join(SY, 'candidates.json'))).items()}
sicp = os.path.join(HERE, '..', 'data', 'sic.json')
sic = json.load(open(sicp)) if os.path.exists(sicp) else {}
sic = {int(k): v for k, v in sic.items()}
todo = [c for c in cand if c not in sic]
print('sic todo', len(todo), flush=True)
import re
def get_sic(cik, tries=2):
    """SIC sits in the first bytes of the submissions JSON; stream only the
    head instead of downloading a filer's whole filing history."""
    u = f'https://data.sec.gov/submissions/CIK{cik:010d}.json'
    for i in range(tries):
        try:
            r = urllib.request.Request(u, headers=H)
            with urllib.request.urlopen(r, timeout=20) as resp:
                head = resp.read(16384).decode('utf-8', 'replace')
            m = re.search(r'"sic":\s*"?(\d{0,4})"?', head)
            return m.group(1) if m else ''
        except Exception:
            if i == tries - 1: raise
            time.sleep(2)

for i, cik in enumerate(todo):
    try:
        sic[cik] = get_sic(cik)
    except Exception:
        sic[cik] = ''
    if i % 200 == 0:
        json.dump(sic, open(sicp, 'w')); print('sic', i, flush=True)
    time.sleep(0.12)
json.dump(sic, open(sicp, 'w'))
print('sic done', len(sic), flush=True)
