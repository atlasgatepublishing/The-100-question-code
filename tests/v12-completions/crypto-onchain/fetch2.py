import urllib.request, json, time, os
from concurrent.futures import ThreadPoolExecutor
BASE="https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
OUT=os.path.join(os.path.dirname(os.path.abspath(__file__)),"data"); os.makedirs(OUT,exist_ok=True)
def get(u):
    last=None
    for a in range(5):
        try:
            req=urllib.request.Request(u, headers={'User-Agent':'Mozilla/5.0'})
            return json.loads(urllib.request.urlopen(req, timeout=120).read())
        except Exception as e:
            last=e; time.sleep(3*(a+1))
    raise last
def chunk(args):
    asset,metrics,y0,y1=args
    u=f"{BASE}?assets={asset}&metrics={metrics}&frequency=1d&start_time={y0}-01-01T00:00:00Z&end_time={y1}-12-31T23:59:59Z&page_size=10000"
    return get(u).get('data',[])
jobs=[]
plan={'btc':2010,'eth':2015,'ltc':2012,'doge':2014,'bch':2017,'ada':2017,'xrp':2013,'xlm':2014,'zec':2016,'dash':2014,'etc':2016}
for c,y0 in plan.items():
    y=y0
    while y<=2026:
        jobs.append((c,'CapMVRVCur,CapMrktCurUSD,PriceUSD',y,min(y+3,2026))); y+=4
for c in ['btc','eth']:
    y=2013 if c=='btc' else 2015
    while y<=2026:
        jobs.append((c,'FlowInExNtv,FlowOutExNtv',y,min(y+3,2026))); y+=4
results={}
with ThreadPoolExecutor(max_workers=4) as ex:
    for args,rows in zip(jobs, ex.map(chunk, jobs)):
        key=(args[0],args[1])
        results.setdefault(key,{})
        for r in rows: results[key][r['time'][:10]]=r
        print('done',args,'rows',len(rows),flush=True)
for (asset,metrics),rows in results.items():
    name=f"cm_{asset}.json" if 'CapMVRV' in metrics else f"cm_{asset}_flows.json"
    data=[rows[k] for k in sorted(rows)]
    json.dump(data, open(f"{OUT}/{name}",'w'))
    print('SAVED',name,len(data), data[0]['time'][:10] if data else None, data[-1]['time'][:10] if data else None, flush=True)
b=urllib.request.urlopen(urllib.request.Request("https://api.bitcoin-data.com/v1/sopr", headers={'User-Agent':'Mozilla/5.0'}), timeout=60).read()
json.dump(json.loads(b), open(f"{OUT}/bgeo_sopr.json",'w'))
print('SAVED sopr', len(json.loads(b)), flush=True)
print('ALL DONE', flush=True)
