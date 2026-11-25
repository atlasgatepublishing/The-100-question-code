#!/usr/bin/env python3
"""Fetch EDGAR frames for tags named on argv into ./data/frames/ (annual CY).
Usage: fetch_frames.py Tag1 Tag2 ...  (run from family folder)"""
import urllib.request, json, os, sys, time
H={'User-Agent':'AtlasGate v12 research research@atlasgate.example'}
OUT=os.path.join(os.getcwd(),'data','frames'); os.makedirs(OUT,exist_ok=True)
def get(u,tries=3):
    for i in range(tries):
        try: return urllib.request.urlopen(urllib.request.Request(u,headers=H),timeout=90).read()
        except Exception:
            if i==tries-1: raise
            time.sleep(2*(i+1))
for tag in sys.argv[1:]:
    for y in range(2009,2026):
        for suf,per in (('D',f'CY{y}'),('I',f'CY{y}Q4I')):
            p=os.path.join(OUT,f'{tag}_{y}{suf}.json')
            if os.path.exists(p): continue
            u=f'https://data.sec.gov/api/xbrl/frames/us-gaap/{tag}/USD/{per}.json'
            try:
                d=json.loads(get(u)); json.dump({int(r['cik']):r['val'] for r in d['data']},open(p,'w')); print(tag,y,suf,'ok',len(d['data']),flush=True)
            except Exception as e: print(tag,y,suf,'MISS',type(e).__name__,flush=True)
            time.sleep(0.12)
print('done')
