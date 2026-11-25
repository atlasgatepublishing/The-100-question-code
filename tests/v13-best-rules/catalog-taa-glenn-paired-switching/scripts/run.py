#!/usr/bin/env python3
"""V13 best-rules: Glenn paired switching + both-negative BIL escape.
Spec frozen in BEST-RULES-SPEC.md before this run. Data read-only from v12 folder.
Monthly, month-end close execution, 0.10%/leg cost, $100 pots."""
import json, os
import numpy as np, pandas as pd

HERE=os.path.dirname(os.path.abspath(__file__)); FOLDER=os.path.dirname(HERE)
DATA=os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/catalog-taa-glenn-paired-switching/data")
COST=0.001; END="2026-11-20"
ROADS={"LONG":"2010-01-01","DECADE":"2016-01-01","CONT":"2019-01-01","VAL":"2023-01-01"}
CHAMP={"LONG":1415.62,"DECADE":667.35,"CONT":544.47,"VAL":288.05}
PUB={"LONG":496.72,"DECADE":205.82,"CONT":160.42,"VAL":133.70}

def load(t):
    df=pd.read_csv(os.path.join(DATA,t+".csv"),parse_dates=["date"])
    return df.set_index("date")["adjclose"]
PX=pd.DataFrame({t:load(t) for t in ["SPY","TLT","BIL"]}).sort_index()
DAYS=PX.index
ME=PX.loc[PX.index.to_series().groupby([PX.index.year,PX.index.month]).max().values]
REBAL=set(ME.index); MPOS={d:i for i,d in enumerate(ME.index)}

def ret3(t,d):
    i=MPOS[d]
    if i<3: return np.nan
    return ME[t].iloc[i]/ME[t].iloc[i-3]-1

def simulate(start,end,mode="best",seed=None):
    """mode: best | published | static | random | random_escape"""
    start=pd.Timestamp(start); end=pd.Timestamp(end)
    days=DAYS[(DAYS>=start)&(DAYS<=end)]
    rng=np.random.default_rng(seed) if seed is not None else None
    shares={}; cash=100.0; dates=[]; vals=[]
    for d in days:
        row=PX.loc[d]
        def eq(): return cash+sum(s*row[t] for t,s in shares.items() if not np.isnan(row[t]))
        if d in REBAL or d==days[0]:
            # signal uses month-end <= d (for first day, most recent month-end)
            cands=ME.index[ME.index<=d]
            if len(cands):
                md=cands[-1]
                if mode=="static": w={"SPY":0.5,"TLT":0.5}
                elif mode in ("random","random_escape"):
                    if mode=="random_escape" and ret3("SPY",md)<=0 and ret3("TLT",md)<=0: w={"BIL":1.0}
                    else: w={rng.choice(["SPY","TLT"]):1.0}
                else:
                    rs,rt=ret3("SPY",md),ret3("TLT",md)
                    if not np.isnan(rs):
                        if mode=="best" and rs<=0 and rt<=0: w={"BIL":1.0}
                        else: w={"SPY":1.0} if rs>=rt else {"TLT":1.0}
                    else: w=None
                if 'w' in dir() and w:
                    e=eq(); tgt={t:e*v for t,v in w.items()}
                    traded=sum(abs(tgt.get(t,0)-shares.get(t,0)*row[t]) for t in set(tgt)|set(shares))
                    scale=(e-COST*traded)/e if e>0 else 0
                    shares={t:tgt[t]/row[t]*scale for t in tgt if tgt[t]>0}; cash=0.0
        dates.append(d); vals.append(eq())
    return pd.Series(vals,index=pd.DatetimeIndex(dates))

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
    out={"family":"catalog-taa-glenn-paired-switching","form":"v13 best rules: published 3m SPY/TLT monthly switch + both-negative BIL escape, no floor","roads":{},"curves":{}}
    for road,st in ROADS.items():
        ec=simulate(st,END,"best"); s=stats(ec)
        pub=simulate(st,END,"published"); sta=simulate(st,END,"static")
        spy=100*PX["SPY"].loc[ec.index]/PX["SPY"].loc[ec.index].iloc[0]
        rnd=[float(simulate(st,END,"random",seed=k).iloc[-1]) for k in range(20)]
        rne=[float(simulate(st,END,"random_escape",seed=k).iloc[-1]) for k in range(20)]
        out["roads"][road]={"best":s,"published_recomputed":stats(pub),"static_5050":stats(sta),
          "spy_final":round(float(spy.iloc[-1]),2),
          "random_switch_beaten":int(sum(1 for x in rnd if s["final"]>x)),"random_median":round(float(np.median(rnd)),2),
          "random_escape_beaten":int(sum(1 for x in rne if s["final"]>x)),"random_escape_median":round(float(np.median(rne)),2),
          "champion":CHAMP[road],"published_v12":PUB[road]}
        if road=="LONG": out["curves"]["LONG_best"]={str(d.date()):round(float(v),4) for d,v in ec.items()}
        print(road,s,"spy",round(float(spy.iloc[-1]),2),"rand beaten",out["roads"][road]["random_switch_beaten"])
    # confirmation folds only if any road beats champion (frozen bars in spec)
    beats=[r for r in ROADS if out["roads"][r]["best"]["final"]>CHAMP[r]]
    out["champion_beating_roads"]=beats
    if beats:
        out["folds"]={}
        for nm,(a,b) in {"fold_2010_2018":("2010-01-01","2018-12-31"),"fold_2019_2026":("2019-01-01",END)}.items():
            ec=simulate(a,b,"best"); out["folds"][nm]=stats(ec)
    with open(os.path.join(FOLDER,"results.json"),"w") as f: json.dump(out,f,indent=1)
    print("beats champion:",beats)

if __name__=="__main__": main()
