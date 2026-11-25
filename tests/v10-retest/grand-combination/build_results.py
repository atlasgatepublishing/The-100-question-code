#!/usr/bin/env python3
"""Assemble results.json (SPEC sweep format) from cells/*.json +
sweep_summary.json. Run after grand-combination-v10.py."""
import json
import os
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]

cells = {}
for cad in CADENCES:
    c = json.load(open(os.path.join(HERE, "cells", f"{cad}.json")))
    twins = [t["final"] for t in c["placebo_twins"]]
    cells[cad] = {
        "final": c["final"], "cagr_pct": c["cagr_pct"],
        "max_dd_pct": c["max_dd_pct"],
        "halts": c["halts"],
        "restart": len(c["restarts"]) > 0,
        "second_halt": c["second_halt"] is not None,
        "costs": c["costs"], "orders": c["orders"],
        "placebo_beaten": c["placebo_beaten"],
        "placebo_note": (
            f"20 seeds, original combination placebo design (random "
            f"picks in the two stock sleeves, ETF sleeve unchanged): "
            f"twin median ${statistics.median(twins):.2f}, best "
            f"${max(twins):.2f}, worst ${min(twins):.2f}; full twin "
            f"finals in cells/{cad}.json"),
    }

out = {
    "slug": "grand-combination",
    "area": ("long-horizon quarterly value/momentum holding on the "
             "pond — W1 variant family (variants of the champion, so "
             "the champion's road is their native ground); combination "
             "of the three promoted components in equal thirds with a "
             "January split-rebalance"),
    "area_source": "backtests/v10-retest/SPEC.md, worker batch W1 + CADENCE GRID (W1: quarterly, native)",
    "cadence": "quarterly",
    "native_cadence": "quarterly",
    "original_cadence_foreign": False,
    "original_cadence_foreign_note": (
        "Original v5 test ran the combination at its native rhythms "
        "(VM quarterly, basket monthly, ETF monthly) — none foreign. "
        "In this sweep, per the uniform cadence treatment stated in "
        "grand-combination-v10.py, the stated cadence governs all "
        "three sleeves' re-pick/rebalance rhythms in every cell "
        "(the trend sleeve's internal monthly trend sign checks "
        "follow the same cadence); the January split-rebalance stays "
        "annual in every cell as the combination's defining "
        "construction. The quarterly cell is therefore the closest "
        "sweep cell to the original form, with the basket and ETF "
        "sleeves slowed from monthly to quarterly."),
    "native_change": (
        "none in form for the integrity runs (original engines, "
        "original windows). Sweep: DECADE road under v9 protection "
        "with the uniform cadence treatment above. Documented data "
        "artifact, never patched: the VM price cache begins "
        "2017-06-01 and its 12-1 momentum needs 253 bars, so the VM "
        "sleeve holds cash until ~2018-06 on the decade road — the "
        "same artifact the champion's published decade run carries."),
    "integrity": {
        "status": "reproduced",
        "original_finals": {"CONT": 306.56, "VAL": 195.83},
        "reproduced_finals": {"CONT": 306.56, "VAL": 195.83},
        "parents_reproduced": {
            "momentum_basket_full2016_original_floor_ladder": 439.45,
            "value_momentum_plainfloor_CONT": 544.47,
            "value_momentum_plainfloor_VAL": 288.05,
            "etf_trend_sleeve_monthly_full2016": 194.61},
        "note": ("All reproduced to the cent through the unmodified "
                 "parent engines in original form (parents' own "
                 "caches, read-only); combination reproduced with "
                 "the original blend3 machinery, pot-level plain "
                 "-15% floor, no restart (original form). No halt in "
                 "either original window."),
    },
    "decade_spy_final": 367.80,
    "spy": {"DECADE": {"final": 367.80,
                       "note": "dividend-adjusted, SPEC reference (W6 verified plumbing)"},
            "CONT": {"final": 313.62}, "VAL": {"final": 187.77},
            "LONG": {"final": 822.94}},
    "champion_reference_finals": {
        "LONG": 1415.62, "DECADE": 65.89, "CONT": 544.47, "VAL": 288.05,
        "decade_caveat": ("champion DECADE $65.89: halted Q4-2018, "
                          "restarted 2019-04-01, second halt "
                          "2020-03-20, liquidated $65.89 on "
                          "2020-03-23 — run ended. Its crown rests "
                          "on the 2010 and 2019 roads.")},
    "parents_decade": {
        "momentum_basket_original": 439.45,
        "etf_trend_sleeve_monthly_original": 194.61,
        "value_momentum_champion_v9": 65.89},
    "cells": cells,
    "money_cadences": ["semiannual"],
    "verdict_area": "REAL BUT SMALL",
    "verdict_change": (
        "The v5 verdict was 'dilution again — tested and rejected' "
        "against value+momentum alone. The v10 decade sweep softens "
        "that to REAL BUT SMALL on the map: the blend owns exactly "
        "one money tempo (semiannual, $383.98 vs SPY $367.80, 18/20 "
        "twins beaten) and never halted at any tempo slower than "
        "daily while the champion's own decade run died on two "
        "halts — but at its native quarterly tempo it trails SPY on "
        "the decade ($320.02 vs $367.80), its best tempo still "
        "trails the momentum-basket parent alone on the decade "
        "($439.45), and the recommendation from v5 stands: for "
        "money, value+momentum alone; the combination is a "
        "smoother-ride defensive blend, not a money winner."),
}

with open(os.path.join(HERE, "results.json"), "w") as f:
    json.dump(out, f, indent=1)
print("wrote results.json")
