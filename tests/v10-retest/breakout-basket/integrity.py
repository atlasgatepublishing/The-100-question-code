#!/usr/bin/env python3
"""Integrity gate for breakout-basket (v10 retest).

Reproduces the ORIGINAL published finals through the ORIGINAL plumbing in
its ORIGINAL form: the v4 engine (backtests/v4/breakout-basket.py) driving
the v2 tournament Portfolio (floor + profit ladder), original windows:
  FULL/continuous 2016-11-21 -> 2026-11-20  (task's "CONT" $309.85)
  VALIDATION      2023-01-01 -> 2026-11-20  (task's "VAL"  $156.71)
Data: the tournament's own cached Yahoo bars (split-adjusted, not
dividend-adjusted), read-only. Nothing here is modified.
"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.join(HERE, "..", "..", "v4")
sys.path.insert(0, V4)
import importlib.util
spec = importlib.util.spec_from_file_location("bb_v4", os.path.join(V4, "breakout-basket.py"))
bb = importlib.util.module_from_spec(spec); spec.loader.exec_module(bb)

frames = bb.build_frames()
out = {}
for name, window in (("continuous", bb.FULL), ("validation", bb.VALIDATION)):
    pf, mkt, r, g, n = bb.run_window(frames, window, "c_breakout52_basket")
    out[name] = {"final": r["final"], "orders": r["orders"], "max_dd_pct": r["max_dd_pct"],
                 "total_costs": r["total_costs"], "halt_date": r["halt_date"], "spy_net": n}
    print(name, round(r["final"], 4), "orders", r["orders"], "halt", r["halt_date"])
res = {"original": {"continuous_final": 309.85, "validation_final": 156.71},
       "reproduced": out,
       "status": "reproduced" if abs(out["continuous"]["final"]-309.85) < 0.05
                 and abs(out["validation"]["final"]-156.71) < 0.05 else "FAILED"}
with open(os.path.join(HERE, "integrity.json"), "w") as fh:
    json.dump(res, fh, indent=2)
print(res["status"])
