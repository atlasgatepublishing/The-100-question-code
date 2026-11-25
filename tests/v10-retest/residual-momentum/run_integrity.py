#!/usr/bin/env python3
"""V10 RETEST — residual-momentum INTEGRITY GATE.
Reproduces the ORIGINAL published finals in the ORIGINAL form (quarterly
selection on the champion chassis, v9 protection module as published in
backtests/v9-muse-rules/residual-momentum/) through the copied engine
(engine_v9.py, a verbatim copy of residual-momentum-v9.py), on the engine's
own cached inputs (build_inputs). Published targets:
  CONT 2019-01-02->2026-11-20: $413.31, placebos 16/20
  VAL  2023-01-03->2026-11-20: $277.43, placebos 18/20
Also compares all 40 placebo twin finals against the v9 results file.
Writes integrity.json in this folder.
"""
import importlib.util
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def load_mod(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


M = load_mod("engine_v9", os.path.join(HERE, "engine_v9.py"))
E = M.E

PUB = {"CONT": {"final": 413.31, "beats": 16},
       "VAL": {"final": 277.43, "beats": 18}}
WINDOWS = {"CONT": M.FULL, "VAL": M.VALIDATION}

v9res = json.load(open(os.path.expanduser(
    "~/workspace/stock-app/backtests/v9-muse-rules/residual-momentum/"
    "residual-momentum-results.json")))
PUB_TWINS = {"CONT": [r["final"] for r in v9res["full"]["placebo"]["rows"]],
             "VAL": [r["final"] for r in v9res["validation"]["placebo"]["rows"]]}

pb, eq, so = M.build_inputs()
M.SPY_RET = M.spy_daily_returns(pb)

out = {"engine": "engine_v9.py (verbatim copy of v9 residual-momentum-v9.py)",
       "form": "original quarterly selection, v9 protection, engine-native inputs",
       "replication": {}, "windows": {}}

# champion replication check (the engine's own gate)
for tag, (ws, we), expect in (("CONT", M.FULL, 544.47),
                              ("VAL", M.VALIDATION, 288.05)):
    r = E.run_pot(pb, eq, so, ws, we, 100.0, 85.0, [], label="REPL",
                  quiet=True)
    out["replication"][tag] = {"champion_final": round(r["final"], 2),
                               "expected": expect,
                               "match": abs(r["final"] - expect) < 0.011}
    print("REPL", tag, round(r["final"], 2), "expect", expect, flush=True)

for tag, (ws, we) in WINDOWS.items():
    r = M.run_pot_resmom(pb, eq, so, ws, we, 100.0, 85.0, M.LADDER,
                         label=f"INTEG {tag}", quiet=True)
    pl = M.placebo_block(pb, eq, so, ws, we, r["final"], f"INTEG {tag}")
    twins = [row["final"] for row in pl["rows"]]
    out["windows"][tag] = {
        "start": ws, "end": we,
        "published_final": PUB[tag]["final"],
        "reproduced_final": round(r["final"], 2),
        "final_match": abs(r["final"] - PUB[tag]["final"]) < 0.011,
        "published_placebo_beaten": PUB[tag]["beats"],
        "reproduced_placebo_beaten": pl["seeds_beaten"],
        "placebo_median": pl["median"],
        "twin_finals": twins,
        "twins_match_published": twins == PUB_TWINS[tag],
        "costs": round(r["costs"], 2), "orders": len(r["trades"]),
        "restarts": r.get("restarts", []),
        "second_halt": r.get("second_halt")}
    print("INTEG", tag, round(r["final"], 2), "pub", PUB[tag]["final"],
          "beats", pl["seeds_beaten"], "twins_match",
          twins == PUB_TWINS[tag], flush=True)

ok = (all(v["match"] for v in out["replication"].values()) and
      all(w["final_match"] and w["twins_match_published"] and
          w["reproduced_placebo_beaten"] == w["published_placebo_beaten"]
          for w in out["windows"].values()))
out["status"] = "reproduced" if ok else "FAILED"
with open(os.path.join(HERE, "integrity.json"), "w") as f:
    json.dump(out, f, indent=1, default=str)
print("INTEGRITY STATUS:", out["status"], flush=True)
