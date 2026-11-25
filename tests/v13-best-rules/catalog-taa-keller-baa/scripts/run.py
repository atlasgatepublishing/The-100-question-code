#!/usr/bin/env python3
"""V13 Best Rules — Keller BAA. Spec frozen in BEST-RULES-SPEC.md before this run.
My form: published BAA verbatim, QUARTERLY cadence, NO floor.
Comparators: published monthly form; no-canary quarterly ablation; static EW-12 quarterly.
Data read-only from v12 folder. Costs 0.10%/side. $100 pots."""
import json, os, sys
import numpy as np, pandas as pd

HERE=os.path.dirname(os.path.abspath(__file__)); FOLDER=os.path.dirname(HERE)
DATA=os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/catalog-taa-keller-baa/data")
COST=0.001
ROADS={"LONG":"2010-01-01","DECADE":"2016-01-01","CONT":"2019-01-01","VAL":"2023-01-01"}
END="2026-11-20"
CHAMP={"LONG":1415.62,"CONT":544.47,"VAL":288.05,"DECADE":667.35}
OFF=["SPY","QQQ","IWM","VGK","EWJ","VWO","VNQ","DBC","GLD","TLT","HYG","LQD"]
DFN=["TIP","DBC","BIL","IEF","TLT","LQD","BND"]
HOLDABLE=["SPY","QQQ","IWM","VGK","EWJ","VWO","VEA","VNQ","DBC","GLD","TLT","HYG","LQD","TIP","BIL","IEF","BND"]

def load():
    out={}
    for fn in os.listdir(DATA):
        if fn.endswith(".csv") and fn[:-4].isupper() and len(fn)<=8:
            p=os.path.join(DATA,fn)
            hdr=pd.read_csv(p,nrows=0).columns
            if "adjclose" in hdr:
                df=pd.read_csv(p,parse_dates=["date"]); out[fn[:-4]]=df.set_index("date")["adjclose"]
    return pd.DataFrame(out).sort_index()
PX=load(); _g=PX.index.to_series().groupby([PX.index.year,PX.index.month]); ME=PX.loc[_g.max().values]
DAYS=PX.index; PXV=PX.values; COL={t:j for j,t in enumerate(PX.columns)}; REBAL_POS=set(PX.index.get_indexer(ME.index)); BIL_C=COL["BIL"]

def m136(i,t):
    if i<12: return np.nan
    p=ME[t]; return 12*(p.iloc[i]/p.iloc[i-1]-1)+4*(p.iloc[i]/p.iloc[i-3]-1)+2*(p.iloc[i]/p.iloc[i-6]-1)+(p.iloc[i]/p.iloc[i-12]-1)
def sma(i,t):
    if i<12: return np.nan
    return ME[t].iloc[i]/ME[t].iloc[i-12:i+1].mean()

def w_baa(i, canary=True):
    if canary:
        can=[m136(i,t) for t in ["SPY","VWO","VEA","BND"]]
        if any(np.isnan(can)): return {}
        if not all(x>0 for x in can):
            rs=sorted(DFN,key=lambda t:-sma(i,t)); bil=sma(i,"BIL"); w={}
            for t in rs[:3]:
                tgt=t if sma(i,t)>=bil else "BIL"; w[tgt]=w.get(tgt,0)+1/3
            return w
    rs=sorted(OFF,key=lambda t:-sma(i,t)); return {t:1/6 for t in rs[:6]}
def w_static(i): return {t:1/12 for t in OFF}

FNMAP={"best":lambda i: w_baa(i,True),"published":lambda i: w_baa(i,True),
       "nocanary":lambda i: w_baa(i,False),"static":w_static}
CAD={"best":3,"published":1,"nocanary":3,"static":3}

