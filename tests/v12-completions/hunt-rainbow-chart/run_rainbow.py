#!/usr/bin/env python3
"""hunt-rainbow-chart — frozen SPEC: 2014 trolololo formula
log10(P)=2.9065*ln(days since 2009-01-03)-19.493; CONSTRUCTED bands 0.20 wide
from -0.50. RAINBOW-ACCUM: enter d<-0.10, exit d>=+0.50. NATIVE+V9. 0.60%/side."""
import json, os, sys, random, math, datetime
sys.path.insert(0, "/tmp/slice6")
from gauge_engine import run, bh, monthly_stats, accum_pos, END
HERE=os.path.dirname(os.path.abspath(__file__)); D=os.path.join(HERE,"data")
cm=json.load(open(f"{D}/cm_btc.json"))
rows=sorted((r["time"][:10], float(r["PriceUSD"])) for r in cm if float(r["PriceUSD"])>0)
GEN=datetime.date(2009,1,3)
dates=[r[0] for r in rows]; prices=[r[1] for r in rows]
dev=[]
for d,p in rows:
    days=(datetime.date.fromisoformat(d)-GEN).days
    reg=2.9065*math.log(days)-19.493
    dev.append(math.log10(p)-reg)
def accum(buy_line, sell_line):
    pos=[]; state=0
    for s in dev:
        if state==0 and s<buy_line: state=1
        elif state==1 and s>=sell_line: state=0
        pos.append(state)
    return pos
WIN={"FULL":(None,END),"DESIGN":(None,"2022-12-31"),"VALIDATION":("2023-01-01",END)}
out={"family":"hunt-rainbow-chart","systems":{"RAINBOW-ACCUM":{}}}
full=accum(-0.10,0.50)
for w,(a,b) in WIN.items():
    idx=[i for i,d in enumerate(dates) if (a is None or d>=a) and d<=b]
    dd=[dates[i] for i in idx]; pp=[prices[i] for i in idx]
    res={}
    for form, fl in [("NATIVE",False),("V9",True)]:
        f,curve,sw,dd2,stop=run(dd,pp,[full[i] for i in idx],floor=fl)
        res[form]=dict(final=round(f,2), switches=sw, max_dd=round(dd2,4), stopped=stop,
                       curve=[[d,round(e,4)] for d,e in curve], monthly=monthly_stats(curve))
    res["BH_bar"]=round(bh(dd,pp),2); out["systems"]["RAINBOW-ACCUM"][w]=res
pl={}
for w in ["FULL","VALIDATION"]:
    a,b=WIN[w]; idx=[i for i,d in enumerate(dates) if (a is None or d>=a) and d<=b]
    dd=[dates[i] for i in idx]; pp=[prices[i] for i in idx]; finals=[]
    for s in range(20):
        rng=random.Random(3000+s); delta=rng.uniform(-0.15,0.15)
        pos=[]; state=0
        for i in idx:
            v=dev[i]
            if state==0 and v<-0.10+delta: state=1
            elif state==1 and v>=0.50+delta: state=0
            pos.append(state)
        f,_,_,_,_=run(dd,pp,pos); finals.append(round(f,2))
    pl[w]=finals
out["placebos"]={"RAINBOW-ACCUM":pl}
json.dump(out, open(os.path.join(HERE,"results.json"),"w"), indent=1)
for w in WIN:
    r=out["systems"]["RAINBOW-ACCUM"][w]; print("RAINBOW",w,"NAT",r["NATIVE"]["final"],"V9",r["V9"]["final"],"BH",r["BH_bar"],"sw",r["NATIVE"]["switches"])
