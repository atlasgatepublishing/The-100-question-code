#!/usr/bin/env python3
"""CONFIRMATION RULE runner: re-run two count specs on DIFFERENT years than
the sweep roads — EARLY 2010-01-04->2016-11-18 and LATE 2020-01-02->2026-11-20
(neither is a sweep road). Usage: confirm.py <countA> <countB> (ints, ALL or
DECILE). Writes confirmation.json. Imports the sweep engine as a module."""
import json, os, sys
import importlib.util
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("sweep", os.path.join(HERE, "run_sweep.py"))
S = importlib.util.module_from_spec(spec)
sys.argv = ["run_sweep.py", "__import_only__"]  # main() guarded by __main__ check anyway
spec.loader.exec_module(S)

WINDOWS = {"EARLY-2010-2016": ("2010-01-04", "2016-11-18"),
           "LATE-2020-2026": ("2020-01-02", "2026-11-20")}
out = {}
for cs_raw in sys.argv[1:]:
    cs = cs_raw if cs_raw in ("ALL", "DECILE") else int(cs_raw)
    for rules in ("native", "house"):
        for wname, (s, e) in WINDOWS.items():
            r = S.run_pot(s, e, cs, rules)
            out[f"{rules}-{wname}-{cs_raw}"] = {"final": r["final"], "max_dd_pct": r["max_dd_pct"],
                                                "costs": r["costs"], "halts": r["halts"]}
            print(f"{rules} {wname} count={cs_raw}: ${r['final']} dd {r['max_dd_pct']}% halts {r['halts']}", flush=True)
with open(os.path.join(HERE, "confirmation.json"), "w") as f:
    json.dump(out, f, indent=1)
print("CONFIRM DONE", flush=True)
