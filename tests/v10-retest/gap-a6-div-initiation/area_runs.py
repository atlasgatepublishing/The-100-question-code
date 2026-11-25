import sys, os, json, random, datetime as dt
sys.path.insert(0,'/tmp/w7')
from lib import *
SLUG_DIR = os.path.expanduser("~/workspace/stock-app/backtests/v10-retest/gap-a6-div-initiation")
M = load_mod("a6", os.path.join(SLUG_DIR,"engine.py"))
E = M.E
UNI = M.UNIVERSE
EXT = [
 {"name":"CSCO","announce":"2011-03-18","basis":"EXTENSION (v10): first dividend EVER. Cisco press release 2011-03-18: board approved initiation of quarterly cash dividends on 2011-03-17; first-ever cash dividend $0.06, paid 2011-04-20. Tape (div_CSCO.json, 2005->2026): no dividend before 2011."},
 {"name":"AAPL","announce":"2012-03-19","basis":"EXTENSION (v10): first dividend in >=5y (last paid 1995; 17-year silence). Apple press release 2012-03-19 'Apple Announces Plans to Initiate Dividend and Share Repurchase Program' — quarterly dividend $2.65 planned from FY Q4 2012. Tape: no dividend 2005->2012."},
]
ALL_EVENTS = EXT + M.EVENTS

def pb_orig():
    bars={t:E.get_prices(t) for t in UNI+["SPY"]}
    return E.PriceBook(bars)
def pb_long():
    cd=os.path.join(SLUG_DIR,"cache"); bars={t:bars_long(t,cd) for t in UNI+["SPY"]}
    return E.PriceBook(bars)

def wrap(pb, sched, s, e):
    r1 = M.run_event_pot(pb, sched, s, e)
    curve=list(r1["curve"]); costs=r1["costs"]; orders=len(r1["trades"]); halts=0; restart=False; second=False
    if r1["halted"]:
        halts=1
        sig=r1["halted"]
        liq=next((d for d in pb.dates if d>sig), sig)
        elig=(dt.date.fromisoformat(liq)+dt.timedelta(days=90)).isoformat()
        if elig<=e:
            restart=True
            r2=M.run_event_pot(pb, sched, elig, e, start_cash=r1["final"], floor0=0.85*r1["final"])
            curve+=list(r2["curve"]); costs+=r2["costs"]; orders+=len(r2["trades"])
            if r2["halted"]: halts=2; second=True
            return r2["final"], costs, orders, halts, restart, second, curve, {"halt_signal":sig,"liquidation":liq,"eligible":elig,"restart_balance":round(r1["final"],2),"ep2_floor":round(0.85*r1["final"],2)}
    return r1["final"], costs, orders, halts, restart, second, curve, None

def placebos(pb, sched, s, e, ranked_final):
    beats=0; finals=[]
    rng_master=random.Random(20261121)
    for seed in range(1,21):
        rng=random.Random(seed)
        ps=[{**ev,"name":rng.choice(UNI)} for ev in sched]
        f,*_=wrap(pb, ps, s, e)
        finals.append(round(f,2)); beats+= 1 if ranked_final>f else 0
    return beats, finals

out={"slug":"gap-a6-div-initiation"}
po=pb_orig(); pl=pb_long()
sched_o=M.derive_schedule(po, M.EVENTS)
# integrity on original pricebook, original windows, episode-1 form = original engine call
integ={}
for nm,(s,e) in (("CONT",("2019-01-02","2026-11-20")),("VAL",("2023-01-03","2026-11-20"))):
    r=M.run_event_pot(po, sched_o, s, e)
    integ[nm]={"final":round(r["final"],2),"halted":r["halted"],"costs":round(r["costs"],2),"orders":len(r["trades"])}
out["integrity_runs"]=integ
out["spy"]={"CONT":spy_final(E,po,"2019-01-02","2026-11-20"),"VAL":spy_final(E,po,"2023-01-03","2026-11-20"),
            "LONG":spy_final(E,pl,"2010-01-04","2026-11-20"),"DECADE":spy_final(E,pl,"2016-11-21","2026-11-20")}
runs={}
# CONT / VAL (v9 wrapper on original pricebook)
for nm,(s,e) in (("CONT",("2019-01-02","2026-11-20")),("VAL",("2023-01-03","2026-11-20"))):
    f,c,o,h,rs,sh,curve,rst=wrap(po, sched_o, s, e)
    pb_beats,_=placebos(po, sched_o, s, e, f)
    runs[nm]=run_block(f,s,e,c,o,h,rs,sh,f"{pb_beats}/20",curve)
    runs[nm]["restart_detail"]=rst
# DECADE (original pricebook; spine starts 2017-06-01, pot in cash until first event 2024 regardless)
s,e="2016-11-21","2026-11-20"
f,c,o,h,rs,sh,curve,rst=wrap(po, sched_o, s, e)
runs["DECADE"]=run_block(f,s,e,c,o,h,rs,sh,None,curve); runs["DECADE"]["restart_detail"]=rst
# LONG (extended pricebook + extended census)
sched_l=M.derive_schedule(pl, ALL_EVENTS)
s,e="2010-01-04","2026-11-20"
f,c,o,h,rs,sh,curve,rst=wrap(pl, sched_l, s, e)
runs["LONG"]=run_block(f,s,e,c,o,h,rs,sh,None,curve); runs["LONG"]["restart_detail"]=rst
out["runs"]=runs
# per-event standalone excess on LONG (all 4 events)
evs=[]
for ev in sched_l:
    if ev["exit"] is None: continue
    nf,_,_,_=M.standalone(pl, ev["name"], ev["entry"], ev["exit"])
    sf,_,_,_=M.standalone(pl, "SPY", ev["entry"], ev["exit"])
    evs.append({"name":ev["name"],"announce":ev["announce"],"entry":ev["entry"],"exit":ev["exit"],
                "net_pct":round(nf-100,2),"spy_pct":round(sf-100,2),"excess_pct":round(nf-sf,2)})
out["events_long"]=evs
out["event_stats_long"]=ev_stats([x["excess_pct"] for x in evs])
out["sched_long"]=[{k:ev[k] for k in ("name","announce","entry","exit")} for ev in sched_l]
json.dump(out, open("/tmp/w7/out_a6.json","w"), indent=1)
print(json.dumps(out, indent=1)[:3000])
