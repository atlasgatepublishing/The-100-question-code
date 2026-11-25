#!/usr/bin/env python3
"""CONSTRUCTED efficiency composite — CONSTRUCTION-SPEC.md.
Percentile-rank composite of Sales/AT, GrossProfit/AT, Sales/PPE."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sigutil import frame, revenue, g
FAM=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..')
W04=os.path.join(FAM,'..','..','v11-native-rules','_w04_broad_data')
cand={int(k):v for k,v in json.load(open(os.path.join(W04,'candidates.json'))).items()}
AT=frame('Assets','I'); PPE=frame('PropertyPlantAndEquipmentNet','I')
GP=frame('GrossProfit','D'); REV=revenue()
def pct(vals):
    s=sorted(vals.items(),key=lambda kv:kv[1]); n=len(s)
    return {c:(i+0.5)/n for i,(c,_) in enumerate(s)}
signals={'EffComp':{'dir':'high','values':{}}}
for F in range(2016,2026):
    y=F-1; a={}; b={}; c_={}
    for cik in cand:
        at=g(AT,y,cik); rev=g(REV,y,cik); gp=g(GP,y,cik); pp=g(PPE,y,cik)
        if at and rev: a[cik]=rev/at
        if at and gp is not None: b[cik]=gp/at
        if pp and rev: c_[cik]=rev/pp
    pa,pb,pc=pct(a),pct(b),pct(c_)
    for cik in set(pa)|set(pb)|set(pc):
        parts=[d[cik] for d in (pa,pb,pc) if cik in d]
        if len(parts)>=2:
            signals['EffComp']['values'].setdefault(str(F),{})[str(cik)]=round(sum(parts)/len(parts),4)
    print(F,'n',len(signals['EffComp']['values'][str(F)]),flush=True)
json.dump({'signals':signals},open(os.path.join(FAM,'signals.json'),'w'))
print('saved')
