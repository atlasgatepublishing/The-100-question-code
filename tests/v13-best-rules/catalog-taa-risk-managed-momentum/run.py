#!/usr/bin/env python3
"""V13 best-rules reconstruction: Risk Managed Momentum (disclosed colour only).
Monthly, score=0.4*1m+0.3*3m+0.2*6m+0.1*12m, top-3 positive equal weight, rest SHY.
Ablation: identical book + 10% vol-target overlay. Costs 0.10% of turnover."""
import json, os, random
import numpy as np, pandas as pd
from datetime import datetime, timezone

HERE=os.path.dirname(os.path.abspath(__file__))
CACHE=os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/catalog-taa-keller-faa/data_etf_cache")
RISKY=["SPY","EFA","EEM","VNQ","DBC","GLD"]; DEF="SHY"; ALL=RISKY+[DEF]
TICKS=sorted(set(ALL+["IEF"]))
def load(t):
    d=json.load(open(os.path.join(CACHE,t+".json")))["chart"]["result"][0]
    ts=d["timestamp"]; q=d["indicators"]["quote"][0]; adj=d["indicators"].get("adjclose",[{}])[0].get("adjclose")
    out={}
    for i,x in enumerate(ts):
        c=q["close"][i]
        if c is None: continue
        dt=datetime.fromtimestamp(x,tz=timezone.utc).strftime("%Y-%m-%d")
        out[dt]= adj[i] if adj and adj[i] else c
    return out
RAW={t:load(t) for t in TICKS}
CAL=sorted(RAW["SPY"].keys()); N=len(CAL)
ARR={}
for t in TICKS:
    a=np.full(N,np.nan); last=np.nan
    for i,d in enumerate(CAL):
        if d in RAW[t]: last=RAW[t][d]
        a[i]=last
    ARR[t]=a
# monthly closes: last trading day of each month
mid=[]
for i,d in enumerate(CAL):
    if i==N-1 or CAL[i+1][:7]!=d[:7]: mid.append(i)
MPRICE={t:ARR[t][mid] for t in TICKS}; MDATES=[CAL[i] for i in mid]; NM=len(mid)
def mret(t,k,lag):  # return over k months ending at monthly index k_idx
    if k-lag<0: return None
    a,b=MPRICE[t][k-lag],MPRICE[t][k]
    return None if (np.isnan(a) or np.isnan(b) or a<=0) else b/a-1
