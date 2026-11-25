#!/usr/bin/env python3
"""Fetch as-filed PIT fundamentals from SEC EDGAR companyconcept API for the
W04 candidate CIKs (read-only input: candidates.json in the v11 W04 folder).
Per CIK, compact output: for each concept, list of (filed, end, start_or_None, val)
tuples, USD units only. Written only inside this v12 folder."""
import urllib.request, json, os, time, sys
H = {'User-Agent': 'AtlasGate v12 research research@atlasgate.example'}
HERE = os.path.dirname(os.path.abspath(__file__))
W04 = os.path.join(HERE, '..', '..', 'v11-native-rules', '_w04_broad_data')
OUT = os.path.join(HERE, 'data', 'facts')
os.makedirs(OUT, exist_ok=True)
CONCEPTS = [
    ('us-gaap', 'StockholdersEquity'),
    ('us-gaap', 'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest'),
    ('us-gaap', 'NetIncomeLoss'),
    ('us-gaap', 'NetCashProvidedByUsedInOperatingActivities'),
    ('dei', 'EntityCommonStockSharesOutstanding'),
    ('us-gaap', 'CommonStockSharesOutstanding'),
]
def get(u, tries=3):
    for i in range(tries):
        try:
            r = urllib.request.Request(u, headers=H)
            return json.loads(urllib.request.urlopen(r, timeout=60).read())
        except Exception:
            if i == tries - 1: raise
            time.sleep(2 * (i + 1))
def fetch_one(cik):
    p = os.path.join(OUT, f'{cik:010d}.json')
    if os.path.exists(p): return 'skip'
    rec = {}
    for tax, con in CONCEPTS:
        u = f'https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/{tax}/{con}.json'
        try:
            d = get(u)
        except Exception:
            continue
        units = d.get('units', {})
        rows = []
        for unit, arr in units.items():
            if unit not in ('USD', 'shares', 'USD/shares'): continue
            for e in arr:
                rows.append([e.get('filed'), e.get('end'), e.get('start'), e.get('val'), e.get('form')])
        if rows: rec[f'{tax}:{con}'] = rows
    json.dump(rec, open(p, 'w'))
    return 'ok'

def main():
    from concurrent.futures import ThreadPoolExecutor
    cand = json.load(open(os.path.join(W04, 'candidates.json')))
    ciks = sorted(int(k) for k in cand)
    done = 0
    with ThreadPoolExecutor(max_workers=6) as ex:
        for r in ex.map(fetch_one, ciks):
            done += 1
            if done % 50 == 0: print('progress', done, flush=True)
    print('DONE', done, flush=True)
if __name__ == '__main__':
    main()
