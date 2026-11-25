#!/usr/bin/env python3
"""V11 NATIVE — F-2 Lunar. Yuan-Zheng-Zhu (2006) / Dichev-Janes (2003) published windows.
Primary: 15-day window = trading days whose calendar date is within +/-7 days of a new moon.
Secondary documented form: 7-day window (+/-3 days). Long SPY in window, cash out.
No stop/floor in the sources (none applied; drawdown reported). Costs 0.10%/side + $0.01/sell.
Placebo: full-moon windows (identical machine, opposite phase) + 20 circular-shift seeds.
New moons: synodic computation from reference new moon 2000-01-06, period 29.530588853 d."""
import json, os, sys
from datetime import date, timedelta
sys.path.insert(0, "/tmp")
from engine import bars, run, spy_bh, placebos

REF = date(2000,1,6); SYN = 29.530588853
def events(kind, lo, hi):
    out=[]; k=0
    while True:
        base = REF + timedelta(days=SYN*k) if kind=="new" else REF + timedelta(days=SYN*(k+0.5))
        if base > hi: break
        if base >= lo: out.append(base)
        k+=1
    return out
def desired(half, kind):
    ev = events(kind, date(2007,1,1), date(2027,1,1))
    des={}
    for b in bars:
        d=date.fromisoformat(b["date"])
        des[b["date"]] = any(abs((d-e).days)<=half for e in ev)
    return des

WINDOWS=[("LONG","2010-01-01","2026-11-20"),("CONT","2019-01-01","2026-11-20"),
         ("VAL","2023-01-01","2026-11-20"),("DECADE","2016-11-21","2026-11-20")]
res={"family":"folklore-f2-lunar","forms":{}}
for name,half in [("15day_primary",7),("7day_secondary",3)]:
    des=desired(half,"new"); ctrl=desired(half,"full")
    f={"windows":{}}
    for w,s,e in WINDOWS:
        r=run(bars,des,s,e); c=run(bars,ctrl,s,e); sp=spy_bh(bars,s,e)
        f["windows"][w]={"strategy":r,"full_moon_control_final":c["final"],"spy_final":sp["final"],"spy_max_dd_pct":sp["max_dd_pct"]}
    f["placebos_long"]=placebos(bars,des,"2010-01-01","2026-11-20")
    f["placebos_decade"]=placebos(bars,des,"2016-11-21","2026-11-20")
    folds={}
    for y in range(2010,2027):
        s=f"{y}-01-01"; e=f"{y}-12-31" if y<2026 else "2026-11-20"
        folds[str(y)]=run(bars,des,s,e)["final"]
    f["year_folds_long_window_starts"]=folds
    res["forms"][name]=f
json.dump(res, open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"results.json"),"w"), indent=1)
for name,f in res["forms"].items():
    print(name, {w:(v["strategy"]["final"], v["full_moon_control_final"], v["spy_final"]) for w,v in f["windows"].items()})
    print(" placebo LONG median/max", f["placebos_long"]["median"], f["placebos_long"]["max"], "| DECADE", f["placebos_decade"]["median"], f["placebos_decade"]["max"])
