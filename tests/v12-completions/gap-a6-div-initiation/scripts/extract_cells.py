#!/usr/bin/env python3
"""Emit one cell file's JSON to stdout from the saved results.json.
Usage: extract_cells.py HOLD12 DECADE  (run.py --emit remains the
primary producer; this avoids recomputation when results.json exists).
"""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def main():
    hname, wname = sys.argv[1], sys.argv[2]
    res = json.load(open(os.path.join(ROOT, "results.json")))
    cell = res["runs"][hname][wname]
    run = dict(cell.get("run") or {})
    curve = run.pop("curve", None)
    out = {"hold": hname, "window": wname, "events_traded": cell["events_traded"],
           "run": run, "curve": curve, "placebo_beaten": cell["placebo_beaten"],
           "placebo_finals": cell["placebo_finals"],
           "shifted_final": cell["shifted_final"], "shifted_events": cell["shifted_events"]}
    sys.stdout.write(json.dumps(out))

if __name__ == "__main__":
    main()
