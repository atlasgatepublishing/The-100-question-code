#!/usr/bin/env python3
"""PV3 holdings-count sweep: monthly rotation, counts grid, house(v9)+native(single-episode)."""
import json, os, sys, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pv3_engine as E
from common import COUNTS, ckey, period_stats, maxdd
OUT=os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","cells_pv3.json")
WINDOWS={"LONG":("2010-01-04","2026-11-20"),"DECADE":("2016-11-21","2026-11-20"),
 "CONT":("2019-01-02","2026-11-20"),"VAL":("2023-01-03","2026-11-20"),
 "CONF_A":("2020-01-01","2023-12-31"),"CONF_B":("2024-01-01","2026-11-20")}
def native(s,e,n):
    cd=E.cadence_dates("monthly",s,e)
    r=E.simulate_cad(s,e,"ranked",cd,n_hold=n)
    return r
def cell(r):
    return {"final":round(r["final"],2),"max_dd_pct":maxdd(r["curve"]),"costs":round(r["costs"],2),
            "orders":r["orders"],"halts":r["halts"] if isinstance(r.get("halts"),list) else ([r["halt_date"]] if r.get("halt_date") else []),
            "curve":[[d,round(v,2)] for d,v in r["curve"]]}
res={"family":"novel-pv3-metaorder","native_count":5,"cadence":"monthly","forms":{}}
for form in ("house","native"):
    cells={}
    for n in COUNTS:
        c={}
        for w,(s,e) in WINDOWS.items():
            if form=="house":
                r=E.run_v9(s,e,"monthly","ranked",n_hold=n); c[w]=cell(r)
            else:
                r=native(s,e,n); c[w]=cell(r)
        if True:  # placebos on DECADE only
            s,e=WINDOWS["DECADE"]; finals=[]
            for seed in range(1,21):
                if form=="house": pr=E.run_v9(s,e,"monthly","placebo",seed=seed,n_hold=n)
                else:
                    cd=E.cadence_dates("monthly",s,e); pr=E.simulate_cad(s,e,"placebo",cd,seed=seed,n_hold=n)
                finals.append(round(pr["final"],2))
            real=c["DECADE"]["final"]
            c["placebos_DECADE"]={"finals":finals,"beaten":sum(1 for f in finals if real>f),"median":round(statistics.median(finals),2)}
        cells[ckey(n)]=c
        print(form,ckey(n),{w:c[w]["final"] for w in WINDOWS},flush=True)
    res["forms"][form]=cells
# period stats for native count + best-on-DECADE per form
for form in ("house","native"):
    cells=res["forms"][form]
    best=max((k for k in cells), key=lambda k: cells[k]["DECADE"]["final"])
    for k in {"5",best}:
        res["forms"][form][k]["DECADE"]["period_stats_monthly"]=period_stats(cells[k]["DECADE"]["curve"])
    res["forms"][form]["_best_DECADE"]=best
    for k in list(cells):
        if k.startswith("_"): continue
        for w in WINDOWS:
            if not (k in {"5",best} and w=="DECADE"): cells[k][w].pop("curve",None)
json.dump(res,open(OUT,"w"))
print("DONE pv3")
