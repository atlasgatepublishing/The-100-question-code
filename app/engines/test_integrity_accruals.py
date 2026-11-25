#!/usr/bin/env python3
"""Integrity test for the Accruals-at-2-holdings engine port.

Standalone: run in replay mode on the original backtest's own data,
the ported cell (Dac | native | native | annual | 2, from
``backtests/v12-completions/catalog-hxz-accruals/``) must reproduce
its published record TO THE CENT — final balance AND total costs on
every road, max drawdown to 4 dp, and the monthly equity curve's
endpoints and length against the folder's own ``results.json`` grid
cell (read read-only, cross-checked, never trusted blindly: the
expected finals/costs below are the frozen published figures).

Basis: $100 start, FLOOR-FREE (native rules — this family is
floor-incompatible; no -15% floor is applied or simulated).

Expected figures (folder RESULTS.md + results.json, cell
"Dac|native|native|annual|2"):
  LONGEST  $2,032.91  costs $45.18  max_dd 0.3353
  DECADE   $1,487.30  costs $32.88  max_dd 0.3353
  CONT       $936.18  costs $18.59  max_dd 0.3353
  VAL        $343.35  costs  $6.34  max_dd 0.1711
  FOLD_A     $381.85  costs  $5.90  max_dd 0.2118
  FOLD_B     $532.39  costs $10.29  max_dd 0.3352

On a full pass the record is written to
``accruals_integrity_results.json`` next to this file; on failure it
goes to ``accruals_integrity_results.last-failure.json`` so a failing
run never overwrites a passing record.

Run:  python3 engines/test_integrity_accruals.py   (from anywhere)
Simulation/replay only. No network, no broker.
"""
import json
import os
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

from engines import accruals  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CELL = "Dac|native|native|annual|2"
GRID = json.load(open(os.path.join(
    accruals.FAMILY, "results.json")))["grid"][CELL]

# (label, window, expected_final, expected_costs, expected_max_dd, road)
CHECKS = [
    ("LONGEST", "longest", 2032.91, 45.18, 0.3353, "LONGEST"),
    ("DECADE", "decade", 1487.30, 32.88, 0.3353, "DECADE"),
    ("CONT (continuous)", "continuous", 936.18, 18.59, 0.3353, "CONT"),
    ("VAL (validation)", "validation", 343.35, 6.34, 0.1711, "VAL"),
    ("FOLD_A", "fold_a", 381.85, 5.90, 0.2118, "FOLD_A"),
    ("FOLD_B", "fold_b", 532.39, 10.29, 0.3352, "FOLD_B"),
]


def main():
    results, all_pass = [], True
    for label, window, exp_final, exp_costs, exp_dd, road in CHECKS:
        try:
            r = accruals.run(start_cash=100.0, protection=None, window=window)
            actual = round(float(r["final"]), 2)
            costs = round(float(r["costs"]), 2)
            max_dd = r.get("max_dd")
            halted = r.get("halted")
            g = GRID[road]
            curve_ok = (
                len(r["equity_curve"]) == len(g["curve"])
                and r["equity_curve"][0] == [g["curve"][0][0], g["curve"][0][1]]
                and r["equity_curve"][-1] == [g["curve"][-1][0], g["curve"][-1][1]]
                and round(float(g["final"]), 2) == exp_final
                and round(float(g["costs"]), 2) == exp_costs)
            ok = (actual == exp_final and costs == exp_costs
                  and max_dd == exp_dd and halted is None and curve_ok)
            entry = {"check": label, "window": window, "expected": exp_final,
                     "actual": actual, "pass": ok,
                     "expected_costs": exp_costs, "costs": costs,
                     "expected_max_dd": exp_dd, "max_dd": max_dd,
                     "halted": halted, "curve_matches_results_json": curve_ok,
                     "formations": r.get("formations"),
                     "holdings_by_formation": r.get("holdings_by_formation")}
        except Exception as e:
            ok = False
            entry = {"check": label, "window": window, "expected": exp_final,
                     "actual": None, "pass": False,
                     "error": f"{type(e).__name__}: {e}"}
        all_pass = all_pass and ok
        results.append(entry)
        if entry["actual"] is not None:
            print(f"{'PASS' if ok else 'FAIL'}  {label:<20} "
                  f"actual ${entry['actual']:>9,.2f}  expected ${exp_final:>9,.2f}  "
                  f"(costs=${entry['costs']:,.2f}, max_dd={entry['max_dd']}, "
                  f"curve_ok={entry['curve_matches_results_json']})", flush=True)
        else:
            print(f"FAIL  {label:<20} ERROR: {entry['error']}", flush=True)

    out = {"engine": "accruals", "cell": CELL,
           "basis": "replay, $100 start, floor-free native rules; original "
                    "catalog engine + signals.json + W04 data read-only",
           "all_pass": all_pass, "checks": results}
    target = os.path.join(
        HERE, "accruals_integrity_results.json" if all_pass
        else "accruals_integrity_results.last-failure.json")
    with open(target, "w") as f:
        json.dump(out, f, indent=1)
    print(f"\n{'ALL PASS' if all_pass else 'FAILURES PRESENT'}: "
          f"{sum(1 for r in results if r['pass'])}/{len(results)} roads "
          f"reproduced to the cent. Record: {target}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
