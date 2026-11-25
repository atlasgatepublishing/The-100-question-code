#!/usr/bin/env python3
"""Assemble results.json (SPEC sweep format) from the saved cell,
integrity and confirmation files. Run after run_sweep.py,
integrity.py and confirmation.py."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]

cells = {}
for cad in CADENCES:
    with open(os.path.join(HERE, "cells", f"{cad}.json")) as f:
        c = json.load(f)
    cells[cad] = {
        "final": c["final"],
        "cagr_pct": c["cagr_pct"],
        "max_dd_pct": c["max_dd_pct"],
        "halts": len(c["halts"]),
        "halt_detail": c["halts"],
        "restart": c["restart"],
        "second_halt": c["second_halt"] is not None,
        "costs": c["costs"],
        "orders": c["orders"],
        "placebo_beaten": c["placebo_beaten"],
        "placebo_note": c["placebo_note"],
        "placebo_canonical_plus6mo_final": c["placebo_canonical_plus6mo_final"],
        "events_eligible": c["events_eligible"],
        "events_traded": c["events_traded"],
        "per_event": c["per_event"],
    }

with open(os.path.join(HERE, "integrity_results.json")) as f:
    integ = json.load(f)
with open(os.path.join(HERE, "sweep_raw.json")) as f:
    sweep = json.load(f)
with open(os.path.join(HERE, "confirmation", "confirmation_summary.json")) as f:
    conf = json.load(f)

out = {
    "slug": "buyback-events",
    "area": "Event strategies (W7): share-repurchase authorization "
            "announcement events, event-to-event, 12-month published "
            "hold, cycled over the DECADE road 2016-11-21 -> 2026-11-20",
    "area_source": "SPEC W7 + CADENCE GRID: buybacks are event-driven; "
                   "8-K-visible subset only, family label "
                   "UNTESTABLE-AS-PUBLISHED preserved",
    "cadence": "event-driven",
    "native_cadence": "event-driven (daily review rhythm in the original "
                      "form: entry next open after filing, exit at the "
                      "12-month date, floor checked daily) — the sweep's "
                      "DAILY cell reproduces the original mechanics "
                      "exactly and is the native-equivalent cell",
    "original_cadence_foreign": False,
    "original_cadence_note": "Original test was already event-driven with "
                             "daily review; no foreign cadence was forced.",
    "cadence_treatment": "Event rules exactly as published (entry at next "
                         "trading day's open after the 8-K filing date, "
                         "1/5-slice sizing, max 5 concurrent, 12-month "
                         "hold). Cadence governs the review/exit-check "
                         "rhythm only: the scheduled 12-month exit is "
                         "executed at the open of the first cadence date "
                         "on/after entry+12 months. The v9 -15% floor is "
                         "a protection, not a signal, and stays checked "
                         "at every daily close in every cell.",
    "integrity": {
        "status": integ["integrity_status"],
        "checks": integ["checks_passed"],
        "original_finals": {
            "champion_FULL_pot": 544.47, "champion_FULL_spy": 313.62,
            "champion_VALIDATION_pot": 288.05, "champion_VALIDATION_spy": 187.77,
            "FULL_real": 314.04, "FULL_placebo_plus6mo": 89.85,
            "VALIDATION_real": 213.22, "VALIDATION_placebo_plus6mo": 224.06,
            "standalone_real_completed": {
                "n": 84, "mean_excess_vs_spy_pct": 5.43,
                "median_excess_vs_spy_pct": 1.58, "share_beating_spy": 0.524},
            "folds_real": {"2020": 86.69, "2021": 124.96, "2022": 84.62,
                           "2023": 122.79, "2024": 119.51, "2025": 127.75,
                           "2026": 96.35},
        },
        "reproduced_finals": {
            "champion_FULL_pot": integ["replication"]["FULL"]["pot"],
            "champion_FULL_spy": integ["replication"]["FULL"]["spy"],
            "champion_VALIDATION_pot": integ["replication"]["VALIDATION"]["pot"],
            "champion_VALIDATION_spy": integ["replication"]["VALIDATION"]["spy"],
            "FULL_real": integ["pots"]["FULL_real"]["final"],
            "FULL_placebo_plus6mo": integ["pots"]["FULL_placebo"]["final"],
            "VALIDATION_real": integ["pots"]["VALIDATION_real"]["final"],
            "VALIDATION_placebo_plus6mo": integ["pots"]["VALIDATION_placebo"]["final"],
            "folds_real": {y: integ["folds"][y]["final"] for y in
                           ("2020", "2021", "2022", "2023", "2024", "2025", "2026")},
        },
        "note": "Every published number reproduced to the cent through the "
                "ORIGINAL v6 engine in its original form and windows "
                "(36/36 checks, integrity_results.json). The v9 record "
                "also stands: main windows identical under v9 (floor never "
                "fired), folds 2020 $90.12 / 2022 $86.22 after restarts.",
    },
    "untestable_as_published": {
        "label": "UNTESTABLE-AS-PUBLISHED",
        "statement": "The published strategy trades ALL share-repurchase "
                     "authorization announcements. On free data that census "
                     "cannot be built: authorizations announced by "
                     "standalone press release never appear in any SEC "
                     "filing channel searchable for free. The original "
                     "audit proved the 8-K channel misses every Microsoft "
                     "authorization (2019 $40B, 2021 $60B, 2024 $60B), "
                     "every Mastercard authorization (Dec 2023, Dec 2024), "
                     "both IBM additions (+$3B 2017, +$4B 2018), and Wells "
                     "Fargo's $30B (2023) and $40B (2025) programs — 10 "
                     "verified missed events (KNOWN_MISSED in engine.py), "
                     "including some of the pond's most reliable "
                     "announcers. The press-release wires have no free, "
                     "complete, searchable 2016-2026 archive, and "
                     "10-K/10-Q footnotes surface months late. Everything "
                     "tested here is therefore the 8-K-VISIBLE SUBSET only: "
                     "91 audited events from 4,786 enumerated 8-Ks "
                     "(1,242 mentioning repurchase/buyback, 132 classifier "
                     "candidates, each manually audited). No number in "
                     "this folder is the published family's result.",
        "tested_instead": "The 8-K-visible subset, exactly as frozen in "
                          "the original v6 test (engine.py EVENTS).",
    },
    "decade_spy_final": sweep["decade_spy_final"],
    "decade_spy_note": "Computed in-plumbing (champion spy_net) on Yahoo "
                       "bars extended back to 2016-11-01 (data_ext/), "
                       "matching the SPEC reference $367.80 exactly; "
                       "extended bars match the champion's shared cache "
                       "to <=1e-6 relative on all 2,383 overlap days "
                       "(SPY/AAPL/JPM/META). The shared cache itself "
                       "starts 2017-06-01 and cannot price the first "
                       "decade months — the extension was necessary and "
                       "is documented, not patched over.",
    "champion_reference": {
        "decade_final": 65.89,
        "note": "Champion (Value+Momentum) decade final $65.89 after two "
                "halts (per SPEC, from the lazy-quarterly test) — its "
                "crown rests on the 2010 and 2019 roads. On the decade "
                "the subset's daily cell ($441.73) and semiannual cell "
                "($579.81) finish above that figure, but neither beats "
                "the champion on the roads the champion owns, and the "
                "semiannual figure failed confirmation (below).",
        "cont_final": 544.47, "val_final": 288.05, "long_final": 1415.62,
    },
    "cells": cells,
    "money_cadences": [],
    "money_cadence_note": "Semiannual is the only cell that beats SPY "
                          "($579.81 vs $367.80), its canonical +6mo "
                          "placebo ($277.03) AND 18/20 seeded placebos — "
                          "but the CONFIRMATION RULE bars the crown: on "
                          "CONT it loses to SPY ($214.89 vs $313.62, "
                          "7/20 placebos), on VAL it beats SPY narrowly "
                          "($198.31 vs $187.77, 10/20), it beats SPY in "
                          "only 2 of 7 yearly folds, and LONG cannot be "
                          "run at all (event census starts 2016-11-21). "
                          "It is recorded as decade-only, unconfirmed, "
                          "and NOT entered as a money cadence. Daily "
                          "(native) beats SPY and 15/20 seeds but loses "
                          "to the strategy's own canonical +6mo placebo "
                          "($528.47), so it is not a money cadence either.",
    "confirmation": {
        "candidate": "semiannual",
        "CONT": conf["CONT"],
        "VAL": conf["VAL"],
        "folds": conf["folds"],
        "LONG": "NOT RUNNABLE — the audited event census begins with "
                "filings of 2016-11-21; no audited pre-2016 event list "
                "exists and building one is a new EDGAR audit, not a "
                "re-run.",
        "outcome": "FAILED — semiannual's decade result does not "
                   "replicate on CONT or the folds; verdict does not flip.",
    },
    "verdict_area": "STILL UNTESTABLE-IN-AREA",
    "verdict_change": "No change to the family verdict: the published "
                      "form remains UNTESTABLE-AS-PUBLISHED / "
                      "STILL UNTESTABLE-IN-AREA. The 8-K-visible subset's "
                      "own record is updated, not flipped: on its "
                      "original windows it stands TESTED-FAILED (FULL "
                      "tie with SPY, beaten by its own placebo on "
                      "VALIDATION); on the decade sweep it beats SPY at "
                      "the native daily cadence but again loses to its "
                      "own +6-month placebo, and its one strong cadence "
                      "(semiannual) failed confirmation. No crown, no "
                      "promotion.",
}

with open(os.path.join(HERE, "results.json"), "w") as f:
    json.dump(out, f, indent=1, default=str)
print("results.json written")
