#!/usr/bin/env python3
"""
MOMENTUM BASKET — v12 HOLDINGS-COUNT SWEEP. Simulation only. No broker orders.

Family (canonical record: v10-retest/momentum-basket/run_sweep.py, frozen):
  Universe: honest Nov-2016 top-30 (AAPL MSFT AMZN GOOGL META BRK-B JPM XOM
    JNJ PG V WMT HD BAC CVX PFE VZ T DIS NFLX INTC CSCO GE IBM MMM UNH MA
    KO PEP WFC).
  Monthly selection (native cadence, held fixed — this wing varies COUNT
    only): eligible = close above own 200-day SMA and 12-1 momentum
    available (close[t-21]/close[t-252]-1, signal from prior day's close,
    trade at open). Rank by momentum, hold top-N equal-weighted (1/N of pot
    each; fewer eligible than N -> hold what's eligible, rest cash).
  NATIVE COUNT = 5.
  Costs (program): 0.10%/side + $0.01 per sell order. $100 pot.

Rule sets:
  house  = v9 protections: plain -15% floor per episode (checked at close),
           liquidate next open; first halt -> 90-day sit-out, restart at
           next monthly selection date, episode-2 floor -15% from restart
           balance; second halt ends the run.
  native = published momentum-portfolio form: NO floor / halt / restart
           (no published momentum basket carries a stop). Same selection,
           cadence, costs. (The 200-day eligibility filter is part of the
           family's canonical program form and is kept in both rule sets;
           the only house/native difference is the v9 protection layer.)

GRID (pre-registered, fixed): counts 1, 2, 3, 5, 8, 10, 15, 20, 30,
  ALL-ELIGIBLE (N = number eligible that month, fully invested).
Roads (all the data honestly supports):
  DECADE 2016-11-21 -> 2026-11-20 ; CONT 2019-01-01 -> 2026-11-20 ;
  VAL 2023-01-01 -> 2026-11-20.
  LONG 2010 is NOT run: the pond is point-in-time Nov-2016 and the cache
  starts 2015-01-02 — a 2010 run would use 2016 knowledge (v10
  confirmation record states the same closure).
Placebos: 20 seeds per cell — random N of the same eligible set, same
  dates, identical machinery. For ALL-ELIGIBLE the random draw IS the
  eligible set, so placebos are not applicable (marked null).

CONFIRMATION (Terry's rule, pre-registered here): if a non-native count
  beats count 5 on ALL THREE roads under house rules, it is re-run on
  different years: fresh-$100 calendar-year folds 2017..2026 (house,
  monthly) head-to-head vs count 5, plus two continuous half-windows
  (2016-11-21->2021-12-31 and 2022-01-01->2026-11-20).

Data: read-only ~/workspace/stock-app/backtests/v4/
  momentum-basket-honest-data/ (Yahoo split-adjusted daily bars).
Engine plumbing copied from the v10 sweep (which reproduced the published
$439.45 / $208.27 to the cent) and parameterized by count + floor toggle.
"""
import json, os, random, statistics
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.expanduser("~/workspace/stock-app/backtests/v4/momentum-basket-honest-data")
UNIVERSE = ["AAPL","MSFT","AMZN","GOOGL","META","BRK-B","JPM","XOM","JNJ","PG",
            "V","WMT","HD","BAC","CVX","PFE","VZ","T","DIS","NFLX","INTC",
            "CSCO","GE","IBM","MMM","UNH","MA","KO","PEP","WFC"]
BENCH = "SPY"
COST_RATE = 0.001; SELL_FEE = 0.01; POT0 = 100.0
COUNTS = [1,2,3,5,8,10,15,20,30,"ALL"]
NATIVE_COUNT = 5
ROADS = {"DECADE": ("2016-11-21","2026-11-20"),
         "CONT":   ("2019-01-01","2026-11-20"),
         "VAL":    ("2023-01-01","2026-11-20")}
SEEDS = list(range(1,21))

def fetch(t):
    with open(os.path.join(CACHE, f"{t}.json")) as f: return json.load(f)

