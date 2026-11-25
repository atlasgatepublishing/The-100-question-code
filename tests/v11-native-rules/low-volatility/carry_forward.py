#!/usr/bin/env python3
"""Carry-forward only: copies the v10 native-cadence (monthly) cell into this folder's results.json. No new backtest is run in v11 for this family — see NATIVE-SPEC.md (strict published native form is not honestly buildable on free data)."""
import json,sys
src=sys.argv[1]; dst=sys.argv[2]
d=json.load(open(src))
json.dump({"cadence":"monthly","final":d.get("final"),"cagr_pct":d.get("cagr_pct"),"max_dd_pct":d.get("max_dd_pct"),"costs":d.get("costs"),"orders":d.get("orders"),"equity_curve":d.get("equity_curve") or d.get("curve")}, open(dst,"w"), indent=1)
print("carried", d.get("final"))
