#!/usr/bin/env python3
"""Integrity test: every ported engine, run in replay mode on the
original backtests' cached data, must reproduce its published record
TO THE CENT — final balance, total costs, order count, and halt state.

Basis (the original published basis): $100 start, plain -15% floor
from the starting balance ($85.00), a close at/below the floor
liquidates at the next open and ends the run. No ladder, no restart.

Expected figures (published records):
  V+M champion   continuous $544.47   validation $288.05
  Lazy Prices    continuous $504.34   validation $324.12
  Momentum basket continuous $439.45  validation $208.27
  N-F3           continuous $505.43   validation $289.53
  Switch B       continuous $549.43
  SPY shadow     continuous $313.62   validation $187.77

v2 Horizon Picker engines (added 2026-11-23; each on ITS OWN published
basis — the v10/v12 chassis these records were produced on, which is
the v9 house rules for Quality-Momentum and the N-F3 horizon forms,
and floor-free for Accruals, exactly as tested; the gate never silently
re-bases a strategy):
  Quality-Momentum decade     daily $847.62  weekly $1,164.49
                              biweekly $1,096.12  monthly $1,097.93
  Quality-Momentum continuous weekly $698.38
  N-F3 horizon decade         quarterly $737.97  semiannual $848.79
  Accruals Dac@2 (floor-free) decade $1,487.30  cont $936.18
                              val $343.35  longest $2,032.91
                              fold_a $381.85  fold_b $532.39
Accruals publishes no trade list (orders cross-checked instead against
the full monthly curve in engines/test_integrity_accruals.py), so its
master-gate rows carry expected_orders=None = "not checked here".

Round 2 hardening (E-7): the gate used to compare ONLY the final
figure — an engine stub returning the right final with garbage costs,
orders and halt state passed 11/11. Every check now also verifies
orders, costs (to the cent) and halted. The gate is also hermetic for
a renamed/moved install: it imports the engines package from THIS
file's own directory, whatever the install folder is called. And a
failing run no longer overwrites the passing record:
integrity_results.json is written only on a full pass; failures go to
integrity_results.last-failure.json.

Run:  python3 -m app.engines.integrity_test   (from the project root)
      python3 engines/integrity_test.py       (from anywhere)
Simulation/replay only.
"""
import json
import os
import sys
from pathlib import Path

# QA M-1 + R2-E7: import the engines package from THIS file's location
# (engines/ -> the install dir), never a hard-coded path or an assumed
# folder name, so a copied/renamed install tests ITSELF.
APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

from engines import (accruals, lazy_prices, momentum_basket, nf3,  # noqa: E402
                     nf3_horizon, quality_momentum, spy, switch_b, vm)

HERE = os.path.dirname(os.path.abspath(__file__))
START_CASH = 100.0
PROTECTION = None  # None = plain -15% floor from start (common.resolve_floor)

# (label, callable, window, expected_final, expected_orders,
#  expected_costs, expected_halted)
CHECKS = [
    ("V+M champion continuous", vm.run, "continuous", 544.47, 202, 5.49, None),
    ("V+M champion validation", vm.run, "validation", 288.05, 100, 2.19, None),
    ("Lazy Prices continuous", lazy_prices.run, "continuous", 504.34, 184, 3.57, None),
    ("Lazy Prices validation", lazy_prices.run, "validation", 324.12, 89, 1.43, None),
    ("Momentum basket continuous", momentum_basket.run, "continuous", 439.45, 750, 18.86, None),
    ("Momentum basket validation", momentum_basket.run, "validation", 208.27, 292, 5.52, None),
    ("N-F3 continuous", nf3.run, "continuous", 505.43, 202, 5.77, None),
    ("N-F3 validation", nf3.run, "validation", 289.53, 101, 2.35, None),
    ("Switch B continuous", switch_b.run, "continuous", 549.43, 302, 6.45, None),
    ("SPY shadow continuous", spy.run, "continuous", 313.62, 2, 0.42, None),
    ("SPY shadow validation", spy.run, "validation", 187.77, 2, 0.30, None),
    # --- v2 Horizon Picker engines (own published bases; see header) ---
    ("QM daily decade", lambda **kw: quality_momentum.run(form="daily", **kw),
     "decade", 847.62, 12279, 178.12, None),
    ("QM weekly decade", lambda **kw: quality_momentum.run(form="weekly", **kw),
     "decade", 1164.49, 2786, 73.07, None),
    ("QM biweekly decade", lambda **kw: quality_momentum.run(form="biweekly", **kw),
     "decade", 1096.12, 1463, 48.14, None),
    ("QM monthly decade", lambda **kw: quality_momentum.run(form="monthly", **kw),
     "decade", 1097.93, 698, 26.36, None),
    ("QM weekly continuous", lambda **kw: quality_momentum.run(form="weekly", **kw),
     "continuous", 698.38, 2191, 44.15, None),
    ("N-F3 horizon quarterly decade",
     lambda **kw: nf3_horizon.run(form="quarterly", **kw),
     "decade", 737.97, 253, 8.87, None),
    ("N-F3 horizon semiannual decade",
     lambda **kw: nf3_horizon.run(form="semiannual", **kw),
     "decade", 848.79, 141, 7.07, None),
    ("Accruals Dac@2 decade", accruals.run, "decade", 1487.30, None, 32.88, None),
    ("Accruals Dac@2 cont", accruals.run, "cont", 936.18, None, 18.59, None),
    ("Accruals Dac@2 val", accruals.run, "val", 343.35, None, 6.34, None),
    ("Accruals Dac@2 longest", accruals.run, "longest", 2032.91, None, 45.18, None),
    ("Accruals Dac@2 fold_a", accruals.run, "fold_a", 381.85, None, 5.90, None),
    ("Accruals Dac@2 fold_b", accruals.run, "fold_b", 532.39, None, 10.29, None),
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
            # expected_orders=None: the engine publishes no trade list
            # (Accruals) — orders are cross-checked in its own gate
            # against the full monthly curve instead; never faked here.
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

    out = {"basis": "replay, $100 start; original engines on the plain "
                    "-15% floor basis (halt ends run); v2 picker engines "
                    "each on their own published basis (v9 house rules for "
                    "QM / N-F3 horizon forms, floor-free for Accruals); "
                    "original backtest caches read-only",
           "all_pass": all_pass, "checks": results}
    if all_pass:
        target = os.path.join(HERE, "integrity_results.json")
    else:
        # R2-E7: a failing/fooled run must not destroy the passing
        # record — failures are kept in a separate file.
        target = os.path.join(HERE, "integrity_results.last-failure.json")
        print("NOTE: failures present — integrity_results.json left "
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
