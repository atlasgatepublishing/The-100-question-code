#!/usr/bin/env python3
"""Assemble results.json (SPEC sweep format) from the saved cell files
and integrity.json. Run after run_v10.py sweep + check."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]

with open(os.path.join(HERE, "integrity.json")) as f:
    integ = json.load(f)
with open(os.path.join(HERE, "fast_lookup_check.json")) as f:
    check = json.load(f)
with open(os.path.join(HERE, "sweep_raw.json")) as f:
    raw = json.load(f)

cells = {}
for cad in CADENCES:
    with open(os.path.join(HERE, "cells", f"{cad}.json")) as f:
        c = json.load(f)
    cells[cad] = {
        "final": c["final"], "cagr_pct": c["cagr_pct"],
        "max_dd_pct": c["max_dd_pct"],
        "worst_close": c["worst_close"],
        "worst_close_date": c["worst_close_date"],
        "halts": c["halts"], "restart": c["restart"],
        "second_halt": c["second_halt"], "costs": c["costs"],
        "orders": c["orders"],
        "placebo_beaten": f"{c['placebo_beaten']}/20",
        "placebo_note": "20 random-rank twins (seeds 1..20), same scored "
                        "pools, same v9 protection wrapper; twin finals "
                        "saved in cells/<cadence>.json",
    }

results = {
    "slug": "gap-a4-distress",
    "area": "Filings & calendar pond strategies (W4): quarterly CHS "
            "failure-probability avoidance screen on the honest Nov-2016 "
            "top-30 pond — long road is its ground; defensive screen, so "
            "drawdown vs SPY is scored alongside money",
    "area_source": "SPEC W4 assignment + CADENCE GRID (gap-a4: quarterly "
                   "as designed, native)",
    "native_cadence": "quarterly",
    "cadence": "quarterly",
    "original_cadence_foreign": False,
    "original_cadence_note": "Original v7/v9 tests ran quarterly — the "
                             "native cadence. No foreign-cadence flag.",
    "integrity": {
        "status": "reproduced",
        "original_finals": {"CONT": 335.88, "VAL": 154.25,
                            "placebo_beaten_VAL": "2/20",
                            "placebo_beaten_CONT": "11/20"},
        "reproduced_finals": {
            "CONT": integ["windows"]["CONT"]["final"],
            "VAL": integ["windows"]["VAL"]["final"],
            "placebo_beaten_VAL": f"{integ['placebos']['VAL']['beaten']}/20",
            "placebo_beaten_CONT": f"{integ['placebos']['CONT']['beaten']}/20"},
        "note": "Original v9 engine (byte copy in engine_original_v9.py) "
                "re-run in original form on original v4-cached prices: "
                "CONT $335.88 and VAL $154.25 to the cent, no halts; "
                "original plain-floor placebos reproduced exactly "
                "(VAL 2/20, CONT 11/20). Fast-lookup validation: the "
                "quarterly DECADE cell computed with unmodified original "
                "helpers equals the fast-helper result to the cent "
                f"(${check['quarterly_decade_final_unmodified_helpers']}).",
        "fast_lookup_check": check,
        "carried_findings": "Failure probabilities bunch near zero on "
                            "mega-caps (pooled median 0.025%, mean "
                            "within-date spread 0.06pp over 886 scored "
                            "name-dates, v7); its one virtue was survival "
                            "— never halted on CONT, COVID trough close "
                            "$107.77 (2020-03-16).",
    },
    "decade_spy_final": raw["decade_spy"]["final"],
    "decade_spy_defensive": {"max_dd_pct": raw["decade_spy"]["max_dd_pct"],
                             "worst_close": raw["decade_spy"]["worst_close"],
                             "worst_close_date": raw["decade_spy"]["worst_close_date"]},
    "champion_reference": {"LONG": 1415.62, "CONT": 544.47, "VAL": 288.05,
                           "DECADE": 65.89,
                           "decade_caveat": "champion decade $65.89 after "
                                            "two halts (lazy-quarterly test); "
                                            "its crown rests on the 2010 and "
                                            "2019 roads"},
    "cells": cells,
    "money_cadences": CADENCES,
    "money_cadences_note": "Every cadence beat SPY ($367.80) AND a majority "
                           "of its 20 placebo twins on the decade. "
                           "Semi-annual is thin (11/20). Best money: monthly "
                           "$593.62 (20/20). Native quarterly: $513.37 (16/20).",
    "verdict_area": "REAL BUT SMALL",
    "verdict_change": "CHANGED on the decade, UNCHANGED on the judging "
                      "window. Original program verdict: NOT PROMOTED — on "
                      "VAL (2023-26) it lost to SPY ($154.25 vs $187.77) "
                      "and to random twins (2/20). That still stands. But "
                      "on the full decade road (2016-26) the screen beats "
                      "SPY at all seven cadences and beats its placebo "
                      "twins at all seven, with zero floor halts anywhere "
                      "and a drawdown 2-4.4 points shallower than SPY's in "
                      "every cell. The original test's two windows happened "
                      "to cover its weakest stretch (2023-26); the decade "
                      "shows a real, modest, survival-flavored edge that "
                      "the VAL window alone missed. It still does not touch "
                      "the champion on CONT ($335.88 vs $544.47) or VAL "
                      "($154.25 vs $288.05); it beats the champion only on "
                      "the decade, where the champion halted twice "
                      "($65.89, caveat printed).",
}

with open(os.path.join(HERE, "results.json"), "w") as f:
    json.dump(results, f, indent=1)
print("results.json written")
