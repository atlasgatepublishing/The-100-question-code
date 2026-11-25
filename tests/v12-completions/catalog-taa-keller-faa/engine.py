#!/usr/bin/env python3
import json, os, math, random, statistics, sys, glob
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
def ret(t,i,n):
    if i-n<0: return 0.0
    a,b=ARR[t][i-n],ARR[t][i]
    if np.isnan(a) or np.isnan(b) or a<=0: return 0.0
    return b/a-1
def _retarr(t,n):
    a=ARR[t]; out=np.zeros(N)
    out[n:]=a[n:]/a[:-n]-1
    out[:n]=0; out[np.isnan(out)]=0
    return out
_R={ (t,n):_retarr(t,n) for t in TICKS for n in (21,63,126,252,84)}
def S(t,i): return 12*_R[(t,21)][i]+4*_R[(t,63)][i]+2*_R[(t,126)][i]+_R[(t,252)][i]
_VC={}
def vol(t,i,n=84):
    key=(t,n)
    if key not in _VC:
        s=pd.Series(ARR[t]); _VC[key]=s.pct_change().rolling(n).std().fillna(0).values
    return float(_VC[key][i])
COST=0.0010
ROADS={"LONG":("2010-01-01","2026-11-20"),"DECADE":("2016-01-01","2026-11-20"),"CONT":("2019-01-01","2026-11-20"),"VAL":("2023-01-01","2026-11-20")}

DATES=[datetime.strptime(d,"%Y-%m-%d") for d in CAL]
_EVALC={}
def eval_indices(cadence, start, end):
    key=(cadence,start,end)
    if key in _EVALC: return _EVALC[key]
    si=next(i for i,d in enumerate(CAL) if d>=start); ei=max(i for i,d in enumerate(CAL) if d<=end)
    if cadence=="monthly":
        idx=[i for i in range(si,ei+1) if i==ei or CAL[i+1][:7]!=CAL[i][:7]]
    elif cadence=="weekly":
        wk=[d.isocalendar()[1] for d in DATES]
        idx=[i for i in range(si,ei+1) if i==ei or wk[i+1]!=wk[i]]
    elif cadence=="biweekly":
        idx=eval_indices("weekly",start,end)[2][::2]
    elif cadence=="quarterly":
        idx=[i for i in eval_indices("monthly",start,end)[2] if CAL[i][5:7] in ("03","06","09","12")]
    elif cadence=="semiannual":
        idx=[i for i in eval_indices("monthly",start,end)[2] if CAL[i][5:7] in ("06","12")]
    elif cadence=="annual":
        idx=[i for i in eval_indices("monthly",start,end)[2] if CAL[i][5:7]=="12"]
    elif cadence=="daily":
        idx=list(range(si,ei+1))
    _EVALC[key]=(si,ei,idx)
    return _EVALC[key]

def run(wfun, road, cadence="monthly", house=False, seed=None):
    start,end=ROADS[road]; si,ei,evals=eval_indices(cadence,start,end)
    evalset=set(evals)
    rng=random.Random(seed) if seed is not None else None
    cash=100.0; shares={}; costs=0.0; orders=0; eq=[]
    ep_start=100.0; halts=0; cash_until=-1
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
        if house and halts<2:
            if i<cash_until: continue
            if v<=0.85*ep_start:
                for t in list(shares.keys()):
                    p=ARR[t][i]
                    if shares[t]>0 and not np.isnan(p): cash+=shares[t]*p*(1-COST); shares[t]=0.0
                halts+=1; ep_start=cash; pending=None
                if halts>=2: cash_until=10**9
                else:
                    j=i
                    while j<N and (DATES[j]-DATES[i]).days<90: j+=1
                    cash_until=j
                continue
        if i in evalset and i<ei and not (house and i<cash_until):
            tgt=wfun(i,rng) if rng is not None else wfun(i)
            if tgt is not None: pending=(i+1,tgt)
    final=eq[-1][1] if eq else cash
    peak=-1; mdd=0.0
    for _,v in eq:
        peak=max(peak,v); mdd=min(mdd, v/peak-1 if peak>0 else 0)
    return {"final":round(final,2),"maxDD":round(mdd*100,2),"costs":round(costs,2),"orders":orders,"halts":halts,"equity":eq}

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

