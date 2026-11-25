#!/usr/bin/env python3
"""
BLEND-ETF-CHASSIS — v10 GREAT RETEST, INTEGRITY GATE.

Reproduces the ORIGINAL published finals through the ORIGINAL engine
(backtests/v4/blend.py, imported read-only; nothing is written outside
this folder). Original form = the frozen v4 blend:
  - Sleeve A: ETF trend sleeve, monthly (../v3/etf-trend-sleeve-monthly.py)
  - Sleeve B: Disciplined chassis combo (quarterly selection + daily exits)
  - 50/50 pot, January rebalance to 50/50, pot-level floor+LADDER
    (0.85*S; S @ 1.25*S close; 1.25*S @ 1.50*S close), halt ends run.

Published targets (backtests/v4/blend.md / blend-results.json):
  - Sleeve A parent, full $100: $194.61, 389 orders, $9.17 costs
  - Sleeve B parent, full $100: $233.54, 152 trades, $6.47 costs
  - BLEND full 2016-11-21->2026-11-20 $100: $211.80, 556 orders, $9.38
    costs, max DD -9.26%, no halts
  - BLEND val 2023-01-01->2026-11-20 $100: $132.73, 230 orders, $3.34
    costs, max DD -8.02%, no halts
  - SPY buy-hold net, full $100: $367.80
Cross-check (NOT published; a prior batch worker's scratch): CONT
2019-01-02->2026-11-20 in original form ~= $181.23 — recomputed here.
"""
import importlib.util
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
V4_BLEND = os.path.join(HERE, "..", "..", "v4", "blend.py")


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BL = load_module("v4_blend", V4_BLEND)

FULL = ("2016-11-21", "2026-11-20")
VAL = ("2023-01-01", "2026-11-20")   # original blend.py validation window
CONT = ("2019-01-02", "2026-11-20")  # SPEC canonical CONT window


def max_dd(curve):
    peak, mdd = -1e18, 0.0
    for _, eq in curve:
        peak = max(peak, eq)
        if peak > 0:
            mdd = min(mdd, eq / peak - 1.0)
    return round(mdd * 100, 2)


def main():
    out = {}

    # ---- parent replication checks (as in the original script) ----
    a_pub = BL.A_MOD.simulate(*FULL)
    out["repl_A_parent"] = {"final": round(a_pub["final"], 2),
                            "orders": a_pub["orders"],
                            "costs": round(a_pub["costs"], 2),
                            "published": {"final": 194.61, "orders": 389,
                                          "costs": 9.17}}
    b_pub = BL.B_MOD.run_window(BL.B_MKT, dict(BL.B_CFG), *FULL,
                                start_capital=100.0)
    out["repl_B_parent"] = {"final": b_pub["final_balance"],
                            "orders": b_pub["total_trades"],
                            "costs": b_pub["total_costs"],
                            "published": {"final": 233.54, "orders": 152,
                                          "costs": 6.47}}

    # ---- the blend itself, original form ----
    for label, win, pub in (
            ("full", FULL, {"final": 211.80, "orders": 556, "costs": 9.38,
                            "maxdd_pct": -9.26, "halted": None}),
            ("val", VAL, {"final": 132.73, "orders": 230, "costs": 3.34,
                          "maxdd_pct": -8.02, "halted": None}),
            ("cont", CONT, None)):
        res = BL.run_blend(win[0], win[1], 100.0)
        rec = {"window": list(win), "final": round(res["final"], 2),
               "orders": res["orders"], "costs": round(res["costs"], 2),
               "maxdd_pct": max_dd(res["curve"]), "halted": res["halted"],
               "n_rebalances": len(res["rebalances"])}
        if pub:
            rec["published"] = pub
            rec["matches_published"] = (
                rec["final"] == pub["final"] and rec["orders"] == pub["orders"]
                and rec["costs"] == pub["costs"]
                and rec["maxdd_pct"] == pub["maxdd_pct"]
                and rec["halted"] == pub["halted"])
        out[f"blend_{label}_100"] = rec
        print(label, json.dumps(rec))

    out["spy_full_100"] = round(BL.spy_buy_hold(*FULL, 100.0), 2)
    out["spy_val_100"] = round(BL.spy_buy_hold(*VAL, 100.0), 2)
    out["spy_cont_100"] = round(BL.spy_buy_hold(*CONT, 100.0), 2)
    print("SPY:", out["spy_full_100"], out["spy_val_100"], out["spy_cont_100"])
    print("A parent:", json.dumps(out["repl_A_parent"]))
    print("B parent:", json.dumps(out["repl_B_parent"]))

    ok = (out["repl_A_parent"]["final"] == 194.61
          and out["repl_B_parent"]["final"] == 233.54
          and out["blend_full_100"].get("matches_published")
          and out["blend_val_100"].get("matches_published")
          and out["spy_full_100"] == 367.80)
    out["integrity_status"] = "reproduced" if ok else "FAILED"
    print("INTEGRITY:", out["integrity_status"])

    with open(os.path.join(HERE, "integrity.json"), "w") as f:
        json.dump(out, f, indent=2)
    print("Saved integrity.json")


if __name__ == "__main__":
    main()
