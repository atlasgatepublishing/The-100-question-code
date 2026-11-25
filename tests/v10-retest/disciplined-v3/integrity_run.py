#!/usr/bin/env python3
"""INTEGRITY driver — disciplined-v3 v10 retest.
Reproduces the ORIGINAL published finals through the ORIGINAL engine
(original_engine.py = byte copy of backtests/v3/disciplined-v3.py),
reading the v3 data cache READ-ONLY (DATA_DIR pointed at v3/data;
all 5 base tickers + sectors are cached there, so nothing is fetched
or written).

Targets (published, v9-results.json / disciplined-v3-results.json):
  BASE  full 2016-11-21->2026-11-20      $194.28
  COMBO design 2016-11-21->2022-12-31    $162.68   (COMBO = D3+D6: dd_cap off, top_k=3)
  COMBO validation 2023-01-01->2026-11-20 $147.93
  COMBO full                              $241.29
  BASE  design $139.44 / BASE validation $150.24 (context)
  PLACEBO (of COMBO, validation, seed 42) $151.44 (context: beat the combo)
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import original_engine as oe

oe.DATA_DIR = os.path.expanduser("~/workspace/stock-app/backtests/v3/data")

mkt = oe.Market()
BASE = dict(oe.BASE_CFG)
COMBO = dict(oe.BASE_CFG); COMBO.update({"dd_cap": False, "top_k": 3})

DESIGN = ("2016-11-21", "2022-12-31")
VALID = ("2023-01-01", "2026-11-20")
FULL = ("2016-11-21", "2026-11-20")

runs = {
    "BASE_design": oe.run_window(mkt, dict(BASE), *DESIGN),
    "BASE_validation": oe.run_window(mkt, dict(BASE), *VALID),
    "BASE_full": oe.run_window(mkt, dict(BASE), *FULL),
    "COMBO_design": oe.run_window(mkt, dict(COMBO), *DESIGN),
    "COMBO_validation": oe.run_window(mkt, dict(COMBO), *VALID),
    "COMBO_full": oe.run_window(mkt, dict(COMBO), *FULL),
    "PLACEBO_validation_seed42": oe.run_window(mkt, dict(COMBO), *VALID,
                                               mode="placebo", seed=42),
}
out = {k: oe.brief(k, v) for k, v in runs.items()}
targets = {"BASE_full": 194.28, "COMBO_design": 162.68,
           "COMBO_validation": 147.93, "COMBO_full": 241.29,
           "BASE_design": 139.44, "BASE_validation": 150.24,
           "PLACEBO_validation_seed42": 151.44}
out["_targets"] = targets
out["_match"] = {k: (abs(out[k]["final"] - t) < 0.005)
                 for k, t in targets.items()}
print(json.dumps(out, indent=2))
with open(os.path.join(HERE, "integrity.json"), "w") as f:
    json.dump(out, f, indent=2)
