#!/usr/bin/env python3
"""F2 holdings-count sweep: quarterly, DECADE/CONT/VAL, house(v9)+native."""
import json, os, sys, random, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import f2_engine as E
from common import COUNTS, ckey, period_stats, maxdd
WINDOWS={"DECADE":("2016-11-21","2026-11-20"),"CONT":("2019-01-02","2026-11-20"),"VAL":("2023-01-03","2026-11-20"),
 "CONF_A":("2020-01-01","2023-12-31"),"CONF_B":("2024-01-01","2026-11-20")}
bars={t: E.bars_adj(E.load_payload(t)) for t in E.UNIVERSE+["SPY"]}
pb=E.FastPriceBook(bars); orig,amend=E.load_signal()
def run_window(s,e,n,form,rng=None):
    td=[d for d in pb.dates if s<=d<=e]
    def run_one(a,b,cash,floor):
        return E.run_pot_cadence(pb, orig, amend, "quarterly", a, b, cash, floor, placebo_rng=rng, n_hold=n)
    if form=="house":
        out=E.run_v9(run_one, td, s, e)
        return {"final":round(out["final"],2),"max_dd_pct":maxdd(out["curve"]),"costs":round(out["costs"],2),
                "orders":out["orders"],"halts":len(out["halts"]),"curve":[[d,round(v,2)] for d,v in out["curve"]]}
    r=run_one(s,e,100.0,85.0)
    return {"final":round(r["final"],2),"max_dd_pct":maxdd(r["curve"]),"costs":round(r["costs"],2),
            "orders":len(r["trades"]),"halts":1 if r["halted"] else 0,"curve":[[d,round(v,2)] for d,v in r["curve"]]}
res={"family":"novel-f2-quiet-corrections","native_count":5,"cadence":"quarterly","forms":{}}
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
    for k in {"5",best}: cells[k]["DECADE"]["period_stats_monthly"]=period_stats(cells[k]["DECADE"]["curve"])
    for k in list(cells):
        if k.startswith("_"): continue
        for w in WINDOWS:
            if not (k in {"5",best} and w=="DECADE"): cells[k][w].pop("curve",None)
json.dump(res,open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","cells_f2.json"),"w"))
print("DONE f2")
