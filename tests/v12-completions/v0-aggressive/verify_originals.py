#!/usr/bin/env python3
"""
v12 v0-aggressive - INTEGRITY: re-run the ORIGINAL era engines from the
byte-identical copies in orig/ (taken from the v10 retest's verified copies)
on their own cached data, and compare against the recorded prints.

Recorded prints (v0 record, confirmed in v10 and v11):
  Week 2026-11-16 -> 2026-11-20: final $100.00, 0 orders, SPY gross $92.02.
  Year 2025-11-21 -> 2026-11-20: final $84.51, 202 orders, 101 round trips,
    32 wins / 69 losses, costs $10.91, max DD 23.93%, halt trigger 2026-10-26,
    liquidation 2026-10-27, SPY net $105.09.
Outputs land in orig/week/ and orig/year/ (this folder only).
"""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))

week = subprocess.run([sys.executable, os.path.join(HERE, "orig", "week", "aggressive-week.py")],
                      capture_output=True, text=True)
print("=== WEEK ENGINE STDOUT ===")
print(week.stdout)
print(week.stderr[-2000:] if week.returncode else "")

year = subprocess.run([sys.executable, os.path.join(HERE, "orig", "year", "aggressive-year.py")],
                      capture_output=True, text=True)
print("=== YEAR ENGINE STDOUT (stats block) ===")
print(year.stdout.split("MONTHLY:")[0])
print(year.stderr[-2000:] if year.returncode else "")

w = json.loads(week.stdout)
y = json.load(open(os.path.join(HERE, "orig", "year", "aggressive-year-stats.json")))["stats"]

checks = {
    "week_final_100.00": w["final_balance"] == 100.00,
    "week_0_orders": w["orders"] == 0,
    "week_spy_gross_92.02": w["bench_gross"] == 92.02,
    "year_final_84.51": y["final_balance"] == 84.51,
    "year_orders_202": y["total_orders"] == 202,
    "year_round_trips_101": y["round_trips"] == 101,
    "year_wins_32_losses_69": (y["wins"], y["losses"]) == (32, 69),
    "year_costs_10.91": y["total_costs"] == 10.91,
    "year_max_dd_23.93": y["max_drawdown_pct"] == 23.93,
    "year_halt_2026-10-26_to_2026-10-27": y["halted"][:2] == ["2026-10-26", "2026-10-27"],
    "year_spy_net_105.09": y["bench_net"] == 105.09,
}
print("=== CHECKS ===")
print(json.dumps(checks, indent=1))
print("ALL REPRODUCED" if all(checks.values()) else "DISCREPANCY - see checks")
with open(os.path.join(HERE, "verify_originals.json"), "w") as f:
    json.dump({"week": w, "year": y, "checks": checks,
               "all_reproduced": all(checks.values())}, f, indent=1, default=str)
