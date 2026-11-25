#!/usr/bin/env python3
"""
INTEGRITY GATE for the Lazy Prices Quarterly (LQ) test.

Before any LQ number is taken, this plumbing must reproduce the
published Lazy Prices record to the cent:
  - continuous 2019-01-02 -> 2026-11-20: $504.34 (costs $3.57, 184 orders)
  - validation 2023-01-03 -> 2026-11-20: $324.12 (costs $1.43, 89 orders)
  - long 2010-01-04 -> 2026-11-20 under v9: $559.69 (costs $7.42,
    387 orders; halt 2010-06-30, restart selection 2010-10-01)
and SPY buy-hold net on the same books: $313.62 / $187.77 / $822.94.
Any failure stops the test — no variant numbers are produced.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lq_common as Q  # noqa: E402

CHECKS = []


def check(name, got, expect):
    ok = round(got, 2) == expect if isinstance(expect, float) else got == expect
    CHECKS.append({"name": name, "got": got, "expected": expect, "match": ok})
    print(f"{name}: {got} expected {expect} MATCH={ok}", flush=True)
    return ok


def run_gate():
    fails = []
    lazy, pb, sims = Q.gap_book()

    r = lazy.run_pot(pb, sims, "2019-01-02", Q.END, label="GATE CONT")
    if not check("lazy_continuous_final", round(r["final"], 2), 504.34):
        fails.append("lazy_continuous_final")
    if not check("lazy_continuous_costs", round(r["costs"], 2), 3.57):
        fails.append("lazy_continuous_costs")
    if not check("lazy_continuous_orders", len(r["trades"]), 184):
        fails.append("lazy_continuous_orders")
    s, _ = lazy.spy_net(pb, "2019-01-02", Q.END)
    if not check("spy_continuous", round(s, 2), 313.62):
        fails.append("spy_continuous")

    r = lazy.run_pot(pb, sims, "2023-01-03", Q.END, label="GATE VAL")
    if not check("lazy_validation_final", round(r["final"], 2), 324.12):
        fails.append("lazy_validation_final")
    if not check("lazy_validation_costs", round(r["costs"], 2), 1.43):
        fails.append("lazy_validation_costs")
    if not check("lazy_validation_orders", len(r["trades"]), 89):
        fails.append("lazy_validation_orders")
    s, _ = lazy.spy_net(pb, "2023-01-03", Q.END)
    if not check("spy_validation", round(s, 2), 187.77):
        fails.append("spy_validation")

    res = Q.E.lazy_v9(Q.pond2010(), Q.era_signals(), "2010-01-04", Q.END)
    if not check("lazy_long_v9_final", res["final"], 559.69):
        fails.append("lazy_long_v9_final")
    if not check("lazy_long_v9_costs", res["costs"], 7.42):
        fails.append("lazy_long_v9_costs")
    if not check("lazy_long_v9_orders", res["orders"], 387):
        fails.append("lazy_long_v9_orders")
    if not check("spy_long", res["spy_final"], 822.94):
        fails.append("spy_long")
    halt_date = res["halts"][0]["signal_date"] if res["halts"] else None
    if not check("lazy_long_halt", halt_date, "2010-06-30"):
        fails.append("lazy_long_halt")
    first_sel = res["restart"]["episode2_first_selection"] \
        if res["restart"] else None
    if not check("lazy_long_restart_selection", first_sel, "2010-10-01"):
        fails.append("lazy_long_restart_selection")

    out = {"checks": CHECKS, "fails": fails,
           "verdict": "ALL PASS" if not fails else f"FAILURES: {fails}"}
    with open(os.path.join(HERE, "integrity_results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("INTEGRITY:", out["verdict"], flush=True)
    return fails, res


if __name__ == "__main__":
    f, _ = run_gate()
    sys.exit(1 if f else 0)
