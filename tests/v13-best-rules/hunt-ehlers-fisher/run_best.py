#!/usr/bin/env python3
"""V13 best-rules: Ehlers Fisher, weekly gate + cross-up only when Fisher<0, no floor.
Constants exactly as published (10, 0.5, 0.999). Spec frozen before run."""
import json, os, math, time, random, statistics
from datetime import date

START=100.0; COST=0.001; FEE=0.01
ROADS={"LONG":("2010-01-01","2026-11-20"),"DECADE":("2016-11-21","2026-11-20"),
       "CONT":("2019-01-01","2026-11-20"),"VAL":("2023-01-01","2026-11-20")}
CHAMP={"LONG":1415.62,"DECADE":667.35,"CONT":544.47,"VAL":288.05}
SPYREF={"LONG":822.94,"DECADE":367.80,"CONT":313.62,"VAL":187.77}
PXDIR=os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
HERE=os.path.dirname(os.path.abspath(__file__))

def load_pxfull(ticker):
    j=json.load(open(os.path.join(PXDIR,f"pxfull_{ticker}.json")))
    r=j["chart"]["result"][0]; ts=r["timestamp"]; q=r["indicators"]["quote"][0]
    adj=r["indicators"]["adjclose"][0]["adjclose"]; bars=[]
    for i,t in enumerate(ts):
        if q["close"][i] is None or adj[i] is None or q["open"][i] is None: continue
        ratio=adj[i]/q["close"][i]
        bars.append({"d":time.strftime("%Y-%m-%d",time.gmtime(t)),
            "o":q["open"][i]*ratio,"h":q["high"][i]*ratio,"l":q["low"][i]*ratio,"c":adj[i]})
    bars.sort(key=lambda b:b["d"]); return bars

def fisher_series(bars):
    n=len(bars); val=[0.0]*n; fish=[0.0]*n
    for i in range(n):
        lo=min(b["l"] for b in bars[max(0,i-9):i+1]); hi=max(b["h"] for b in bars[max(0,i-9):i+1])
        med=(bars[i]["h"]+bars[i]["l"])/2.0
        raw=0.0 if hi==lo else 2.0*((med-lo)/(hi-lo)-0.5)
        v=0.5*raw+0.5*(val[i-1] if i>0 else 0.0); v=max(-0.999,min(0.999,v)); val[i]=v
        fish[i]=0.5*math.log((1+v)/(1-v))+0.5*(fish[i-1] if i>0 else 0.0)
    return fish

def weekly_targets(bars):
    fish=fisher_series(bars); n=len(bars)
    # last trading day of each ISO week
    last=set()
    for i,b in enumerate(bars):
        y,m,d=map(int,b["d"].split("-")); wk=date(y,m,d).isocalendar()[:2]
        if i==n-1: last.add(i); continue
        y2,m2,d2=map(int,bars[i+1]["d"].split("-")); wk2=date(y2,m2,d2).isocalendar()[:2]
        if wk2!=wk: last.add(i)
    targets=[False]*n; pos=False
    for i in range(n):
        if i in last and i>=2:
            if not pos and fish[i]>fish[i-1] and fish[i-1]<=fish[i-2] and fish[i]<0:
                pos=True
            elif pos and fish[i]<fish[i-1] and fish[i-1]>=fish[i-2]:
                pos=False
        targets[i]=pos
    return targets

def simulate(bars,targets,start,end,shift_seed=None):
    idx=[i for i,b in enumerate(bars) if start<=b["d"]<=end]
    if not idx: return None
    tgt=list(targets)
    if shift_seed is not None:
        rng=random.Random(shift_seed); seg=[tgt[i] for i in idx]
        if len(seg)>1:
            k=rng.randrange(1,len(seg)); seg=seg[k:]+seg[:k]
            for j,i in enumerate(idx): tgt[i]=seg[j]
    desired=False
    for i in range(idx[0]): desired=tgt[i]
    cash,shares,costs=START,0.0,0.0; trades=[]; curve=[]; pending=desired if desired else None
    days_inv=0
    for pos,i in enumerate(idx):
        b=bars[i]
        if pending is not None:
            if pending and shares==0.0 and cash>0:
                bv=cash/(1+COST); cfee=bv*COST; shares=bv/b["o"]; cash-=bv+cfee; costs+=cfee
                trades.append([b["d"],"BUY",round(b["o"],6),round(bv,2),round(cfee,2)])
            elif not pending and shares>0:
                val=shares*b["o"]; cfee=val*COST+FEE; cash+=val-cfee; costs+=cfee; shares=0.0
                trades.append([b["d"],"SELL",round(b["o"],6),round(val,2),round(cfee,2)])
            pending=None
        if tgt[i]!=(shares>0): pending=tgt[i]
        eq=cash+shares*b["c"]
        if shares>0: days_inv+=1
        curve.append([b["d"],round(eq,4)])
    if shares>0:
        last=bars[idx[-1]]; val=shares*last["c"]; cfee=val*COST+FEE; cash+=val-cfee; costs+=cfee; shares=0.0
        trades.append([last["d"],"SELL-END",round(last["c"],6),round(val,2),round(cfee,2)])
        curve[-1]=[last["d"],round(cash,4)]
    peak=-1.0; maxdd=0.0
    for _,v in curve:
        peak=max(peak,v)
        if peak>0: maxdd=max(maxdd,(peak-v)/peak)
    return {"final":round(cash,2),"max_dd_pct":round(maxdd*100,2),"costs":round(costs,2),
            "orders":len(trades),"trades":trades,
            "invested_pct":round(100.0*days_inv/len(idx),1),"equity_curve":curve}

