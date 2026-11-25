#!/usr/bin/env python3
"""V11 NATIVE — F-9 Presidential cycle (Stock Trader's Almanac / Hirsch).
Form A (core published cycle): long SPY calendar years 3-4 of each term, cash years 1-2.
  Terms inaugurated Jan of Y: year3=Y+2, year4=Y+3. Inaugurations 2009,2013,2017,2021,2025.
Form B (documented Almanac sweet-spot overlay): long from Oct 1 of midterm year (Y+1)
  through Jul 31 of pre-election year (Y+2) only; cash otherwise.
No stop/floor published (none applied). Costs 0.10%/side + $0.01/sell. 20 circular-shift placebos."""
import json, os, sys
sys.path.insert(0, "/tmp")
from engine import bars, run, spy_bh, placebos
from datetime import date
INAUG=[2009,2013,2017,2021,2025]
def desA():
    longy=set()
    for Y in INAUG: longy|={Y+2,Y+3}
    return {b["date"]: date.fromisoformat(b["date"]).year in longy for b in bars}
def desB():
    des={}
    for b in bars:
        d=date.fromisoformat(b["date"]); long=False
        for Y in INAUG:
            if date(Y+1,10,1) <= d <= date(Y+2,7,31): long=True
        des[b["date"]]=long
    return des
WINDOWS=[("LONG","2010-01-01","2026-11-20"),("CONT","2019-01-01","2026-11-20"),
         ("VAL","2023-01-01","2026-11-20"),("DECADE","2016-11-21","2026-11-20")]
res={"family":"folklore-f9-presidential","forms":{}}
for name,des in [("A_core_years3_4",desA()),("B_sweet_spot_oct_midterm_to_jul_preelection",desB())]:
    f={"windows":{}}
    for w,s,e in WINDOWS:
        r=run(bars,des,s,e); sp=spy_bh(bars,s,e)
        f["windows"][w]={"strategy":r,"spy_final":sp["final"],"spy_max_dd_pct":sp["max_dd_pct"]}
    f["placebos_long"]=placebos(bars,des,"2010-01-01","2026-11-20")
    f["placebos_decade"]=placebos(bars,des,"2016-11-21","2026-11-20")
    folds={}
    for y in range(2010,2027):
        s=f"{y}-01-01"; e=f"{y}-12-31" if y<2026 else "2026-11-20"
        folds[str(y)]=run(bars,des,s,e)["final"]
    f["year_folds"]=folds
    res["forms"][name]=f
json.dump(res, open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"results.json"),"w"), indent=1)
for name,f in res["forms"].items():
    print(name, {w:(v["strategy"]["final"], v["strategy"]["max_dd_pct"], v["spy_final"]) for w,v in f["windows"].items()})
    print(" placebo LONG median/max", f["placebos_long"]["median"], f["placebos_long"]["max"], "| DECADE", f["placebos_decade"]["median"], f["placebos_decade"]["max"])
