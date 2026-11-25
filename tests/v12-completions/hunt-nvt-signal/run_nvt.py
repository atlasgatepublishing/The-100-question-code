#!/usr/bin/env python3
"""hunt-nvt-signal — frozen SPEC-FROZEN.md: NVTS = CapMrktCurUSD /
SMA90(blockchain.com estimated tx volume USD). NVTS-ACCUM (buy<45, sell>=150)
and NVTS-ZONE (long unless >=150). NATIVE + V9 plain -15% floor. 0.60%/side.
Simulation only."""
import json, os, sys, random, statistics as st
sys.path.insert(0, "/tmp/slice6")
from gauge_engine import run, bh, monthly_stats, accum_pos, zone_pos, END
HERE=os.path.dirname(os.path.abspath(__file__)); D=os.path.join(HERE,"data")
cm=json.load(open(f"{D}/cm_btc.json")); bc=json.load(open(f"{D}/bc_volume.json"))
vol={ }
for v in bc["values"]:
    import datetime
    d=datetime.datetime.utcfromtimestamp(v["x"]).strftime("%Y-%m-%d"); vol[d]=v["y"]
rows=[]
for r in cm:
    d=r["time"][:10]
    if d in vol and float(r["PriceUSD"])>0: rows.append((d, float(r["PriceUSD"]), float(r["CapMrktCurUSD"]), vol[d]))
rows.sort()
dates=[r[0] for r in rows]; prices=[r[1] for r in rows]
sma=[None]*len(rows); s=0.0
for i,r in enumerate(rows):
    s+=r[3]
    if i>=90: s-=rows[i-90][3]
    if i>=89: sma[i]=s/90
nvts=[None if sma[i] is None else rows[i][2]/sma[i] for i in range(len(rows))]
WIN={"FULL":(None,END),"DESIGN":(None,"2022-12-31"),"VALIDATION":("2023-01-01",END)}
out={"family":"hunt-nvt-signal","systems":{}}
for name, mk in [("NVTS-ACCUM", lambda b,s: accum_pos(nvts,b,s)), ("NVTS-ZONE", lambda b,s: zone_pos(nvts,s))]:
    out["systems"][name]={}
    for w,(a,b) in WIN.items():
        idx=[i for i,d in enumerate(dates) if (a is None or d>=a) and d<=b]
        dd=[dates[i] for i in idx]; pp=[prices[i] for i in idx]; ss=[nvts[i] for i in idx]
        res={}
        for form, fl in [("NATIVE",False),("V9",True)]:
            pos= mk(45,150) if name=="NVTS-ACCUM" else mk(None,150)
            pos=[pos[i] for i in idx]
            f,curve,sw,dd2,stop=run(dd,pp,pos,floor=fl)
            res[form]=dict(final=round(f,2), switches=sw, max_dd=round(dd2,4), stopped=stop,
                           curve=[[d,round(e,4)] for d,e in curve], monthly=monthly_stats(curve))
        res["BH_bar"]=round(bh(dd,pp),2)
        out["systems"][name][w]=res
# placebos
random.seed(20261122)
pl={"NVTS-ACCUM":{},"NVTS-ZONE":{}}
for w in ["FULL","VALIDATION"]:
    a,b=WIN[w]; idx=[i for i,d in enumerate(dates) if (a is None or d>=a) and d<=b]
    dd=[dates[i] for i in idx]; pp=[prices[i] for i in idx]
    finals=[]
    for s in range(20):
        rng=random.Random(1000+s)
        pos=accum_pos([nvts[i] for i in idx], rng.uniform(30,65), rng.uniform(110,200))
        f,_,_,_,_=run(dd,pp,pos); finals.append(round(f,2))
    pl["NVTS-ACCUM"][w]=finals
    finals=[]
    for mult in [0.75,0.85,1.15,1.30]:
        pos=zone_pos([nvts[i] for i in idx], 150*mult)
        f,_,_,_,_=run(dd,pp,pos); finals.append(round(f,2))
    pl["NVTS-ZONE"][w]=finals
out["placebos"]=pl
json.dump(out, open(os.path.join(HERE,"results.json"),"w"), indent=1)
for n in out["systems"]:
    for w in WIN:
        r=out["systems"][n][w]
        print(n, w, "NAT", r["NATIVE"]["final"], "V9", r["V9"]["final"], "BH", r["BH_bar"], "sw", r["NATIVE"]["switches"])
