#!/usr/bin/env python3
"""Confirmation for orgcap grid counts 1/2/3: split folds 2016-2020 and
2021-2025 formations (different years than the full-road prints)."""
import importlib.util, json, os
spec=importlib.util.spec_from_file_location("oc", os.path.join(os.path.dirname(os.path.abspath(__file__)),"run_orgcap.py"))
# run_orgcap executes at import; instead re-implement minimal by exec of defs only:
src=open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"run_orgcap.py")).read()
head=src.split("ROADS=")[0]
g={"__name__":"oc_defs","__file__":os.path.join(os.path.dirname(os.path.abspath(__file__)),"run_orgcap.py")}
exec(head, g)
run_road=g["run_road"]; spy=g["spy"]; months=g["months"]; ym=g["ym"]
out={}
for cnt in [1,2,3]:
    out[str(cnt)]={}
    for nm, fy in [("FOLD16-20", list(range(2016,2021))), ("FOLD21-25", list(range(2021,2026)))]:
        f,_=run_road(fy,cnt)
        pls=[run_road(fy,cnt,placebo_seed=8000+s)[0] for s in range(20)]
        a,b=ym(fy[0],6), ym(fy[-1]+1,6)
        sa=[spy[m] for m in months if a<=m<=b]
        bar=round(100*(1-0.001)*(sa[-1]/sa[0])*(1-0.001),2)
        out[str(cnt)][nm]=dict(final=f, SPY_bar=bar, placebo_beaten=sum(1 for x in pls if f>x))
        print(cnt, nm, f, "SPY", bar, "plbeat", out[str(cnt)][nm]["placebo_beaten"], flush=True)
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"grid","confirm_folds.json"),"w"), indent=1)
