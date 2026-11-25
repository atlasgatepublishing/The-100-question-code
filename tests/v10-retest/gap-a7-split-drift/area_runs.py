import sys, os, json, random, datetime as dt
sys.path.insert(0,'/tmp/w7')
from lib import *
D = os.path.expanduser("~/workspace/stock-app/backtests/v10-retest/gap-a7-split-drift")
M = load_mod("a7", os.path.join(D,"engine.py")); E=M.E; UNI=M.UNIVERSE
EXT=[
 {"ticker":"KO","ratio":"2-for-1","announced":"2012-04-25","effective":"2012-08-13","basis":"EXTENSION (v10): Coca-Cola board approved 2-for-1 split announced 2012-04-25 (first split in 16 years); split-adjusted trading began 2012-08-13."},
 {"ticker":"MA","ratio":"10-for-1","announced":"2013-12-10","effective":"2014-01-21","basis":"EXTENSION (v10): MasterCard 8-K filed 2013-12-10, Ex-99.1 press release: board approved 10-for-1 stock split via stock dividend; distribution 2014-01-21."},
 {"ticker":"AAPL","ratio":"7-for-1","announced":"2014-04-23","effective":"2014-06-09","basis":"EXTENSION (v10): Apple announced 7-for-1 split with Q2 FY2014 earnings 2014-04-23; split-adjusted trading began 2014-06-09."},
 {"ticker":"V","ratio":"4-for-1","announced":"2015-01-29","effective":"2015-03-19","basis":"EXTENSION (v10): Visa announced 4-for-1 split 2015-01-29 (Q1 FY2015 earnings release); split completed 2015-03-18, split-adjusted trading 2015-03-19."},
 {"ticker":"NFLX","ratio":"7-for-1","announced":"2015-06-23","effective":"2015-07-15","basis":"EXTENSION (v10): Netflix 8-K filed 2015-06-23, Ex-99.1: board approved 7-for-1 split via stock dividend, payable 2015-07-14; regular-way post-split trading 2015-07-15."},
]
ALL = EXT + M.EVENTS
def pb_orig(): return E.PriceBook({t:E.get_prices(t) for t in UNI+["SPY"]})
def pb_long():
    cd=os.path.join(D,"cache"); return E.PriceBook({t:bars_long(t,cd) for t in UNI+["SPY"]})
def run1(pb, sched, s, e, cash=100.0, floor=85.0, names=None):
    M.START_CASH=cash; M.FLOOR0=floor
    if names is None: names=[ev["ticker"] for ev in sched]
    r=M.run_event_pot(pb, sched, s, e, names)
    return r
def wrap(pb, sched, s, e, names=None):
    r1=run1(pb,sched,s,e,names=names)
    curve=list(r1.get("curve") or []); costs=r1["costs"]; orders=len(r1["trades"]); halts=0; restart=False; second=False; detail=None
    if r1.get("halted"):
        halts=1; sig=r1["halted"]
        liq=next((d for d in pb.dates if d>sig), sig)
        elig=(dt.date.fromisoformat(liq)+dt.timedelta(days=90)).isoformat()
        if elig<=e:
            restart=True
            r2=run1(pb,sched,elig,e,cash=r1["final"],floor=0.85*r1["final"],names=names)
            curve+=list(r2.get("curve") or []); costs+=r2["costs"]; orders+=len(r2["trades"])
            if r2.get("halted"): halts=2; second=True
            detail={"halt_signal":sig,"liquidation":liq,"eligible":elig,"restart_balance":round(r1["final"],2),"ep2_floor":round(0.85*r1["final"],2)}
            return r2["final"],costs,orders,halts,restart,second,curve,detail
    return r1["final"],costs,orders,halts,restart,second,curve,detail
def placebos(pb, sched, s, e, ranked_final):
    beats=0
    for seed in range(1,21):
        rng=random.Random(seed)
        names=[rng.choice(UNI) for _ in sched]
        f,*_=wrap(pb,sched,s,e,names=names)
        beats+= 1 if ranked_final>f else 0
    return beats
out={"slug":"gap-a7-split-drift"}
po=pb_orig(); pl=pb_long()
integ={}
for nm,(s,e) in (("CONT",("2019-01-02","2026-11-20")),("VAL",("2023-01-03","2026-11-20"))):
    sch=M.schedule_events(po, M.EVENTS, s, e)
    r=run1(po,sch,s,e)
    integ[nm]={"final":round(r["final"],2),"halted":r.get("halted"),"costs":round(r["costs"],2),"orders":len(r["trades"]),"n_events":len(sch)}
out["integrity_runs"]=integ
out["spy"]={"CONT":spy_final(E,po,"2019-01-02","2026-11-20"),"VAL":spy_final(E,po,"2023-01-03","2026-11-20"),
            "LONG":spy_final(E,pl,"2010-01-04","2026-11-20"),"DECADE":spy_final(E,pl,"2016-11-21","2026-11-20")}
runs={}
for nm,(s,e) in (("CONT",("2019-01-02","2026-11-20")),("VAL",("2023-01-03","2026-11-20"))):
    sch=M.schedule_events(po, M.EVENTS, s, e)
    f,c,o,h,rs,sh,curve,detail=wrap(po,sch,s,e)
    beats=placebos(po,sch,s,e,f)
    runs[nm]=run_block(f,s,e,c,o,h,rs,sh,f"{beats}/20",curve); runs[nm]["restart_detail"]=detail; runs[nm]["n_events"]=len(sch)
s,e="2016-11-21","2026-11-20"
sch=M.schedule_events(po, M.EVENTS, s, e)
f,c,o,h,rs,sh,curve,detail=wrap(po,sch,s,e)
runs["DECADE"]=run_block(f,s,e,c,o,h,rs,sh,None,curve); runs["DECADE"]["restart_detail"]=detail; runs["DECADE"]["n_events"]=len(sch)
s,e="2010-01-04","2026-11-20"
sch_l=M.schedule_events(pl, ALL, s, e)
f,c,o,h,rs,sh,curve,detail=wrap(pl,sch_l,s,e)
runs["LONG"]=run_block(f,s,e,c,o,h,rs,sh,None,curve); runs["LONG"]["restart_detail"]=detail; runs["LONG"]["n_events"]=len(sch_l)
out["runs"]=runs
evs=[]
for ev in sch_l:
    nf,_,_,_=M.standalone(pl, ev["ticker"], ev["entry"], ev["exit"])
    sf,_,_,_=M.standalone(pl, "SPY", ev["entry"], ev["exit"])
    evs.append({"ticker":ev["ticker"],"announced":ev["announced"],"entry":ev["entry"],"exit":ev["exit"],
                "net_pct":round(nf-100,2),"spy_pct":round(sf-100,2),"excess_pct":round(nf-sf,2)})
out["events_long"]=evs; out["event_stats_long"]=ev_stats([x["excess_pct"] for x in evs])
json.dump(out, open("/tmp/w7/out_a7.json","w"), indent=1)
print(json.dumps({k:out[k] for k in ("integrity_runs","spy","event_stats_long")}, indent=1))
print({k:(v["final"],v["max_dd_pct"],v["placebo_beaten"]) for k,v in runs.items()})
