#!/usr/bin/env python3
"""V13 BEST RULES — Momentum Basket. Spec: BEST-RULES-SPEC.md (frozen).
Top-3, 12-1, monthly, 200d filter, SPY 63d vol-scaled exposure
E=clip(0.18/realized_vol,0.40,1.00), NO floor. Costs 0.10%/side+$0.01/sell.
Data: read-only v4 honest cache."""
import json, math, os, random, statistics
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.expanduser("~/workspace/stock-app/backtests/v4/momentum-basket-honest-data")
UNIVERSE = ["AAPL","MSFT","AMZN","GOOGL","META","BRK-B","JPM","XOM","JNJ","PG","V","WMT","HD","BAC","CVX","PFE","VZ","T","DIS","NFLX","INTC","CSCO","GE","IBM","MMM","UNH","MA","KO","PEP","WFC"]
BENCH="SPY"; COST=0.001; FEE=0.01; N=3; TARGET_VOL=0.18
ROADS={"DECADE":("2016-11-21","2026-11-20"),"CONT":("2019-01-01","2026-11-20"),"VAL":("2023-01-01","2026-11-20")}

def load(t):
    with open(os.path.join(CACHE,f"{t}.json")) as f: return json.load(f)

class Mkt:
    def __init__(self):
        spy=load(BENCH); self.cal=[r["d"] for r in spy]
        self.bars={}; self.closes={}
        for t in UNIVERSE+[BENCH]:
            raw=spy if t==BENCH else load(t)
            self.bars[t]={r["d"]:(r["o"],r["c"]) for r in raw}
            arr=[]; last=None
            for d in self.cal:
                if d in self.bars[t]: last=self.bars[t][d][1]
                arr.append(last)
            self.closes[t]=arr
    def op(self,t,i):
        d=self.cal[i]; return self.bars[t][d][0] if d in self.bars[t] else None
    def cp(self,t,i): return self.closes[t][i]
    def sma(self,t,i,n):
        if i+1<n: return None
        seg=self.closes[t][i-n+1:i+1]
        return None if any(v is None for v in seg) else sum(seg)/n
    def mom(self,t,i):
        if i-252<0: return None
        a,b=self.closes[t][i-252],self.closes[t][i-21]
        return None if (a is None or b is None or a<=0) else b/a-1.0
    def spy_vol(self,i):
        """annualized realized vol of SPY over trailing 63 closes ending at i"""
        if i<64: return None
        seg=self.closes[BENCH][i-63:i+1]
        if any(v is None for v in seg): return None
        rets=[math.log(seg[k]/seg[k-1]) for k in range(1,len(seg))]
        return statistics.pstdev(rets)*math.sqrt(252)

def exposure(mkt,j):
    v=mkt.spy_vol(j)
    if v is None or v<=0: return 1.0
    return min(1.0, max(0.40, TARGET_VOL/v))

