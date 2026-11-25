#!/usr/bin/env python3
"""CONSTRUCTED meta composite (Chordia-style rank average) — CONSTRUCTION-SPEC.md.
Mean percentile rank of: 12-1 momentum, earnings yield, low accruals, gross profitability."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sigutil import frame, g
FAM=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..')
W04=os.path.join(FAM,'..','..','v11-native-rules','_w04_broad_data')
def loadj(p): return json.load(open(p)) if os.path.exists(p) else {}
cand={int(k):v for k,v in loadj(os.path.join(W04,'candidates.json')).items()}
px={}
for cik,info in cand.items():
    t=info['ticker'].replace('/','-'); p=os.path.join(W04,f'px_{t}.json')
    if os.path.exists(p):
        try: px[cik]={r[0]:(r[1],r[2]) for r in loadj(p)}
        except Exception: pass
shares_f={}
for y in range(2009,2026):
    shares_f[y]={int(k):v for k,v in loadj(os.path.join(W04,'frames',f'Shares_{y}I.json')).items()}
AT=frame('Assets','I'); NI=frame('NetIncomeLoss','D'); OCF=frame('NetCashProvidedByUsedInOperatingActivities','D'); GP=frame('GrossProfit','D')
def pct(vals):
    s=sorted(vals.items(),key=lambda kv:kv[1]); n=len(s)
    return {c:(i+0.5)/n for i,(c,_) in enumerate(s)}
signals={'MetaComp':{'dir':'high','values':{}}}
for F in range(2016,2026):
    y=F-1; mom={}; ey={}; la={}; gp={}
    for cik in cand:
        s=px.get(cik)
        if s:
            a=s.get(f'{F:04d}-05'); b=s.get(f'{F-1:04d}-05'); c0=s.get(f'{F:04d}-06')
            if a and b and c0 and b[0]>0 and a[0]>0:
                mom[cik]=(a[0]/b[0])/(c0[0]/a[0])-1 if c0[0]>0 else a[0]/b[0]-1
        at=g(AT,y,cik); at0=g(AT,y-1,cik); ni=g(NI,y,cik); ocf=g(OCF,y,cik); gpv=g(GP,y,cik)
        sh=shares_f.get(y,{}).get(cik)
        if s and sh:
            e=s.get(f'{F:04d}-06')
            if e and e[1] and ni is not None:
                cap=sh*e[1]
                if cap>0: ey[cik]=ni/cap
        if at and at0 and ni is not None and ocf is not None:
            la[cik]=-((ni-ocf)/((at+at0)/2))
        if at and gpv is not None: gp[cik]=gpv/at
    parts=[pct(d) for d in (mom,ey,la,gp)]
    allc=set()
    for d in parts: allc|=set(d)
    for cik in allc:
        vs=[d[cik] for d in parts if cik in d]
        if len(vs)>=3:
            signals['MetaComp']['values'].setdefault(str(F),{})[str(cik)]=round(sum(vs)/len(vs),4)
    print(F,'n',len(signals['MetaComp']['values'].get(str(F),{})),flush=True)
json.dump({'signals':signals},open(os.path.join(FAM,'signals.json'),'w'))
print('saved')
