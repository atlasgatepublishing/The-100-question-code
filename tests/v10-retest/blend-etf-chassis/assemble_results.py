#!/usr/bin/env python3
"""Assemble results.json (SPEC sweep format) from integrity.json +
sweep_cells.json produced by integrity.py / run_sweep.py."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(HERE, "integrity.json")) as f:
    integ = json.load(f)
with open(os.path.join(HERE, "sweep_cells.json")) as f:
    sweep = json.load(f)

PLACEBO_NOTE = ("20 seeded random twins of BOTH legs per cell: Sleeve A "
                "randomly samples the same number of assets the trend rule "
                "selected (same inv-vol capped weights/band); Sleeve B "
                "randomly samples the same number of picks from the "
                "eligible (above-200d-MA) set (defensive share rule kept).")

cells = {}
for cad, c in sweep["cells"].items():
    cells[cad] = {
        "final": c["final"], "cagr_pct": c["cagr_pct"],
        "max_dd_pct": c["max_dd_pct"], "halts": len(c["halts"]),
        "restart": c["restart"], "second_halt": c["second_halt"],
        "costs": c["costs"], "orders": c["orders"],
        "placebo_beaten": c["placebo_beaten"],
        "placebo_note": PLACEBO_NOTE,
        "ret_2020_pct": c["ret_2020_pct"], "ret_2022_pct": c["ret_2022_pct"],
    }

results = {
    "slug": "blend-etf-chassis",
    "area": "defensive allocation (trend-sleeve + chassis blend), scored "
            "on return AND drawdown AND 2022",
    "area_source": "SPEC W8 assignment; CADENCE GRID: blend-etf-chassis "
                   "native cadence = monthly",
    "cadence": "monthly",
    "native_cadence": "monthly",
    "native_form": "Published form is MIXED-tempo: Sleeve A (ETF trend) "
                   "evaluates monthly; Sleeve B (chassis) selects "
                   "quarterly with DAILY trend exits; pot rebalances to "
                   "50/50 every January. The sweep's monthly cell is the "
                   "uniform-cadence version of that form (see "
                   "cadence_treatment).",
    "cadence_treatment": "Cadence governs BOTH legs uniformly: cadence "
                         "dates = first trading day of each period; "
                         "Sleeve A evaluates its trend signal at the "
                         "cadence-date close and rebalances next open; "
                         "Sleeve B runs selection at the cadence-date "
                         "open (prior-close signals, as published) and "
                         "its 200-day trend-exit scan at the cadence-date "
                         "close, exits next open. The January 50/50 pot "
                         "rebalance is kept in every cell (the blend's "
                         "defining pot rule, not a sleeve cadence); the "
                         "v9 floor check stays daily (protection, not a "
                         "signal).",
    "original_cadence_foreign": False,
    "original_cadence_note": "Grid classifies the blend monthly and its "
                             "lead sleeve (A) is monthly in the original; "
                             "not flagged foreign. The original's mixed "
                             "tempo (B quarterly + daily exits) is not any "
                             "single sweep cell — the published $211.80 "
                             "sits beside the table as its own row.",
    "integrity": {
        "status": integ["integrity_status"],
        "original_finals": {
            "blend_full_100": 211.80, "blend_val_100": 132.73,
            "sleeveA_parent_full_100": 194.61,
            "sleeveB_parent_full_100": 233.54, "spy_full_100": 367.80},
        "reproduced_finals": {
            "blend_full_100": integ["blend_full_100"]["final"],
            "blend_val_100": integ["blend_val_100"]["final"],
            "sleeveA_parent_full_100": integ["repl_A_parent"]["final"],
            "sleeveB_parent_full_100": integ["repl_B_parent"]["final"],
            "spy_full_100": integ["spy_full_100"]},
        "notes": "Original v4 engine imported read-only; full and "
                 "validation finals, orders, costs and max DD reproduced "
                 "to the cent. CONT 2019-01-02->2026-11-20 in original "
                 "form (not a published window) recomputed at $181.23 — "
                 "matches the prior batch worker's scratch figure "
                 "exactly, corroborating the plumbing.",
    },
    "decade_spy_final": sweep["spy"]["final"],
    "decade_spy_max_dd_pct": sweep["spy"]["max_dd_pct"],
    "champion_decade_reference": {
        "final": 65.89,
        "caveat": "Champion (Value+Momentum) DECADE $65.89 after two "
                  "halts — from the lazy-quarterly test; its crown rests "
                  "on the 2010 and 2019 roads (LONG $1,415.62; CONT "
                  "$544.47; VAL $288.05). Printed wherever the decade "
                  "matrix is summarized."},
    "original_program_numbers": {
        "blend_full_decade_100": {"final": 211.80, "max_dd_pct": -9.26,
                                  "orders": 556, "costs": 9.38,
                                  "ret_2022_pct": -7.15, "halts": 0},
        "blend_val_100": {"final": 132.73, "max_dd_pct": -8.02},
        "blend_cont_original_form_100": {"final": 181.23,
                                         "max_dd_pct": -9.28},
        "spy_decade": 367.80, "spy_val": 187.77, "spy_cont": 313.62},
    "cells": cells,
    "money_cadences": [],
    "verdict_area": "REAL BUT SMALL",
    "verdict_note": "Defense only. No cadence beats SPY on money (best "
                    "cell: annual $245.83 vs SPY $367.80), so there are "
                    "no money cadences and nothing to confirm. The "
                    "defensive character is real: every cadence's max "
                    "drawdown (-13% to -22%) is far shallower than SPY's "
                    "-33.72%, the blend beats its own 20-seed placebo "
                    "twins at 5 of 7 cadences, and the published form "
                    "lost only -7.15% in 2022 vs SPY's -18.18%. As a "
                    "money strategy it has NO GROUND; as a defensive "
                    "chassis it is REAL BUT SMALL — the same verdict "
                    "the original program reached.",
    "verdict_change": "None. The original program verdict stands at "
                      "every tempo: best defensive configuration tested, "
                      "no return engine. The dilution record is intact — "
                      "no cadence undoes it (the blend trails SPY by "
                      "$122-$238 at every tempo, and even trails its own "
                      "published mixed-tempo form at the native monthly "
                      "cadence: $205.69 vs $211.80).",
}

with open(os.path.join(HERE, "results.json"), "w") as f:
    json.dump(results, f, indent=2)
print("Saved results.json")
