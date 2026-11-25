#!/usr/bin/env python3
"""HXZ accruals complex — frozen by SPEC-FROZEN.md.
Oa Sloan BS form; Ta RSST total BS identity; Poa/Pta percent (Hafzalla);
Dac modified-Jones cross-sectional SIC2-year residuals (Xie)."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sigutil import frame, revenue, g
import numpy as np
FAM=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..')
W04=os.path.join(FAM,'..','..','v11-native-rules','_w04_broad_data')
cand={int(k):v for k,v in json.load(open(os.path.join(W04,'candidates.json'))).items()}
AT=frame('Assets','I'); CA=frame('AssetsCurrent','I'); CL=frame('LiabilitiesCurrent','I')
CASH=frame('CashAndCashEquivalentsAtCarryingValue','I'); DC=frame('DebtCurrent','I')
LTDN=frame('LongTermDebtNoncurrent','I'); LTD=frame('LongTermDebt','I')
NI=frame('NetIncomeLoss','D'); DEP=frame('DepreciationDepletionAndAmortization','D')
REV=revenue(); _r1=frame('ReceivablesNetCurrent','I'); _r2=frame('AccountsReceivableNetCurrent','I')
RECV={y:{**_r1.get(y,{}),**_r2.get(y,{})} for y in range(2009,2026)}; PPE=frame('PropertyPlantAndEquipmentNet','I')
def debt(y,cik):
    a=g(DC,y,cik) or 0.0; b=g(LTDN,y,cik)
    if b is None: b=g(LTD,y,cik)
    return a+(b or 0.0)
def comp(F):
    """values at fiscal year F-1 vs F-2 -> dict cik->dict of raw components"""
    y=F-1; p=F-2; out={}
    for cik in cand:
        at1,at0=g(AT,y,cik),g(AT,p,cik)
        if not at1 or not at0: continue
        avg=(at1+at0)/2
        ca1,ca0,cl1,cl0=g(CA,y,cik),g(CA,p,cik),g(CL,y,cik),g(CL,p,cik)
        ch1,ch0=g(CASH,y,cik),g(CASH,p,cik)
        if None in (ca1,ca0,cl1,cl0,ch1,ch0): continue
        dep=g(DEP,y,cik) or 0.0
        dca=(ca1-ch1)-(ca0-ch0); dcl=(cl1-(g(DC,y,cik) or 0.0))-(cl0-(g(DC,p,cik) or 0.0))
        oa=(dca-dcl-dep)/avg
        liab1,liab0=None,None
        ta=None
        # total accruals BS identity: (dAT-dCash) - (dLiab - dDebtTotal) - Dep
        L=frame_cache_liab
        li1,li0=g(L,y,cik),g(L,p,cik)
        if li1 is not None and li0 is not None:
            ta=((at1-ch1)-(at0-ch0))-((li1-debt(y,cik))-(li0-debt(p,cik)))
            ta=(ta-dep)/avg
        ni=g(NI,y,cik)
        d={'Oa':oa,'Ta':ta,'avg':avg,'ni':ni,'dep':dep,'dca':dca,'dcl':dcl,
           'tca':(dca-dcl),'rev1':g(REV,y,cik),'rev0':g(REV,p,cik),
           'recv1':g(RECV,y,cik),'recv0':g(RECV,p,cik),'ppe':g(PPE,y,cik),'at0':at0}
        out[cik]=d
    return out
frame_cache_liab=frame('Liabilities','I')
signals={'Oa':{'dir':'low','values':{}},'Ta':{'dir':'low','values':{}},
         'Poa':{'dir':'low','values':{}},'Pta':{'dir':'low','values':{}},
         'Dac':{'dir':'low','values':{}}}
for F in range(2016,2026):
    c=comp(F)
    for cik,d in c.items():
        signals['Oa']['values'].setdefault(str(F),{})[str(cik)]=round(d['Oa'],6)
        if d['Ta'] is not None: signals['Ta']['values'].setdefault(str(F),{})[str(cik)]=round(d['Ta'],6)
        if d['ni']:
            signals['Poa']['values'].setdefault(str(F),{})[str(cik)]=round(d['Oa']*d['avg']/abs(d['ni']),6)
            if d['Ta'] is not None: signals['Pta']['values'].setdefault(str(F),{})[str(cik)]=round(d['Ta']*d['avg']/abs(d['ni']),6)
    # modified Jones by SIC2
    groups={}
    for cik,d in c.items():
        if None in (d['rev1'],d['rev0'],d['recv1'],d['recv0'],d['ppe']): continue
        sic=str(cand[cik].get('sic') or '')[:2]
        if len(sic)<2: continue
        groups.setdefault(sic,[]).append(cik)
    dac={}
    for sic,ciks in groups.items():
        if len(ciks)<12: continue
        X=[]; Y=[]
        for cik in ciks:
            d=c[cik]; A=d['at0']
            X.append([1.0/A,(d['rev1']-d['rev0']-(d['recv1']-d['recv0']))/A,d['ppe']/A]); Y.append(d['tca']/A)
        X=np.array(X); Y=np.array(Y)
        try:
            beta,res,_,_=np.linalg.lstsq(X,Y,rcond=None)
            pred=X@beta
            for cik,r in zip(ciks,Y-pred): dac[cik]=float(r)
        except Exception: pass
    for cik,v in dac.items(): signals['Dac']['values'].setdefault(str(F),{})[str(cik)]=round(v,6)
    print(F,{k:len(v.get(str(F),{})) for k,v in signals.items()},flush=True)
json.dump({'signals':signals},open(os.path.join(FAM,'signals.json'),'w'))
print('saved')
