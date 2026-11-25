#!/usr/bin/env python3
"""hunt-reserve-risk — frozen SPEC: BGeometrics keyless reserve-risk series
(verified 2026-11-22). RR-ACCUM (buy<0.0026, sell>=0.0200), RR-ZONE (long
unless >=0.0200). Window = series span only (2022-11-22->latest). NATIVE+V9.
0.60%/side. Price = CoinMetrics PriceUSD aligned by date."""
import json, os, sys, random
sys.path.insert(0, "/tmp/slice6")
from gauge_engine import run, bh, monthly_stats, accum_pos, zone_pos
HERE=os.path.dirname(os.path.abspath(__file__)); D=os.path.join(HERE,"data")
rr={r["d"]: float(r["reserveRisk"]) for r in json.load(open(f"{D}/bgeo_reserve_risk.json"))}
cm={r["time"][:10]: float(r["PriceUSD"]) for r in json.load(open(f"{D}/cm_btc.json"))}
dates=sorted(d for d in rr if d in cm and cm[d]>0)
prices=[cm[d] for d in dates]; sig=[rr[d] for d in dates]
out={"family":"hunt-reserve-risk","window":[dates[0],dates[-1]],"systems":{}}
for name, pos in [("RR-ACCUM", accum_pos(sig,0.0026,0.0200)), ("RR-ZONE", zone_pos(sig,0.0200))]:
    res={}
    for form, fl in [("NATIVE",False),("V9",True)]:
        f,curve,sw,dd2,stop=run(dates,prices,pos,floor=fl)
        res[form]=dict(final=round(f,2), switches=sw, max_dd=round(dd2,4), stopped=stop,
                       curve=[[d,round(e,4)] for d,e in curve], monthly=monthly_stats(curve))
    res["BH_bar"]=round(bh(dates,prices),2); out["systems"][name]=res
pl={}
for s in range(20):
    rng=random.Random(4000+s)
    pos=accum_pos(sig, rng.uniform(0.0015,0.004), rng.uniform(0.012,0.030))
    f,_,_,_,_=run(dates,prices,pos); pl.setdefault("RR-ACCUM",[]).append(round(f,2))
out["placebos"]=pl
json.dump(out, open(os.path.join(HERE,"results.json"),"w"), indent=1)
for n in out["systems"]:
    r=out["systems"][n]; print(n,"NAT",r["NATIVE"]["final"],"V9",r["V9"]["final"],"BH",r["BH_bar"],"sw",r["NATIVE"]["switches"],"sig range",min(sig),max(sig))
