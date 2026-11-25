#!/usr/bin/env python3
"""Assemble results.json (SPEC sweep format) from cells/*.json + area.json."""
import json, os
HERE = os.path.dirname(os.path.abspath(__file__))
CADS = ["daily", "weekly", "biweekly", "monthly", "quarterly",
        "semiannual", "annual"]
cells, raw = {}, {}
for c in CADS:
    d = json.load(open(os.path.join(HERE, "cells", f"{c}.json")))
    raw[c] = d
    cells[c] = {
        "final": d["final"], "cagr_pct": d["cagr_pct"],
        "max_dd_pct": d["max_dd_pct"], "halts": len(d["halts"]),
        "halt_dates": d["halts"], "restart": d["restart"],
        "second_halt": d["second_halt"], "costs": d["costs"],
        "orders": d["orders"], "placebo_beaten": f"{d['placebo_beaten']}/20",
        "placebo_note": ("Both placebos run at this cadence under v9: "
                         "(a) design placebo — 20 seeds, 5 random pond names "
                         "per event on the ranked (third-Friday) dates, all "
                         "20 twin finals in cells/<cadence>.json; "
                         "(b) calendar placebo — the identical compression "
                         "screen on the SECOND Friday (single deterministic "
                         "twin), final in calendar_placebo_final."),
        "calendar_placebo_final": d["calendar_placebo_final"],
        "beats_calendar_placebo": d["beats_calendar_placebo"],
        "placebo_median": d["placebo_median"],
        "n_events": d["n_events"],
        "n_events_traded": d["event_stats"]["n_events_traded"],
        "mean_excess_net_pct": d["event_stats"]["mean_excess_net_pct"],
        "mean_excess_gross_pct": d["event_stats"]["mean_excess_gross_pct"],
        "median_excess_net_pct": d["event_stats"]["median_excess_net_pct"],
        "events_beat_spy_net": d["event_stats"]["events_beat_spy_net"],
        "calendar_placebo_event_stats": d["calendar_placebo_event_stats"]}
area = json.load(open(os.path.join(HERE, "area.json")))
integ = json.load(open(os.path.join(
    HERE, "integrity", "novel-x4-opex-release-results.json")))
out = {
 "slug": "novel-x4-opex-release",
 "area": ("Calendar-event strategies (SPEC W5) — invented rule X4: buy the "
          "most volatility-compressed, up-trending pond names at the close "
          "of monthly options-expiration Friday, hold 5 trading days, SPY "
          "otherwise; decade cadence sweep on the DECADE road "
          "2016-11-21 -> 2026-11-20"),
 "area_source": "SPEC.md W5 batch + CADENCE GRID (novel-x4: event-driven, monthly OpEx calendar) + THE CADENCE SWEEP (2026-11-21 ~22:09)",
 "native_cadence": "event-driven",
 "cadence": "event-driven",
 "original_cadence_foreign": {
   "foreign": False,
   "note": ("Original program test ran the published event-driven form "
            "(monthly OpEx entries, exit at the close of the 5th trading "
            "day after E, daily floor checks) — native cadence; no foreign "
            "cadence was forced. The v10 sweep varies only the review/exit "
            "rhythm around those unchanged event rules.")},
 "native_change": ("none in the event rules. v10 cadence treatment for this "
                   "EVENT strategy: entries exactly as published (close of "
                   "the anchor Friday); the published exit (close of E+5) "
                   "executes on the first cadence date on/after it, and the "
                   "v9 -15% floor is checked only on cadence dates. Baskets "
                   "whose exit slips past the next event are held as "
                   "separate lots; later events that find the pot fully "
                   "invested buy only what cash allows (funded-events count "
                   "is reported per cell). Daily cadence == the original "
                   "form, asserted against the saved area runs."),
 "cadence_validation": json.load(open(os.path.join(HERE, "sweep_raw.json")))["validation"],
 "integrity": {
   "status": "reproduced",
   "original_finals": {"CONT": 247.09, "VAL": 182.30},
   "reproduced_finals": {"CONT": integ["full"]["ranked"]["final"],
                         "VAL": integ["validation"]["ranked"]["final"]},
   "note": ("Batch worker's gate (integrity/ folder, saved): CONT $247.09 "
            "and VAL $182.30 reproduced through the original engine; SPY "
            "controls exact. The sweep engine at daily cadence additionally "
            "reproduced DECADE ranked $253.90 / calendar $280.30, CONT "
            "$247.09 / $260.88 and VAL $182.30 / $188.24 to the cent before "
            "any sweep number was taken (sweep.py asserts; see sweep.log)."),
   "candidate_gates_original": integ["candidate_gates"],
   "original_verdict": integ["verdict"]},
 "decade_spy_final": 367.80,
 "spy": area["spy"],
 "cells": cells,
 "money_cadences": ["quarterly", "semiannual", "annual"],
 "money_cadences_status": ("PROVISIONAL — decade-only, unconfirmed. Per "
   "the CONFIRMATION RULE these three cadences beat SPY ($367.80), their "
   "20-seed design placebos (18/20, 20/20, 20/20) and their calendar "
   "placebos on the DECADE road only; the flip does not enter the "
   "scoreboard until the money cadences are re-run on LONG, CONT and VAL "
   "with fresh yearly folds. CANDIDATE CEILING also applies: X4 is an "
   "invented rule, so even a confirmed flip caps at CANDIDATE pending a "
   "forward paper trial."),
 "area_runs_reference": area["runs"],
 "champion_reference": {"LONG": 1415.62, "CONT": 544.47, "VAL": 288.05,
                        "DECADE": 65.89,
                        "decade_note": "champion decade $65.89 after two halts (lazy-quarterly test) — rules artifact of its crash halts, printed wherever the decade matrix is summarized"},
 "verdict_area": "NO GROUND (native event-driven ground) — with a PROVISIONAL, decade-only flip at slow review rhythms",
 "verdict_change": ("Partial, and PROVISIONAL. On its own ground — the "
   "published 5-trading-day OpEx release, at daily/weekly/biweekly/monthly "
   "review — the original verdict stands and hardens: every fast cell "
   "trails SPY ($367.80) AND loses to its own second-Friday calendar "
   "placebo, i.e. the calendar, not the expiration rule, did the work; "
   "per-event mean net excess vs SPY is negative at every fast cadence. "
   "What changes: at quarterly/semi-annual/annual review the exit slips "
   "by weeks-to-months, the trade stops being a 5-day release and becomes "
   "a long hold of the compression screen's picks — and on the decade "
   "those three cells beat SPY, the design placebos and the calendar "
   "placebos. That is a NEW strategy wearing X4's screen, found on one "
   "road; per the CONFIRMATION RULE it is decade-only and unconfirmed, "
   "and per the invented-rule ceiling it could cap at CANDIDATE even if "
   "confirmed. No crown without cross-year confirmation.")}
json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
print("results.json written")
