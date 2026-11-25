#!/usr/bin/env python3
"""V13 best-rules ACA: monthly checks, sleeve-local accounts, annual reset, no floor.
Reuses v12 Panel/loaders (read-only). Costs 0.10%/side + $0.01/sell order."""
import json, os, random, sys
sys.path.insert(0, os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/catalog-taa-stoken-aca/scripts"))
from engine import Panel, load_t2, load_etf_json, period_stats, ROADS_2016
from datetime import date

COST=0.001; SELLFEE=0.01; POT=100.0
SLEEVES=[("SPY",126,252),("VNQ",126,252),("GLD",252,126)]
OUT=os.path.expanduser("~/workspace/stock-app/backtests/v13-best-rules/catalog-taa-stoken-aca")

def panel():
    p=Panel(load_t2("SPY")); ds,cs=load_t2("SPY"); p.series["SPY"]=cs[:]
    for s in ["VNQ","GLD"]: p.add(s, load_t2(s))
    p.add("IEF", load_etf_json("IEF"))
    return p

def month_end_decisions(p, idx):
    dec=set(); prev=None
    for i in idx:
        d=p.dates[i]; k=(d.year,d.month)
        if prev is not None and k!=prev: dec.add(prev_i)
        prev=k; prev_i=i
    return dec

def simulate(p, idx, placebo_seed=None):
    rng=random.Random(placebo_seed) if placebo_seed is not None else None
    dec=month_end_decisions(p, idx)
    # sleeve accounts: dict sym->shares, cash per sleeve
    accts=[{"cash":POT/3,"shares":{},"state":True} for _ in SLEEVES]
    costs=0.0; orders=0; curve=[]; pending=None; last_year=[None]
    def acct_eq(a,i):
        return a["cash"]+sum(sh*p.close(s,i) for s,sh in a["shares"].items() if p.close(s,i))
    def trade_to(a,i,target_sym):
        nonlocal costs,orders
        # liquidate current holding
        for s in list(a["shares"]):
            if s==target_sym: continue
            c=p.close(s,i); v=a["shares"][s]*c; fee=v*COST+SELLFEE
            a["cash"]+=v-fee; costs+=fee; orders+=1; del a["shares"][s]
        if target_sym and a["cash"]>0.02:
            c=p.close(target_sym,i); bv=min(a["cash"]/(1+COST), a["cash"])
            fee=bv*COST; a["cash"]-=bv+fee; costs+=fee; orders+=1
            a["shares"][target_sym]=a["shares"].get(target_sym,0)+bv/c
    def total_eq(i): return sum(acct_eq(a,i) for a in accts)
    for pos,i in enumerate(idx):
        if pending is not None:
            for a,tgt in zip(accts,pending): trade_to(a,i,tgt)
            pending=None
        # annual reset at first decision day of a new year: equalize sleeve equity via cash transfers is complex;
        # implement as: at Jan decision, rebalance total equity into thirds by trading each sleeve to its risk/def state asset
        curve.append((p.dates[i], round(total_eq(i),2)))
        if i in dec and pos < len(idx)-1:
            yr=p.dates[i].year
            if last_year[0] is not None and yr!=last_year[0]:
                # annual reset: liquidate all, split equity in thirds, rebuy states
                tot=total_eq(i)
                states=[a["state"] for a in accts]
                for a in accts:
                    for s in list(a["shares"]):
                        c=p.close(s,i); v=a["shares"][s]*c; fee=v*COST+SELLFEE
                        a["cash"]+=v-fee; costs+=fee; orders+=1; del a["shares"][s]
                pool=sum(a["cash"] for a in accts)
                for a in accts: a["cash"]=pool/3
                pending=[ (SLEEVES[k][0] if states[k] else "IEF") for k in range(3)]
            last_year[0]=yr
            targets=[]
            for a,(sym,up,dn) in zip(accts,SLEEVES):
                if rng is not None:
                    a["state"]=rng.random()<0.5
                else:
                    c=p.close(sym,i)
                    if a["state"]:
                        w=[p.close(sym,j) for j in range(max(0,i-dn),i)]; w=[x for x in w if x is not None]
                        if w and c<min(w): a["state"]=False
                    else:
                        w=[p.close(sym,j) for j in range(max(0,i-up),i)]; w=[x for x in w if x is not None]
                        if w and c>max(w): a["state"]=True
                targets.append(sym if a["state"] else "IEF")
            if pending is None: pending=targets
            else: pending=targets  # state targets take effect next day (reset rebuy superseded consistently)
    # final liquidation
    i=idx[-1]; tot=0.0
    for a in accts:
        for s in list(a["shares"]):
            c=p.close(s,i); v=a["shares"][s]*c; fee=v*COST+SELLFEE
            a["cash"]+=v-fee; costs+=fee; orders+=1
        tot+=a["cash"]
    curve[-1]=(p.dates[i], round(tot,2))
    eqs=[POT]+[e for _,e in curve]; peak=eqs[0]; dd=0.0
    for e in eqs:
        peak=max(peak,e); dd=max(dd,(peak-e)/peak if peak>0 else 0)
    return {"final":round(tot,2),"max_dd_pct":round(dd*100,2),"costs":round(costs,2),
            "orders":orders,"curve":[[str(d),e] for d,e in curve]}

def buyhold(p, idx, weights):
    cash=POT; shares={}
    i0=idx[0]
    for s,w in weights.items():
        bv=w*POT/(1+COST); shares[s]=bv/p.close(s,i0)
    i=idx[-1]; tot=sum(sh*p.close(s,i) for s,sh in shares.items())
    fee=sum(sh*p.close(s,i)*COST+SELLFEE for s,sh in shares.items())
    return round(tot-fee,2)

def main():
    p=panel(); res={"family":"catalog-taa-stoken-aca","form":"v13-best-rules","roads":{},"curves":{},"period_stats":{},"scale":{}}
    for name,(a,b) in ROADS_2016.items():
        idx=[i for i,d in enumerate(p.dates) if a<=d<=b]
        r=simulate(p,idx)
        twins=[simulate(p,idx,placebo_seed=s)["final"] for s in range(1,21)]
        res["roads"][name]={"final":r["final"],"max_dd_pct":r["max_dd_pct"],"costs":r["costs"],"orders":r["orders"],
                            "placebo_finals":twins,"placebos_beaten":sum(1 for t in twins if r["final"]>t)}
        res["curves"][name]=r["curve"]
        res["period_stats"][name]=period_stats(r["curve"],p.dates,"monthly")
        res["scale"][name]={"SPY_buyhold_same_window":buyhold(p,idx,{"SPY":1.0}),
                            "static_thirds_SPY_VNQ_GLD":buyhold(p,idx,{"SPY":1/3,"VNQ":1/3,"GLD":1/3})}
        print(name, r["final"], r["max_dd_pct"], "orders", r["orders"], "placebos", res["roads"][name]["placebos_beaten"], flush=True)
    json.dump(res, open(os.path.join(OUT,"results.json"),"w"), indent=1)
if __name__=="__main__": main()