class Market:
    def __init__(self, tickers):
        self.bars={}; self.closes={}
        spy=fetch(BENCH); self.cal=[r["d"] for r in spy]
        raw={BENCH:spy}
        for t in tickers: raw[t]=fetch(t)
        for t in tickers+[BENCH]:
            self.bars[t]={r["d"]:(r["o"],r["c"]) for r in raw[t]}
            arr,last=[],None
            for d in self.cal:
                if d in self.bars[t]: last=self.bars[t][d][1]
                arr.append(last)
            self.closes[t]=arr
        self.sma200={}; self.mom={}; n=len(self.cal)
        for t in tickers:
            c=self.closes[t]; s=[None]*n; m=[None]*n
            for i in range(n):
                if i+1>=200:
                    seg=c[i-199:i+1]
                    if not any(v is None for v in seg): s[i]=sum(seg)/200.0
                if i-252>=0:
                    a,b=c[i-252],c[i-21]
                    if a is not None and b is not None and a>0: m[i]=b/a-1.0
            self.sma200[t]=s; self.mom[t]=m
    def open_px(self,t,i):
        d=self.cal[i]
        return self.bars[t][d][0] if d in self.bars[t] else None
    def close_px(self,t,i): return self.closes[t][i]

def monthly_indices(mkt,i0,i1):
    out={i0}; prev=mkt.cal[i0][:7]
    for i in range(i0+1,i1+1):
        k=mkt.cal[i][:7]
        if k!=prev: prev=k; out.add(i)
    return out

class Result:
    def __init__(self):
        self.final=None; self.orders=0; self.costs=0.0
        self.halts=[]; self.restarts=[]; self.max_dd=0.0; self.equity_curve=[]

def simulate(mkt,start_d,end_d,count,house,mode="ranked",seed=42):
    rng=random.Random(seed)
    i0=next(i for i,d in enumerate(mkt.cal) if d>=start_d)
    i1=max(i for i,d in enumerate(mkt.cal) if d<=end_d)
    sel_days=monthly_indices(mkt,i0,i1)
    episode=1; floor=0.85*POT0 if house else None
    restart_idx=None; cash=float(POT0); pos={}; res=Result()
    pending=False
    def equity_at(i,use_open):
        tot=cash
        for t,sh in pos.items():
            px=mkt.open_px(t,i) if use_open else mkt.close_px(t,i)
            if px is None: px=mkt.close_px(t,i)
            tot+=sh*px
        return tot
    for i in range(i0,i1+1):
        d=mkt.cal[i]
        if pending:
            for t in list(pos):
                px=mkt.open_px(t,i)
                if px is None: px=mkt.close_px(t,i)
                val=pos[t]*px; fee=val*COST_RATE+SELL_FEE
                cash+=val-fee; res.costs+=fee; res.orders+=1; del pos[t]
            res.halts.append(d); res.equity_curve.append((d,cash)); pending=False
            if episode==1:
                y,m,dd=(int(x) for x in d.split("-"))
                earliest=(date(y,m,dd)+timedelta(days=90)).isoformat()
                ridx=None
                for j in sorted(sel_days):
                    if j>i and mkt.cal[j]>=earliest: ridx=j; break
                if ridx is not None:
                    restart_idx=ridx; episode=2
                    res.restarts.append({"halt_date":d,"restart_date":mkt.cal[ridx],
                        "restart_balance":round(cash,2),"episode2_floor":round(0.85*cash,2)})
                    floor=0.85*cash; continue
            res.final=cash; break
        if restart_idx is not None and i<restart_idx:
            res.equity_curve.append((d,cash)); continue
        if restart_idx is not None and i==restart_idx: restart_idx=None
        if i in sel_days and i>0:
            j=i-1; elig=[]
            for t in UNIVERSE:
                s=mkt.sma200[t][j]; c=mkt.close_px(t,j)
                if s is None or c is None or c<=s: continue
                mo=mkt.mom[t][j]
                if mo is None: continue
                elig.append((t,mo))
            n_req=len(elig) if count=="ALL" else count
            if mode=="ranked":
                elig.sort(key=lambda x:-x[1]); picks=[t for t,_ in elig[:n_req]]
            else:
                names=sorted(t for t,_ in elig)
                picks=rng.sample(names,min(n_req,len(names))) if names else []
            if picks:
                eq_open=equity_at(i,use_open=True)
                w=1.0/len(picks) if count=="ALL" else 1.0/count
                # ALL: fully invested across eligible. Fixed N: 1/N each
                # (fewer eligible -> remainder cash), as the original form.
                if count=="ALL": w=1.0/len(picks)
                target_val={t:w*eq_open for t in picks}
                for t in list(pos):
                    px=mkt.open_px(t,i)
                    if px is None: continue
                    cur=pos[t]*px; want=target_val.get(t,0.0)
                    if cur>want+0.01:
                        sv=cur-want; fee=sv*COST_RATE+SELL_FEE
                        cash+=sv-fee; res.costs+=fee; res.orders+=1
                        pos[t]-=sv/px
                        if want<=0.0 or pos[t]*px<0.01: del pos[t]
                for t in picks:
                    px=mkt.open_px(t,i)
                    if px is None: continue
                    cur=pos.get(t,0.0)*px; deficit=target_val[t]-cur
                    if deficit<=0.01: continue
                    bv=min(deficit,cash/(1.0+COST_RATE))
                    if bv<=0.01: continue
                    fee=bv*COST_RATE; cash-=bv+fee; res.costs+=fee; res.orders+=1
                    pos[t]=pos.get(t,0.0)+bv/px
        eq_close=equity_at(i,use_open=False)
        res.equity_curve.append((d,eq_close))
        if house and eq_close<=floor:
            pending=True
            if i==i1:
                tot=cash
                for t,sh in list(pos.items()):
                    val=sh*mkt.close_px(t,i); fee=val*COST_RATE+SELL_FEE
                    tot+=val-fee; res.costs+=fee; res.orders+=1
                res.final=tot; res.halts.append(d); pos.clear(); break
    if res.final is None: res.final=res.equity_curve[-1][1]
    peak=-1.0
    for d,eq in res.equity_curve:
        peak=max(peak,eq)
        if peak>0: res.max_dd=min(res.max_dd,eq/peak-1.0)
    return res

