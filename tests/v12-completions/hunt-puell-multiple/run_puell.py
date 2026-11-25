#!/usr/bin/env python3
"""hunt-puell-multiple — frozen SPEC: Puell = IssTotUSD / SMA365(IssTotUSD).
PUELL-ACCUM (buy<0.5, sell>=4.0), PUELL-ZONE (long unless >=4.0). 365d warmup
in cash. NATIVE + V9 plain floor. 0.60%/side. Simulation only."""
import json, os, sys, random
sys.path.insert(0, "/tmp/slice6")
from gauge_engine import run, bh, monthly_stats, accum_pos, zone_pos, END
HERE=os.path.dirname(os.path.abspath(__file__)); D=os.path.join(HERE,"data")
cm=json.load(open(f"{D}/cm_btc.json"))
rows=sorted((r["time"][:10], float(r["PriceUSD"]), float(r["IssTotUSD"])) for r in cm if float(r["PriceUSD"])>0)
dates=[r[0] for r in rows]; prices=[r[1] for r in rows]
sma=[None]*len(rows); s=0.0
for i,r in enumerate(rows):
    s+=r[2]
    if i>=365: s-=rows[i-365][2]
    if i>=364: sma[i]=s/365
puell=[None if sma[i] is None else rows[i][2]/sma[i] for i in range(len(rows))]
WIN={"FULL":(None,END),"DESIGN":(None,"2022-12-31"),"VALIDATION":("2023-01-01",END)}
out={"family":"hunt-puell-multiple","systems":{}}
for name, mk in [("PUELL-ACCUM", lambda: accum_pos(puell,0.5,4.0)), ("PUELL-ZONE", lambda: zone_pos(puell,4.0))]:
    full=mk(); out["systems"][name]={}
    for w,(a,b) in WIN.items():
        idx=[i for i,d in enumerate(dates) if (a is None or d>=a) and d<=b]
        dd=[dates[i] for i in idx]; pp=[prices[i] for i in idx]
        res={}
        for form, fl in [("NATIVE",False),("V9",True)]:
            f,curve,sw,dd2,stop=run(dd,pp,[full[i] for i in idx],floor=fl)
            res[form]=dict(final=round(f,2), switches=sw, max_dd=round(dd2,4), stopped=stop,
                           curve=[[d,round(e,4)] for d,e in curve], monthly=monthly_stats(curve))
        res["BH_bar"]=round(bh(dd,pp),2); out["systems"][name][w]=res
pl={"PUELL-ACCUM":{},"PUELL-ZONE":{}}
for w in ["FULL","VALIDATION"]:
    a,b=WIN[w]; idx=[i for i,d in enumerate(dates) if (a is None or d>=a) and d<=b]
    dd=[dates[i] for i in idx]; pp=[prices[i] for i in idx]
    finals=[]
    for s in range(20):
        rng=random.Random(2000+s)
        pos=accum_pos([puell[i] for i in idx], rng.uniform(0.35,0.65), rng.uniform(3.0,5.0))
        f,_,_,_,_=run(dd,pp,pos); finals.append(round(f,2))
    pl["PUELL-ACCUM"][w]=finals
    finals=[]
    for mult in [0.75,0.85,1.15,1.30]:
        pos=zone_pos([puell[i] for i in idx], 4.0*mult)
        f,_,_,_,_=run(dd,pp,pos); finals.append(round(f,2))
    pl["PUELL-ZONE"][w]=finals
out["placebos"]=pl
json.dump(out, open(os.path.join(HERE,"results.json"),"w"), indent=1)
for n in out["systems"]:
    for w in WIN:
        r=out["systems"][n][w]; print(n,w,"NAT",r["NATIVE"]["final"],"V9",r["V9"]["final"],"BH",r["BH_bar"],"sw",r["NATIVE"]["switches"])
