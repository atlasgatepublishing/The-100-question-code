#!/usr/bin/env python3
"""Assemble results.json (SPEC sweep format) from the saved run files:
integrity.json (integrity gate) + sweep_summary.json / cells/*.json."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
integ = json.load(open(os.path.join(HERE, "integrity.json")))
sweep = json.load(open(os.path.join(HERE, "sweep_summary.json")))

cells = {}
for cad, c in sweep["cells"].items():
    cells[cad] = {"final": c["final"], "cagr_pct": c["cagr_pct"],
                  "max_dd_pct": c["max_dd_pct"], "halts": c["halts"],
                  "restart": c["restart"], "second_halt": bool(c["second_halt"]),
                  "costs": c["costs"], "orders": c["orders"],
                  "placebo_beaten": c["placebo_beaten"],
                  "placebo_median": c["placebo_median"],
                  "placebo_best": c["placebo_best"],
                  "placebo_note": "20 seeds run; all twin finals in cells/%s.json" % cad}

payload = {
    "slug": "residual-momentum",
    "name": "Residual Momentum (Blitz-Huij-Martens 2011, SPY single-factor form)",
    "area": "Pond ranking strategy (W4) — long road is its ground; sweep road = DECADE 2016-11-21 -> 2026-11-20",
    "area_source": "SPEC W4 assignment + CADENCE GRID (W4 line): residual-momentum — monthly",
    "cadence": "monthly",
    "native_cadence": "monthly",
    "original_cadence_foreign": True,
    "original_cadence_note": "Original program test (v6, carried into v9) ran residual momentum QUARTERLY on the champion's chassis; the published Blitz-Huij-Martens form is MONTHLY rebalanced. The original cadence was foreign — flagged per the CADENCE GRID.",
    "integrity": {
        "status": integ["status"],
        "form": "original quarterly form, v9 protection, engine-native inputs (run_integrity.py via engine_v9.py, a verbatim copy of the v9 script)",
        "original_finals": {"CONT": 413.31, "VAL": 277.43,
                            "CONT_placebo_beaten": "16/20",
                            "VAL_placebo_beaten": "18/20"},
        "reproduced_finals": {
            "CONT": integ["windows"]["CONT"]["reproduced_final"],
            "VAL": integ["windows"]["VAL"]["reproduced_final"],
            "CONT_placebo_beaten": integ["windows"]["CONT"]["reproduced_placebo_beaten"],
            "VAL_placebo_beaten": integ["windows"]["VAL"]["reproduced_placebo_beaten"]},
        "champion_replication_check": integ["replication"],
        "placebo_twins_match_published": {
            "CONT": integ["windows"]["CONT"]["twins_match_published"],
            "VAL": integ["windows"]["VAL"]["twins_match_published"]},
        "notes": "Ranked finals reproduced to the cent and all 40 placebo twin finals identical to the v9 record. The sweep engine (engine_v10.py = engine_v9.py + date-keyed score memoization only) was separately proven equivalent on VAL: $277.43, 18/20, twins identical (validate_cache.py / cache_validation.json). E.pit_value was replaced in the sweep only by fastpit.fast_pit_value — identical outputs on 49,560 chain/date comparisons on the exact sweep chains (validate_fastpit.py)."},
    "decade_spy_final": sweep["decade_spy_final"],
    "decade_window": sweep["road"],
    "cells": cells,
    "money_cadences": ["weekly"],
    "money_cadence_note": "Strict rule: beats SPY ($367.80) AND all 20 placebo seeds. Weekly is the only cell meeting both ($589.98, 20/20). Monthly (native), biweekly and semiannual each beat SPY and 18/20 seeds; quarterly (the original foreign cadence) beats SPY at 16/20; annual beats SPY at 15/20. Daily beats all 20 of its (cost-crushed) twins but finishes BELOW SPY — turnover costs ate the signal.",
    "champion_window_finals": {
        "CONT_quarterly_original_form": 413.31,
        "VAL_quarterly_original_form": 277.43,
        "champion_reference": {"LONG": 1415.62, "CONT": 544.47, "VAL": 288.05,
                               "DECADE": 65.89},
        "champion_decade_caveat": "Champion DECADE $65.89 is from the lazy-quarterly test after two halts; its crown rests on the 2010 and 2019 roads. Every residual-momentum cadence cell beats that decade figure, but on CONT/VAL the champion still leads ($544.47/$288.05 vs residual momentum's $413.31/$277.43 in original quarterly form)."},
    "verdict_area": "OWNS ITS GROUND",
    "verdict_change": "CHANGED on the decade road, unchanged on the champion's judging windows. Original program verdict (quarterly, CONT/VAL): 'real signal, weaker sibling, NOT PROMOTED' — it trailed the champion $413.31 vs $544.47 (CONT) and $277.43 vs $288.05 (VAL), and that still stands on those windows. But judged on the DECADE road at its own tempos it beats SPY at every cadence except daily, posts its best money at weekly ($589.98, 20/20 placebos) and at its native monthly ($562.64, 18/20) — while the champion's own decade run ended at $65.89 after two halts (caveat: the champion's crown rests on the 2010/2019 roads). The foreign quarterly cadence was NOT what held it back on CONT/VAL-era form; the decade is simply ground where this strategy's steadier tempo survived and the champion's did not.",
    "data_note": "Sweep data (read-only shared caches): prices from long-run-2010 lr_common.yahoo_payload (v7 long-hold pxfull cache; GOOGL from long-run-2010/data) via bars_adj (champion bar construction), assembled in the engine's own FastBook; EDGAR chains via lr_common.load_facts + equity_chain/shares_chain; universe = the engine's honest PIT top-30 as of Nov 2016. No writes to shared folders. The stood-down batch worker's scratch in this folder (w4lib.py, supplementary_monthly.py) was reviewed and SUPERSEDED by this run; its unsaved monthly figures do not count and were not used.",
    "halts_note": "No cell halted on the decade road (no restarts, no second halts). Worst closes: daily $88.30 (2020-03-23, $3.30 above the $85 episode floor); all other cadences' worst closes were early-window dips of $96-$100 in 2016-2017, before the pot had gains to protect.",
}
with open(os.path.join(HERE, "results.json"), "w") as f:
    json.dump(payload, f, indent=1, default=str)
print("results.json written")
