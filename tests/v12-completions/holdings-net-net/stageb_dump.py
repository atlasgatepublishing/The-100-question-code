#!/usr/bin/env python3
"""Stage-B-only re-dump: recomputes pool.json from the local concept_cache
(no network) using build_pool_fast.py's exact logic, writing via tmp+rename
(the direct write was intermittently denied by the sync layer)."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_pool_fast as B

def main():
    stageA = {}
    for F in B.FORMATIONS:
        ca = B.load_frame(f'AssetsCurrent_{F-1}I.json')
        li = B.load_frame(f'Liabilities_{F-1}I.json')
        stageA[F] = {cik for cik in set(ca) & set(li) if ca[cik] - li[cik] > 0}
    sh_series = {y: B.load_frame(f'Shares_{y}I.json') for y in range(2014, 2026)}
    def sf(cik, F):
        avail = [(y, sh_series[y][cik]) for y in range(2014, 2026) if sh_series[y].get(cik)]
        f = 1.0
        for (y0, a), (y1, b) in zip(avail, avail[1:]):
            if y1 >= F:
                r = b / a
                if r >= 1.6 or r <= 0.625: f *= r
        return f
    pool, counts = {}, {}
    for F in B.FORMATIONS:
        form_date = f'{F}-06-30'
        rows = []
        c = {'stageA': len(stageA[F]), 'asfiled_ncav_le0': 0, 'no_shares': 0, 'pstar_lt_025': 0, 'in_pool': 0}
        for cik in stageA[F]:
            ca = B.pick_asfiled(B.load_concept(cik, 'AssetsCurrent'), ['USD'], F - 1, form_date)
            li = B.pick_asfiled(B.load_concept(cik, 'Liabilities'), ['USD'], F - 1, form_date)
            if ca is None or li is None or ca - li <= 0:
                c['asfiled_ncav_le0'] += 1; continue
            shv = B.pick_asfiled(B.load_concept(cik, 'EntityCommonStockSharesOutstanding'), ['shares'], F - 1, form_date)
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
    out = os.path.join(B.HERE, 'pool.json')
    tmp = out + '.tmp'
    json.dump({'pool': pool, 'counts': counts}, open(tmp, 'w'), indent=1)
    os.replace(tmp, out)
    tmp2 = os.path.join(B.HERE, 'stageb_counts.json.tmp')
    json.dump(counts, open(tmp2, 'w'), indent=1)
    os.replace(tmp2, os.path.join(B.HERE, 'stageb_counts.json'))
    print('saved pool.json', flush=True)

if __name__ == '__main__':
    main()
