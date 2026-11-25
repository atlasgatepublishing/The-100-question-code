#!/usr/bin/env python3
"""V13 best-rules run for catalog-taa-momentum-turning-points.
Construction EXACT per v12 SPEC-FROZEN except sizing ladder 100/75/25/0 (see BEST-RULES-SPEC.md).
Plumbing copied from v12 run_engine.py (read-only inputs)."""
import json, os, random, statistics, sys
import numpy as np, pandas as pd
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/catalog-taa-keller-faa/data_etf_cache")
TICKS = ["SPY","EFA","IEF","BWX","DBC","GLD","BIL"]
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
def ret(t,i,n):
    if i-n<0: return 0.0
    a,b=ARR[t][i-n],ARR[t][i]
    if np.isnan(a) or np.isnan(b) or a<=0: return 0.0
    return b/a-1
COST=0.0010
ROADS={"LONG":("2010-01-01","2026-11-20"),"DECADE":("2016-01-01","2026-11-20"),"CONT":("2019-01-01","2026-11-20"),"VAL":("2023-01-01","2026-11-20")}
DATES=[datetime.strptime(d,"%Y-%m-%d") for d in CAL]
def eval_indices(start,end):
    si=next(i for i,d in enumerate(CAL) if d>=start); ei=max(i for i,d in enumerate(CAL) if d<=end)
    idx=[i for i in range(si,ei+1) if i==ei or CAL[i+1][:7]!=CAL[i][:7]]
    return si,ei,idx

U=["SPY","EFA","IEF","BWX","DBC","GLD"]
def ladder(i, corr, reb):
    out={}
    for t in U:
        lt=ret(t,i,252)-ret("BIL",i,252); st=ret(t,i,21)-ret("BIL",i,21)
        if lt>0 and st>0: e=1.0
        elif lt<0 and st<0: e=0.0
        elif lt>0: e=corr
        else: e=reb
        if e>0: out[t]=e/6.0
    pw=1.0-sum(out.values())
    if pw>0.01: out["BIL"]=out.get("BIL",0)+pw
    return out
def w_best(i): return ladder(i,0.75,0.25)
def w_published(i): return ladder(i,0.50,0.50)
def w_static(i): return {t:1.0/6 for t in U}
def w_spy(i): return {"SPY":1.0}
def placebo_holdings(i,rng): return {t:1.0/3 for t in rng.sample(U,3)}
def placebo_timing(i,rng):
    out={}
    for t in U:
        e=rng.choice([0.0,0.25,0.5,0.75,1.0])
        if e>0: out[t]=e/6.0
    pw=1.0-sum(out.values())
    if pw>0.01: out["BIL"]=out.get("BIL",0)+pw
    return out

def run(wfun, road, seed=None):
    start,end=ROADS[road]; si,ei,evals=eval_indices(start,end); evalset=set(evals)
    rng=random.Random(seed) if seed is not None else None
    cash=100.0; shares={}; costs=0.0; orders=0; eq=[]
    def value(i):
        v=cash
        for t,sh in shares.items():
            if sh>0 and not np.isnan(ARR[t][i]): v+=sh*ARR[t][i]
        return v
    pending=None
    for i in range(si,ei+1):
        if pending is not None and i==pending[0]:
            target=pending[1]; cur=value(i)
            for t in list(shares.keys()):
                if t not in target:
                    p=ARR[t][i]
                    if shares[t]>0 and not np.isnan(p): cash+=shares[t]*p*(1-COST); costs+=shares[t]*p*COST; orders+=1
                    shares[t]=0.0
            for t,w in target.items():
                p=ARR[t][i]
                if np.isnan(p) or p<=0: continue
                want=w*cur; have=shares.get(t,0.0)*p; dv=want-have
                if abs(dv)<0.25: continue
                c=abs(dv)*COST; costs+=c; orders+=1; cash-=dv+c; shares[t]=shares.get(t,0.0)+dv/p
            pending=None
        v=value(i); eq.append((CAL[i],round(v,4)))
        if i in evalset and i<ei:
            tgt=wfun(i,rng) if rng is not None else wfun(i)
            if tgt is not None: pending=(i+1,tgt)
    final=eq[-1][1] if eq else cash
    peak=-1; mdd=0.0
    for _,v in eq:
        peak=max(peak,v); mdd=min(mdd, v/peak-1 if peak>0 else 0)
    return {"final":round(final,2),"maxDD":round(mdd*100,2),"costs":round(costs,2),"orders":orders,"equity":eq}

def period_stats(eq):
    pts={}
    for d,v in eq: pts[d[:7]]=v
    keys=sorted(pts); rets=[]
    for a,b in zip(keys,keys[1:]): rets.append(pts[b]/pts[a]-1)
    if not rets: return {}
    pos=sum(1 for r in rets if r>0)
    streak=0; mx=0
    for r in rets:
        streak=streak+1 if r<=0 else 0; mx=max(mx,streak)
    peak=-1; last=0; mxnh=0
    for kix,k in enumerate(keys):
        if pts[k]>=peak: peak=pts[k]; last=kix
        mxnh=max(mxnh,kix-last)
    return {"periods":len(rets),"share_pos":round(100*pos/len(rets),1),"median_pct":round(statistics.median(rets)*100,2),
            "best_pct":round(max(rets)*100,2),"worst_pct":round(min(rets)*100,2),
            "avg_pct":round(statistics.mean(rets)*100,2),"longest_losing_streak":mx,"longest_no_new_high_periods":mxnh}

def main():
    res={"family":"catalog-taa-momentum-turning-points","variant":"v13-best-rules ladder 100/75/25/0, monthly, no floor","roads":{}}
    for road in ROADS:
        best=run(w_best,road); pub=run(w_published,road); sta=run(w_static,road); spy=run(w_spy,road)
        res["roads"][road]={"best":best,"published_check":pub,"static_mix":sta,"spy_check":spy,
                            "period_distribution_best_monthly":period_stats(best["equity"])}
        print(road,"best",best["final"],best["maxDD"],"| published-check",pub["final"],"| static",sta["final"],"| spy",spy["final"],flush=True)
    res["placebo_finals"]={}
    for road in ("LONG","DECADE"):
        hf=[run(placebo_holdings,road,seed=1000+s)["final"] for s in range(20)]
        tf=[run(placebo_timing,road,seed=3000+s)["final"] for s in range(20)]
        res["placebo_finals"][road]={"holdings":hf,"timing":tf}
        b=res["roads"][road]["best"]["final"]
        res["roads"][road]["placebos_beaten_holdings"]=sum(1 for f in hf if b>f)
        res["roads"][road]["placebos_beaten_timing"]=sum(1 for f in tf if b>f)
        print(road,"placebos beaten: holdings",res["roads"][road]["placebos_beaten_holdings"],"/20 timing",res["roads"][road]["placebos_beaten_timing"],"/20",flush=True)
    json.dump(res,open(os.path.join(BASE,"results.json"),"w"),indent=1)
    print("DONE")

if __name__=="__main__": main()
