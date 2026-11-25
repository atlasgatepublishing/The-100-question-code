import urllib.request, json, os, time, gzip
HERE=os.path.dirname(os.path.abspath(__file__))
OUT=os.path.join(HERE,"data","edgar"); os.makedirs(OUT, exist_ok=True)
W04=os.path.expanduser("~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data")
cand=json.load(open(os.path.join(W04,"candidates.json")))
UA={'User-Agent':'StockAppResearch admin@example.com'}
def get(u):
    for a in range(3):
        try:
            req=urllib.request.Request(u, headers=UA)
            b=urllib.request.urlopen(req, timeout=30).read()
            try: return json.loads(gzip.decompress(b))
            except Exception: return json.loads(b)
        except urllib.error.HTTPError as e:
            if e.code==404: return None
            time.sleep(1.5*(a+1))
        except Exception: time.sleep(1.5*(a+1))
    return None
CONCEPTS=["Revenues","SalesRevenueNet","RevenueFromContractWithCustomerExcludingAssessedTax","SalesRevenueGoodsNet","SalesRevenueServicesNet","WeightedAverageNumberOfSharesOutstandingBasic"]
done=0
for cik in cand:
    f=os.path.join(OUT,f"{cik}.json")
    if os.path.exists(f): done+=1; continue
    rec={}
    for c in CONCEPTS:
        d=get(f"https://data.sec.gov/api/xbrl/companyconcept/CIK{int(cik):010d}/us-gaap/{c}.json")
        if d and 'units' in d:
            u=d['units'].get('USD') or d['units'].get('shares') or []
            if u: rec[c]=u
        time.sleep(0.11)
    json.dump(rec, open(f,'w')); done+=1
    if done%100==0: print("rev fetch", done, flush=True)
print("rev fetch DONE", done, flush=True)