def simulate(mkt,sd,ed,mode,seed=42,pot0=100.0):
    rng=random.Random(seed)
    i0=next(i for i,d in enumerate(mkt.cal) if d>=sd)
    i1=max(i for i,d in enumerate(mkt.cal) if d<=ed)
    cash=float(pot0); pos={}; curve=[]; orders=0; costs=0.0; cur=None; exposures=[]
    def eq(i,use_open):
        tot=cash
        for t,sh in pos.items():
            px=mkt.op(t,i) if use_open else mkt.cp(t,i)
            if px is None: px=mkt.cp(t,i)
            tot+=sh*px
        return tot
    for i in range(i0,i1+1):
        d=mkt.cal[i]; mk=d[:7]
        if mk!=cur and i>0:
            cur=mk; j=i-1
            elig=[]
            for t in UNIVERSE:
                s=mkt.sma(t,j,200); c=mkt.cp(t,j)
                if s is None or c is None or c<=s: continue
                m=mkt.mom(t,j)
                if m is not None: elig.append((t,m))
            if mode=="ranked":
                elig.sort(key=lambda x:-x[1]); picks=[t for t,_ in elig[:N]]
            else:
                names=sorted(t for t,_ in elig); picks=rng.sample(names,min(N,len(names))) if names else []
            E=exposure(mkt,j); exposures.append(round(E,3))
            eqo=eq(i,True); tgt={t:(E/N)*eqo for t in picks}
            for t in list(pos):
                px=mkt.op(t,i)
                if px is None: continue
                cv=pos[t]*px; want=tgt.get(t,0.0)
                if cv>want+0.01:
                    sv=cv-want; fee=sv*COST+FEE; cash+=sv-fee; costs+=fee; orders+=1
                    pos[t]-=sv/px
                    if want<=0 or pos[t]*px<0.01: del pos[t]
            for t in picks:
                px=mkt.op(t,i)
                if px is None: continue
                deficit=tgt[t]-pos.get(t,0.0)*px
                if deficit<=0.01: continue
                bv=min(deficit, cash/(1+COST))
                if bv<=0.01: continue
                fee=bv*COST; cash-=bv+fee; costs+=fee; orders+=1
                pos[t]=pos.get(t,0.0)+bv/px
        curve.append((d,eq(i,False)))
    final=curve[-1][1]
    peak=-1; mdd=0.0
    for _,e in curve:
        peak=max(peak,e); mdd=min(mdd, e/peak-1.0 if peak>0 else 0.0)
    return {"final":round(final,2),"max_dd_pct":round(mdd*100,2),"orders":orders,
            "costs":round(costs,2),"equity_curve":curve,"exposures":exposures}

def spy_net(mkt,sd,ed,pot0=100.0):
    i0=next(i for i,d in enumerate(mkt.cal) if d>=sd); i1=max(i for i,d in enumerate(mkt.cal) if d<=ed)
    sh=(pot0*(1-COST))/mkt.op(BENCH,i0)
    return round(sh*mkt.cp(BENCH,i1)*(1-COST)-FEE,2)

