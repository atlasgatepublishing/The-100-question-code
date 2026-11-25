import urllib.request, json, os, time, sys
H={'User-Agent':'AtlasGate v12 research research@atlasgate.example'}
def get(u,tries=3):
    for i in range(tries):
        try: return urllib.request.urlopen(urllib.request.Request(u,headers=H),timeout=90).read()
        except Exception:
            if i==tries-1: raise
            time.sleep(2*(i+1))
def frame(outdir,concept,year,suffix):
    p=os.path.join(outdir,f'{concept}_{year}{suffix}.json')
    if os.path.exists(p): return
    u=f'https://data.sec.gov/api/xbrl/frames/us-gaap/{concept}/USD/CY{year}{"Q4I" if suffix=="I" else ""}.json'
    try:
        d=json.loads(get(u)); json.dump({int(r['cik']):r['val'] for r in d['data']},open(p,'w')); print(concept,year,'ok',len(d['data']),flush=True)
    except Exception as e: print(concept,year,'MISS',e,flush=True)
    time.sleep(0.12)
def frame_q(outdir,concept,year,q):
    p=os.path.join(outdir,f'{concept}_{year}Q{q}.json')
    if os.path.exists(p): return
    u=f'https://data.sec.gov/api/xbrl/frames/us-gaap/{concept}/USD/CY{year}Q{q}.json'
    try:
        d=json.loads(get(u))
        rows=[]
        from datetime import date
        for r in d['data']:
            if 'start' not in r: continue
            s=date.fromisoformat(r['start']); e=date.fromisoformat(r['end']); dur=(e-s).days
            if 80<=dur<=100: rows.append((int(r['cik']),r['val']))
        dd={}
        for k,v in rows: dd[k]=v
        json.dump(dd,open(p,'w')); print(concept,year,q,'ok',len(dd),flush=True)
    except Exception as e: print(concept,year,q,'MISS',e,flush=True)
    time.sleep(0.12)
