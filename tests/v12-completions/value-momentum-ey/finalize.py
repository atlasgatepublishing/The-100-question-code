#!/usr/bin/env python3
"""Assemble results.json from cells/ + confirmation/ artifacts."""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
CHAMP = {"LONG": 1415.62, "CONT": 544.47, "VAL": 288.05, "DECADE": 65.89}
SPY_REF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}

def slim(cell):
    return {k: cell[k] for k in ("road", "cadence", "window", "final",
            "cagr_pct", "max_dd_pct", "costs", "orders", "spy_final",
            "placebo_beaten", "placebo_median", "placebo_finals",
            "n_zeroed", "pool_sizes_first_last", "second_halt",
            "equity_curve")} | {"halts": cell["halts"],
            "restart": cell["restart"],
            "zeroed_events": cell["zeroed_events"]}

out = {"slug": "value-momentum-ey", "program": "v12-completions",
       "constructed": True,
       "construction_spec": "CONSTRUCTION-SPEC.md",
       "fences": "F1 seed survivorship (flatters, upper bound); F2 program "
                 "costs on broad universe (flatters, worst at fast cadences); "
                 "F3 vanished->ZERO (hurts); F4 current-ticker reuse; "
                 "F5 no short leg (long-only top quintile only)",
       "champions": CHAMP, "spy_reference": SPY_REF, "cells": {},
       "confirmation": {}}
for fn in sorted(os.listdir(os.path.join(HERE, "cells"))):
    if fn.endswith(".json"):
        c = json.load(open(os.path.join(HERE, "cells", fn)))
        out["cells"][c["cadence"]] = slim(c)
cdir = os.path.join(HERE, "confirmation")
if os.path.isdir(cdir):
    for fn in sorted(os.listdir(cdir)):
        if fn.endswith(".json"):
            c = json.load(open(os.path.join(cdir, fn)))
            out["confirmation"].setdefault(c["cadence"], {})[c["road"]] = slim(c)
json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
print("results.json written:",
      {k: v["final"] for k, v in out["cells"].items()},
      {k: {r: v["final"] for r, v in d.items()}
       for k, d in out["confirmation"].items()})
