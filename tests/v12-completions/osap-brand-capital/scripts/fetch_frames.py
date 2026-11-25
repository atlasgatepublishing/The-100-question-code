#!/usr/bin/env python3
"""Fetch EDGAR frames AdvertisingExpense (annual CY) 2009-2025 into data/frames/."""
import urllib.request, json, os, time
H={'User-Agent':'AtlasGate v12 research research@atlasgate.example'}
OUT=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','data','frames')
os.makedirs(OUT,exist_ok=True)
def get(u,tries=3):
    for i in range(tries):
        try: return urllib.request.urlopen(urllib.request.Request(u,headers=H),timeout=90).read()
        except Exception:
            if i==tries-1: raise
            time.sleep(2*(i+1))
for y in range(2009,2026):
    p=os.path.join(OUT,f'AdvertisingExpense_{y}D.json')
    if os.path.exists(p): continue
    u=f'https://data.sec.gov/api/xbrl/frames/us-gaap/AdvertisingExpense/USD/CY{y}.json'
    try:
        d=json.loads(get(u)); json.dump({int(r['cik']):r['val'] for r in d['data']},open(p,'w')); print(y,'ok',len(d['data']),flush=True)
    except Exception as e: print(y,'MISS',e,flush=True)
    time.sleep(0.12)
print('done')
