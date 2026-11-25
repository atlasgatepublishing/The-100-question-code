#!/usr/bin/env python3
"""V13 best-rules run for catalog-taa-kipnis-daaa.
Spec: BEST-RULES-SPEC.md (frozen before this run).
Only change vs v12 published-form engine: top-5 weighting = EQUAL WEIGHT
(v12 used constructed inverse-vol 21d substitute for author min-variance).
Everything else identical chassis: 0.10%/side, fractional, adjusted closes,
month-end signal, next-day execution, $100 pots.
Adds per spec: static EW10 control, time-in-defense, placebos on all roads.
"""
import json, os, math, random, statistics, sys
import numpy as np
import pandas as pd
from datetime import datetime, timezone

CACHE = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/catalog-taa-keller-faa/data_etf_cache")
TICKS = ["SPY","QQQ","IWM","EFA","VEA","VWO","EEM","VGK","EWJ","VNQ","RWX","DBC","GLD","TLT","IEF","SHY","BIL","AGG","BND","LQD","HYG","UUP","TIP","BWX","IEFA"]
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
CAL=sorted(RAW["SPY"].keys()); CI={d:i for i,d in enumerate(CAL)}
N=len(CAL)
ARR={}
for t in TICKS:
    a=np.full(N,np.nan); last=np.nan
    for i,d in enumerate(CAL):
        if d in RAW[t]: last=RAW[t][d]
        a[i]=last
    ARR[t]=a
def _retarr(t,n):
    a=ARR[t]; out=np.zeros(N)
    out[n:]=a[n:]/a[:-n]-1
    out[:n]=0; out[np.isnan(out)]=0
    return out
_R={ (t,n):_retarr(t,n) for t in TICKS for n in (21,63,126,252,84)}
def S(t,i): return 12*_R[(t,21)][i]+4*_R[(t,63)][i]+2*_R[(t,126)][i]+_R[(t,252)][i]
COST=0.0010
ROADS={"LONG":("2010-01-01","2026-11-20"),"DECADE":("2016-01-01","2026-11-20"),"CONT":("2019-01-01","2026-11-20"),"VAL":("2023-01-01","2026-11-20")}
DATES=[datetime.strptime(d,"%Y-%m-%d") for d in CAL]

def eval_indices(cadence, start, end):
    si=next(i for i,d in enumerate(CAL) if d>=start); ei=max(i for i,d in enumerate(CAL) if d<=end)
    if cadence=="monthly":
        idx=[i for i in range(si,ei+1) if i==ei or CAL[i+1][:7]!=CAL[i][:7]]
    return si,ei,idx

def run(wfun, road, cadence="monthly", seed=None):
    start,end=ROADS[road]; si,ei,evals=eval_indices(cadence,start,end)
    evalset=set(evals)
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
    pos=sum(1 for r in rets if r>0); med=statistics.median(rets)
    streak=0; mx=0
    for r in rets:
        streak=streak+1 if r<=0 else 0; mx=max(mx,streak)
    peak=-1; last=0; mxnh=0
    for kix,k in enumerate(keys):
        if pts[k]>=peak: peak=pts[k]; last=kix
        mxnh=max(mxnh, kix-last)
    return {"periods":len(rets),"share_pos":round(100*pos/len(rets),1),"median_pct":round(med*100,2),"best_pct":round(max(rets)*100,2),"worst_pct":round(min(rets)*100,2),"avg_pct":round(statistics.mean(rets)*100,2),"longest_losing_streak":mx,"longest_no_new_high_periods":mxnh}

def top_pos(universe,i,n):
    sc=sorted(((S(t,i),t) for t in universe),reverse=True)
    return [t for s,t in sc if s>0][:n]

UNIV=["SPY","VGK","EWJ","EEM","VNQ","RWX","IEF","TLT","DBC","GLD"]

def kipnis_state(i):
    can=[S("EEM",i)>0, S("AGG",i)>0]
    expo=1.0 if all(can) else (0.5 if any(can) else 0.0)
    picks=top_pos(UNIV,i,5)
    return expo,picks

def w_kipnis_v13(i):
    """Best-rules DAAA: published signal/canary/top5, EQUAL-WEIGHT top 5."""
    expo,picks=kipnis_state(i)
    out={}
    if picks and expo>0:
        for t in picks: out[t]=expo/len(picks)
    pw=1.0-sum(out.values())
    if pw>0.01:
        d="IEF" if S("IEF",i)>0 else "BIL"; out[d]=out.get(d,0)+pw
    return out

def w_static_mix(i):
    return {t:1.0/len(UNIV) for t in UNIV}

def placebo_wfun(i, rng):
    picks=rng.sample(UNIV, 5)
    return {t:1.0/len(picks) for t in picks}

def time_in_defense(road):
    start,end=ROADS[road]; si,ei,evals=eval_indices("monthly",start,end)
    n100=n50=n0=0; def_share=[]
    for i in evals:
        if i>=ei: continue
        expo,picks=kipnis_state(i)
        if expo==1.0: n100+=1
        elif expo==0.5: n50+=1
        else: n0+=1
        tgt=w_kipnis_v13(i)
        def_share.append(tgt.get("IEF",0.0)+tgt.get("BIL",0.0))
    tot=n100+n50+n0
    return {"evals":tot,"pct_full_exposure":round(100*n100/tot,1) if tot else 0,
            "pct_half_exposure":round(100*n50/tot,1) if tot else 0,
            "pct_zero_exposure":round(100*n0/tot,1) if tot else 0,
            "avg_defensive_remainder_weight_pct":round(100*statistics.mean(def_share),1) if def_share else 0}

def main():
    res={"family":"catalog-taa-kipnis-daaa","program":"v13-best-rules",
         "spec":"BEST-RULES-SPEC.md","roads":{},"placebo_finals":{}}
    for road in ROADS:
        r=run(w_kipnis_v13,road)
        ctrl=run(w_static_mix,road)
        spy=run(lambda i: {"SPY":1.0},road)
        res["roads"][road]={"best_rules":r,"static_mix_control":ctrl,"spy_in_engine":spy,
                            "period_distribution_monthly":period_stats(r["equity"]),
                            "time_in_defense":time_in_defense(road)}
        finals=[run(placebo_wfun,road,seed=1000+s)["final"] for s in range(20)]
        res["placebo_finals"][road]=finals
        res["roads"][road]["placebos_beaten"]=sum(1 for f in finals if r["final"]>f)
        print(road, "best", r["final"], r["maxDD"], "ctrl", ctrl["final"], ctrl["maxDD"],
              "spy", spy["final"], "placebos_beaten", res["roads"][road]["placebos_beaten"], flush=True)
    out=os.path.join(os.path.dirname(os.path.abspath(__file__)),"results.json")
    json.dump(res, open(out,"w"), indent=1)
    print("wrote", out)

if __name__=="__main__":
    main()
