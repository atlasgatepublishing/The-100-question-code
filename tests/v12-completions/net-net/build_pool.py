#!/usr/bin/env python3
"""v12 net-net Stage A+B pool builder (frozen per CONSTRUCTION-SPEC.md).
Stage A: EDGAR frames (read-only shared cache) NCAV>0 recall screen, all filers.
Stage B: per-CIK companyconcept as-filed verification (filed <= June 30 of F).
Writes pool.json + stageb_counts.json into this folder only. Simulation data only.
"""
import json, os, time, urllib.request, urllib.error
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
            time.sleep(1.5 * (i + 1))

TAX = {'AssetsCurrent': 'us-gaap', 'Liabilities': 'us-gaap',
       'EntityCommonStockSharesOutstanding': 'dei'}
NAMES = ['AssetsCurrent', 'Liabilities', 'EntityCommonStockSharesOutstanding']

def fetch_one(job):
    cik, name = job
    fn = os.path.join(CACHE, f'{cik:010d}_{name}.json')
    if os.path.exists(fn): return
    url = f'https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/{TAX[name]}/{name}.json'
    try:
        d = json.loads(get(url))
    except urllib.error.HTTPError as e:
        if e.code != 404: raise
        d = {'units': {}}
    except Exception:
        d = {'units': {}}
    json.dump(d, open(fn, 'w'))

def concept(cik, tax, name):
    fn = os.path.join(CACHE, f'{cik:010d}_{name}.json')
    if os.path.exists(fn):
        return json.load(open(fn))
    return {'units': {}}

def pick_asfiled(d, unit_keys, year, form_date):
    """Latest period-end in `year` among obs filed <= form_date; ties -> latest filed."""
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
    # Stage A
    stageA = {}
    all_ciks = set()
    for F in FORMATIONS:
        ca = load_frame(f'AssetsCurrent_{F-1}I.json')
        li = load_frame(f'Liabilities_{F-1}I.json')
        s = {cik for cik in set(ca) & set(li) if ca[cik] - li[cik] > 0}
        stageA[F] = s
        all_ciks |= s
    print('stageA unique CIKs', len(all_ciks), flush=True)
    # Stage B pulls (3 concepts per CIK, cached, 5 workers < EDGAR 10/s cap)
    from concurrent.futures import ThreadPoolExecutor
    jobs = [(cik, n) for cik in sorted(all_ciks) for n in NAMES]
    with ThreadPoolExecutor(max_workers=9) as ex:
        for i, _ in enumerate(ex.map(fetch_one, jobs)):
            if i % 1000 == 0: print('fetched', i, 'of', len(jobs), flush=True)
    concepts = {}
    for cik in sorted(all_ciks):
        concepts[cik] = {
            'ca': concept(cik, 'us-gaap', 'AssetsCurrent'),
            'li': concept(cik, 'us-gaap', 'Liabilities'),
            'sh': concept(cik, 'dei', 'EntityCommonStockSharesOutstanding'),
        }
    # split factors from frames shares series (v11 method)
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
            cc = concepts[cik]
            ca = pick_asfiled(cc['ca'], ['USD'], F - 1, form_date)
            li = pick_asfiled(cc['li'], ['USD'], F - 1, form_date)
            if ca is None or li is None or ca - li <= 0:
                c['asfiled_ncav_le0'] += 1; continue
            shv = pick_asfiled(cc['sh'], ['shares'], F - 1, form_date)
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
    print('saved pool.json', flush=True)

if __name__ == '__main__':
    main()
