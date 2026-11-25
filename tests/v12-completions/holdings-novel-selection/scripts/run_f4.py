#!/usr/bin/env python3
"""F4 holdings-count sweep: quarterly, DECADE/CONT/VAL, house(v9)+native(single episode)."""
import json, os, sys, random, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import f4_engine as F
eng=F.eng
from common import COUNTS, ckey, period_stats, maxdd
WINDOWS={"DECADE":("2016-11-21","2026-11-20"),"CONT":("2019-01-02","2026-11-20"),"VAL":("2023-01-03","2026-11-20"),
 "CONF_A":("2020-01-01","2023-12-31"),"CONF_B":("2024-01-01","2026-11-20")}
bars={t: F.get_prices_local(t) for t in eng.UNIVERSE+["SPY"]}
pb=eng.PriceBook(bars)
sel=F.cadence_dates(pb,"quarterly",WINDOWS["DECADE"][0],WINDOWS["DECADE"][1])
ranked_by_date=json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"f4_ranked_cache.json")))
print("ranked cache loaded", len(sel), flush=True)
def picks_for(n):
    out={}
    for d,r in ranked_by_date.items():
        picks = r if n is None else (r[:n] if len(r)>=3 else [])
        if n is not None and len(r)<3: picks=[]
        out[d]={"eligible": sorted(r), "picks": picks}
    return out
def run_window(s,e,n,form,rng=None):
    pbd=picks_for(n)
    if form=="house":
        if rng is not None:
            r=F.run_pot_v9c_placebo(pb,pbd,sel,s,e,100.0,rng)
        else:
            r=F.run_pot_v9c(pb,pbd,sel,s,e,100.0)
        return {"final":round(r["final"],2),"max_dd_pct":maxdd(r["curve"]),"costs":round(r["costs"],2),
                "orders":len(r["trades"]),"halts":(1 if r["halted"] else 0)+(1 if r["second_halt"] else 0),
                "curve":[[d,round(v,2)] for d,v in r["curve"]]}
    floor1=round(0.85*100.0,2)
    r=F.run_pot_c(pb,pbd,sel,s,e,100.0,floor1,placebo_rng=rng)
    return {"final":round(r["final"],2),"max_dd_pct":maxdd(r["curve"]),"costs":round(r["costs"],2),
            "orders":len(r["trades"]),"halts":1 if r["halted"] else 0,"curve":[[d,round(v,2)] for d,v in r["curve"]]}
res={"family":"novel-f4-cash-collected","native_count":5,"cadence":"quarterly","forms":{}}
import os as _os
ONLY=_os.environ.get("F4_ONLY","")
if ONLY:
    _parts=ONLY.split(":"); _forms=_parts[0].split(","); _counts=_parts[1].split(",")
else:
    _forms=None; _counts=None
for form in ("house","native"):
    if _forms and form not in _forms: continue
    cells={}
    for n in COUNTS:
        if _counts and ckey(n) not in _counts: continue
        c={w:run_window(s,e,n,form) for w,(s,e) in WINDOWS.items()}
        s,e=WINDOWS["DECADE"]; finals=[]
        for seed in range(1,21):
            finals.append(run_window(s,e,n,form,rng=random.Random(seed))["final"])
        real=c["DECADE"]["final"]
        c["placebos_DECADE"]={"finals":finals,"beaten":sum(1 for f in finals if real>f),"median":round(statistics.median(finals),2)}
        cells[ckey(n)]=c; print(form,ckey(n),{w:c[w]["final"] for w in WINDOWS},"pl",c["placebos_DECADE"]["beaten"],flush=True)
    res["forms"][form]=cells
for form in ("house","native"):
    if form not in res["forms"]: continue
    cells=res["forms"][form]; best=max(cells,key=lambda k: cells[k]["DECADE"]["final"])
    res["forms"][form]["_best_DECADE"]=best
    for k in {"5",best}:
        if k in cells: cells[k]["DECADE"]["period_stats_monthly"]=period_stats(cells[k]["DECADE"]["curve"])
    for k in list(cells):
        if k.startswith("_"): continue
        for w in WINDOWS:
            if not (k in {"5",best} and w=="DECADE"): cells[k][w].pop("curve",None)
_outp=os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","cells_f4.json")
for _f in list(res["forms"]):
    for _k in list(res["forms"][_f]):
        if _k.startswith("_"): continue
        for _w in list(res["forms"][_f][_k]):
            if isinstance(res["forms"][_f][_k][_w],dict): res["forms"][_f][_k][_w].pop("curve",None)
import sys as _s; _s.stdout.write("RESULTJSON:"+json.dumps(res)+"\n")
print("DONE f4")
