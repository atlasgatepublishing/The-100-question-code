#!/usr/bin/env python3
"""
Metadata repair for cells/daily.json (numbers unchanged).

The first full run recorded halt #1's liquidation_date by inference from
floor-liquidation trade dates. That inference is wrong when a halt trips
on an already-flat book (daily halt #1, triggered 2020-01-15 with the pot
in cash at $84.04 — nothing to sell on liquidation day 2020-01-16, so the
inference grabbed the NEXT halt's liquidation date, 2023-08-07).

gap_up_engine.py now records the liquidation date directly at the
liquidation step. This script re-runs ONLY the daily cell (real run + its
20 placebo twins) with the corrected recorder, verifies every number —
final, costs, orders, all 20 placebo finals — matches the originally
saved cell to the cent, and only then rewrites cells/daily.json with the
corrected halt records. Simulation only.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gap_up_engine as E
from run_all import PLACEBO_SEEDS, cell_record, curve_json

HERE = os.path.dirname(os.path.abspath(__file__))
path = os.path.join(HERE, "cells", "daily.json")

old = json.load(open(path))
mkt = E.build_market()

pf, events = E.run_gap(mkt, "g_gap_up_daily", cadence="daily",
                       protection="v9")
s = E.score(pf, mkt.test_dates[0])
cad_dates = sorted(E.cadence_dates(mkt.test_dates, "daily"))
pool = cad_dates[:-1]
placebo_finals = []
for seed in PLACEBO_SEEDS:
    sched = E.make_placebo_schedule(pool, E.STOCK_UNIVERSE, s["entries"],
                                    seed)
    ppf, _ = E.run_gap(mkt, "g_gap_up_daily_placebo", cadence="daily",
                       protection="v9", placebo_schedule=sched)
    placebo_finals.append(E.score(ppf, mkt.test_dates[0])["final"])

_, rec = cell_record(pf, events, placebo_finals)
assert rec["final"] == old["final"], (rec["final"], old["final"])
assert rec["costs"] == old["costs"] and rec["orders"] == old["orders"]
assert rec["placebo_finals"] == old["placebo_finals"], "placebo mismatch"
print("verified: final, costs, orders and all 20 placebo finals identical")
print("corrected halt events:", json.dumps(events["halts"], indent=1))

rec["cadence"] = "daily"
rec["n_cadence_dates"] = len(cad_dates)
rec["equity_curve"] = curve_json(pf)
rec["placebo_seeds"] = PLACEBO_SEEDS
rec["placebo_note"] = old["placebo_note"]
rec["metadata_repair"] = (
    "Halt liquidation dates re-recorded directly by the corrected "
    "engine (first pass inferred them from trade dates, which mis-dated "
    "halt #1 — a flat-book halt with nothing to liquidate). Every number "
    "in this cell was verified identical to the first pass before the "
    "rewrite; see fix_daily_cell.py.")
with open(path, "w") as f:
    json.dump(rec, f, indent=1)
print("cells/daily.json rewritten with corrected halt records")
