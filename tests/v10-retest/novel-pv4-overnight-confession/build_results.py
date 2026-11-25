#!/usr/bin/env python3
"""Assemble results.json (SPEC sweep format) for N-PV4 from the saved
cells/*.json, area.json and the integrity gate. No runs happen here."""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
area = json.load(open(os.path.join(HERE, "area.json")))
v9 = json.load(open(os.path.join(HERE, "integrity", "v9-results.json")))
CADS = ["daily", "weekly", "biweekly", "monthly", "quarterly",
        "semiannual", "annual"]
cells = {}
for c in CADS:
    cell = json.load(open(os.path.join(HERE, "cells", f"{c}.json")))
    cells[c] = {k: cell[k] for k in
                ("final", "cagr_pct", "max_dd_pct", "halts", "restart",
                 "second_halt", "costs", "orders", "placebo_beaten")}
    cells[c]["restart_info"] = cell["restart_info"]
    cells[c]["events_taken"] = cell["events_taken"]
    cells[c]["placebo_median"] = cell["placebo_median"]
    cells[c]["placebo_note"] = cell["placebo_note"]

SPY_DECADE = 367.80
money = [c for c in CADS
         if cells[c]["final"] > SPY_DECADE and cells[c]["placebo_beaten"] == 20]
# SPEC: money cadence = beats SPY AND its placebo distribution. Beating
# the distribution is read strictly here as beating the median AND a
# majority of seeds; no cell beats SPY at all, so the list is empty
# under any reading.
money = [c for c in CADS if cells[c]["final"] > SPY_DECADE
         and cells[c]["placebo_beaten"] is not None
         and cells[c]["placebo_beaten"] >= 11
         and cells[c]["final"] > cells[c]["placebo_median"]]

out = {
 "slug": "novel-pv4-overnight-confession",
 "area": "Invented price/volume short-cycle rule (W5): overnight "
         "gap-down (<= -2%) fully reclaimed by the same day's close, "
         "bought at the next open, held 10 trading days — cycled and "
         "compounded over the full road, plus its native short-window "
         "score (per-year record on LONG in area.json).",
 "area_source": "backtests/v10-retest/SPEC.md, worker batch W5; frozen "
                "rule source: research/v8-novel/novel-price-volume.md, "
                "RULE N-PV4 (invented 2026).",
 "native_cadence": "daily",
 "cadence": "daily",
 "original_cadence_foreign": False,
 "original_cadence_foreign_note": "None — the original program test ran "
                "the rule at its native daily tempo (event scan every "
                "trading day, exit at the 11th trading day's open).",
 "cadence_treatment": "Cadence governs (a) which nights count: an event "
                "is taken only if its signal day (the day whose overnight "
                "gap <= -2% is fully reclaimed by the close) is a cadence "
                "date — first trading day of the period per the SPEC's "
                "uniform definition; and (b) exit checks: the published "
                "exit becomes due at the open of the 11th trading day "
                "after entry but executes only at the open of the first "
                "cadence date on/after the due date. Entry at the next "
                "session's open after the signal, 1/5 slicing marked at "
                "the signal close, 5-slot cap, gap-rank order, program "
                "costs and the daily-close v9 floor check are unchanged. "
                "At daily cadence this is exactly the native form (the "
                "sweep asserts it reproduces the saved area DECADE run "
                "to the cent).",
 "integrity": {
   "status": "reproduced",
   "original_finals": {"CONT": v9["his"]["continuous_final"],
                       "VAL": v9["his"]["validation_final"]},
   "reproduced_finals": {"CONT": area["runs"]["CONT"]["final"],
                         "VAL": area["runs"]["VAL"]["final"]},
   "detail": "Saved gate (integrity/, not re-run by this worker): the "
             "v9 engine reproduced CONT $84.25 / VAL $104.46 to the cent, "
             "and episode 1 reproduced his recorded finals exactly "
             "(CONT ep1 $86.05, halted 2020-03-16; VAL $104.46, no halt). "
             "The sweep's own daily cell additionally reproduces the "
             "saved area DECADE run exactly ($83.19, costs $5.51, 244 "
             "orders, halt 2020-03-12).",
   "candidate_ceiling": "INVENTED RULE — the best verdict this strategy "
             "can ever earn in a backtest is CANDIDATE; only a forward "
             "paper trial can promote an invented rule.",
 },
 "decade_spy_final": SPY_DECADE,
 "cells": cells,
 "money_cadences": money,
 "area_runs_v9": {w: {k: area["runs"][w][k] for k in
                      ("final", "costs", "orders", "halts", "restart",
                       "second_halt", "max_dd_pct", "placebo_beaten",
                       "start", "end")}
                  for w in ("LONG", "DECADE", "CONT", "VAL")},
 "area_spy": area["spy"],
 "champion_reference": {
   "LONG": 1415.62, "CONT": 544.47, "VAL": 288.05,
   "DECADE": 65.89,
   "decade_caveat": "Champion decade $65.89 comes from the lazy-quarterly "
                    "test after two halts; its crown rests on the 2010 "
                    "and 2019 roads. PV4's best decade cell (annual, "
                    "$124.33) finishes ahead of that one halted champion "
                    "decade number — a window-specific comparison against "
                    "a two-halt run, not a crown change: the same cell "
                    "trails SPY by $243 and rests on 4 events.",
 },
 "verdict_area": "NO GROUND",
 "verdict_change": "Unchanged. The original program's verdict was NOT A "
                   "CANDIDATE (failing all four frozen prongs); the "
                   "cadence sweep finds no money cadence on the decade — "
                   "no cell beats SPY — so there is no flip and the "
                   "CONFIRMATION RULE is not triggered. Slower cadences "
                   "lose less (they take 4-28 events instead of 122 and "
                   "hold them far longer), but every one still trails "
                   "buy-hold SPY by $240+ and the slow cells' small gains "
                   "sit on a handful of long holds whose placebo twins "
                   "do nearly as well.",
 "data_note": "Bars: read-only shared cache backtests/v7/long-hold/data "
              "pxfull payloads (adjusted open/close, program price basis) "
              "plus the slug-local pxfull_GOOGL.json, exactly as in "
              "driver.py. No downloads; nothing written outside this "
              "folder. Scripts: integrity/ (original engine copy), "
              "driver.py (area runs), sweep.py (this sweep), "
              "build_results.py (this assembly).",
}
json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
print("money_cadences:", money)
print("wrote results.json")