def dist(curve):
    me={}
    for d,e in curve: me[d[:7]]=e
    ks=sorted(me); rets=[me[b]/me[a]-1 for a,b in zip(ks,ks[1:])]
    if not rets: return {}
    s=sorted(rets); n=len(s)
    med=s[n//2] if n%2 else (s[n//2-1]+s[n//2])/2
    streak=cur_s=0
    for r in rets:
        cur_s=cur_s+1 if r<=0 else 0; streak=max(streak,cur_s)
    peak=-1; since=longest=0
    for _,e in curve:
        if e>=peak: peak=e; since=0
        else: since+=1
        longest=max(longest,since)
    # approx months between highs from daily counter /21
    return {"periods":n,"median_pct":round(med*100,2),"pct_positive":round(100*sum(1 for r in rets if r>0)/n,1),
            "best_pct":round(max(rets)*100,2),"worst_pct":round(min(rets)*100,2),
            "longest_losing_streak_mo":streak,"longest_days_between_highs":longest,
            "avg_pct_secondary":round(sum(rets)/n*100,2),"monthly_rets":[round(r*100,2) for r in rets]}

def main():
    mkt=Mkt(); out={"family":"momentum-basket","spec":"top3 12-1 monthly 200d vol-scaled E=clip(.18/rv63,.4,1) no floor","roads":{},"placebos":{}}
    ranked={}
    for road,(sd,ed) in ROADS.items():
        r=simulate(mkt,sd,ed,"ranked"); ranked[road]=r
        out["roads"][road]={"final":r["final"],"max_dd_pct":r["max_dd_pct"],"orders":r["orders"],"costs":r["costs"],
                            "spy_net_price_only":spy_net(mkt,sd,ed),
                            "equity_curve":r["equity_curve"],"mean_exposure":round(sum(r["exposures"])/len(r["exposures"]),3) if r["exposures"] else None}
        print(road, r["final"], r["max_dd_pct"], "meanE", out["roads"][road]["mean_exposure"], flush=True)
        finals=[]
        for seed in range(1,21):
            p=simulate(mkt,sd,ed,"placebo",seed=seed); finals.append(p["final"])
        beaten=sum(1 for v in finals if r["final"]>v)
        sf=sorted(finals)
        out["placebos"][road]={"finals":finals,"median":sf[10],"best":sf[-1],"worst":sf[0],"ranked_beats_n_of_20":beaten}
        print(road,"placebo median",sf[10],"beats",beaten,"/20",flush=True)
    out["distribution_decade_monthly"]=dist(ranked["DECADE"]["equity_curve"])
    # Confirmation prep: calendar-year folds + halves, my-rules vs published count-5 form (no vol scale, N=5, full exposure)
    # published form simulated with same engine via globals override
    import copy
    def sim_form(sd,ed,n,volscale):
        global N
        old=N; N=n
        # monkeypatch exposure by toggling: simplest — inline flag via attribute
        r=_simulate_form(mkt,sd,ed,volscale)
        N=old; return r
    folds={}
    for y in range(2017,2027):
        sd=f"{y}-01-01"; ed=f"{y}-12-31"
        if y==2026: ed="2026-11-20"
        a=_simulate_form(mkt,sd,ed,True,3); b=_simulate_form(mkt,sd,ed,False,5)
        folds[str(y)]={"mine":a["final"],"published5":b["final"],"win":a["final"]>b["final"]}
    halves={}
    for nm,(sd,ed) in {"H1":("2016-11-21","2021-12-31"),"H2":("2022-01-01","2026-11-20")}.items():
        a=_simulate_form(mkt,sd,ed,True,3); b=_simulate_form(mkt,sd,ed,False,5)
        halves[nm]={"mine":a["final"],"published5":b["final"],"win":a["final"]>b["final"]}
    out["confirmation_vs_published5"]={"folds":folds,"fold_wins":sum(1 for v in folds.values() if v["win"]),"halves":halves}
    with open(os.path.join(HERE,"results.json"),"w") as f: json.dump(out,f,indent=1)
    print("saved results.json")

def _simulate_form(mkt,sd,ed,volscale,n):
    """form simulator: n picks, volscale on/off, ranked only"""
    i0=next(i for i,d in enumerate(mkt.cal) if d>=sd); i1=max(i for i,d in enumerate(mkt.cal) if d<=ed)
    cash=100.0; pos={}; curve=[]; orders=0; costs=0.0; cur=None
    def eq(i,use_open):
        tot=cash
        for t,sh in pos.items():
            px=mkt.op(t,i) if use_open else mkt.cp(t,i)
            if px is None: px=mkt.cp(t,i)
            tot+=sh*px
        return tot
    for i in range(i0,i1+1):
        d=mkt.cal[i]; mk=d[:7]
        if mk!=cur and i>0:
            cur=mk; j=i-1; elig=[]
            for t in UNIVERSE:
                s=mkt.sma(t,j,200); c=mkt.cp(t,j)
                if s is None or c is None or c<=s: continue
                m=mkt.mom(t,j)
                if m is not None: elig.append((t,m))
            elig.sort(key=lambda x:-x[1]); picks=[t for t,_ in elig[:n]]
            E=exposure(mkt,j) if volscale else 1.0
            eqo=eq(i,True); tgt={t:(E/n)*eqo for t in picks}
            for t in list(pos):
                px=mkt.op(t,i)
                if px is None: continue
                cv=pos[t]*px; want=tgt.get(t,0.0)
                if cv>want+0.01:
                    sv=cv-want; fee=sv*COST+FEE; cash+=sv-fee; costs+=fee; orders+=1; pos[t]-=sv/px
                    if want<=0 or pos[t]*px<0.01: del pos[t]
            for t in picks:
                px=mkt.op(t,i)
                if px is None: continue
                deficit=tgt[t]-pos.get(t,0.0)*px
                if deficit<=0.01: continue
                bv=min(deficit,cash/(1+COST))
                if bv<=0.01: continue
                fee=bv*COST; cash-=bv+fee; costs+=fee; orders+=1; pos[t]=pos.get(t,0.0)+bv/px
        curve.append((d,eq(i,False)))
    peak=-1; mdd=0.0
    for _,e in curve:
        peak=max(peak,e); mdd=min(mdd,e/peak-1.0 if peak>0 else 0.0)
    return {"final":round(curve[-1][1],2),"max_dd_pct":round(mdd*100,2),"orders":orders,"costs":round(costs,2)}

if __name__=="__main__": main()
