#!/usr/bin/env python3
"""W04 broad universe v2: EDGAR FRAMES cross-sections.
For each concept x year: {cik: val} saved compactly. Instant concepts use
CY{y}Q4I (balance sheet dated in Q4 of y); duration concepts use CY{y}
(annual periods beginning in y). Universe candidates = union of top-600
filers by Assets in any year 2016..2025, mapped to CURRENT tickers via
company_tickers_exchange.json. KNOWN LIMITATIONS (printed in every spec):
(1) frames carry period values as ultimately reported (restatements filed
later are folded in -- formation is lagged to June 30 after fiscal year-end
so original filings were long public, but restated values can leak);
(2) current-ticker mapping drops filers that delisted and lost their ticker
(survivorship: results are an upper bound, worst for distress strategies);
(3) non-calendar fiscal filers' annual flows may be filed a few weeks after
a June 30 formation in a minority of cases."""
import urllib.request, json, os, time
H={'User-Agent':'AtlasGate v11 research research@atlasgate.example'}
HERE=os.path.dirname(os.path.abspath(__file__))
def get(u,tries=3):
    for i in range(tries):
        try:
            r=urllib.request.Request(u,headers=H); return urllib.request.urlopen(r,timeout=90).read()
        except Exception as e:
            if i==tries-1: raise
            time.sleep(2*(i+1))
INSTANT=['Assets','AssetsCurrent','Liabilities','LiabilitiesCurrent','StockholdersEquity',
 'CashAndCashEquivalentsAtCarryingValue','PropertyPlantAndEquipmentNet','LongTermDebtCurrent',
 'DebtCurrent','LongTermDebtNoncurrent','LongTermDebt']
DURATION=['OperatingIncomeLoss','InterestExpense','InterestAndDebtExpense','NetIncomeLoss',
 'NetCashProvidedByUsedInOperatingActivities','GrossProfit','Revenues','SalesRevenueNet',
 'RevenueFromContractWithCustomerExcludingAssessedTax','CostOfRevenue','CostOfGoodsAndServicesSold',
 'CostOfGoodsSold','WeightedAverageNumberOfDilutedSharesOutstanding','WeightedAverageNumberOfSharesOutstandingBasic']
YEARS=list(range(2014,2026))
def frame(tax,concept,unit,per):
    u=f'https://data.sec.gov/api/xbrl/frames/{tax}/{concept}/{unit}/{per}.json'
    d=json.loads(get(u)); return {int(r['cik']): r['val'] for r in d['data']}
def main():
    os.makedirs(os.path.join(HERE,'frames'),exist_ok=True)
    for c in INSTANT:
        for y in YEARS:
            p=os.path.join(HERE,'frames',f'{c}_{y}I.json')
            if os.path.exists(p): continue
            try: json.dump(frame('us-gaap',c,'USD',f'CY{y}Q4I'), open(p,'w'))
            except Exception as e: print('MISS',c,y,e,flush=True)
            time.sleep(0.12)
        print('instant done',c,flush=True)
    for c in DURATION:
        for y in YEARS:
            p=os.path.join(HERE,'frames',f'{c}_{y}D.json')
            if os.path.exists(p): continue
            try: json.dump(frame('us-gaap',c,'USD',f'CY{y}'), open(p,'w'))
            except Exception as e: print('MISS',c,y,e,flush=True)
            time.sleep(0.12)
        print('duration done',c,flush=True)
    for y in YEARS:
        p=os.path.join(HERE,'frames',f'Shares_{y}I.json')
        if os.path.exists(p): continue
        try: json.dump(frame('dei','EntityCommonStockSharesOutstanding','shares',f'CY{y}Q4I'), open(p,'w'))
        except Exception as e: print('MISS shares',y,e,flush=True)
        time.sleep(0.12)
    print('frames complete',flush=True)
    # candidates: top600 by Assets per year 2016..2025
    tick=json.loads(get('https://www.sec.gov/files/company_tickers_exchange.json'))
    f=tick['fields']; cik2={int(r[f.index('cik')]):{'ticker':r[f.index('ticker')],'name':r[f.index('name')],'exchange':r[f.index('exchange')]} for r in tick['data']}
    cand={}
    for y in range(2016,2026):
        a=json.load(open(os.path.join(HERE,'frames',f'Assets_{y}I.json')))
        for cik,v in sorted(((int(k),v) for k,v in a.items()), key=lambda kv:-kv[1])[:600]:
            if cik in cik2:
                cand.setdefault(cik,{**cik2[cik],'years':{}}); cand[cik]['years'][str(y)]=v
    print('candidates',len(cand),flush=True)
    for cik,info in cand.items():
        sf=os.path.join(HERE,f'sub_{cik:010d}.json')
        try:
            if not os.path.exists(sf): open(sf,'wb').write(get(f'https://data.sec.gov/submissions/CIK{cik:010d}.json'))
            s=json.load(open(sf)); info['sic']=s.get('sic'); info['sicDesc']=s.get('sicDescription')
        except Exception as e: info['sic']=None
        time.sleep(0.11)
    json.dump(cand, open(os.path.join(HERE,'candidates.json'),'w'), indent=1)
    print('ALL DONE',flush=True)
if __name__=='__main__': main()
