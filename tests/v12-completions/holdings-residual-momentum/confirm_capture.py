#!/usr/bin/env python3
"""CONFIRMATION RULE (Terry): challengers that beat the native DECILE count
on >=3 roads are re-run on DIFFERENT years — EARLY 2010-01-04->2016-11-18
and LATE 2020-01-02->2026-11-20 (neither is a sweep road). Stdout capture,
same protocol as run_capture.py. Counts from env COUNTS (comma list)."""
import json, sys, importlib.util, os
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("sweep", os.path.join(HERE, "run_sweep.py"))
S = importlib.util.module_from_spec(spec)
sys.argv = ["run_sweep.py", "__import_only__"]
spec.loader.exec_module(S)
WINDOWS = {"EARLY-2010-2016": ("2010-01-04", "2016-11-18"),
           "LATE-2020-2026": ("2020-01-02", "2026-11-20")}
for cs_raw in os.environ["COUNTS"].split(","):
    cs = cs_raw if cs_raw in ("ALL", "DECILE") else int(cs_raw)
    for rules in ("native", "house"):
        for wname, (s, e) in WINDOWS.items():
            r = S.run_pot(s, e, cs, rules)
            print("CONF " + json.dumps({"rules": rules, "window": wname, "count": cs_raw,
                  "final": r["final"], "max_dd_pct": r["max_dd_pct"],
                  "costs": r["costs"], "halts": r["halts"]}), flush=True)
print("CONFIRM DONE", flush=True)
