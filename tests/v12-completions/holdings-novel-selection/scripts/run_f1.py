#!/usr/bin/env python3
"""F1 holdings-count sweep: quarterly, DECADE/CONT/VAL, house(v9)+native."""
import json, os, sys, random, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import f1_engine as E
from common import COUNTS, ckey, period_stats, maxdd
C = E.C
WINDOWS={"DECADE":("2016-11-21","2026-11-20"),"CONT":("2019-01-02","2026-11-20"),"VAL":("2023-01-03","2026-11-20"),
 "CONF_A":("2020-01-01","2023-12-31"),"CONF_B":("2024-01-01","2026-11-20")}
ciks = E.nf1.get_ciks(); filings={}
for t in E.UNIVERSE:
    cik = E.nf1.CIK_OVERRIDES.get(t, ciks[t][0]); filings[t]=E.nf1.get_filing_index(cik)
bars={t: C.bars_adj(E.payload_for(t)) for t in E.UNIVERSE+["SPY"]}
pb=C.FastPriceBook(bars)
sdates=E.cadence_dates(pb, WINDOWS["DECADE"][0], WINDOWS["DECADE"][1], "quarterly")
pools,_=E.nf1.build_pools(filings, sdates)
print("pools built", {d: len(pools[d]) for d in sdates[:3]}, flush=True)
def run_window(s,e,n,form,rng=None):
    td=[d for d in pb.dates if s<=d<=e]
    def run_one(a,b,cash,floor):
        return E.run_pot_cad(pb, pools, a, b, cash, floor, sdates, placebo_rng=rng, n_hold=n)
    if form=="house":
        out=C.run_v9(run_one, td, s, e, 100.0)
        return {"final":round(out["final"],2),"max_dd_pct":maxdd(out["curve"]),"costs":round(out["costs"],2),
                "orders":out["orders"],"halts":len(out["halts"]),"curve":[[d,round(v,2)] for d,v in out["curve"]]}
    r=run_one(s,e,100.0,85.0)
    return {"final":round(r["final"],2),"max_dd_pct":maxdd(r["curve"]),"costs":round(r["costs"],2),
            "orders":len(r["trades"]),"halts":1 if r["halted"] else 0,"curve":[[d,round(v,2)] for d,v in r["curve"]]}
res={"family":"novel-f1-slow-filer","native_count":5,"cadence":"quarterly","forms":{}}
for form in ("house","native"):
    cells={}
    for n in COUNTS:
        c={w:run_window(s,e,n,form) for w,(s,e) in WINDOWS.items()}
        s,e=WINDOWS["DECADE"]; finals=[]
        for seed in range(1,21):
            finals.append(run_window(s,e,n,form,rng=random.Random(seed))["final"])
        real=c["DECADE"]["final"]
        c["placebos_DECADE"]={"finals":finals,"beaten":sum(1 for f in finals if real>f),"median":round(statistics.median(finals),2)}
        cells[ckey(n)]=c; print(form,ckey(n),{w:c[w]["final"] for w in WINDOWS},"pl",c["placebos_DECADE"]["beaten"],flush=True)
    res["forms"][form]=cells
for form in ("house","native"):
    cells=res["forms"][form]; best=max(cells,key=lambda k: cells[k]["DECADE"]["final"])
    res["forms"][form]["_best_DECADE"]=best
    for k in {"5",best}: cells[k]["DECADE"]["period_stats_quarterly"]=period_stats(cells[k]["DECADE"]["curve"],"quarter" if False else "month")
    for k in list(cells):
        if k.startswith("_"): continue
        for w in WINDOWS:
            if not (k in {"5",best} and w=="DECADE"): cells[k][w].pop("curve",None)
json.dump(res,open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","cells_f1.json"),"w"))
print("DONE f1")
