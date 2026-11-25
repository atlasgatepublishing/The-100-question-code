#!/usr/bin/env python3
"""Dechow-Dichev accrual quality (Francis et al 2005) — SPEC-FROZEN.md.
TCA_t on CFO_{t-1},CFO_t,CFO_{t+1} (scaled by avg assets), firm-level
rolling 7-year windows; AQ = std of residuals. Signal at formation F
uses the window ending F-2 (lead CFO at F-1 is published by then)."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sigutil import frame, g
import numpy as np
FAM=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..')
W04=os.path.join(FAM,'..','..','v11-native-rules','_w04_broad_data')
cand={int(k):v for k,v in json.load(open(os.path.join(W04,'candidates.json'))).items()}
AT=frame('Assets','I'); CA=frame('AssetsCurrent','I'); CL=frame('LiabilitiesCurrent','I')
CASH=frame('CashAndCashEquivalentsAtCarryingValue','I'); DC=frame('DebtCurrent','I')
OCF=frame('NetCashProvidedByUsedInOperatingActivities','D')
# per-cik scaled series
series={}
for cik in cand:
    s={}
    for y in range(2010,2025):
        at1,at0=g(AT,y,cik),g(AT,y-1,cik)
        ca1,ca0,cl1,cl0=g(CA,y,cik),g(CA,y-1,cik),g(CL,y,cik),g(CL,y-1,cik)
        ch1,ch0=g(CASH,y,cik),g(CASH,y-1,cik)
        ocf=g(OCF,y,cik)
        if None in (at1,at0,ca1,ca0,cl1,cl0,ch1,ch0,ocf): continue
        avg=(at1+at0)/2
        if avg<=0: continue
        tca=((ca1-ch1)-(ca0-ch0))-((cl1-(g(DC,y,cik) or 0.0))-(cl0-(g(DC,y-1,cik) or 0.0)))
        s[y]=(tca/avg, ocf/avg)
    if len(s)>=9: series[cik]=s
def aq(cik,t):
    s=series[cik]; rows=[]
    for y in range(t-6,t+1):
        if y in s and (y-1) in s and (y+1) in s:
            rows.append((s[y][0],s[y-1][1],s[y][1],s[y+1][1]))
    if len(rows)<5: return None
    Y=np.array([r[0] for r in rows]); X=np.array([[1.0,r[1],r[2],r[3]] for r in rows])
    try:
        beta,_,_,_=np.linalg.lstsq(X,Y,rcond=None)
        resid=Y-X@beta
        return float(np.std(resid,ddof=1))
    except Exception: return None
signals={'Acq':{'dir':'low','values':{}}}
for F in range(2018,2026):
    t=F-2; n=0
    for cik in series:
        v=aq(cik,t)
        if v is not None and v>0:
            signals['Acq']['values'].setdefault(str(F),{})[str(cik)]=round(v,6); n+=1
    print(F,'window end',t,'n',n,flush=True)
json.dump({'signals':signals},open(os.path.join(FAM,'signals.json'),'w'))
print('saved')
