#!/usr/bin/env python3
"""Repair pass: re-fetch every missing/zero-byte/invalid concept file via
companyconcept (small payloads), with verified writes (tmp + fsync +
replace-with-retries + parse-verify). Prints progress to stdout (pipe)."""
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

def valid(fn):
    try:
        d = json.load(open(fn))
        return isinstance(d, dict) and 'units' in d
    except Exception:
        return False

def robust_write(fn, obj):
    data = json.dumps(obj)
    for attempt in range(10):
        try:
            tmp = fn + f'.rep{os.getpid()}'
            with open(tmp, 'w') as fh:
                fh.write(data); fh.flush(); os.fsync(fh.fileno())
            os.replace(tmp, fn)
            if valid(fn): return True
        except Exception:
            time.sleep(0.4 * (attempt + 1))
    return False

def fetch(job):
    cik, tax, name = job
    fn = os.path.join(CACHE, f'{cik:010d}_{name}.json')
    if valid(fn): return True
    url = f'https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/{tax}/{name}.json'
    d = None
    for i in range(4):
        try:
            r = urllib.request.Request(url, headers=H)
            d = json.loads(urllib.request.urlopen(r, timeout=45).read())
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                d = {'units': {}}
                break
            time.sleep(2 * (i + 1))
        except Exception:
            time.sleep(2 * (i + 1))
    if d is None: return False
    return robust_write(fn, {'units': d.get('units', {})})

def main():
    ciks = stageA_ciks()
    jobs = []
    for cik in ciks:
        for tax, name in NAMES:
            fn = os.path.join(CACHE, f'{cik:010d}_{name}.json')
            if not valid(fn):
                if os.path.exists(fn):
                    try: os.remove(fn)
                    except Exception: pass
                jobs.append((cik, tax, name))
    print('repair jobs:', len(jobs), flush=True)
    ok = 0
    with ThreadPoolExecutor(max_workers=12) as ex:
        for i, r in enumerate(ex.map(fetch, jobs)):
            ok += 1 if r else 0
            if i % 500 == 0: print('done', i, 'ok', ok, flush=True)
    left = sum(1 for cik in ciks for _, name in NAMES
               if not valid(os.path.join(CACHE, f'{cik:010d}_{name}.json')))
    print('repair pass complete. ok', ok, 'still invalid:', left, flush=True)

if __name__ == '__main__':
    main()
