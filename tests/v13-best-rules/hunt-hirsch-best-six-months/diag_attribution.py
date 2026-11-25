#!/usr/bin/env python3
"""Reporting-only attribution (NOT a rule choice; rules were frozen in
BEST-RULES-SPEC.md before the run). Decomposes the v13 improvement over the
v12 published form into (a) vehicle DIA->SPY at cash-0% and (b) the SHY
off-season leg, by re-running the same calendar state with the off-season
asset's returns zeroed (cash form on the SPY vehicle)."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_v13 as R

out = {}
st = R.build_state()
for road, (s, e) in R.ROADS.items():
    # cash form: temporarily flatten SHY (all closes equal -> 0% off-season,
    # switch costs still charged on both legs, an upper bound on cash form)
    saved = [b["SHY"] for b in R.bars]
    for b in R.bars: b["SHY"] = saved[0]
    r_cash = R.simulate(st, s, e)
    for b, v in zip(R.bars, saved): b["SHY"] = v
    r_mine = R.simulate(st, s, e)
    out[road] = {"spy_cash0": r_cash["final"], "spy_shy_mine": r_mine["final"],
                 "published_v12_dia_cash0": R.PUBLISHED_V12[road]}
    print(road, out[road])
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "diag_attribution.json"), "w"), indent=1)
