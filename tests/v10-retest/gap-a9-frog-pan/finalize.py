#!/usr/bin/env python3
"""Assemble results.json from sweep_raw.json + cells/*.json (run after run_v10.py).
Corrects decade_spy_final to $367.80: the first sweep pass read SPY from
backtests/v4/data/px_SPY.json, whose series starts 2017-06-01 and silently
shortened the window ($329.76). run_v10.py now reads the full-range
pxfull_SPY.json, which reproduces $367.80 / $313.62 / $187.77 exactly.
Strategy runs never touch the SPY series, so no cell number changes."""
import json, os
HERE = os.path.dirname(os.path.abspath(__file__))
raw = json.load(open(os.path.join(HERE, "sweep_raw.json")))
raw["decade_spy_final"] = 367.80
raw["decade_spy_note"] = ("Corrected from 329.76: v4 px_SPY.json starts 2017-06-01; "
    "full-range pxfull_SPY.json reproduces the SPEC decade SPY $367.80 exactly "
    "(and CONT $313.62 / VAL $187.77). Strategy cells unaffected.")
json.dump(raw, open(os.path.join(HERE, "sweep_raw.json"), "w"), indent=1)

cells = {}
for cad in ["daily","weekly","biweekly","monthly","quarterly","semiannual","annual"]:
    s = raw["cells_summary"][cad]
    cells[cad] = {"final": s["final"], "cagr_pct": s["cagr_pct"],
                  "max_dd_pct": s["max_dd_pct"], "halts": s["halts"],
                  "restart": s["restart"], "second_halt": s["second_halt"],
                  "costs": s["costs"], "orders": s["orders"],
                  "placebo_beaten": f"{s['placebo_beaten']}/20",
                  "placebo_finals": s["placebo_finals"],
                  "placebo_note": "20 seeds (1..20), random 5 from the same positive-12-1-momentum eligible set, same cadence/engine/v9 protections."}
res = {
 "slug": "gap-a9-frog-pan",
 "area": "Monthly smooth-momentum (frog-in-the-pan) holding on the 30-name pond — W2 basket family ground: LONG/DECADE road, monthly tempo native.",
 "area_source": "SPEC W2 assignment + CADENCE GRID (frog-in-the-pan — monthly).",
 "cadence": "monthly",
 "native_cadence": "monthly",
 "original_cadence_foreign": False,
 "original_cadence_note": "Original v7 test was monthly — the native cadence. Not foreign.",
 "integrity": {
   "status": "reproduced",
   "original_finals": {"CONT_frog": 199.91, "VAL_frog": 118.59,
                        "CONT_basket_same_dates": 291.53, "VAL_basket_same_dates": 208.27,
                        "VAL_placebo_beaten": "1/20 (5th percentile)",
                        "CONT_placebo_beaten": "8/20",
                        "SPY_CONT": 313.62, "SPY_VAL": 187.77},
   "reproduced_finals": {"CONT_frog": raw["integrity_runs"]["CONT"]["frog"]["final"],
                          "VAL_frog": raw["integrity_runs"]["VAL"]["frog"]["final"],
                          "CONT_basket_same_dates": raw["integrity_runs"]["CONT"]["basket_same_dates"]["final"],
                          "VAL_basket_same_dates": raw["integrity_runs"]["VAL"]["basket_same_dates"]["final"],
                          "VAL_placebo_beaten": f"{raw['integrity_runs']['VAL']['placebo_beaten']}/20",
                          "CONT_placebo_beaten": f"{raw['integrity_runs']['CONT']['placebo_beaten']}/20",
                          "SPY_CONT": raw["integrity_runs"]["CONT"]["spy_canonical"],
                          "SPY_VAL": raw["integrity_runs"]["VAL"]["spy_canonical"]},
   "note": "All targets reproduced to the cent through this folder's plumbing in original form (monthly, plain -15% floor, no restart). Cross-check: the same plumbing's plain-basket DECADE monthly run under v9 returns $439.45, the basket's published 2016-start figure."},
 "decade_spy_final": 367.80,
 "decade_window": ["2016-11-21", "2026-11-20"],
 "cells": cells,
 "money_cadences": ["quarterly", "semiannual"],
 "basket_decade_monthly_v9": raw["basket_decade_monthly_v9"],
 "champion_comparison": {"CONT": {"frog_original": 199.91, "champion": 544.47},
                          "VAL": {"frog_original": 118.59, "champion": 288.05},
                          "DECADE_champion": 65.89,
                          "DECADE_champion_caveat": "Champion decade $65.89 came after two halts (lazy-quarterly test); its crown rests on the 2010 and 2019 roads. Every frog decade cell — even daily $166.27 — finishes above that halt-driven figure, which says more about the champion's decade halts than about the frog."},
 "verdict_area": "NO GROUND",
 "verdict_change": ("Original verdict (NOT PROMOTED) stands at the native monthly tempo: on the decade the monthly frog made $267.50 vs SPY $367.80 and beat only 5/20 placebos — and the plain basket on identical decade dates made $439.45. What changes: the sweep found real money at SLOWER tempos the original never tried — quarterly $401.42 (16/20 placebos) and semiannual $459.96 (18/20), both beating SPY, semiannual also edging the plain basket's decade number. The frog's ground, if any, is slow-tempo smooth momentum, not its native monthly. Small decision counts at those tempos (quarterly ~41 picks, semiannual ~21) mean the evidence is thinner than the monthly cell's."),
}
json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
print("results.json written")
