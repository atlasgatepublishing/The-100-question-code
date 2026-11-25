#!/usr/bin/env python3
"""Standalone integrity test for the Quality + Momentum port.

Runs the ported engine (replay mode, original caches read-only) and
checks each cadence form against the published v10 figures TO THE
CENT, printing PASS/FAIL per form per road, and writes the record to
``qm_integrity_results.json`` next to this file.

Targets (source: backtests/v10-retest/quality-momentum/results.json
and confirmation/summary.json, $100 start, v9 protections):
  DECADE 2016-11-21 -> 2026-11-20:
    daily $847.62 / weekly $1,164.49 / biweekly $1,096.12 /
    monthly $1,097.93
  continuous 2019-01-02 -> 2026-11-20, weekly form: $698.38

Run:  python3 engines/test_integrity_qm.py   (from anywhere)
Simulation/replay only.
"""
import json
import os
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

from engines import quality_momentum  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

# (label, window, form, expected_final)
CHECKS = [
    ("decade daily", "decade", "daily", 847.62),
    ("decade weekly", "decade", "weekly", 1164.49),
    ("decade biweekly", "decade", "biweekly", 1096.12),
    ("decade monthly", "decade", "monthly", 1097.93),
    ("continuous weekly", "continuous", "weekly", 698.38),
]


def main():
    results = []
    all_pass = True
    for label, window, form, expected in CHECKS:
        try:
            r = quality_momentum.run(start_cash=100.0, protection=None,
                                     window=window, form=form)
            actual = round(float(r["final"]), 2)
            ok = actual == expected
            entry = {"check": label, "road": window, "form": form,
                     "expected": expected, "actual": actual,
                     "pass": ok, "costs": round(float(r["costs"]), 2),
                     "orders": r.get("orders"),
                     "halted": r.get("halted"),
                     "halts": r.get("halts"),
                     "restart": r.get("restart")}
        except Exception as e:  # a crash is a FAIL, reported plainly
            ok = False
            entry = {"check": label, "road": window, "form": form,
                     "expected": expected, "actual": None,
                     "pass": False,
                     "error": f"{type(e).__name__}: {e}"}
        all_pass = all_pass and ok
        results.append(entry)
        if entry["actual"] is not None:
            print(f"{'PASS' if ok else 'FAIL'}  {label:<20} "
                  f"actual ${entry['actual']:>9,.2f}  "
                  f"expected ${expected:>9,.2f}  "
                  f"(orders={entry['orders']}, "
                  f"costs=${entry['costs']:,.2f}, "
                  f"halted={entry['halted']})", flush=True)
        else:
            print(f"FAIL  {label:<20} ERROR: {entry['error']}",
                  flush=True)

    out = {"engine": "quality_momentum",
           "basis": "replay, $100 start, v9 protections (plain -15% "
                    "floor, 90-day sit-out, one restart); original "
                    "backtest caches read-only",
           "source": "backtests/v10-retest/quality-momentum/qm_v10.py",
           "all_pass": all_pass, "checks": results}
    target = os.path.join(HERE, "qm_integrity_results.json")
    with open(target, "w") as f:
        json.dump(out, f, indent=1)
    print(f"\n{'ALL PASS' if all_pass else 'FAILURES PRESENT'}: "
          f"{sum(1 for r in results if r['pass'])}/{len(results)} "
          "figures reproduced to the cent.")
    print(f"Wrote {target}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
