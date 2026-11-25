#!/usr/bin/env python3
"""Assemble results.json (SPEC sweep format) from the saved cell files
+ sweep_raw.json (integrity, coverage). Also corrects sweep_raw.json's
quarterly entry, which in the first pass duplicated the monthly cell
(cadence_dates patch contamination — documented in RESULTS.md)."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CADS = ["daily", "weekly", "biweekly", "monthly", "quarterly",
        "semiannual", "annual"]

raw = json.load(open(os.path.join(HERE, "sweep_raw.json")))
cells = {}
for cad in CADS:
    c = json.load(open(os.path.join(HERE, "cells", f"{cad}.json")))
    cells[cad] = {
        "final": c["final"], "cagr_pct": c["cagr_pct"],
        "max_dd_pct": c["max_dd_pct"], "halts": len(c["halts"]),
        "restart": bool(c["restarts"]),
        "second_halt": bool(c["second_halt"]),
        "costs": c["costs"], "orders": c["orders"],
        "placebo_beaten": c["placebo_beaten"],
        "placebo_median_twin": c["placebo_median_twin"],
        "placebo_note": "20 seeds, random 5 from the same cheapest-third "
                        "F-scorable candidate set, v9 protections per twin",
        "beats_spy": c["beats_spy"],
        "n_selection_dates": c["n_selection_dates"]}
    # keep sweep_raw consistent with the corrected quarterly cell
    raw["cells"][cad] = {
        "final": c["final"], "cagr_pct": c["cagr_pct"],
        "max_dd_pct": c["max_dd_pct"], "costs": c["costs"],
        "orders": c["orders"], "placebo_beaten": c["placebo_beaten"],
        "placebo_median_twin": c["placebo_median_twin"],
        "beats_spy": c["beats_spy"], "halts": len(c["halts"]),
        "restart": bool(c["restarts"]),
        "second_halt": bool(c["second_halt"])}
raw["quarterly_correction"] = (
    "First-pass quarterly cell duplicated monthly (cadence_dates called "
    "the per-cell-patched E.quarter_selection_dates). Fixed and re-run "
    "via rerun_quarterly.py; cells/quarterly.json is the corrected cell.")
with open(os.path.join(HERE, "sweep_raw.json"), "w") as f:
    json.dump(raw, f, indent=1, default=str)

money = [cad for cad in CADS
         if cells[cad]["beats_spy"] and cells[cad]["placebo_beaten"] >= 20]
out = {
    "slug": "piotroski",
    "area": "Long-holding fundamental sort: F-score fundamental strength "
            "inside the cheapest third by book-to-market, on the "
            "champion's point-in-time mega-cap pond (W3 fundamental sorts)",
    "area_source": "SPEC W3 assignment + CADENCE GRID (Piotroski 2000)",
    "native_cadence": "annual",
    "original_cadence_foreign": True,
    "original_cadence_note": "Native = ANNUAL (Piotroski: score after "
        "annual filings, hold one year). The original program test ran a "
        "QUARTERLY top-5 adaptation — a foreign cadence, flagged per SPEC.",
    "integrity": {
        "status": "reproduced",
        "original_finals": {"CONT_his_rules": 88.10, "VAL_his_rules": 293.24},
        "reproduced_finals": {
            "CONT": raw["integrity"]["CONT"],
            "VAL": raw["integrity"]["VAL"]},
        "note": "Original form = quarterly top-5, plain -15% floor, no "
                "restart, original v4 cache prices. CONT reproduced "
                "$88.10 halted 2020-03-12; VAL reproduced $293.24; SPY "
                "controls reproduced $313.62 / $187.77. The v9 "
                "restart-rescued CONT final was $293.44. Original VAL "
                "headline was VOIDED by its own placebo in the v6 record "
                "(ranked $293.24 vs median twin $279.78, beats 10/20, "
                "50th percentile)."},
    "decade_spy_final": raw["decade_spy_final"],
    "decade_window": ["2016-11-21", "2026-11-20"],
    "decade_note": "Full decade covered: prices re-fetched from Yahoo "
                   "with the original engine's own method into ./data "
                   "(the v4 cache starts 2017-06-01). SPY decade on this "
                   "plumbing = $367.80, matching the SPEC reference.",
    "cells": cells,
    "money_cadences": money,
    "verdict_area": "NO GROUND",
    "verdict_change": "Worse on its own ground. The original quarterly "
        "adaptation at least produced a (placebo-voided) VAL headline; at "
        "the NATIVE annual cadence on the decade the ranked pot ($348.76) "
        "trails SPY ($367.80) AND its own random twins (median $477.51, "
        "beats only 3/20). The only cell beating both SPY and all 20 "
        "twins is WEEKLY ($428.08) — a tempo the strategy was never "
        "designed for, where what is being harvested is the cheap-third "
        "pond plus fast equal-weight rebalancing, not annual F-score "
        "information (scores change only when filings land). No cadence "
        "earns Piotroski a place on the map as an F-score strategy.",
    "champion_windows": {
        "CONT": {"piotroski_his_rules": 88.10,
                 "piotroski_v9": 293.44, "champion": 544.47},
        "VAL": {"piotroski": 293.24, "champion": 288.05},
        "note": "VAL is the one window where Piotroski's final tops the "
                "champion's — and it is the window its own placebo "
                "voided (median twin $279.78, 50th percentile)."},
    "coverage_artifacts": raw["coverage"],
    "caveats": [
        "F-scores bunch on mega-caps: across 21,473 candidate scorings on "
        "the decade, median F-score 5, maximum 8, ZERO 9s. The 0-9 "
        "industrial-firm scale has almost no resolution on this pond.",
        "JPM entered the cheapest third on 2,303 selection dates and was "
        "scorable on 0 (long-term debt untagged after 2013 -> 6 of 9 "
        "signals max, below the >=7 gate). BRK-B: in third 114 times, "
        "scorable 0 (unclassified balance sheet). Documented in the "
        "original, carried here, never patched.",
        "No cell halted on the decade under v9 protections (worst "
        "drawdowns 31-37% were peak-to-trough inside rising episodes, "
        "never a -15% breach from an episode start).",
        "First-pass quarterly cell duplicated monthly due to a "
        "selection-date patch bug in this worker's sweep driver; caught "
        "by identical outputs, fixed, re-run (rerun_quarterly.py). All "
        "other cells were unaffected (their date generators never touch "
        "the patched function).",
        "Selection used indexed fast paths for pit_value/_at_end after "
        "an exact-equality check against the original scans on 20 "
        "sampled decade dates (pool, third, scores, picks all identical) "
        "and after the integrity gate passed on the original code path."],
}
with open(os.path.join(HERE, "results.json"), "w") as f:
    json.dump(out, f, indent=1, default=str)
print("results.json written; money cadences:", money)
