#!/usr/bin/env python3
"""Candidate universe: union of top-1500 filers by Assets in any year
2010..2025 (EDGAR frames), mapped CIK->ticker via the CURRENT SEC
company_tickers_exchange.json. Unmapped CIKs are counted (fence #1).
Also computes Tiingo roster disjoint-window counts per ticker (reuse
guard) and writes candidates.json + fence_unmapped.json."""
import json, os, csv, zipfile, io
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')
FR = os.path.join(DATA, 'frames')

def load_frame(name):
    p = os.path.join(FR, name)
    if not os.path.exists(p): return {}
    return {int(k): v for k, v in json.load(open(p)).items()}

def main():
    tick = json.load(open(os.path.join(DATA, 'company_tickers_exchange.json')))
    f = tick['fields']; ci = f.index('cik'); ti = f.index('ticker'); ni = f.index('name'); ei = f.index('exchange')
    cik2tick = {}
    for row in tick['data']:
        cik2tick.setdefault(int(row[ci]), {'ticker': row[ti], 'name': row[ni], 'exchange': row[ei]})
    cand = {}
    unmapped = {}
    for y in range(2010, 2026):
        a = load_frame(f'Assets_{y}I.json')
        top = sorted(a.items(), key=lambda kv: -kv[1])[:1500]
        n_map = 0
        for cik, v in top:
            if cik in cik2tick:
                n_map += 1
                cand.setdefault(cik, {**cik2tick[cik], 'years': {}})
                cand[cik]['years'][str(y)] = v
            else:
                unmapped.setdefault(str(y), []).append(cik)
        print(y, 'frame rows', len(a), 'top1500 mapped', n_map, 'cum candidates', len(cand), flush=True)
    # Tiingo roster: disjoint windows per ticker
    z = zipfile.ZipFile(os.path.join(DATA, 'tiingo_supported_tickers.zip'))
    rows = list(csv.DictReader(io.TextIOWrapper(z.open(z.namelist()[0]), encoding='utf-8')))
    windows = {}
    for r in rows:
        if r['assetType'] != 'Stock': continue
        windows.setdefault(r['ticker'], set()).add((r['startDate'], r['endDate']))
    multi = {t for t, w in windows.items() if len(w) > 1}
    n_flag = 0
    for cik, info in cand.items():
        info['reuse_risk'] = info['ticker'] in multi
        if info['reuse_risk']: n_flag += 1
    print('candidates', len(cand), 'reuse-risk flagged', n_flag)
    json.dump({str(k): v for k, v in cand.items()}, open(os.path.join(DATA, 'candidates.json'), 'w'), indent=1)
    json.dump(unmapped, open(os.path.join(DATA, 'fence_unmapped.json'), 'w'), indent=1)
    print('unmapped per year:', {y: len(v) for y, v in sorted(unmapped.items())})

if __name__ == '__main__':
    main()
