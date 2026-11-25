#!/usr/bin/env python3
"""V13 best-rules run for catalog-taa-keller-vaa. Spec: BEST-RULES-SPEC.md (frozen first).
Reuses the v12 slice engine's data plumbing (shared ETF cache, read-only)."""
import json, os, math, random, statistics, sys
import numpy as np
import pandas as pd
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/catalog-taa-keller-faa/data_etf_cache")
TICKS = ["SPY","EFA","EEM","AGG","LQD","IEF","BIL"]
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
def _retarr(t,n):
    a=ARR[t]; out=np.zeros(N)
    out[n:]=a[n:]/a[:-n]-1
    out[:n]=0; out[np.isnan(out)]=0
    return out
_R={ (t,n):_retarr(t,n) for t in TICKS for n in (21,63,126,252)}
def S(t,i): return 12*_R[(t,21)][i]+4*_R[(t,63)][i]+2*_R[(t,126)][i]+_R[(t,252)][i]
COST=0.0010
ROADS={"LONG":("2010-01-01","2026-11-20"),"DECADE":("2016-01-01","2026-11-20"),"CONT":("2019-01-01","2026-11-20"),"VAL":("2023-01-01","2026-11-20")}
DATES=[datetime.strptime(d,"%Y-%m-%d") for d in CAL]
RISKY=["SPY","EFA","EEM","AGG"]; DEF=["LQD","IEF","BIL"]

def eval_indices(start,end):
    si=next(i for i,d in enumerate(CAL) if d>=start); ei=max(i for i,d in enumerate(CAL) if d<=end)
    idx=[i for i in range(si,ei+1) if i==ei or CAL[i+1][:7]!=CAL[i][:7]]
    return si,ei,idx

def top_pos(universe,i,n):
    sc=sorted(((S(t,i),t) for t in universe),reverse=True)
    return [t for s,t in sc if s>0][:n]

def w_vaa(i):
    b=sum(1 for t in RISKY if S(t,i)>0)
    bestR=max(RISKY,key=lambda t:S(t,i))
    dp=top_pos(DEF,i,1); bestD=dp[0] if dp else "BIL"
    if b==4: return {bestR:1.0}
    dw=(4-b)/4.0
    if S(bestR,i)>0: return {bestR:1-dw, bestD:dw}
    return {bestD:1.0}

def w_noswitch(i):
    bestR=max(RISKY,key=lambda t:S(t,i))
    if S(bestR,i)>0: return {bestR:1.0}
    dp=top_pos(DEF,i,1); return {(dp[0] if dp else "BIL"):1.0}

STATIC={**{t:0.75/4 for t in RISKY}, **{t:0.25/3 for t in DEF}}
def w_static(i): return dict(STATIC)
def w_spy(i): return {"SPY":1.0}

def run(wfun, road, seed=None, track_defense=False):
    start,end=ROADS[road]; si,ei,evals=eval_indices(start,end)
    evalset=set(evals)
    rng=random.Random(seed) if seed is not None else None
    cash=100.0; shares={}; costs=0.0; orders=0; eq=[]
    pending=None; last_target=None; switches=0
    defw_months=[]  # defensive weight at each eval target
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
        v=value(i); eq.append((CAL[i],round(v,4)))
        if i in evalset and i<ei:
            tgt=wfun(i,rng) if rng is not None else wfun(i)
            if tgt is not None:
                if track_defense:
                    defw_months.append(sum(w for t,w in tgt.items() if t in DEF))
                    if last_target is not None and tgt!=last_target: switches+=1
                    last_target=dict(tgt)
                pending=(i+1,tgt)
    final=eq[-1][1] if eq else cash
    peak=-1; mdd=0.0
    for _,v in eq:
        peak=max(peak,v); mdd=min(mdd, v/peak-1 if peak>0 else 0)
    out={"final":round(final,2),"maxDD":round(mdd*100,2),"costs":round(costs,2),"orders":orders,"equity":eq}
    if track_defense and defw_months:
        out["switch_diagnostics"]={
            "eval_months":len(defw_months),
            "switches":switches,
            "share_months_any_defense":round(100*sum(1 for w in defw_months if w>0.001)/len(defw_months),1),
            "share_months_full_defense":round(100*sum(1 for w in defw_months if w>0.999)/len(defw_months),1),
            "avg_defensive_weight_pct":round(100*statistics.mean(defw_months),1),
        }
    return out

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
    # trade-level expectancy proxy: monthly period expectancy = mean period return (labeled secondary)
    return {"periods":len(rets),"share_pos":round(100*pos/len(rets),1),"median_pct":round(med*100,2),
            "best_pct":round(max(rets)*100,2),"worst_pct":round(min(rets)*100,2),
            "avg_pct":round(statistics.mean(rets)*100,2),
            "longest_losing_streak":mx,"longest_no_new_high_periods":mxnh}

def placebo_wfun(i, rng):
    pick=rng.sample(RISKY,1)
    return {pick[0]:1.0}

def main():
    res={"family":"catalog-taa-keller-vaa","program":"v13-best-rules","roads":{}}
    for road in ROADS:
        prim=run(w_vaa,road,track_defense=True)
        entry={
            "primary_v13":prim,
            "benchmark_spy_buyhold":run(w_spy,road),
            "benchmark_static_mix":run(w_static,road),
            "ablation_noswitch_offense":run(w_noswitch,road),
            "period_distribution_primary_monthly":period_stats(prim["equity"]),
            "period_distribution_spy_monthly":period_stats(run(w_spy,road)["equity"]),
        }
        res["roads"][road]=entry
        print(road, "primary", prim["final"], "DD", prim["maxDD"], "| spy", entry["benchmark_spy_buyhold"]["final"],
              "| static", entry["benchmark_static_mix"]["final"], "| noswitch", entry["ablation_noswitch_offense"]["final"],
              "| diag", prim.get("switch_diagnostics"), flush=True)
    res["placebo_finals"]={}
    for road in ("LONG","DECADE"):
        finals=[run(placebo_wfun,road,seed=1000+s)["final"] for s in range(20)]
        res["placebo_finals"][road]=finals
        beaten=sum(1 for f in finals if res["roads"][road]["primary_v13"]["final"]>f)
        res["roads"][road]["placebos_beaten"]=beaten
        print(road,"placebos beaten",beaten,"/20  median placebo",round(statistics.median(finals),2), flush=True)
    json.dump(res, open(os.path.join(BASE,"results.json"),"w"), indent=1)
    print("DONE")

if __name__=="__main__":
    main()
