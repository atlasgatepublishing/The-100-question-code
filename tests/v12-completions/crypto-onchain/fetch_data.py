import urllib.request, json, time, os
BASE="https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
OUT=os.path.join(os.path.dirname(os.path.abspath(__file__)),"data"); os.makedirs(OUT,exist_ok=True)
def get(u):
    for a in range(4):
        try:
            req=urllib.request.Request(u, headers={'User-Agent':'Mozilla/5.0'})
            return json.loads(urllib.request.urlopen(req, timeout=60).read())
        except Exception as e:
            time.sleep(2*(a+1))
    raise RuntimeError(u)
def fetch(asset, metrics, y0=2009, y1=2026):
    rows={}
    for y in range(y0,y1+1):
        u=f"{BASE}?assets={asset}&metrics={metrics}&frequency=1d&start_time={y}-01-01T00:00:00Z&end_time={y}-12-31T23:59:59Z&page_size=10000"
        d=get(u)
        for r in d.get('data',[]): rows[r['time'][:10]]=r
        time.sleep(0.7)
    return [rows[k] for k in sorted(rows)]
coins=['btc','eth','ltc','doge','bch','ada','xrp','xlm','zec','dash','etc']
for c in coins:
    rows=fetch(c,'CapMVRVCur,CapMrktCurUSD,PriceUSD')
    json.dump(rows, open(f"{OUT}/cm_{c}.json",'w'))
    print(c, len(rows), rows[0]['time'][:10] if rows else None, rows[-1]['time'][:10] if rows else None, flush=True)
for c in ['btc','eth']:
    rows=fetch(c,'FlowInExNtv,FlowOutExNtv')
    json.dump(rows, open(f"{OUT}/cm_{c}_flows.json",'w'))
    print(c+' flows', len(rows), rows[0]['time'][:10] if rows else None, rows[-1]['time'][:10] if rows else None, flush=True)
# SOPR keyless
b=urllib.request.urlopen(urllib.request.Request("https://api.bitcoin-data.com/v1/sopr", headers={'User-Agent':'Mozilla/5.0'}), timeout=60).read()
json.dump(json.loads(b), open(f"{OUT}/bgeo_sopr.json",'w'))
print('sopr rows', len(json.loads(b)))
