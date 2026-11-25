#!/usr/bin/env python3
"""Integrity test for the derived Champion app.

DERIVED APP ADAPTATION of the frozen companion app's gate (recorded
in BUILD-REPORT.md): the frozen gate checked every ported engine.
This app ships one engine, so the gate checks exactly what ships:
the V+M champion and the SPY shadow, each in both published windows,
run in replay mode on the original backtests' cached data through the
VENDORED champion original (engines/champion_original.py). Every
check must reproduce its published record TO THE CENT: final balance,
total costs, order count, and halt state.

Basis (the original published basis): $100 start, plain -15% floor
from the starting balance ($85.00), a close at/below the floor
liquidates at the next open and ends the run. No ladder, no restart.

Expected figures (published records):
  V+M champion   continuous $544.47   validation $288.05
  SPY shadow     continuous $313.62   validation $187.77

The gate is hermetic for a renamed or moved install: it imports the
engines package from THIS file's own directory. A failing run does
not overwrite the passing record: integrity_results.json is written
only on a full pass; failures go to
integrity_results.last-failure.json.

Run:  python3 engines/integrity_test.py       (from anywhere)
Simulation/replay only.
"""
import json
import os
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

from engines import spy, vm  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
START_CASH = 100.0
PROTECTION = None  # None = plain -15% floor from start (common.resolve_floor)

# (label, callable, window, expected_final, expected_orders,
#  expected_costs, expected_halted)
CHECKS = [
    ("V+M champion continuous", vm.run, "continuous", 544.47, 202, 5.49, None),
    ("V+M champion validation", vm.run, "validation", 288.05, 100, 2.19, None),
    ("SPY shadow continuous", spy.run, "continuous", 313.62, 2, 0.42, None),
    ("SPY shadow validation", spy.run, "validation", 187.77, 2, 0.30, None),
]


def main():
    results = []
    all_pass = True
    for label, fn, window, expected, exp_orders, exp_costs, exp_halted in CHECKS:
        try:
            r = fn(start_cash=START_CASH, protection=PROTECTION,
                   window=window)
            actual = round(float(r["final"]), 2)
            orders = r.get("orders")
            costs = round(float(r.get("costs", 0.0)), 2)
            halted = r.get("halted")
            ok = (actual == expected
                  and (exp_orders is None or orders == exp_orders)
                  and costs == exp_costs and halted == exp_halted)
            entry = {"check": label, "window": window,
                     "expected": expected, "actual": actual,
                     "pass": ok, "halted": halted,
                     "orders": orders, "costs": costs,
                     "expected_orders": exp_orders,
                     "expected_costs": exp_costs,
                     "expected_halted": exp_halted}
        except Exception as e:  # a crash is a FAIL, reported plainly
            ok = False
            entry = {"check": label, "window": window,
                     "expected": expected, "actual": None,
                     "pass": False, "error": f"{type(e).__name__}: {e}"}
        all_pass = all_pass and ok
        results.append(entry)
        if entry["actual"] is not None:
            print(f"{'PASS' if ok else 'FAIL'}  {label:<32} "
                  f"actual ${entry['actual']:>8,.2f}  "
                  f"expected ${expected:>8,.2f}  "
                  f"(orders={entry['orders']}, costs=${entry['costs']:,.2f}, "
                  f"halted={entry['halted']})", flush=True)
        else:
            print(f"FAIL  {label:<32} ERROR: {entry['error']}", flush=True)

    out = {"basis": "replay, $100 start; the vendored champion original "
                    "on the plain -15% floor basis (halt ends run); "
                    "original backtest caches read-only",
           "all_pass": all_pass, "checks": results}
    if all_pass:
        target = os.path.join(HERE, "integrity_results.json")
    else:
        target = os.path.join(HERE, "integrity_results.last-failure.json")
        print("NOTE: failures present; integrity_results.json left "
              "untouched; this run is recorded in "
              "integrity_results.last-failure.json", flush=True)
    with open(target, "w") as f:
        json.dump(out, f, indent=1)
    print(f"\n{'ALL PASS' if all_pass else 'FAILURES PRESENT'}: "
          f"{sum(1 for r in results if r['pass'])}/{len(results)} figures "
          f"reproduced to the cent.")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
