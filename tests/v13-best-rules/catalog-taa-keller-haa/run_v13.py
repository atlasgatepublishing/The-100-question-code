#!/usr/bin/env python3
"""V13 best-rules run for catalog-taa-keller-haa. Spec: BEST-RULES-SPEC.md (frozen before run).
Reuses the v12 slice data cache read-only; identical costs/execution plumbing to v12."""
import json, os, random, statistics
import numpy as np
from datetime import datetime, timezone

CACHE = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/catalog-taa-keller-faa/data_etf_cache")
TICKS = ["SPY","IWM","VEA","VWO","VNQ","DBC","GLD","AGG","IEF","TLT","SHY","BIL","TIP"]
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
    a=ARR[t]; out=np.zeros(N); out[n:]=a[n:]/a[:-n]-1; out[:n]=0; out[np.isnan(out)]=0; return out
_R={(t,n):_retarr(t,n) for t in TICKS for n in (21,63,126,252)}
def ret(t,i,n): return float(_R[(t,n)][i])
def S(t,i): return 12*_R[(t,21)][i]+4*_R[(t,63)][i]+2*_R[(t,126)][i]+_R[(t,252)][i]
COST=0.0010
ROADS={"LONG":("2010-01-01","2026-11-20"),"DECADE":("2016-01-01","2026-11-20"),"CONT":("2019-01-01","2026-11-20"),"VAL":("2023-01-01","2026-11-20")}
CHAMP={"LONG":1415.62,"CONT":544.47,"VAL":288.05,"DECADE":667.35}
SPYREF={"LONG":822.94,"CONT":313.62,"VAL":187.77,"DECADE":367.80}
RISKY=["SPY","IWM","VEA","VWO","VNQ","DBC","GLD","AGG"]
DEF=["IEF","TLT","SHY"]

def eval_indices(start,end):
    si=next(i for i,d in enumerate(CAL) if d>=start); ei=max(i for i,d in enumerate(CAL) if d<=end)
    idx=[i for i in range(si,ei+1) if i==ei or CAL[i+1][:7]!=CAL[i][:7]]
    return si,ei,idx

def ranked(universe,i):
    return sorted(((S(t,i),t) for t in universe),reverse=True)
def def_target(i,weight):
    picks=[t for s,t in ranked(DEF,i) if s>0][:2]
    if not picks: return {"BIL":weight}
    return {t:weight/len(picks) for t in picks}

def make_target(buffer=False, canary=True):
    """Returns stateful target fn(i, state)->dict. state['risky']=current risky holdings list."""
    def f(i, state):
        risk_on = (ret("TIP",i,21) > ret("BIL",i,21)) if canary else True
        if not risk_on:
            state["risky"]=[]
            return def_target(i,1.0)
        rk=ranked(RISKY,i)
        pos=[t for s,t in rk if s>0]
        top6=set(pos[:6])
        if buffer:
            kept=[t for t in state["risky"] if t in top6]
            picks=list(kept)
            for t in pos:
                if len(picks)>=4: break
                if t not in picks: picks.append(t)
        else:
            picks=pos[:4]
        state["risky"]=list(picks)
        out={t:0.25 for t in picks}
        rem=1.0-sum(out.values())
        if rem>0.01:
            for t,w in def_target(i,rem).items(): out[t]=out.get(t,0)+w
        return out
    return f

def run(tfun, road=None, start=None, end=None, seed=None):
    if road: start,end=ROADS[road]
    si,ei,evals=eval_indices(start,end); evalset=set(evals)
    rng=random.Random(seed) if seed is not None else None
    state={"risky":[]}
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
            tgt=tfun(i,rng) if rng is not None else tfun(i,state)
            if tgt is not None: pending=(i+1,tgt)
    final=eq[-1][1] if eq else cash
    peak=-1; mdd=0.0
    for _,v in eq:
        peak=max(peak,v); mdd=min(mdd, v/peak-1 if peak>0 else 0)
    return {"final":round(final,2),"maxDD":round(mdd*100,2),"costs":round(costs,2),"orders":orders,"equity":eq}

def period_stats(eq):
    pts={}
    for d,v in eq: pts[d[:7]]=v
    keys=sorted(pts); rets=[pts[b]/pts[a]-1 for a,b in zip(keys,keys[1:])]
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
            "best_pct":round(max(rets)*100,2),"worst_pct":round(min(rets)*100,2),"avg_pct":round(statistics.mean(rets)*100,2),
            "longest_losing_streak":mx,"longest_no_new_high_periods":mxnh}

def buyhold(ticker, start, end, weight=1.0):
    si=next(i for i,d in enumerate(CAL) if d>=start); ei=max(i for i,d in enumerate(CAL) if d<=end)
    eq=[]; p0=ARR[ticker][si]
    for i in range(si,ei+1):
        eq.append((CAL[i], round(100*weight*(1-COST)*ARR[ticker][i]/p0 + (100*(1-weight) if weight<1 else 0),4)))
    return eq
