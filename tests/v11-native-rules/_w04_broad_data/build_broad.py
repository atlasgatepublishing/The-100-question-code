#!/usr/bin/env python3
"""W04 broad point-in-time universe builder (v11 native rules).
Universe seed: SEC EDGAR frames Assets cross-section per calendar year-end
2016..2025 -> largest filers by total assets -> map CIK to CURRENT ticker via
company_tickers_exchange.json (documented survivorship limitation: filers that
delisted and lost their ticker mapping are absent; results are an upper bound).
Then per-CIK: submissions (SIC) + companyfacts (as-filed, with filed dates).
Prices fetched separately (Yahoo monthly adjclose) by fetch_prices.py.
Shared inputs read-only; everything written only under this folder."""
import urllib.request, json, os, time
H={'User-Agent':'AtlasGate v11 research research@atlasgate.example'}
HERE=os.path.dirname(os.path.abspath(__file__))
def get(u, tries=3):
    for i in range(tries):
        try:
            r=urllib.request.Request(u,headers=H); return urllib.request.urlopen(r,timeout=90).read()
        except Exception as e:
            if i==tries-1: raise
            time.sleep(2*(i+1))
def main():
    tick=json.loads(get('https://www.sec.gov/files/company_tickers_exchange.json'))
    fields=tick['fields']; ci=fields.index('cik'); ti=fields.index('ticker'); ei=fields.index('exchange'); ni=fields.index('name')
    cik2tick={}
    for row in tick['data']:
        cik2tick.setdefault(int(row[ci]), {'ticker':row[ti],'exchange':row[ei],'name':row[ni]})
    cand={}  # cik -> {years: assets}
    for y in range(2016,2026):
        fr=json.loads(get(f'https://data.sec.gov/api/xbrl/frames/us-gaap/Assets/USD/CY{y}Q4I.json'))
        rows=sorted(fr['data'], key=lambda r:-r['val'])[:600]
        n_map=0
        for r in rows:
            cik=int(r['cik'])
            if cik in cik2tick:
                n_map+=1
                cand.setdefault(cik, {'ticker':cik2tick[cik]['ticker'],'name':cik2tick[cik]['name'],'exchange':cik2tick[cik]['exchange'],'years':{}})
                cand[cik]['years'][str(y)]=r['val']
        print(f'{y}: frames rows {len(fr["data"])}, top600 mapped {n_map}, cumulative candidates {len(cand)}', flush=True)
        time.sleep(0.15)
    print('total candidate CIKs', len(cand))
    ok=0
    for cik,info in cand.items():
        cf=os.path.join(HERE,f'facts_{cik:010d}.json'); sf=os.path.join(HERE,f'sub_{cik:010d}.json')
        try:
            if not os.path.exists(cf):
                open(cf,'wb').write(get(f'https://data.sec.gov/api/xbrl/companyconcept/../companyfacts/CIK{cik:010d}.json'.replace('companyconcept/../','')))
            if not os.path.exists(sf):
                open(sf,'wb').write(get(f'https://data.sec.gov/submissions/CIK{cik:010d}.json'))
            sub=json.load(open(sf)); info['sic']=sub.get('sic'); info['sicDesc']=sub.get('sicDescription')
            ok+=1
        except Exception as e:
            info['error']=str(e)
        time.sleep(0.12)
    json.dump(cand, open(os.path.join(HERE,'candidates.json'),'w'), indent=1)
    print('done, facts fetched ok', ok)
if __name__=='__main__': main()
