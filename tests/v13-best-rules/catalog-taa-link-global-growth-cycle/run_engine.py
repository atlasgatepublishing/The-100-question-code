#!/usr/bin/env python3
"""V13 best-rules: Link GGC Enhanced with DI-as-weight dial. Spec: BEST-RULES-SPEC.md (frozen)."""
import json, os, random, statistics, glob
import numpy as np, pandas as pd
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/catalog-taa-keller-faa/data_etf_cache")
CLI_DIR = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/catalog-taa-link-global-growth-cycle/data_cli")
TICKS = ["SPY","EFA","AGG","BIL"]
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

def load_cli():
    series={}
    for f in sorted(glob.glob(os.path.join(CLI_DIR,"cli_*.csv"))):
        rows=open(f).read().strip().splitlines()[1:]
        d={}
        for r in rows:
            p=r.split(",")
            if len(p)==2 and p[1]: d[p[0][:7]]=float(p[1])
        series[f]=d
    return series
CLI=load_cli()
def diffusion(i):
    y,m=int(CAL[i][:4]),int(CAL[i][5:7])
    def shift(y,m,k):
        m-=k
        while m<=0: m+=12; y-=1
        return f"{y:04d}-{m:02d}"
    cur,prev=shift(y,m,2),shift(y,m,3)
    up=tot=0
    for s in CLI.values():
        if cur in s and prev in s:
            tot+=1; up+= 1 if s[cur]>s[prev] else 0
    return (up/tot) if tot>=5 else None

def defensive_asset(i):
    return "AGG" if ret("AGG",i,252)>ret("BIL",i,252) else "BIL"
def equity_asset(i):
    return "SPY" if ret("SPY",i,252)>=ret("EFA",i,252) else "EFA"

def w_dial(i):
    di=diffusion(i)
    if di is None: return {"BIL":1.0}
    out={}
    if di>0: out[equity_asset(i)]=di
    if di<1: out[defensive_asset(i)]=1.0-di
    return out
def w_published(i):
    di=diffusion(i)
    if di is None: return {"BIL":1.0}
    if di>0.5: return {equity_asset(i):1.0}
    return {defensive_asset(i):1.0}
def w_static(i):
    return {"SPY":0.6,"AGG":0.4}
def w_spy(i):
    return {"SPY":1.0}
def placebo_wfun():
    def f(i,rng):
        w=rng.random(); eq=rng.choice(["SPY","EFA"])
        return {eq:w, defensive_asset(i):1.0-w}
    return f

def run(wfun, road, seed=None):
    start,end=ROADS[road]; si,ei,evals=eval_indices(start,end); evalset=set(evals)
    rng=random.Random(seed) if seed is not None else None
    cash=100.0; shares={}; costs=0.0; orders=0; eq=[]; pending=None
    def value(i):
        v=cash
        for t,sh in shares.items():
            if sh>0 and not np.isnan(ARR[t][i]): v+=sh*ARR[t][i]
        return v
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
        eq.append((CAL[i],round(value(i),4)))
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
    streak=mx=0
    for r in rets:
        streak=streak+1 if r<=0 else 0; mx=max(mx,streak)
    peak=-1; last=0; mxnh=0
    for kix,k in enumerate(keys):
        if pts[k]>=peak: peak=pts[k]; last=kix
        mxnh=max(mxnh,kix-last)
    return {"periods":len(rets),"share_pos":round(100*pos/len(rets),1),"median_pct":round(med*100,2),
            "best_pct":round(max(rets)*100,2),"worst_pct":round(min(rets)*100,2),
            "avg_pct":round(statistics.mean(rets)*100,2),"longest_losing_streak":mx,
            "longest_no_new_high_periods":mxnh}

def yearly_stats(eq):
    yrs={}
    for d,v in eq: yrs[d[:4]]=v
    keys=sorted(yrs); out={}
    prev=None
    for k in keys:
        if prev is not None: out[k]=round(yrs[k]/prev-1,4)
        prev=yrs[k]
    return out

def main():
    res={"family":"catalog-taa-link-global-growth-cycle","variant":"v13-best-rules DI-dial, monthly, no floor",
         "data_fence":"CLI is current-vintage FRED (revised, not point-in-time vintages); availability lag T-2 vs T-3 honoured. Bias FLATTERS.",
         "roads":{}}
    pw=placebo_wfun()
    for road in ROADS:
        mine=run(w_dial,road); pub=run(w_published,road); spy=run(w_spy,road); static=run(w_static,road)
        finals=[run(pw,road,seed=3000+s)["final"] for s in range(20)]
        res["roads"][road]={"best_rules":mine,"published_recomputed":pub,"spy_buyhold":spy,"static_60_40":static,
            "period_distribution":period_stats(mine["equity"]),"yearly_returns":yearly_stats(mine["equity"]),
            "placebo_finals":finals,"placebos_beaten":sum(1 for f in finals if mine["final"]>f)}
        print(road, "mine",mine["final"],mine["maxDD"],"pub",pub["final"],"spy",spy["final"],"static",static["final"],"placebos",res["roads"][road]["placebos_beaten"],flush=True)
    json.dump(res,open(os.path.join(BASE,"results.json"),"w"),indent=1)
if __name__=="__main__": main()
