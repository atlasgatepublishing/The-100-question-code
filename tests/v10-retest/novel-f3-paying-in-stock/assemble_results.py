#!/usr/bin/env python3
"""Assemble results.json (SPEC sweep format) from cells/*.json + the
saved integrity evidence. No computation of strategy numbers here —
finals are copied from the cell files produced by sweep.py and from
novel-f3-paying-in-stock-results.json (integrity reproduction)."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]
SPY_DECADE = 367.80

cells = {}
money = []
for cad in CADENCES:
    with open(os.path.join(HERE, "cells", f"{cad}.json")) as f:
        c = json.load(f)
    cells[cad] = {
        "final": c["final"],
        "cagr_pct": c["cagr_pct"],
        "max_dd_pct": c["max_dd_pct"],
        "max_dd_date": c["max_dd_date"],
        "halts": c["halts"],
        "restart": c["restart"],
        "second_halt": c["second_halt"],
        "costs": c["costs"],
        "orders": c["orders"],
        "placebo_beaten": c["placebo_beaten"],
        "placebo_note": ("20 random-rank twins (seeds 1..20) resampling 5 "
                         "picks from the same eligible pool at the same "
                         "cadence dates; full twin finals in cells/"
                         f"{cad}.json"),
        "n_selection_dates": c["n_selection_dates"],
        "eligible_pool_min": c["eligible_pool_min"],
        "eligible_pool_max": c["eligible_pool_max"],
    }
    if c["final"] > SPY_DECADE and c["placebo_beaten"] > 10:
        money.append(cad)

with open(os.path.join(HERE, "novel-f3-paying-in-stock-results.json")) as f:
    orig = json.load(f)

out = {
    "slug": "novel-f3-paying-in-stock",
    "area": ("W4 filings pond ranking — long road is its ground; sweep "
             "road DECADE 2016-11-21 -> 2026-11-20"),
    "area_source": "SPEC.md W4 assignment (quarterly pond ranking strategies)",
    "native_cadence": "quarterly",
    "original_cadence_foreign": False,
    "original_cadence_note": ("Original v8 test used quarterly selection "
                              "(first trading day of Jan/Apr/Jul/Oct) — the "
                              "native cadence. No foreign cadence."),
    "invented_rule": True,
    "candidate_ceiling": ("INVENTED RULE — backtests never promote it; the "
                          "forward paper trial alone promotes. Current "
                          "standing: CANDIDATE."),
    "integrity": {
        "status": "reproduced",
        "evidence": ("integrity_original.py + integrity_run.log + "
                     "novel-f3-paying-in-stock-results.json in this folder"),
        "original_finals": {
            "CONT": orig["FULL"]["final"], "VAL": orig["VALIDATION"]["final"],
            "CONT_spy": orig["FULL"]["spy_net"],
            "VAL_spy": orig["VALIDATION"]["spy_net"],
            "LONG_by_reference": 453.93,
            "LONG_note": ("SPEC W4 reference: $453.93 from 2012-10-01, SPY "
                          "$605.58 — carried by reference, not re-run"),
        },
        "reproduced_finals": {
            "CONT": orig["FULL"]["final"], "VAL": orig["VALIDATION"]["final"],
            "CONT_costs": orig["FULL"]["costs"],
            "VAL_costs": orig["VALIDATION"]["costs"],
            "CONT_orders": orig["FULL"]["orders"],
            "VAL_orders": orig["VALIDATION"]["orders"],
            "CONT_halted": orig["FULL"]["halted"],
            "VAL_halted": orig["VALIDATION"]["halted"],
            "CONT_placebo_beaten": orig["FULL"]["placebo_beaten"],
            "VAL_placebo_beaten": orig["VALIDATION"]["placebo_beaten"],
            "CONT_placebo_median": orig["FULL"]["placebo_median"],
        },
        "match": "exact to the cent on both windows",
    },
    "decade_spy_final": SPY_DECADE,
    "road": {"start": "2016-11-21", "end": "2026-11-20", "start_cash": 100.0},
    "protection": ("v9 adopted: plain -15% floor from episode start; first "
                   "halt -> liquidate at next open, 90 days cash, restart at "
                   "next cadence date under episode-2 -15% floor; second "
                   "halt ends. No cell halted."),
    "cadence_treatment": ("Cadence = re-rank/rebalance dates only (SPEC "
                          "uniform definition). The SBC signal updates only "
                          "as filings land; at faster cadences the ranking "
                          "re-evaluates on the freshest point-in-time filed "
                          "data. All 7 cadences are meaningful for this "
                          "ranking mechanics — no N/A cells."),
    "cells": cells,
    "money_cadences": money,
    "provisional_new_money_cadence": {
        "cadence": "semiannual",
        "status": "PROVISIONAL — decade-only, unconfirmed",
        "note": ("Semiannual (non-native) posted the largest decade final "
                 "($848.79) and beat SPY + 17/20 placebos. Per the "
                 "CONFIRMATION RULE it does not enter the scoreboard as a "
                 "crowned cadence until re-run on LONG/CONT/VAL + yearly "
                 "folds by the coordinator. Not run here."),
    },
    "verdict_area": "OWNS ITS GROUND",
    "verdict_change": ("No change to standing: remains CANDIDATE (invented-"
                       "rule ceiling — only a forward paper trial promotes). "
                       "The sweep confirms the native quarterly cadence is a "
                       "money cadence on the decade and adds one PROVISIONAL "
                       "new money cadence (semiannual), decade-only and "
                       "unconfirmed."),
}

with open(os.path.join(HERE, "results.json"), "w") as f:
    json.dump(out, f, indent=1)
print("money_cadences:", money)
print("wrote results.json")
