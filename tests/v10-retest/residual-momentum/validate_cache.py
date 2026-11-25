#!/usr/bin/env python3
"""Equivalence proof: engine_v10.py (score-cache copy) vs the published
v9 record, on the engine's own integrity inputs, VAL window, original
quarterly form. Pass = ranked final $277.43 and all 20 placebo twin
finals identical to backtests/v9-muse-rules/residual-momentum/
residual-momentum-results.json."""
import importlib.util
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def load_mod(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


M = load_mod("engine_v10", os.path.join(HERE, "engine_v10.py"))
M.SCORES_CACHE = {}
pb, eq, so = M.build_inputs()
M.SPY_RET = M.spy_daily_returns(pb)
ws, we = M.VALIDATION
r = M.run_pot_resmom(pb, eq, so, ws, we, 100.0, 85.0, M.LADDER,
                     label="CACHECHECK", quiet=True)
pl = M.placebo_block(pb, eq, so, ws, we, r["final"], "CACHECHECK")
twins = [row["final"] for row in pl["rows"]]
v9res = json.load(open(os.path.expanduser(
    "~/workspace/stock-app/backtests/v9-muse-rules/residual-momentum/"
    "residual-momentum-results.json")))
pub_twins = [row["final"] for row in v9res["validation"]["placebo"]["rows"]]
ok = (abs(r["final"] - 277.43) < 0.011 and twins == pub_twins
      and pl["seeds_beaten"] == 18)
print("ranked", round(r["final"], 2), "beats", pl["seeds_beaten"],
      "twins_match", twins == pub_twins, "EQUIVALENCE", "PASS" if ok else "FAIL",
      flush=True)
json.dump({"ranked_final": round(r["final"], 2), "twins": twins,
           "published_twins": pub_twins, "pass": ok},
          open(os.path.join(HERE, "cache_validation.json"), "w"), indent=1)
