#!/usr/bin/env python3
"""Fetch EDGAR companyfacts (1 call/CIK) for Stage-A CIKs missing any of the
3 needed concepts; extract concepts into concept_cache in companyconcept
format so build_pool.py runs fetch-free. 9 workers (EDGAR cap 10/s; the
binding constraint here is ~9s/call latency, not rate)."""
import json, os, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__))
FR = os.path.join(HERE, '..', '..', 'v11-native-rules', '_w04_broad_data', 'frames')
CACHE = os.path.join(HERE, 'concept_cache')
H = {'User-Agent': 'AtlasGate v12 research research@atlasgate.example'}
NAMES = [('us-gaap', 'AssetsCurrent'), ('us-gaap', 'Liabilities'),
         ('dei', 'EntityCommonStockSharesOutstanding')]

def load_frame(name):
    p = os.path.join(FR, name)
    if not os.path.exists(p): return {}
    return {int(k): v for k, v in json.load(open(p)).items()}

def stageA_ciks():
    s = set()
    for F in range(2016, 2026):
        ca = load_frame(f'AssetsCurrent_{F-1}I.json')
        li = load_frame(f'Liabilities_{F-1}I.json')
        s |= {c for c in set(ca) & set(li) if ca[c] - li[c] > 0}
    return sorted(s)

def missing(cik):
    return [n for _, n in NAMES if not os.path.exists(os.path.join(CACHE, f'{cik:010d}_{n}.json'))]

def fetch(cik):
    url = f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json'
    d = None
    for i in range(3):
        try:
            r = urllib.request.Request(url, headers=H)
            d = json.loads(urllib.request.urlopen(r, timeout=45).read())
            break
        except Exception:
            time.sleep(2 * (i + 1))
    if d is None:
        return cik  # write NOTHING on failure; a later pass retries
    facts = d.get('facts', {})
    for tax, name in NAMES:
        fn = os.path.join(CACHE, f'{cik:010d}_{name}.json')
        if os.path.exists(fn): continue
        sub = facts.get(tax, {}).get(name, {'units': {}})
        try:
            tmp = fn + f'.tmp{os.getpid()}'
            json.dump({'units': sub.get('units', {})}, open(tmp, 'w'))
            os.replace(tmp, fn)
        except Exception:
            pass  # contained: a later round retries whatever is missing
    return cik

def main():
    for rnd in range(3):
        ciks = [c for c in stageA_ciks() if missing(c)]
        print(f'round {rnd}: CIKs needing facts:', len(ciks), flush=True)
        if not ciks: break
        with ThreadPoolExecutor(max_workers=20) as ex:
            for i, _ in enumerate(ex.map(fetch, ciks)):
                if i % 250 == 0: print('done', i, flush=True)
    print('facts complete; still missing:', len([c for c in stageA_ciks() if missing(c)]), flush=True)

if __name__ == '__main__':
    main()
