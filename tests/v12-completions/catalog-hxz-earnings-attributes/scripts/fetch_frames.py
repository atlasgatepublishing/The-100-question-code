#!/usr/bin/env python3
"""Fetch EDGAR frames into ../data/frames/ : TAGS = [(tag, 'I'|'D')]"""
import urllib.request, json, os, time
H={'User-Agent':'AtlasGate v12 research research@atlasgate.example'}
OUT=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','data','frames')
os.makedirs(OUT,exist_ok=True)
TAGS=[('NetIncomeLoss', 'D'), ('NetCashProvidedByUsedInOperatingActivities', 'D'), ('Assets', 'I')]
def get(u,tries=3):
    for i in range(tries):
        try: return urllib.request.urlopen(urllib.request.Request(u,headers=H),timeout=90).read()
        except Exception:
            if i==tries-1: raise
            time.sleep(2*(i+1))
for tag,suf in TAGS:
    for y in range(2009,2026):
        p=os.path.join(OUT,f'{tag}_{y}{suf}.json')
        if os.path.exists(p): continue
        per=f'CY{y}Q4I' if suf=='I' else f'CY{y}'
        u=f'https://data.sec.gov/api/xbrl/frames/us-gaap/{tag}/USD/{per}.json'
        try:
            d=json.loads(get(u)); json.dump({int(r['cik']):r['val'] for r in d['data']},open(p,'w')); print(tag,y,'ok',len(d['data']),flush=True)
        except Exception as e: print(tag,y,'MISS',e,flush=True)
        time.sleep(0.12)
print('done')
