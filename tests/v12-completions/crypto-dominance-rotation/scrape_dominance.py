#!/usr/bin/env python3
"""Scrape CMC historical Sunday pages for top-20 market caps (same pages the
program's weekly snapshots came from). Output data/dominance.json:
{date: {btc_mcap, top20_mcap, eth_mcap, rows:[{cmc_id,symbol,mcap}]}}"""
import json, os, re, time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
import requests
HERE=os.path.dirname(os.path.abspath(__file__))
OUT=os.path.join(HERE,"data","dominance.json"); os.makedirs(os.path.join(HERE,"data"),exist_ok=True)
H={"User-Agent":"Mozilla/5.0"}
PAT=re.compile(r'cmc-static-icon-(\d+)"?/?><a href="/currencies/([a-z0-9\-]+)/" title="[^"]*" class="cmc-table__column-name--symbol cmc-link">([A-Z0-9]+)</a>')
def fetch(d):
    ds=d.strftime("%Y%m%d")
    for _ in range(3):
        try:
            r=requests.get(f"https://coinmarketcap.com/historical/{ds}/",headers=H,timeout=25)
            if r.status_code!=200: time.sleep(2); continue
            ms=list(PAT.finditer(r.text)); rows=[]
            for i,m in enumerate(ms[:20]):
                seg=r.text[m.start():(ms[i+1].start() if i+1<len(ms) else m.start()+4000)]
                dl=re.findall(r'\$([0-9,]{5,})',seg)
                if not dl: continue
                rows.append({"cmc_id":int(m.group(1)),"symbol":m.group(3),"mcap":int(dl[0].replace(',',''))})
            if len(rows)>=15:
                tot=sum(x["mcap"] for x in rows)
                btc=next((x["mcap"] for x in rows if x["cmc_id"]==1),None)
                eth=next((x["mcap"] for x in rows if x["cmc_id"]==1027),None)
                return d.strftime("%Y-%m-%d"),{"snapshot_date":ds,"rows":rows,"top20_mcap":tot,"btc_mcap":btc,"eth_mcap":eth,"dominance_top20":round(btc/tot*100,4) if btc else None}
            time.sleep(2)
        except Exception: time.sleep(2)
    return d.strftime("%Y-%m-%d"),None
def main():
    days=[]; d=date(2017,1,1)
    while d<=date(2026,11,15): days.append(d); d+=timedelta(days=7)
    res={}; fails=[]
    if os.path.exists(OUT):
        res=json.load(open(OUT))
    todo=[d for d in days if d.strftime("%Y-%m-%d") not in res]
    print(f"{len(days)} Sundays, todo {len(todo)}",flush=True)
    with ThreadPoolExecutor(max_workers=6) as ex:
        for k,v in ex.map(fetch,todo):
            if v is None: fails.append(k)
            else: res[k]=v
    print(f"ok={len(res)} fails={fails}",flush=True)
    json.dump(res,open(OUT,"w"),indent=1)
if __name__=="__main__": main()