def score(t,k):
    parts=[(0.40,21//21),(0.30,3),(0.20,6),(0.10,12)]  # months 1,3,6,12
    tot=0.0
    for w,m in [(0.40,1),(0.30,3),(0.20,6),(0.10,12)]:
        r=mret(t,k,m)
        if r is None: return None
        tot+=w*r
    return tot
def book(k, overlay=False):
    sc={t:score(t,k) for t in RISKY}
    if any(v is None for v in sc.values()): return {}
    pos=sorted([t for t in RISKY if sc[t]>0], key=lambda t: sc[t], reverse=True)[:3]
    if not pos: return {DEF:1.0}
    w={t:1.0/len(pos) for t in pos}
    # remainder (if <3 positive) to SHY
    held=sum(w.values())
    # top3 always sums to 1 when >=1? No: spec: hold only positives equal weight among themselves, remainder to SHY when <3.
    # Implement: each positive gets 1/3, remainder SHY.
    w={t:1.0/3 for t in pos}
    rem=1.0-sum(w.values())
    if rem>1e-9: w[DEF]=rem
    if overlay:
        # trailing 63 trading-day vol of equal-weight(1/3) selected book, daily rets
        di=mid[k]
        if di>=63:
            rets=[]
            for j in range(di-62, di+1):
                r=0.0
                for t in pos: r+=(1.0/3)*(ARR[t][j]/ARR[t][j-1]-1)
                rets.append(r)
            vol=float(np.std(rets)*np.sqrt(252))
            if vol>0:
                scale=min(1.0, 0.10/vol)
                w={t:v*scale for t,v in w.items() if t!=DEF}
                w[DEF]=1.0-sum(w.values())
    return w
COST=0.001
ROADS={"LONG":("2010-01-01","2026-11-20"),"DECADE":("2016-01-01","2026-11-20"),"CONT":("2019-01-01","2026-11-20"),"VAL":("2023-01-01","2026-11-20")}
def period_stats(eq):
    r=eq.pct_change().dropna()
    ls=cur=0
    for x in r: cur=cur+1 if x<=0 else 0; ls=max(ls,cur)
    rm=eq.cummax(); below=(eq<rm-1e-9); lb=cur=0
    for x in below: cur=cur+1 if x else 0; lb=max(lb,cur)
    return {"n_periods":int(len(r)),"share_positive":round(float((r>0).mean()),3),"median_period":round(float(r.median()),4),
            "mean_period_secondary":round(float(r.mean()),4),"best":round(float(r.max()),4),"worst":round(float(r.min()),4),
            "longest_losing_streak":int(ls),"longest_below_high_months":int(lb),"max_dd":round(float((eq/rm-1).min()),4)}
def simulate(mode, road, seed=None):
    start,end=ROADS[road]
    ks=[k for k,d in enumerate(MDATES) if start<=d<=end]
    rng=random.Random(seed) if seed is not None else None
    eq=100.0; curve={}; weights={}; total_cost=0.0; turnover_total=0.0
    for ii,k in enumerate(ks):
        curve[MDATES[k]]=round(eq,4)
        if ii==len(ks)-1: break
        k1=ks[ii+1]
        if rng is not None:
            n=rng.randint(1,len(ALL)); pick=rng.sample(ALL,n); ws=rng.random(); 
            raw=[rng.random() for _ in pick]; s=sum(raw); new_w={a:v/s for a,v in zip(pick,raw)}
        elif mode=="spy": new_w={"SPY":1.0}
        elif mode=="static": new_w={"SPY":0.6,"IEF":0.4}
        elif mode=="best": new_w=book(k, overlay=False)
        elif mode=="overlay": new_w=book(k, overlay=True)
        else: raise ValueError(mode)
        allk=set(weights)|set(new_w); turn=sum(abs(new_w.get(a,0)-weights.get(a,0)) for a in allk)
        turnover_total+=turn; c=eq*turn*COST; total_cost+=c; eq-=c
        ret=sum(w*(MPRICE[a][k1]/MPRICE[a][k]-1) for a,w in new_w.items())
        eq*=(1+ret); weights=new_w
    s=pd.Series(curve); s.index=pd.to_datetime(s.index)
    return {"final":round(float(eq),2),"cost":round(total_cost,2),"turnover":round(turnover_total,2),
            "stats":period_stats(s),"curve":{str(d.date()):v for d,v in s.items()}}
out={"family":"catalog-taa-risk-managed-momentum","note":"Reconstruction from disclosed colour only; author rules unpublished (v12 STILL UNBUILDABLE).","roads":{},"placebos":{},"ablation":{}}
for road in ROADS:
    out["roads"][road]={"best":simulate("best",road),"spy":simulate("spy",road),"static6040":simulate("static",road)}
    out["ablation"][road]=simulate("overlay",road)
    print(road,"best",out["roads"][road]["best"]["final"],"overlay",out["ablation"][road]["final"],
          "spy",out["roads"][road]["spy"]["final"],"static",out["roads"][road]["static6040"]["final"],
          "dd",out["roads"][road]["best"]["stats"]["max_dd"],"turn",out["roads"][road]["best"]["turnover"])
for road in ("LONG","CONT"):
    finals=[]; beats=0
    for seed in range(20):
        f=simulate("best",road,seed=seed)["final"]; finals.append(f)
        if out["roads"][road]["best"]["final"]>f: beats+=1
    out["placebos"][road]={"beats":beats,"median_placebo":round(float(np.median(finals)),2),"placebo_finals":finals}
    print("placebo",road,beats,"/20 median",out["placebos"][road]["median_placebo"])
# confirmation only if any road beats champion
CHAMP={"LONG":1415.62,"CONT":544.47,"VAL":288.05,"DECADE":667.35}
out["champion_vm"]=CHAMP; out["spy_reference"]={"LONG":822.94,"CONT":313.62,"VAL":187.77,"DECADE":367.80}
out["confirmation_needed"]=[r for r in ROADS if out["roads"][r]["best"]["final"]>CHAMP[r]]
json.dump(out, open(os.path.join(HERE,"results.json"),"w"), indent=1)
print("confirmation_needed", out["confirmation_needed"])
