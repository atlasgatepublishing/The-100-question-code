#!/usr/bin/env python3
"""Fresh v13 buildability check for employee-count data (spec section 10 gate).
Checks (public EDGAR only, throttled):
 1. frames API for us-gaap and dei EntityNumberOfEmployees (several years)
 2. companyfacts for a sample of W04 candidates: any concept key containing 'mploy'
    in any taxonomy, with observation counts / forms / filed dates.
Writes hunt_result.json beside this script's folder. Simulation/data-check only.
"""
import json, os, time, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
FAM = os.path.join(HERE, '..')
W04 = os.path.join(FAM, '..', '..', 'v11-native-rules', '_w04_broad_data')
UA = {'User-Agent': 'AtlasGate research contact@example.com', 'Accept': 'application/json'}

def get(url):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode('utf-8', 'replace'))
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:
        return str(e), None

out = {'frames': {}, 'companyfacts_sample': {}}

for tax in ('us-gaap', 'dei'):
    for yr in (2016, 2020, 2024):
        url = f'https://data.sec.gov/api/xbrl/frames/{tax}/EntityNumberOfEmployees/USD/CY{yr}.json'
        st, _ = get(url)
        out['frames'][f'{tax}/CY{yr}'] = st
        time.sleep(0.15)

cand = {int(k): v for k, v in json.load(open(os.path.join(W04, 'candidates.json'))).items()}
# deterministic sample: 40 largest-by-2024-assets candidates (candidates.json 'years' is assets)
ranked = sorted(cand.items(), key=lambda kv: -(kv[1].get('years', {}).get('2024') or 0))[:40]
hits = 0
for cik, info in ranked:
    url = f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json'
    st, data = get(url)
    found = {}
    if data and 'facts' in data:
        for tax, concepts in data['facts'].items():
            for name, payload in concepts.items():
                if 'mploy' in name.lower():
                    units = payload.get('units', {})
                    n = sum(len(v) for v in units.values())
                    forms = sorted({o.get('form') for v in units.values() for o in v})
                    found[f'{tax}:{name}'] = {'obs': n, 'forms': forms[:6]}
    if found:
        hits += 1
    out['companyfacts_sample'][info['ticker']] = {'cik': cik, 'status': st, 'employee_concepts': found}
    time.sleep(0.15)

out['sample_size'] = len(ranked)
out['sample_filers_with_any_employee_concept'] = hits
json.dump(out, open(os.path.join(FAM, 'hunt_result.json'), 'w'), indent=1)
print(json.dumps(out, indent=1))