def simulate(start,end,form,placebo_seed=None):
    fn=FNMAP[form]; cadence=CAD[form]
    start=pd.Timestamp(start); end=pd.Timestamp(end); pos=np.where((DAYS>=start)&(DAYS<=end))[0]
    rng=np.random.default_rng(placebo_seed) if placebo_seed is not None else None
    shares={}; cash=100.0; dates=[]; vals=[]; last=None; cache={}
    for p in pos:
        row=PXV[p]; d=DAYS[p]
        def eq(): return cash+sum(s*row[COL[t]] for t,s in shares.items() if not np.isnan(row[COL[t]]))
        isr=(p in REBAL_POS) or (p==pos[0])
        if isr and cadence>1:
            mk=d.year*12+d.month
            if last is not None and (mk-last)%cadence!=0: isr=False
            else: last=mk
        elif isr: last=d.year*12+d.month
        if isr:
            mi=ME.index.get_indexer([ME.index[ME.index<=d][-1]])[0]
            if mi not in cache: cache[mi]=fn(mi)
            w=cache[mi]
            if w:
                e=eq()
                if rng is not None:
                    inv=sum(v for t,v in w.items() if t!="BIL"); k=sum(1 for v in w.values() if v>0.01)
                    pool=[t for t in HOLDABLE if t!="BIL"]; picks=list(rng.choice(pool,size=min(k,len(pool)),replace=False))
                    w={t:inv/len(picks) for t in picks}
                    if inv<0.999: w["BIL"]=1-inv
                tv={t:e*v for t,v in w.items()}; traded=0.0; ns={}
                for t in set(tv)|set(shares):
                    cur=shares.get(t,0.0)*row[COL[t]]; traded+=abs(tv.get(t,0.0)-cur)
                    if tv.get(t,0.0)>0: ns[t]=tv[t]/row[COL[t]]
                scale=(e-COST*traded)/e if e>0 else 0; shares={t:s*scale for t,s in ns.items()}; cash=0.0
        dates.append(d); vals.append(eq())
    return pd.Series(vals,index=pd.DatetimeIndex(dates))

def spy_road(s,e):
    days=DAYS[(DAYS>=pd.Timestamp(s))&(DAYS<=pd.Timestamp(e))]; x=PX["SPY"].loc[days]; return 100*x/x.iloc[0]
def stats(ec):
    dd=float((ec/ec.cummax()-1).min()); m=ec.resample("M").last(); mr=m.pct_change().dropna()
    streak=cur=0
    for x in mr: cur=cur+1 if x<0 else 0; streak=max(streak,cur)
    lh=0; gap=0; cm=m.cummax()
    for j in range(len(m)):
        if m.iloc[j]>=cm.iloc[j]-1e-12: lh=j
        gap=max(gap,j-lh)
    return {"final":round(float(ec.iloc[-1]),2),"max_dd_pct":round(100*dd,1),"months":int(len(mr)),
      "share_pos":round(float((mr>0).mean()),3) if len(mr) else None,
      "median_month_pct":round(100*float(mr.median()),2) if len(mr) else None,
      "avg_month_pct":round(100*float(mr.mean()),2) if len(mr) else None,
      "best_month_pct":round(100*float(mr.max()),2) if len(mr) else None,
      "worst_month_pct":round(100*float(mr.min()),2) if len(mr) else None,
      "longest_losing_streak_months":int(streak),"longest_below_high_months":int(gap)}

def main():
    out={"family":"catalog-taa-keller-baa","program":"v13-best-rules","forms":{},"champions":CHAMP}
    for form in ["best","published","nocanary","static"]:
        out["forms"][form]={}
        for road,st in ROADS.items():
            ec=simulate(st,END,form); s=stats(ec); spy=spy_road(st,END)
            row={"stats":s,"spy_final":round(float(spy.iloc[-1]),2)}
            if form=="best":
                beaten=sum(1 for seed in range(20) if s["final"]>float(simulate(st,END,form,placebo_seed=seed).iloc[-1]))
                row["placebos_beaten"]=beaten
                row["curve"]={str(d.date()):round(float(v),4) for d,v in ec.items()} if road=="LONG" else {str(d.date()):round(float(v),4) for d,v in ec.resample("M").last().items()}
            out["forms"][form][road]=row
            print(form,road,s,flush=True)
    # confirmation check (only if any best road > champion)
    out["confirmation"]={"triggered":False}
    beats=[r for r in ROADS if out["forms"]["best"][r]["stats"]["final"]>CHAMP[r]]
    if beats:
        out["confirmation"]["triggered"]=True; out["confirmation"]["roads"]=beats; folds={}
        for r in beats:
            yrs=[]; 
            for y in range(int(ROADS[r][:4]),2027):
                a=f"{y}-01-01"; b=f"{y}-12-31" if y<2026 else END
                if pd.Timestamp(a)>pd.Timestamp(END): break
                yrs.append(round(float(simulate(a,b,"best").iloc[-1]),2))
            mid=pd.Timestamp(ROADS[r])+ (pd.Timestamp(END)-pd.Timestamp(ROADS[r]))/2
            h1=round(float(simulate(ROADS[r],str(mid.date()),"best").iloc[-1]),2); h2=round(float(simulate(str(mid.date()),END,"best").iloc[-1]),2)
            folds[r]={"yearly_fresh100":yrs,"median_year":float(np.median(yrs)),"half_windows":[h1,h2]}
        out["confirmation"]["folds"]=folds
    with open(os.path.join(FOLDER,"results.json"),"w") as f: json.dump(out,f,indent=1)
    print("DONE")

if __name__=="__main__": main()
