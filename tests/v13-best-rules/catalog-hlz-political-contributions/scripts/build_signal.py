#!/usr/bin/env python3
"""Build the v13 political-contributions signal from raw FEC bulk data.

Construction frozen in ../BEST-RULES-SPEC.md:
- Source: fec.gov public bulk downloads (committee master 'cm' +
  committee-to-candidate contributions 'pas2'), cycles ending
  2014, 2016, 2018, 2020, 2022, 2024.
- Firm linkage: FEC committee master's own CONNECTED_ORG_NM field,
  restricted to corporate sponsors (ORG_TP == 'C'), matched to SEC
  registrant names in the W04 stack by deterministic normalization.
  No hand aliases. If several CIKs share one normalized name, the
  match goes to the CIK with the largest 2016 size figure in the
  stack's candidates file (one firm, one line).
- Signal per firm-cycle: distinct candidates (CAND_ID) receiving a
  non-memo type-24K contribution with amount > 0 from any matched
  committee of the firm; tie-break dollars = net sum of all non-memo
  24K amounts.
Output: ../data/signal.json {cycle_end_year: {cik: [n_candidates, dollars]}}
plus a printed match audit for the run log.
"""
import json, os, re, zipfile, io, csv
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')
W04 = '/home/hatch/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data'
CYCLES = [2014, 2016, 2018, 2020, 2022, 2024]

SUFFIX = {'INC', 'CORP', 'CORPORATION', 'CO', 'COMPANY', 'LLC', 'LLP', 'LP',
          'LTD', 'PLC', 'HOLDINGS', 'HLDGS', 'GROUP', 'THE', 'AND', '&'}

def norm(name):
    if not name: return ''
    s = name.upper().split('/')[0]
    s = s.replace('&', ' AND ')
    s = re.sub(r'[^A-Z0-9 ]', ' ', s)
    toks = [t for t in s.split() if t not in SUFFIX]
    return ' '.join(toks).strip()

cand = {int(k): v for k, v in json.load(open(os.path.join(W04, 'candidates.json'))).items()}
name2cik = {}
for cik, v in cand.items():
    n = norm(v.get('name') or '')
    if not n: continue
    size = (v.get('years') or {}).get('2016') or 0
    if n not in name2cik or size > name2cik[n][1]:
        name2cik[n] = (cik, size)
name2cik = {n: c for n, (c, _) in name2cik.items()}
print(f'W04 registrants: {len(cand)}; distinct normalized names: {len(name2cik)}')

def read_zip_txt(path):
    z = zipfile.ZipFile(path)
    name = [n for n in z.namelist() if n.endswith('.txt')][0]
    return io.TextIOWrapper(z.open(name), encoding='utf-8', errors='replace')

signal = {}
audit = {}
for cyc in CYCLES:
    yy = str(cyc)[2:]
    cmte2cik = {}
    n_corp = 0
    with read_zip_txt(os.path.join(DATA, f'cm{yy}.zip')) as f:
        for row in csv.reader(f, delimiter='|'):
            if len(row) < 15: continue
            cmte_id, org_tp, conn = row[0], row[12], row[13]
            if org_tp != 'C' or not conn: continue
            n_corp += 1
            cik = name2cik.get(norm(conn))
            if cik is not None:
                cmte2cik[cmte_id] = cik
    firm_cands = defaultdict(set)
    firm_dollars = defaultdict(float)
    n_rec = 0
    with read_zip_txt(os.path.join(DATA, f'pas2{yy}.zip')) as f:
        for row in csv.reader(f, delimiter='|'):
            if len(row) < 22: continue
            cmte_id, ttype, memo, cand_id = row[0], row[5], row[19], row[16]
            if cmte_id not in cmte2cik or ttype != '24K' or memo == 'X': continue
            try: amt = float(row[14])
            except ValueError: continue
            cik = cmte2cik[cmte_id]
            n_rec += 1
            firm_dollars[cik] += amt
            if amt > 0 and cand_id:
                firm_cands[cik].add(cand_id)
    sig = {}
    for cik, cs in firm_cands.items():
        if len(cs) >= 1:
            sig[str(cik)] = [len(cs), round(firm_dollars[cik], 2)]
    signal[str(cyc)] = sig
    audit[str(cyc)] = {'corp_connected_committees': n_corp,
                       'matched_committees': len(cmte2cik),
                       'matched_firms': len(sig),
                       'contribution_records_used': n_rec}
    top = sorted(sig.items(), key=lambda kv: -kv[1][0])[:8]
    print(f'cycle {cyc}: corp committees {n_corp}, matched {len(cmte2cik)}, '
          f'firms in pond {len(sig)}, records {n_rec}')
    for cik, (n, d) in top:
        print(f'   top: {cand[int(cik)]["name"]} ({cand[int(cik)]["ticker"]}) '
              f'cands={n} dollars={d:,.0f}')

json.dump(signal, open(os.path.join(DATA, 'signal.json'), 'w'), indent=1)
json.dump(audit, open(os.path.join(DATA, 'match_audit.json'), 'w'), indent=1)
print('saved signal.json + match_audit.json')