def static_mix(start,end):
    si=next(i for i,d in enumerate(CAL) if d>=start); ei=max(i for i,d in enumerate(CAL) if d<=end)
    eq=[]
    for i in range(si,ei+1):
        v=60*(1-COST)*ARR["SPY"][i]/ARR["SPY"][si] + 40*(1-COST)*ARR["AGG"][i]/ARR["AGG"][si]
        eq.append((CAL[i],round(v,4)))
    peak=-1; mdd=0.0
    for _,v in eq: peak=max(peak,v); mdd=min(mdd,v/peak-1 if peak>0 else 0)
    return {"final":round(eq[-1][1],2),"maxDD":round(mdd*100,2),"equity":eq}
def summarize(eq):
    peak=-1; mdd=0.0
    for _,v in eq: peak=max(peak,v); mdd=min(mdd,v/peak-1 if peak>0 else 0)
    return {"final":round(eq[-1][1],2),"maxDD":round(mdd*100,2)}

def placebo_fun(i, rng):
    picks=rng.sample(RISKY,4)
    return {t:0.25 for t in picks}

def main():
    res={"family":"catalog-taa-keller-haa","program":"v13-best-rules","roads":{},"placebo_finals":{}}
    main_f=make_target(buffer=True, canary=True)
    pub_f=make_target(buffer=False, canary=True)
    abl_f=make_target(buffer=True, canary=False)
    for road in ROADS:
        start,end=ROADS[road]
        # fresh stateful fns per road (state resets via new closures in run? state is per-run dict) -> make_target closures are stateless; state lives in run()
        m=run(make_target(buffer=True,canary=True),road=road)
        p=run(make_target(buffer=False,canary=True),road=road)
        a=run(make_target(buffer=True,canary=False),road=road)
        spy=summarize(buyhold("SPY",start,end))
        mix=static_mix(start,end)
        res["roads"][road]={"main":m,"published_rerun":p,"ablation_no_canary":a,
                            "spy_buyhold":spy,"static_mix_60_40":mix,
                            "period_distribution_main_monthly":period_stats(m["equity"]),
                            "period_distribution_published_monthly":period_stats(p["equity"]),
                            "period_distribution_ablation_monthly":period_stats(a["equity"])}
        print(road,"main",m["final"],m["maxDD"],"pub",p["final"],"abl",a["final"],"spy",spy["final"],"mix",mix["final"],flush=True)
    for road in ("LONG","DECADE"):
        finals=[run(placebo_fun,road=road,seed=1000+s)["final"] for s in range(20)]
        res["placebo_finals"][road]=finals
        res["roads"][road]["placebos_beaten_main"]=sum(1 for f in finals if res["roads"][road]["main"]["final"]>f)
        res["roads"][road]["placebos_beaten_published"]=sum(1 for f in finals if res["roads"][road]["published_rerun"]["final"]>f)
        print(road,"placebos beaten main",res["roads"][road]["placebos_beaten_main"],"/20",flush=True)
    # Confirmation (frozen bars in spec) — only if a road beats champion V+M
    res["confirmation"]={}
    for road in ROADS:
        if res["roads"][road]["main"]["final"]>CHAMP[road]:
            start,end=ROADS[road]
            y0=int(start[:4]); y1=int(end[:4])
            folds={}; mixfolds={}
            for y in range(y0,y1+1):
                fs=f"{y}-01-01"; fe=min(f"{y}-12-31",end)
                if fs<start: fs=start
                folds[str(y)]=run(make_target(buffer=True,canary=True),start=fs,end=fe)["final"]
                mixfolds[str(y)]=static_mix(fs,fe)["final"]
            yrs=sorted(folds); above=sum(1 for y in yrs if folds[y]>100)
            med_main=statistics.median([folds[y] for y in yrs]); med_mix=statistics.median([mixfolds[y] for y in yrs])
            si,ei,_=eval_indices(start,end); mid=CAL[(si+ei)//2]
            h1=run(make_target(buffer=True,canary=True),start=start,end=mid)
            h2=run(make_target(buffer=True,canary=True),start=mid,end=end)
            spy1=summarize(buyhold("SPY",start,mid)); spy2=summarize(buyhold("SPY",mid,end))
            mix1=static_mix(start,mid); mix2=static_mix(mid,end)
            bar_a = (above>len(yrs)/2) and (med_main>med_mix)
            bar_b = (h1["final"]>spy1["final"] or h2["final"]>spy2["final"]) and (h1["final"]>=mix1["final"] and h2["final"]>=mix2["final"])
            res["confirmation"][road]={"yearly_folds":folds,"static_mix_folds":mixfolds,"folds_above_100":above,
                "median_fold_main":med_main,"median_fold_mix":med_mix,"half1":{"main":h1["final"],"spy":spy1["final"],"mix":mix1["final"]},
                "half2":{"main":h2["final"],"spy":spy2["final"],"mix":mix2["final"]},"bar_a_pass":bar_a,"bar_b_pass":bar_b,"confirmed":bool(bar_a and bar_b)}
            print(road,"CONFIRMATION confirmed=",bar_a and bar_b,flush=True)
        else:
            res["confirmation"][road]="not triggered (main did not beat champion V+M on this road)"
    json.dump(res,open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"results.json"),"w"),indent=1)
    print("DONE")

if __name__=="__main__":
    main()