def top_pos(universe,i,n,score=None):
    score=score or S
    sc=sorted(((score(t,i),t) for t in universe),reverse=True)
    return [t for s,t in sc if s>0][:n], sc
def def_top(i):
    picks,_=top_pos(["IEF","BIL"],i,1); return picks[0] if picks else "BIL"

_FAAC={}
def _faa_order(i):
    if i in _FAAC: return _FAAC[i]
    U=["SPY","VEA","VWO","AGG","VNQ","DBC","SHY"]
    rR={t:-ret(t,i,84) for t in U}; rV={t:vol(t,i) for t in U}
    rets={}
    for t in U:
        w=ARR[t][i-84:i+1]; rets[t]=np.diff(w)/w[:-1]
    rC={}
    for t in U:
        cs=[]
        for u in U:
            if u==t: continue
            a,b=rets[t],rets[u]; m=~np.isnan(a)&~np.isnan(b)
            if m.sum()>10: cs.append(np.corrcoef(a[m],b[m])[0,1])
        rC[t]=float(np.mean(cs)) if cs else 0.0
    def ranks(d):
        order=sorted(d,key=lambda k:d[k]); return {k:j+1 for j,k in enumerate(order)}
    kR,kV,kC=ranks(rR),ranks(rV),ranks(rC)
    L={t:kR[t]+0.5*kV[t]+0.5*kC[t] for t in U}
    order=sorted(L,key=lambda k:L[k]); _FAAC[i]=order; return order
def w_faa(i, topn=3):
    picks=_faa_order(i)[:topn]; out={}
    for t in picks:
        k="SHY" if ret(t,i,84)<0 else t
        out[k]=out.get(k,0)+1.0/topn
    return out

def w_haa(i, topn=4):
    if ret("TIP",i,21) > ret("BIL",i,21):
        picks,_=top_pos(["SPY","IWM","VEA","VWO","VNQ","DBC","GLD","AGG"],i,topn)
        out={t:1.0/topn for t in picks}
        rem=1.0-sum(out.values())
        if rem>0.01:
            dp,_=top_pos(["IEF","TLT","SHY"],i,2)
            if dp:
                for t in dp: out[t]=out.get(t,0)+rem/len(dp)
            else: out["BIL"]=out.get("BIL",0)+rem
        return out
    dp,_=top_pos(["IEF","TLT","SHY"],i,2)
    if not dp: return {"BIL":1.0}
    return {t:1.0/len(dp) for t in dp}
def w_haa_simple(i):
    return {"SPY":1.0} if ret("TIP",i,21)>ret("BIL",i,21) else {"IEF":1.0}

def w_laa(i):
    sma=np.nanmean(ARR["SPY"][i-210:i+1])
    timed="SPY" if ARR["SPY"][i]>sma else "IEF"
    return {"QQQ":0.25,"IWM":0.25,"GLD":0.25,timed:0.25}

def w_paa(i, topn=3):
    R=["SPY","EFA","EEM","VNQ","DBC","TLT"]
    a=sum(1 for t in R if S(t,i)>0)
    picks,_=top_pos(R,i,topn)
    out={}
    rw=a/6.0
    if picks:
        for t in picks: out[t]=rw/topn
    pw=1.0-sum(out.values())
    if pw>0.01:
        d=def_top(i); out[d]=out.get(d,0)+pw
    return out

def w_gpm(i, topn=3):
    R=["SPY","QQQ","EFA","EEM","VNQ","DBC","GLD","TLT","LQD","AGG"]
    expo=sum(1 for t in R if S(t,i)>0)/len(R)
    picks,_=top_pos(R,i,topn)
    out={}
    if picks:
        for t in picks: out[t]=expo/topn
    pw=1.0-sum(out.values())
    if pw>0.01:
        d=def_top(i); out[d]=out.get(d,0)+pw
    return out

