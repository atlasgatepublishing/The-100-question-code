#!/usr/bin/env python3
"""Integrity test: N-F3 horizon forms (quarterly / semiannual).

The ported ``nf3_horizon`` engine, run in replay mode on the original
v10 sweep's cached data (via lr_common), must reproduce the published
DECADE-road records TO THE CENT — final balance, total costs, order
count, and halt state.

Published records (backtests/v10-retest/novel-f3-paying-in-stock/
results.json + cells/, $100 start, 2016-11-21 -> 2026-11-20, v9
protections — plain -15% floor per episode, 90-day restart; neither
form halted):
  quarterly  : $737.97  costs $8.87  orders 253  halted None
  semiannual : $848.79  costs $7.07  orders 141  halted None

Results are written to nf3_horizon_integrity_results.json next to
this file.

Run:  python3 engines/test_integrity_nf3_horizon.py  (from anywhere)
Simulation/replay only.
"""
import json
import os
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

from engines import nf3_horizon  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

# (form, expected_final, expected_costs, expected_orders, expected_halted)
CHECKS = [
    ("quarterly", 737.97, 8.87, 253, None),
    ("semiannual", 848.79, 7.07, 141, None),
]


def main():
    results = []
    all_pass = True
    for form, expected, exp_costs, exp_orders, exp_halted in CHECKS:
        label = f"N-F3 horizon {form} decade"
        try:
            r = nf3_horizon.run(start_cash=100.0, protection=None,
                                window="decade", form=form)
            actual = round(float(r["final"]), 2)
            orders = r.get("orders")
            costs = round(float(r.get("costs", 0.0)), 2)
            halted = r.get("halted")
            ok = (actual == expected and orders == exp_orders
                  and costs == exp_costs and halted == exp_halted)
            entry = {"check": label, "form": form, "window": "decade",
                     "start": r.get("start"), "end": r.get("end"),
                     "expected": expected, "actual": actual,
                     "pass": ok, "halted": halted,
                     "orders": orders, "costs": costs,
                     "expected_orders": exp_orders,
                     "expected_costs": exp_costs,
                     "expected_halted": exp_halted}
        except Exception as e:  # a crash is a FAIL, reported plainly
            ok = False
            entry = {"check": label, "form": form, "window": "decade",
                     "expected": expected, "actual": None,
                     "pass": False, "error": f"{type(e).__name__}: {e}"}
        all_pass = all_pass and ok
        results.append(entry)
        if entry["actual"] is not None:
            print(f"{'PASS' if ok else 'FAIL'}  {label:<34} "
                  f"actual ${entry['actual']:>8,.2f}  "
                  f"expected ${expected:>8,.2f}  "
                  f"(orders={entry['orders']}, costs=${entry['costs']:,.2f}, "
                  f"halted={entry['halted']})", flush=True)
        else:
            print(f"FAIL  {label:<34} ERROR: {entry['error']}", flush=True)

    out = {"basis": "replay, $100 start, DECADE 2016-11-21 -> 2026-11-20, "
                    "v9 protections (plain -15% floor per episode, first "
                    "halt -> 90 days cash -> restart; second halt ends); "
                    "original v10 sweep caches read-only via lr_common",
           "all_pass": all_pass, "checks": results}
    target = os.path.join(HERE, "nf3_horizon_integrity_results.json")
    with open(target, "w") as f:
        json.dump(out, f, indent=1)
    print(f"\n{'ALL PASS' if all_pass else 'FAILURES PRESENT'}: "
          f"{sum(1 for r in results if r['pass'])}/{len(results)} figures "
          f"reproduced to the cent. Results: {target}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
