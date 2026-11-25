#!/usr/bin/env python3
"""
CHAMPION (value+momentum) — longest honest run.

Rebuilds the 2010 point-in-time pond with this test's own plumbing,
asserts it equals the published long-hold universe, reproduces the
published Terry's-rules run ($85.34, halted 2010-08-26), then runs the
official v9-rules run and reconciles it against the published v9
long-hold ($1,415.62) field by field.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lr_common as C  # noqa: E402
import lr_engines as E  # noqa: E402

START, END = "2010-01-04", C.END

P = E.pool_data()
pb_info = E.pond_at(START)
pond = pb_info["pond"]
with open(os.path.join(C.BT, "v7", "long-hold",
                       "universe-build-long.json")) as f:
    pub = json.load(f)
pond_match = pond == pub["universe"]
print(f"pond rebuilt == published long-hold universe: {pond_match}",
      flush=True)
print(f"pond: {pond}", flush=True)

# ---- Terry's rules (published his-rules form)
terry, terry_spy = E.champion_terry(pond, START, END)
print(f"TERRY run: final ${terry['final']:,.2f} halted={terry['halted']} "
      f"halt={terry.get('halt_info')}", flush=True)
terry_repro = (round(terry["final"], 2) == 85.34 and terry["halted"]
               and terry["halt_info"]["signal_date"] == "2010-08-26")

# ---- v9 rules (official)
res = E.champion_v9(pond, START, END)
print(f"V9 run: final ${res['final']:,.2f} halts={res['halts']} "
      f"restart={res['restart']} spy=${res['spy_final']:,.2f}",
      flush=True)

with open(os.path.join(C.BT, "v9-muse-rules", "long-hold",
                       "v9-results.json")) as f:
    v9pub = json.load(f)
rec = {
    "pond_matches_published": pond_match,
    "terry_final": round(terry["final"], 2),
    "terry_halt": terry.get("halt_info"),
    "terry_reproduces_published_85.34_halt_2010-08-26": terry_repro,
    "v9_final_mine": res["final"],
    "v9_final_published": v9pub["v9"]["finals"]["long_hold_2010_start"],
    "v9_final_match":
        res["final"] == v9pub["v9"]["finals"]["long_hold_2010_start"],
    "v9_restart_mine": res["restart"],
    "v9_restart_published": v9pub["v9"]["restarts"],
    "v9_ep2_worst_published": {
        "close": 81.04, "date": "2011-08-08",
        "source": "v9-results.json notes (episode 2 worst close)"},
    "v9_ep2_worst_mine": {
        "close": res["episodes"][1]["worst_close"],
        "date": res["episodes"][1]["worst_close_date"]},
    "v9_total_costs_mine": res["costs"],
    "v9_total_costs_published": 17.81,
    "v9_total_costs_source": "v9-results.json notes ($0.43 ep1 + "
                             "$17.39 ep2)",
    "spy_mine": res["spy_final"],
    "spy_published": v9pub["his"]["finals"]["spy_buyhold_same_window"],
    "spy_match":
        res["spy_final"] == v9pub["his"]["finals"]["spy_buyhold_same_window"],
}
out = {"pond_build": {k: pb_info[k] for k in
                      ("start", "price_date", "pond", "unrankable",
                       "ranking")},
       "terry_rules": {"final": round(terry["final"], 2),
                       "halted": terry["halted"],
                       "halt_info": terry.get("halt_info"),
                       "costs": round(terry["costs"], 2),
                       "orders": len(terry["trades"]),
                       "spy": round(terry_spy, 2),
                       "diag": C.curve_diagnostics(terry["curve"])},
       "v9": res, "reconciliation": rec}
with open(os.path.join(HERE, "results_champion.json"), "w") as f:
    json.dump(out, f, indent=1, default=str)
print(json.dumps(rec, indent=1, default=str), flush=True)
print("saved results_champion.json", flush=True)