def w_raa(i, topn=5):
    R=["SPY","VGK","EWJ","EEM","VNQ","RWX","IEF","TLT","DBC","GLD"]
    s=sum(1 for t in R if S(t,i)>0)/len(R)
    expo=1.0 if s>=0.999 else (0.5 if s>=0.5 else 0.0)
    picks,_=top_pos(R,i,topn)
    out={}
    if picks and expo>0:
        for t in picks: out[t]=expo/topn
    pw=1.0-sum(out.values())
    if pw>0.01:
        d="IEF" if S("IEF",i)>0 else "BIL"; out[d]=out.get(d,0)+pw
    return out

def w_vaa(i):
    R=["SPY","EFA","EEM","AGG"]; D=["LQD","IEF","BIL"]
    b=sum(1 for t in R if S(t,i)>0)
    bestR=max(R,key=lambda t:S(t,i))
    dp,_=top_pos(D,i,1); bestD=dp[0] if dp else "BIL"
    if b==4: return {bestR:1.0}
    dw=(4-b)/4.0
    if S(bestR,i)>0: return {bestR:1-dw, bestD:dw}
    return {bestD:1.0}

def w_kipnis(i, topn=5):
    U=["SPY","VGK","EWJ","EEM","VNQ","RWX","IEF","TLT","DBC","GLD"]
    can=[S("EEM",i)>0, S("AGG",i)>0]
    expo=1.0 if all(can) else (0.5 if any(can) else 0.0)
    picks,_=top_pos(U,i,topn)
    out={}
    if picks and expo>0:
        iv={t:(1.0/vol(t,i,21) if vol(t,i,21)>0 else 0.0) for t in picks}
        tot=sum(iv.values())
        for t in picks: out[t]=expo*iv[t]/tot if tot>0 else expo/len(picks)
    pw=1.0-sum(out.values())
    if pw>0.01:
        d="IEF" if S("IEF",i)>0 else "BIL"; out[d]=out.get(d,0)+pw
    return out

CLI_DIR=os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/catalog-taa-link-global-growth-cycle/data_cli")
def load_cli():
    series={}
    for f in glob.glob(os.path.join(CLI_DIR,"cli_*.csv")):
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
def w_ggc_orig(i):
    di=diffusion(i)
    if di is None: return {"BIL":1.0}
    return {"SPY":1.0} if di>0.5 else {"BIL":1.0}
def w_ggc_enh(i):
    di=diffusion(i)
    if di is None: return {"BIL":1.0}
    if di>0.5:
        return {"SPY":1.0} if ret("SPY",i,252)>=ret("EFA",i,252) else {"EFA":1.0}
    return {"AGG":1.0} if ret("AGG",i,252)>ret("BIL",i,252) else {"BIL":1.0}

def w_mtp(i):
    U=["SPY","EFA","IEF","BWX","DBC","GLD"]
    out={}
    for t in U:
        lt=ret(t,i,252)-ret("BIL",i,252); st=ret(t,i,21)-ret("BIL",i,21)
        expo=1.0 if (lt>0 and st>0) else (0.5 if (lt>0)!=(st>0) else 0.0)
        if expo>0: out[t]=expo/6.0
    pw=1.0-sum(out.values())
    if pw>0.01: out["BIL"]=out.get("BIL",0)+pw
    return out

