#!/usr/bin/env python3
"""Assemble results.json (SPEC sweep format) from sweep_raw.json + cells/."""
import json, os
HERE = os.path.dirname(os.path.abspath(__file__))
raw = json.load(open(os.path.join(HERE, "sweep_raw.json")))
CAD = ["daily", "weekly", "biweekly", "monthly", "quarterly",
       "semiannual", "annual"]
cells = {}
for c in CAD:
    d = raw["decade"]["cells"][c]
    cells[c] = {
        "final": d["final"], "cagr_pct": d["cagr_pct"],
        "max_dd_pct": d["max_dd_pct"], "halts": d["halts"],
        "restart": d["restart"], "second_halt": d["second_halt"],
        "costs": d["costs"], "orders": d["orders"],
        "placebo_beaten": f"{d['placebo_beaten']}/20",
        "placebo_note": d["placebo_note"],
        "defense": d["defense"], "costs_detail": d["costs_detail"],
        "n_rebalances": d["n_rebalances"]}
money = [c for c in CAD
         if cells[c]["final"] > raw["decade"]["spy_net_final"]
         and cells[c]["placebo_beaten"] == "19/20"]
out = {
    "slug": "re-put-hedge",
    "area": "Champion-with-insurance overlay — its ground is the crash "
            "windows: defense (max drawdown, 2020 and 2022 behavior, "
            "halt survival) scored first-class, money second.",
    "area_source": "SPEC W8: 'Put-hedge = the champion-with-insurance "
                   "overlay — its ground is the crash windows'",
    "native_cadence": "monthly (PPUT roll, per SPEC CADENCE GRID W8)",
    "cadence": "monthly",
    "original_cadence_foreign": True,
    "original_cadence_note": "The hedge leg rolls monthly inside the "
        "published PPUT index at every cadence (cannot be altered). The "
        "ORIGINAL test rebalanced the 50/50 blend weights only each "
        "January (annual). In this sweep, cadence governs how often the "
        "50/50 champion/PPUT split is reviewed and rebalanced back to "
        "50/50; the champion sleeve keeps its own quarterly selection "
        "at every cadence.",
    "integrity": {
        "status": "reproduced",
        "note": "All 4 original windows reproduced to the cent through "
                "the original v7 plumbing, including LONG 2010 blend "
                "$1,017.61 (never halted) and the champion's 2010 halt "
                "($85.34, 2010-08-26). One documented fix was required: "
                "the first v10 draft omitted the v7 line setting "
                "E.UNIVERSE to the rebuilt 2010 top-30 before running "
                "the 2010 book; without it LONG gave champion $1,153.64 "
                "unhalted (wrong-universe run preserved in "
                "run_completion_wronguniverse.log). With the v7 line "
                "restored exactly, every window matches.",
        "original_finals": raw["integrity_check"]["published"],
        "reproduced_finals": raw["integrity_check"]["reproduced"],
        "all_match": raw["integrity_check"]["all_match"]},
    "decade_spy_final": raw["decade"]["spy_net_final"],
    "decade_spy_max_dd_pct": raw["decade"]["spy_max_dd_pct"],
    "decade_window": "2016-11-21 -> 2026-11-20 on the long-hold 2010 "
        "book (the chassis the original 2010 window used; the honest "
        "champion book's prices start 2017-06-01 and cannot cover a "
        "2016-11-21 start). On this chassis the floored $100 champion "
        "alone ends the decade at $89.58, halted 2020-03-23 — a "
        "different number from the lazy-quarterly Nov-2016-pond decade "
        "champion ($65.89); the chassis differ, both are printed.",
    "cells": cells,
    "long_supplementary": raw["long_supplementary"],
    "money_cadences": money,
    "money_cadence_note": "Weekly through annual beat SPY ($367.80) and "
        "their placebo twins (19/20) on the decade — BUT the 50/50 "
        "champion/SPY control blend beats the PPUT blend at every one "
        "of those cadences (annual: control $545.10 vs blend $493.87). "
        "The money in these cells is the champion sleeve's, not the "
        "hedge's; swapping the SPY leg for PPUT always cost money. "
        "Listed mechanically per SPEC; the verdict below weighs the "
        "control, as the original test did.",
    "verdict_area": "REAL BUT SMALL",
    "verdict_change": "No change. The original REJECTED verdict stands: "
        "the blend still fails its defining crash test (2020 fold halt "
        "2020-03-20 at $78.98, reproduced to the cent), and at every "
        "cadence the unhedged SPY-blend control makes more money. What "
        "the retest adds: the defense is real — decade max drawdown "
        "-26.3% vs SPY's -33.7% and vs the control blend's -37.4%, and "
        "2022 was positive (+4.0% to +7.5% across non-daily cadences) "
        "while SPY fell -18.18%. Insurance that works, priced like "
        "insurance: the PPUT leg cost $72.01 of decade mark vs holding "
        "SPY ($316.30 over LONG). No cadence flips the verdict, so no "
        "confirmation runs are triggered.",
    "placebo_design": "20 random-rank champion-sleeve twins, each "
        "blended 50/50 with the same PPUT sleeve at the same cadence "
        "(the original test's house placebo design), run on the decade "
        "for every cadence. LONG supplementary cells have no placebos "
        "(placebos were specified for the sweep road).",
    "data_note": "PPUT levels read read-only from the v7 folder "
        "(PPUT_History.csv, CBOE free CDN, downloaded 2026-11-21 by "
        "the original test). No option is ever priced: PPUT is the "
        "published total-return index (S&P 500 + monthly 5% OTM SPX "
        "put, 3rd-Friday roll, costs inside the index). PPUT launched "
        "2015-06-30; earlier levels are CBOE back-calculations. "
        "Champion books read-only from v4 caches and the v7 long-hold "
        "cache. No new downloads.",
}
with open(os.path.join(HERE, "results.json"), "w") as f:
    json.dump(out, f, indent=1)
print("results.json written; money cadences:", money)