def period_distribution(curve):
    """Monthly periods from a daily equity curve (Terry's reporting std)."""
    months=[]; prev_eq=POT0; prev_key=None; last_eq=None
    month_ends=[]
    for d,eq in curve:
        k=d[:7]
        if prev_key is not None and k!=prev_key: month_ends.append((prev_key,last_eq))
        prev_key=k; last_eq=eq
    if prev_key is not None: month_ends.append((prev_key,last_eq))
    rets=[]
    for k,eq in month_ends:
        rets.append(eq/prev_eq-1.0); prev_eq=eq
    n=len(rets); prof=sum(1 for r in rets if r>0)
    longest_loss=0; run=0
    for r in rets:
        run=run+1 if r<0 else 0; longest_loss=max(longest_loss,run)
    # longest stretch between new highs (in monthly periods, month-end eq)
    peak=-1; last_high=0; max_gap=0
    eqs=[eq for _,eq in month_ends]
    for idx,eq in enumerate(eqs):
        if eq>=peak: peak=eq; max_gap=max(max_gap,idx-last_high); last_high=idx
    max_gap=max(max_gap,len(eqs)-1-last_high)
    return {"tempo":"monthly","periods":n,
        "pct_periods_profitable":round(100.0*prof/n,1) if n else None,
        "median_period_pct":round(100*statistics.median(rets),2) if rets else None,
        "best_period_pct":round(100*max(rets),2) if rets else None,
        "worst_period_pct":round(100*min(rets),2) if rets else None,
        "longest_losing_run_periods":longest_loss,
        "longest_stretch_between_new_highs_periods":max_gap,
        "average_period_pct_SECONDARY_LABELED":round(100*statistics.mean(rets),2) if rets else None}

def spy_net(mkt,start_d,end_d):
    i0=next(i for i,d in enumerate(mkt.cal) if d>=start_d)
    i1=max(i for i,d in enumerate(mkt.cal) if d<=end_d)
    buy=mkt.open_px(BENCH,i0); sell=mkt.close_px(BENCH,i1)
    sh=(POT0*(1-COST_RATE))/buy
    return round(sh*sell*(1-COST_RATE)-SELL_FEE,2)

