#!/usr/bin/env python3
"""Beneish M-score (1999 probit coefficients, as republished by
Beneish-Lee-Nichols 2013) — SPEC-FROZEN.md. TATA = cash-flow variant
(NI-OCF)/AT, labelled. Securities in AQI -> 0 (labelled)."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sigutil import frame, revenue, cogs, g
FAM=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..')
W04=os.path.join(FAM,'..','..','v11-native-rules','_w04_broad_data')
cand={int(k):v for k,v in json.load(open(os.path.join(W04,'candidates.json'))).items()}
AT=frame('Assets','I'); CA=frame('AssetsCurrent','I'); CL=frame('LiabilitiesCurrent','I')
DC=frame('DebtCurrent','I'); LTDN=frame('LongTermDebtNoncurrent','I'); LTD=frame('LongTermDebt','I')
_r1=frame('ReceivablesNetCurrent','I'); _r2=frame('AccountsReceivableNetCurrent','I')
RECV={y:{**_r1.get(y,{}),**_r2.get(y,{})} for y in range(2009,2026)}; PPE=frame('PropertyPlantAndEquipmentNet','I')
NI=frame('NetIncomeLoss','D'); OCF=frame('NetCashProvidedByUsedInOperatingActivities','D')
DEP=frame('DepreciationDepletionAndAmortization','D'); SGA=frame('SellingGeneralAndAdministrativeExpense','D')
REV=revenue(); COGS=cogs()
def ltd(y,cik):
    b=g(LTDN,y,cik)
    if b is None: b=g(LTD,y,cik)
    return b or 0.0
signals={'Mscore':{'dir':'low','values':{}}}
for F in range(2016,2026):
    y,p=F-1,F-2; n=0
    for cik in cand:
        s1,s0=g(REV,y,cik),g(REV,p,cik); r1,r0=g(RECV,y,cik),g(RECV,p,cik)
        c1,c0=g(COGS,y,cik),g(COGS,p,cik)
        at1,at0=g(AT,y,cik),g(AT,p,cik); ca1,ca0=g(CA,y,cik),g(CA,p,cik)
        pp1,pp0=g(PPE,y,cik),g(PPE,p,cik); d1,d0=g(DEP,y,cik),g(DEP,p,cik)
        sg1,sg0=g(SGA,y,cik),g(SGA,p,cik); ni,ocf=g(NI,y,cik),g(OCF,y,cik)
        if None in (s1,s0,r1,r0,c1,c0,at1,at0,ca1,ca0,pp1,pp0,d1,d0,sg1,sg0,ni,ocf): continue
        if min(s1,s0,at1,at0)<=0: continue
        try:
            dsri=(r1/s1)/(r0/s0)
            gmi=((s0-c0)/s0)/((s1-c1)/s1)
            aqi=(1-(ca1+pp1)/at1)/(1-(ca0+pp0)/at0)
            sgi=s1/s0
            depi=(d0/(pp0+d0))/(d1/(pp1+d1)) if (pp1+d1)>0 and (pp0+d0)>0 else 1.0
            sgai=(sg1/s1)/(sg0/s0)
            tata=(ni-ocf)/at1
            lvgi=((ltd(y,cik)+g(CL,y,cik))/at1)/((ltd(p,cik)+g(CL,p,cik))/at0)
            m=-4.84+0.920*dsri+0.528*gmi+0.404*aqi+0.892*sgi+0.115*depi-0.172*sgai+4.679*tata-0.327*lvgi
        except Exception: continue
        signals['Mscore']['values'].setdefault(str(F),{})[str(cik)]=round(m,4); n+=1
    print(F,'n',n,flush=True)
json.dump({'signals':signals},open(os.path.join(FAM,'signals.json'),'w'))
print('saved')
