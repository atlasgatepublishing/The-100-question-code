#!/usr/bin/env python3
"""Assemble results.json from cells_*.json (finals, placebos, period stats)."""
import json, os
BASE=os.path.join(os.path.dirname(os.path.abspath(__file__)),"..")
out={"wing":"holdings-novel-selection","families":{}}
for fn,key in [("cells_f1.json","novel-f1-slow-filer"),("cells_f2.json","novel-f2-quiet-corrections"),
               ("cells_f4.json","novel-f4-cash-collected"),("cells_pv3.json","novel-pv3-metaorder"),
               ("cells_pv1.json","novel-pv1-standing-bid"),("cells_pv2.json","novel-pv2-last-seller"),
               ("cells_pv4.json","novel-pv4-overnight-confession"),("cells_x3.json","novel-x3-window-dressing")]:
    p=os.path.join(BASE,fn)
    if os.path.exists(p): out["families"][key]=json.load(open(p))
json.dump(out,open(os.path.join(BASE,"results.json"),"w"))
for k,f in out["families"].items():
    print(k, "forms:", list(f["forms"].keys()))
