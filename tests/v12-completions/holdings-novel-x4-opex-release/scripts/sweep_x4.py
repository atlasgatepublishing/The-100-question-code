#!/usr/bin/env python3
"""Slice H3: novel-x4-opex-release count sweep. Count = picks per event
(M.TOP_N), native 5. House = v10 driver.run_v9; native = single episode,
no floor. Placebos 20 seeds on DECADE (house). ALL = all eligible per event;
its placebo is degenerate (random draw of all eligible = the pool)."""
import json, os, random
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "x4_results.json")
src = open(os.path.expanduser("~/workspace/stock-app/backtests/v10-retest/novel-x4-opex-release/driver.py")).read()
src = src.split("WINDOWS =")[0]
ns = {"__file__": os.path.expanduser("~/workspace/stock-app/backtests/v10-retest/novel-x4-opex-release/driver.py"), "__name__":"x4driver_head"}
exec(compile(src, "x4driver_head", "exec"), ns)
M = ns["M"]; build = ns["build"]; run_v9 = ns["run_v9"]; CAL = ns["CAL"]
COUNTS = [1,2,3,5,8,10,15,20,30,"ALL"]
WINDOWS = {"LONG":("2010-01-04","2026-11-20"),"DECADE":("2016-11-21","2026-11-20"),
           "CONT":("2019-01-02","2026-11-20"),"VAL":("2023-01-03","2026-11-20")}
orig_topn = M.TOP_N
def build_c(s,e,af,count):
    if count=="ALL":
        evs=[]
        for p in M.build_events(ns["CAL_INDEX"], s, e, 3):
            if af and CAL[p] < af: continue
            ranked, detail = M.screen(ns["CLOSES"], p)
            evs.append({"p":p,"picks":ranked,"n_eligible":len(ranked),"detail":detail})
        return evs
    return build(3,s,e,af)
out = {"roads":{}}
for w,(s,e) in WINDOWS.items():
    cell={}
    for c in COUNTS:
        M.TOP_N = 999 if c=="ALL" else c
        h = run_v9(s,e, lambda s2,e2,af,c=c: build_c(s2,e2,af,c))
        evs = build_c(s,e,None,c)
        M.START_CASH=100.0; M.FLOOR0=0.0
        rn_ = M.run_pot(CAL, ns["CLOSES"], ns["OPENS"], evs, s, e, label="nat")
        M.START_CASH=100.0; M.FLOOR0=85.0
        cell[str(c)]={"house":{"final":round(h["final"],2),"costs":h["costs"],"halts":h["halts"],"max_dd_pct":h["max_dd_pct"]},
                      "native":{"final":round(rn_["final"],2),"costs":round(rn_["costs"],2),"max_dd_pct":rn_["max_drawdown_pct"]}}
        print(w,c,cell[str(c)]["house"]["final"],cell[str(c)]["native"]["final"],flush=True)
    if w=="DECADE":
        for c in COUNTS:
            M.TOP_N = 999 if c=="ALL" else c
            base = build_c(s,e,None,c)
            finals=[]
            for seed in range(1,21):
                rng=random.Random(seed)
                pev=[{"p":ev["p"],"picks": (ev["picks"] if c=="ALL" else rng.sample(sorted(M.UNIVERSE), c)),"n_eligible":None,"detail":{}} for ev in base]
                def pf(s2,e2,af,pev=pev):
                    if af is None: return pev
                    return [ev for ev in pev if CAL[ev["p"]]>=af]
                pr=run_v9(s,e,pf); finals.append(round(pr["final"],2))
            cell[str(c)]["placebo_finals"]=finals
            cell[str(c)]["placebo_beaten"]=sum(1 for f in finals if f<cell[str(c)]["house"]["final"])
    out["roads"][w]=cell
    json.dump(out, open(OUT,"w"))
M.TOP_N = orig_topn
print("X4 DONE")