def main():
    mkt=Market(UNIVERSE)
    cells={}; curves={}
    # integrity first
    r=simulate(mkt,*ROADS["DECADE"],5,True)
    rv=simulate(mkt,*ROADS["VAL"],5,True)
    print(f"INTEGRITY house N=5 DECADE={r.final:.2f} (pub 439.45) VAL={rv.final:.2f} (pub 208.27)",flush=True)
    for rules,house in (("house",True),("native",False)):
        for road,(sd,ed) in ROADS.items():
            for count in COUNTS:
                key=f"{rules}|{road}|{count}"
                res=simulate(mkt,sd,ed,count,house)
                pfinals=None; beaten=None
                if count!="ALL":
                    pfinals=[]
                    for s in SEEDS:
                        pr=simulate(mkt,sd,ed,count,house,mode="placebo",seed=s)
                        pfinals.append(round(pr.final,2))
                    beaten=sum(1 for v in pfinals if res.final>v)
                cells[key]={"rules":rules,"road":road,"count":str(count),
                    "final":round(res.final,2),"max_dd_pct":round(res.max_dd*100,2),
                    "costs":round(res.costs,2),"orders":res.orders,
                    "halts":res.halts,"restarts":res.restarts,
                    "placebo_beaten":beaten,"placebo_finals":pfinals}
                curves[key]=[[d,round(e,4)] for d,e in res.equity_curve]
                print(f"{key}: final={res.final:.2f} maxDD={res.max_dd*100:.2f}% costs={res.costs:.2f} orders={res.orders} halts={len(res.halts)} beaten={beaten}",flush=True)
    # winner under house rules: highest summed final across the 3 roads
    totals={}
    for count in COUNTS:
        totals[str(count)]=sum(cells[f"house|{road}|{count}"]["final"] for road in ROADS)
    winner=max(totals,key=totals.get)
    print("house totals:",{k:round(v,2) for k,v in totals.items()},"winner:",winner,flush=True)
    # confirmation if a non-native count beats 5 on ALL roads (house)
    confirmation=None
    cands=[str(c) for c in COUNTS if str(c)!=str(NATIVE_COUNT) and
           all(cells[f"house|{road}|{c}"]["final"]>cells[f"house|{road}|{NATIVE_COUNT}"]["final"] for road in ROADS)]
    if cands:
        confirmation={}
        for cand in cands:
            cc = "ALL" if cand=="ALL" else int(cand)
            folds={}
            for yr in range(2017,2027):
                sd=f"{yr}-01-01"; ed=f"{yr}-12-31"
                a=simulate(mkt,sd,ed,cc,True); b=simulate(mkt,sd,ed,NATIVE_COUNT,True)
                folds[str(yr)]={"candidate":round(a.final,2),"native5":round(b.final,2)}
            halves={}
            for lbl,(sd,ed) in {"H1":("2016-11-21","2021-12-31"),"H2":("2022-01-01","2026-11-20")}.items():
                a=simulate(mkt,sd,ed,cc,True); b=simulate(mkt,sd,ed,NATIVE_COUNT,True)
                halves[lbl]={"candidate":round(a.final,2),"native5":round(b.final,2)}
            cw=sum(1 for v in folds.values() if v["candidate"]>v["native5"])
            confirmation[cand]={"folds":folds,"fold_wins_of_10":cw,"halves":halves}
            print(f"CONFIRMATION {cand}: fold wins {cw}/10 halves={halves}",flush=True)
    dist={}
    for cnt in {winner,str(NATIVE_COUNT)}:
        cc="ALL" if cnt=="ALL" else int(cnt)
        for rules in ("house","native"):
            dist[f"{rules}|DECADE|{cnt}"]=period_distribution(curves[f"{rules}|DECADE|{cnt}"])
    out={"family":"momentum-basket","native_count":NATIVE_COUNT,"native_cadence":"monthly",
        "universe":"Nov-2016 top-30 (30 names, see script header)",
        "grid_counts":[str(c) for c in COUNTS],
        "roads":ROADS,
        "long_road_note":"LONG 2010 NOT RUN: pond is point-in-time Nov-2016, cache starts 2015-01-02 (v10 confirmation closure).",
        "integrity":{"house_N5_DECADE":round(r.final,2),"published":439.45,
                     "house_N5_VAL":round(rv.final,2),"published_val":208.27},
        "spy_price_only_net":{road:spy_net(mkt,sd,ed) for road,(sd,ed) in ROADS.items()},
        "spy_dividend_adjusted_reference":{"DECADE":367.80,"CONT":313.62,"VAL":187.77},
        "cells":cells,"house_totals":{k:round(v,2) for k,v in totals.items()},
        "winner_count_house":winner,"confirmation":confirmation,
        "period_distributions":dist,
        "curves":{k:curves[k] for k in curves if k.split("|")[2] in (winner,str(NATIVE_COUNT))}}
    with open(os.path.join(HERE,"results.json"),"w") as f: json.dump(out,f,indent=1)
    print("saved results.json",flush=True)

if __name__=="__main__": main()