def buy_hold(bars,start,end):
    days=[b for b in bars if start<=b["d"]<=end]
    sh=(START/(1+COST))/days[0]["o"]
    curve=[[b["d"],round(sh*b["c"],4)] for b in days]
    val=sh*days[-1]["c"]; final=val-(val*COST+FEE); curve[-1]=[days[-1]["d"],round(final,4)]
    peak=-1.0; maxdd=0.0
    for _,v in curve:
        peak=max(peak,v)
        if peak>0: maxdd=max(maxdd,(peak-v)/peak)
    return {"final":round(final,2),"max_dd_pct":round(maxdd*100,2),"equity_curve":curve}

def period_stats(curve):
    vals=[]; last=None
    for d,v in curve:
        k=d[:7]
        if k!=last: vals.append(v); last=k
        else: vals[-1]=v
    series=[START]+vals
    rets=[(series[i]/series[i-1]-1)*100 if series[i-1]>0 else 0.0 for i in range(1,len(series))]
    pos=sum(1 for r in rets if r>0); streak=worst=0
    for r in rets:
        if r<0: streak+=1; worst=max(worst,streak)
        else: streak=0
    peak=series[0]; lh=0; longest=0
    for i,v in enumerate(series):
        if v>=peak: peak=v; longest=max(longest,i-lh); lh=i
    longest=max(longest,len(series)-1-lh)
    return {"periods":len(rets),"pct_positive":round(100*pos/len(rets),1),
            "median_pct":round(statistics.median(rets),3),
            "mean_pct_secondary_average_only":round(statistics.mean(rets),3),
            "best_pct":round(max(rets),2),"worst_pct":round(min(rets),2),
            "longest_losing_streak":worst,"longest_between_highs":longest}

def main():
    bars=load_pxfull("SPY"); tgt=weekly_targets(bars)
    out={"family":"hunt-ehlers-fisher","program":"v13-best-rules",
         "spec":"weekly evaluation; cross-up entry only if Fisher<0; cross-down exit; no floor; SPY all-in long-only; Ehlers constants untouched (10, 0.5, 0.999)",
         "costs":"stocks 0.10%/side + $0.01 sell fee","roads":{}}
    for name,(s,e) in ROADS.items():
        r=simulate(bars,tgt,s,e); bh=buy_hold(bars,s,e)
        finals=[]
        for seed in range(1,21):
            finals.append(simulate(bars,tgt,s,e,shift_seed=seed)["final"])
        rec={"best_rules":r,"period_stats":period_stats(r["equity_curve"]),
             "benchmark_hold":{"final":bh["final"],"max_dd_pct":bh["max_dd_pct"]},
             "champion_vm":CHAMP[name],"spy_program_ref":SPYREF[name],
             "placebo":{"seed_finals":finals,"beaten_of_20":sum(1 for p in finals if r["final"]>p),
                        "design":"circular shift of daily in/out state series within road, 20 seeds"}}
        out["roads"][name]=rec
        print(f"{name}: best ${r['final']} DD {r['max_dd_pct']}% costs ${r['costs']} orders {r['orders']} inv {r['invested_pct']}% placebos {rec['placebo']['beaten_of_20']}/20 | hold ${bh['final']}")
    json.dump(out,open(os.path.join(HERE,"results.json"),"w"),indent=1)
    print("DONE")

if __name__=="__main__": main()