STRATS={
 "catalog-taa-keller-faa": (w_faa, ["SPY","VEA","VWO","AGG","VNQ","DBC"], 3),
 "catalog-taa-keller-haa": (w_haa, ["SPY","IWM","VEA","VWO","VNQ","DBC","GLD","AGG"], 4),
 "catalog-taa-keller-laa": (w_laa, ["SPY","QQQ","IWM","GLD"], None),
 "catalog-taa-keller-paa": (w_paa, ["SPY","EFA","EEM","VNQ","DBC","TLT"], 3),
 "catalog-taa-keller-paa-gpm": (w_gpm, ["SPY","QQQ","EFA","EEM","VNQ","DBC","GLD","TLT","LQD","AGG"], 3),
 "catalog-taa-keller-raa": (w_raa, ["SPY","VGK","EWJ","EEM","VNQ","RWX","IEF","TLT","DBC","GLD"], 5),
 "catalog-taa-keller-vaa": (w_vaa, ["SPY","EFA","EEM","AGG"], 1),
 "catalog-taa-kipnis-daaa": (w_kipnis, ["SPY","VGK","EWJ","EEM","VNQ","RWX","IEF","TLT","DBC","GLD"], 5),
 "catalog-taa-link-global-growth-cycle": (w_ggc_enh, ["SPY","EFA","AGG"], 1),
 "catalog-taa-momentum-turning-points": (w_mtp, ["SPY","EFA","IEF","BWX","DBC","GLD"], None),
}
def placebo_wfun(universe, n):
    def f(i, rng):
        n2=n if n is not None else max(1,len(universe)//2)
        picks=rng.sample(universe, min(n2,len(universe)))
        return {t:1.0/len(picks) for t in picks}
    return f

def main(slug):
    wfun, universe, topn = STRATS[slug]
    base=os.path.expanduser(f"~/workspace/stock-app/backtests/v12-completions/{slug}")
    res={"family":slug,"roads":{},"grid":{}}
    for road in ROADS:
        nat=run(wfun,road); hou=run(wfun,road,house=True)
        res["roads"][road]={"native":nat,"house":hou,"period_distribution_native_monthly":period_stats(nat["equity"])}
    pw=placebo_wfun(universe, topn)
    res["placebo_finals"]={}
    for road in ("LONG","DECADE"):
        finals=[run(pw,road,seed=1000+s)["final"] for s in range(20)]
        res["placebo_finals"][road]=finals
        res["roads"][road]["placebos_beaten"]=sum(1 for f in finals if res["roads"][road]["native"]["final"]>f)
    variants=[None]
    if topn is not None: variants=[1,2,3,5,8,10,"ALL"]
    for cad in ("weekly","biweekly","monthly","quarterly","semiannual","annual"):
        for v in variants:
            if v is None:
                wf=wfun; key=cad
            else:
                n = len(universe) if v=="ALL" else v
                if slug=="catalog-taa-keller-faa": wf=lambda i,n=n: w_faa(i,topn=n)
                elif slug=="catalog-taa-keller-haa": wf=lambda i,n=n: w_haa(i,topn=n)
                elif slug=="catalog-taa-keller-paa": wf=lambda i,n=n: w_paa(i,topn=n)
                elif slug=="catalog-taa-keller-paa-gpm": wf=lambda i,n=n: w_gpm(i,topn=n)
                elif slug=="catalog-taa-keller-raa": wf=lambda i,n=n: w_raa(i,topn=n)
                elif slug=="catalog-taa-kipnis-daaa": wf=lambda i,n=n: w_kipnis(i,topn=n)
                else: wf=wfun
                key=f"{cad}/top{v}"
            r=run(wf,"DECADE",cadence=cad)
            pw2=placebo_wfun(universe, topn if v is None else (len(universe) if v=="ALL" else v))
            pf=[run(pw2,"DECADE",cadence=cad,seed=2000+s)["final"] for s in range(20)]
            res["grid"][key]={"final":r["final"],"maxDD":r["maxDD"],"placebos_beaten":sum(1 for f in pf if r["final"]>f),"placebo_finals":pf}
    if slug=="catalog-taa-keller-haa":
        res["variant_haa_simple"]={road:run(w_haa_simple,road) for road in ROADS}
    if slug=="catalog-taa-link-global-growth-cycle":
        res["variant_ggc_original"]={road:run(w_ggc_orig,road) for road in ROADS}
    json.dump(res, open(os.path.join(base,"results.json"),"w"), indent=1)
    with open(os.path.join(base,"grid","grid_results.json"),"w") as f: json.dump(res["grid"],f,indent=1)
    print(slug, {r:res["roads"][r]["native"]["final"] for r in ROADS}, flush=True)

if __name__=="__main__":
    main(sys.argv[1])
