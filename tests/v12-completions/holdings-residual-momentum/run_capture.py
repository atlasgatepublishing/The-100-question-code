#!/usr/bin/env python3
"""Stdout-capture runner for the residual-momentum holdings sweep.
Imports run_sweep.py as the engine (unchanged mechanics), runs ONE ruleset
(sys.argv[1] = native|house), prints each cell as one JSON line to stdout.
Shell redirection saves the lines — Python file writes were EPERM-blocked
in this VM during the program (same workaround as sibling holdings folders).
Placebos: 20 seeds per cell, same engine, seeded random twins."""
import json, sys, importlib.util, os
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("sweep", os.path.join(HERE, "run_sweep.py"))
S = importlib.util.module_from_spec(spec)
sys.argv = ["run_sweep.py", "__import_only__"]
spec.loader.exec_module(S)

rules = sys.argv[1] if len(sys.argv) > 1 else "native"
# argv was overwritten above for the import; recover rules from env instead
rules = os.environ.get("RULES", "native")
for road, (s, e) in S.ROADS.items():
    print(json.dumps({"spy": road, "final": S.spy_final(s, e)}), flush=True)
    for cs in S.COUNTS:
        spec_cs = cs if cs in ("ALL", "DECILE") else int(cs)
        r = S.run_pot(s, e, spec_cs, rules)
        pfin = []
        for seed in range(1, 21):
            pr = S.run_pot(s, e, spec_cs, rules, placebo_seed=seed)
            pfin.append(pr["final"])
        beaten = sum(1 for x in pfin if r["final"] > x)
        cell = {"rules": rules, "road": road, "count": cs, "start": s, "end": e,
                "final": r["final"], "max_dd_pct": r["max_dd_pct"], "costs": r["costs"],
                "orders": r["orders"], "halts": r["halts"], "restarts": r["restarts"],
                "second_halt": r["second_halt"], "placebo_beaten": beaten,
                "placebo_finals": pfin,
                "placebo_median": round(float(np.median(pfin)), 2),
                "vanished_held": r["vanished_held"], "equity_curve": r["curve"]}
        print("CELL " + json.dumps(cell), flush=True)
print("CAPTURE DONE " + rules, flush=True)
