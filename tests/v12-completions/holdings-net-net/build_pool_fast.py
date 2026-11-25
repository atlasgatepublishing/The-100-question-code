#!/usr/bin/env python3
"""Holdings-sweep replica of the v12 net-net frozen pool builder
(CONSTRUCTION-SPEC.md in ../net-net/). IDENTICAL logic to the canonical
build_pool.py (Stage A frames recall screen -> Stage B as-filed verification,
filed <= June 30 of F; split factor SF from frames shares series; pool iff
p* = (2/3 NCAV)/(shares*SF) >= $0.25). Only difference: concept pulls are
concurrent (8 workers, SEC fair-access) and the cache lives in THIS folder.
Writes pool.json + stageb_counts.json here only. Simulation data only.
"""
import json, os, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__))
FR = os.path.join(HERE, '..', '..', 'v11-native-rules', '_w04_broad_data', 'frames')
CACHE = os.path.join(HERE, 'concept_cache')
os.makedirs(CACHE, exist_ok=True)
H = {'User-Agent': 'AtlasGate v12 research research@atlasgate.example'}
FORMATIONS = list(range(2016, 2026))

def load_frame(name):
    p = os.path.join(FR, name)
    if not os.path.exists(p): return {}
    return {int(k): v for k, v in json.load(open(p)).items()}

def get(url, tries=3):
    for i in range(tries):
        try:
            r = urllib.request.Request(url, headers=H)
            return urllib.request.urlopen(r, timeout=60).read()
        except Exception as e:
            if i == tries - 1: raise
            time.sleep(1.0 * (i + 1))

def concept(args):
    cik, tax, name = args
    fn = os.path.join(CACHE, f'{cik:010d}_{name}.json')
    if os.path.exists(fn):
        return
    url = f'https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/{tax}/{name}.json'
    try:
        raw = get(url)
        d = json.loads(raw)
    except urllib.error.HTTPError as e:
        d = {'units': {}} if e.code == 404 else {'units': {}}
    except Exception:
        d = {'units': {}}
    try:
        tmp = fn + f'.tmp{os.getpid()}'
        json.dump(d, open(tmp, 'w'))
        os.replace(tmp, fn)
    except Exception:
        pass  # a failed cache write just means a later re-pull / empty concept
    time.sleep(0.05)

def load_concept(cik, name):
    fn = os.path.join(CACHE, f'{cik:010d}_{name}.json')
    if not os.path.exists(fn): return {'units': {}}
    try:
        return json.load(open(fn))
    except Exception:
        return {'units': {}}

def pick_asfiled(d, unit_keys, year, form_date):
    best = null = None
    best = None
    for uk in unit_keys:
        for r in d.get('units', {}).get(uk, []):
            end = r.get('end', '')
            if not end.startswith(str(year)): continue
            if r.get('filed', '9999') > form_date: continue
            key = (end, r.get('filed', ''))
            if best is None or key > best[0]:
                best = (key, r['val'])
    return best[1] if best else None

def main():
    stageA = {}
    all_ciks = set()
    for F in FORMATIONS:
        ca = load_frame(f'AssetsCurrent_{F-1}I.json')
        li = load_frame(f'Liabilities_{F-1}I.json')
        s = {cik for cik in set(ca) & set(li) if ca[cik] - li[cik] > 0}
        stageA[F] = s
        all_ciks |= s
    print('stageA unique CIKs', len(all_ciks), flush=True)
    jobs = []
    for cik in sorted(all_ciks):
        jobs.append((cik, 'us-gaap', 'AssetsCurrent'))
        jobs.append((cik, 'us-gaap', 'Liabilities'))
        jobs.append((cik, 'dei', 'EntityCommonStockSharesOutstanding'))
    with ThreadPoolExecutor(max_workers=24) as ex:
        for i, _ in enumerate(ex.map(concept, jobs)):
            if i % 2000 == 0: print('pulled', i, '/', len(jobs), flush=True)
    print('pulls done', flush=True)
    sh_series = {y: load_frame(f'Shares_{y}I.json') for y in range(2014, 2026)}
    def sf(cik, F):
        avail = [(y, sh_series[y][cik]) for y in range(2014, 2026) if sh_series[y].get(cik)]
        f = 1.0
        for (y0, a), (y1, b) in zip(avail, avail[1:]):
            if y1 >= F:
                r = b / a
                if r >= 1.6 or r <= 0.625: f *= r
        return f
    pool = {}
    counts = {}
    for F in FORMATIONS:
        form_date = f'{F}-06-30'
        rows = []
        c = {'stageA': len(stageA[F]), 'asfiled_ncav_le0': 0, 'no_shares': 0, 'pstar_lt_025': 0, 'in_pool': 0}
        for cik in stageA[F]:
            ca = pick_asfiled(load_concept(cik, 'AssetsCurrent'), ['USD'], F - 1, form_date)
            li = pick_asfiled(load_concept(cik, 'Liabilities'), ['USD'], F - 1, form_date)
            if ca is None or li is None or ca - li <= 0:
                c['asfiled_ncav_le0'] += 1; continue
            shv = pick_asfiled(load_concept(cik, 'EntityCommonStockSharesOutstanding'), ['shares'], F - 1, form_date)
            if not shv:
                c['no_shares'] += 1; continue
            ncav = ca - li
            sff = sf(cik, F)
            pstar = (2.0 / 3.0 * ncav) / (shv * sff)
            if pstar < 0.25:
                c['pstar_lt_025'] += 1; continue
            rows.append({'cik': cik, 'ncav': round(ncav), 'shares': shv, 'sf': sff, 'pstar': round(pstar, 4)})
            c['in_pool'] += 1
        pool[F] = rows
        counts[F] = c
        print(F, c, flush=True)
    json.dump({'pool': pool, 'counts': counts}, open(os.path.join(HERE, 'pool.json'), 'w'), indent=1)
    json.dump(counts, open(os.path.join(HERE, 'stageb_counts.json'), 'w'), indent=1)
    print('saved pool.json', flush=True)

if __name__ == '__main__':
    main()
