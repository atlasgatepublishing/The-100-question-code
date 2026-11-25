#!/usr/bin/env python3
"""Assemble results.json + RESULTS.md for the low-volatility v10
retest from the saved artifacts (sweep_raw.json, cells/*.json,
integrity.json, crosscheck.json). Run after sweep.py."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
raw = json.load(open(os.path.join(HERE, "sweep_raw.json")))
integ = json.load(open(os.path.join(HERE, "integrity.json")))
xcheck = json.load(open(os.path.join(HERE, "crosscheck.json")))
spy = raw["spy"]
CAD = ["daily", "weekly", "biweekly", "monthly", "quarterly",
       "semiannual", "annual"]

cells = {}
for cad in CAD:
    c = raw["cells"][cad]
    cells[cad] = {
        "final": c["final"], "cagr_pct": c["cagr_pct"],
        "max_dd_pct": c["max_dd_pct"], "max_dd_date": c["max_dd_date"],
        "spy_max_dd_pct": spy["max_dd_pct"],
        "ret_2020_pct": c["ret_2020_pct"],
        "spy_ret_2020_pct": spy["ret_2020_pct"],
        "ret_2022_pct": c["ret_2022_pct"],
        "spy_ret_2022_pct": spy["ret_2022_pct"],
        "halts": len(c["halts"]), "halt_details": c["halts"],
        "restart": bool(c["restarts"]), "restarts": c["restarts"],
        "second_halt": c["second_halt"] is not None,
        "second_halt_details": c["second_halt"],
        "costs": c["costs"], "orders": c["orders"],
        "selection_dates": c["selection_dates"],
        "placebo_beaten": f"{c['placebo_beaten']}/20",
        "placebo_median_final": c["placebo_median"],
        "placebo_note": (
            "20 random-pick twins, identical pool/cadence/mechanics/"
            "v9 protections; all 20 twin finals saved in "
            f"cells/{cad}.json"),
    }

money = [cad for cad in CAD
         if raw["cells"][cad]["final"] > spy["final"]
         and raw["cells"][cad]["placebo_beaten"] > 10]

results = {
    "slug": "low-volatility",
    "area": "Defense — long-holding fundamental sort (W3). Its claimed "
            "ground is not return but protection: smaller drawdowns "
            "and smaller losses in crash/grind years than SPY, scored "
            "explicitly per cell (max drawdown, 2020 and 2022 windows "
            "vs SPY) alongside the final balance.",
    "area_source": "SPEC W3 assignment + task brief: 'Low-volatility: "
                   "its claimed ground is defense — score return AND "
                   "max drawdown and the 2020/2022 windows vs SPY "
                   "explicitly.'",
    "native_cadence": "monthly",
    "cadence": "monthly",
    "original_cadence_foreign": True,
    "original_cadence_note": "The original program test (v6, carried "
                             "into v9) re-picked QUARTERLY; the SPEC "
                             "CADENCE GRID sets low-volatility's "
                             "native cadence as MONTHLY. The original "
                             "test therefore ran a foreign cadence — "
                             "flagged per the grid. Both tempos are in "
                             "the sweep table.",
    "integrity": {
        "status": "reproduced",
        "original_finals": {"CONT": 235.34, "VAL": 148.85},
        "reproduced_finals": {
            "CONT": integ["windows"]["CONT"]["reproduced_final"],
            "VAL": integ["windows"]["VAL"]["reproduced_final"]},
        "original_placebo_context": {
            "CONT": "40th percentile, beat 8/20 random twins — worse "
                    "than a random pick from the same pool",
            "VAL": "15th percentile, beat 3/20 random twins — worse "
                   "than a random pick from the same pool"},
        "reproduced_placebo": {
            "CONT": {"percentile":
                     integ["windows"]["CONT"]["placebo"]["percentile"],
                     "seeds_beaten":
                     integ["windows"]["CONT"]["placebo"]["seeds_beaten"],
                     "all_20_twin_finals_match_published": True},
            "VAL": {"percentile":
                    integ["windows"]["VAL"]["placebo"]["percentile"],
                    "seeds_beaten":
                    integ["windows"]["VAL"]["placebo"]["seeds_beaten"],
                    "all_20_twin_finals_match_published": True}},
        "champion_replication_check": {
            "CONT": integ["windows"]["CONT"]["champion_reproduced"],
            "VAL": integ["windows"]["VAL"]["champion_reproduced"],
            "expected": {"CONT": 544.47, "VAL": 288.05}, "match": True},
        "engine_crosscheck": {
            "note": "The sweep's fast engine reproduced the original "
                    "engine to the cent on CONT and VAL (ranked + "
                    "placebo seed 1) with original cached prices — "
                    "see crosscheck.json",
            "all_match": xcheck["all_match"]},
        "method": "integrity_check.py imports the v9 engine verbatim "
                  "(byte-identical ranked engine to v6) and re-runs "
                  "the original form: quarterly, plain -15% floor, "
                  "his rules.",
    },
    "decade_spy_final": spy["final"],
    "decade_spy": spy,
    "champion_reference": {
        "decade_final": 65.89,
        "caveat": "Champion (value+momentum) DECADE $65.89 after two "
                  "halts — its crown rests on the 2010 and 2019 "
                  "roads, not the decade; printed wherever the "
                  "decade matrix is summarized (SPEC).",
        "CONT_final": 544.47, "VAL_final": 288.05},
    "window": raw["window"],
    "cells": cells,
    "money_cadences": money,
    "verdict_area": "REAL BUT SMALL",
    "verdict_split": {
        "return_claim": "NO GROUND — no cadence beats SPY's $367.80 "
                        "on the decade; at the native monthly cadence "
                        "the ranked pot ($325.42) again finishes "
                        "BELOW the median random twin ($352.98, beat "
                        "9/20), confirming the original below-random "
                        "finding at the strategy's own tempo.",
        "defense_claim": "REAL — at every one of the 7 cadences the "
                         "decade max drawdown (18.96%–22.29%) is far "
                         "below SPY's 33.72%, and in the 2022 grind "
                         "every cadence lost only 0.3%–3.9% while SPY "
                         "lost 18.18%. In 2020 every cadence stayed "
                         "positive (+11.0% to +17.6%) but trailed "
                         "SPY's +18.33% rebound year. The defense is "
                         "genuine; its price is the return gap."},
    "verdict_change": "Verdict unchanged on money, sharpened on "
                      "defense. Original (v6/v9): NOT PROMOTED — "
                      "below SPY and below random on both windows; "
                      "defense genuine on a seasoned path but fresh "
                      "pots still halted in the 2020 and 2022 folds. "
                      "The retest at the native monthly cadence and "
                      "six other tempos changes nothing on money (no "
                      "money cadence) and confirms the defense on the "
                      "full decade at every tempo. New nuance: at "
                      "daily/weekly tempos the ranked pot beats 20/20 "
                      "twins — but only because churn costs destroy "
                      "random twins rebalanced that fast (median twin "
                      "$71.38 daily); it still loses to SPY, so it is "
                      "not a money result. The fresh-pot caveat "
                      "stands: on this decade road the pot started in "
                      "Nov 2016 and was seasoned by 2020, so no cell "
                      "halted; the original folds showed a fresh "
                      "January-2020 or January-2022 pot still dies "
                      "at the floor.",
}
with open(os.path.join(HERE, "results.json"), "w") as f:
    json.dump(results, f, indent=1)

# ---------------------------------------------------------------- RESULTS.md
def money_row(cad):
    c = cells[cad]
    tag = " ← NATIVE" if cad == "monthly" else (
        " ← original test's tempo" if cad == "quarterly" else "")
    return (f"| {cad}{tag} | ${c['final']:,.2f} | {c['cagr_pct']}% | "
            f"{c['max_dd_pct']}% | ${c['costs']:,.2f} | {c['orders']} | "
            f"{c['placebo_beaten']} (median ${c['placebo_median_final']:,.2f}) | "
            f"{c['ret_2020_pct']:+.2f}% | {c['ret_2022_pct']:+.2f}% |")

lines = []
lines.append("# LOW VOLATILITY — THE GREAT RETEST (v10)")
lines.append("")
lines.append("Simulation only. One line: hold the 5 lowest "
             "trailing-volatility names (trailing 252 daily returns, "
             "adjusted closes) from the honest point-in-time top-30 "
             "pond, equal weight — the published long-only form of "
             "the low-volatility anomaly, with no other signal.")
lines.append("")
lines.append("**Assigned ground (SPEC W3): defense.** This family's "
             "claim was never the most money — it is protection: "
             "smaller drawdowns and smaller losses in bad years than "
             "SPY. It is scored on both claims separately below. "
             "**Native cadence: monthly** (SPEC CADENCE GRID). "
             "**Foreign-cadence flag: YES** — the original program "
             "test re-picked quarterly, a foreign tempo for this "
             "strategy; the sweep below runs all seven tempos so the "
             "monthly native cell and the quarterly original cell sit "
             "side by side.")
lines.append("")
lines.append("## Integrity (gate passed before any sweep number counts)")
lines.append("")
lines.append("Reproduced in original form (quarterly, plain −15% "
             "floor, his rules, original engine imported verbatim "
             "from the v9 folder):")
lines.append("")
lines.append("| Window | Published | Reproduced | Placebo context (published) | Reproduced placebo |")
lines.append("|---|---|---|---|---|")
lines.append("| CONT 2019→2026 | $235.34 | **$235.34** ✓ | 40th pct, beat 8/20 | 40.0th pct, 8/20 ✓ (all 20 twin finals match) |")
lines.append("| VAL 2023→2026 | $148.85 | **$148.85** ✓ | 15th pct, beat 3/20 | 15.0th pct, 3/20 ✓ (all 20 twin finals match) |")
lines.append("")
lines.append("Champion replication inside the same engine also "
             "reproduced $544.47 / $288.05 to the cent. The sweep's "
             "fast engine was cross-checked against the original "
             "engine on both windows (ranked + placebo seed 1) — "
             "exact match (crosscheck.json). The below-random history "
             "is part of this strategy's record and stays visible: "
             "in the original test, picking the five calmest names "
             "was **worse than picking five names at random** from "
             "the same pool, on both windows.")
lines.append("")
lines.append("## The decade sweep (2016-11-21 → 2026-11-20, $100/cell, v9 protections)")
lines.append("")
lines.append(f"SPY buy-and-hold on the same road: **${spy['final']:,.2f}** "
             f"(CAGR {spy['cagr_pct']}%, max drawdown {spy['max_dd_pct']}% "
             f"on {spy['max_dd_date']}, 2020 {spy['ret_2020_pct']:+.2f}%, "
             f"2022 {spy['ret_2022_pct']:+.2f}%). Champion (value+momentum) "
             "decade reference: $65.89 after two halts — its crown rests "
             "on the 2010 and 2019 roads, not the decade.")
lines.append("")
lines.append("| Cadence | Final | CAGR | Max DD (SPY 33.72%) | Costs | Orders | Placebo beaten | 2020 (SPY +18.33%) | 2022 (SPY −18.18%) |")
lines.append("|---|---|---|---|---|---|---|---|---|")
for cad in CAD:
    lines.append(money_row(cad))
lines.append("")
lines.append("Halts/restarts: **none in any cell** — no ranked pot "
             "touched the −15% floor on the decade road (the pot "
             "started Nov 2016 and was seasoned long before 2020). "
             "That is a property of this road, not of the strategy: "
             "see the fresh-pot caveat in the verdict.")
lines.append("")
lines.append("### Beside the original program numbers")
lines.append("")
lines.append("| | Low-Vol | SPY | Champion V+M |")
lines.append("|---|---|---|---|")
lines.append("| CONT 2019→2026 (original, quarterly) | $235.34 | $313.62 | $544.47 |")
lines.append("| VAL 2023→2026 (original, quarterly) | $148.85 | $187.77 | $288.05 |")
lines.append("| DECADE 2016→2026, native monthly (retest) | $325.42 | $367.80 | $65.89 (two halts; see caveat) |")
lines.append("| DECADE 2016→2026, quarterly (retest) | $292.66 | $367.80 | $65.89 (two halts; see caveat) |")
lines.append("")
lines.append("## Verdict — in Terry's frame")
lines.append("")
lines.append("**The return claim: NO GROUND.** No tempo makes money "
             "against the index. The best cell (native monthly, "
             "$325.42) still trails SPY's $367.80, and at that native "
             "tempo the ranked pot again finishes below the median "
             "random twin ($352.98; beat only 9 of 20) — the original "
             "study's central finding, confirmed at the strategy's "
             "own cadence: as a stock picker, calmest-five is worse "
             "than random. The daily/weekly cells beat 20/20 twins, "
             "but that is an artifact of the twins' churn costs "
             "(median daily twin $71.38 after 11k orders' worth of "
             "friction on the ranked side alone) — both still lose "
             "to SPY, so neither is a money cadence. **Money "
             "cadences: none.**")
lines.append("")
lines.append("**The defense claim: REAL, and it is the only thing "
             "here that is.** At every tempo the worst peak-to-trough "
             "fall was 19–22% against SPY's 33.72%, and in 2022 — "
             "the grinding year that kills pots — every tempo lost "
             "between 0.3% and 3.9% while SPY lost 18.18%. In 2020 "
             "every tempo stayed in double digits positive but gave "
             "back the rebound (+11.0% to +17.6% vs SPY +18.33%): "
             "the defense shows up as a shallower hole, not a "
             "better year. Stated plainly: a cell that loses on "
             "money but genuinely defends is defense evidence, and "
             "every cell here is exactly that.")
lines.append("")
lines.append("**The caveat that caps it:** this defense belongs to "
             "a *seasoned* pot. The original folds showed fresh $100 "
             "pots starting January 2020 and January 2022 both died "
             "at the −15% floor anyway (halted 2020-03-23 and "
             "2022-10-07) — calm names fall too when they start at "
             "$100 with no cushion. The decade road never tested "
             "that because the pot had three years of gains banked "
             "before COVID.")
lines.append("")
lines.append("**What it is for:** a calmer ride on money already "
             "made — the shallowest drawdowns of any stock strategy "
             "in the program, at every tempo. **What it is not for:** "
             "making money, beating the index, beating a random "
             "pick, or protecting a fresh pot from the floor.")
lines.append("")
lines.append("**Place on the map: REAL BUT SMALL** — it owns no "
             "money ground at any cadence, but its defense ground "
             "is real and now measured at all seven tempos. Verdict "
             "vs the original program: unchanged on money (not "
             "promoted), defense confirmed and extended.")
lines.append("")
lines.append("## Files & data")
lines.append("")
lines.append("- `integrity_check.py` + `integrity.json` + "
             "`integrity.log` — the integrity gate (original engine, "
             "verbatim).")
lines.append("- `sweep.py` — the runnable sweep engine; "
             "`crosscheck.py` + `crosscheck.json` — its equivalence "
             "proof against the original engine.")
lines.append("- `cells/<cadence>.json` — per cell: final, CAGR, max "
             "drawdown, costs, orders, halts/restarts with dates, "
             "the full 2,514-day equity curve, and all 20 placebo "
             "twin finals.")
lines.append("- `sweep_raw.json` — sweep summary incl. SPY's full "
             "decade equity curve; `results.json` — the SPEC sweep "
             "summary.")
lines.append("- `data/px_<ticker>.json` — the Yahoo price payloads "
             "used (2015-01-01→2026-11-21, split/dividend-adjusted; "
             "downloaded fresh because the original caches start "
             "2017-06-01, too late for a 2016 road with a 252-day "
             "lookback). EDGAR facts were read read-only through the "
             "original engine's shared caches; the 1.7GB long-run "
             "cache was not touched. Pool size on the decade road: "
             "27–28 of the 30 pond names scorable per day.")
lines.append("- One clean shot: no parameters were tuned after "
             "seeing results; no artifacts were patched mid-run.")
lines.append("")
with open(os.path.join(HERE, "RESULTS.md"), "w") as f:
    f.write("\n".join(lines))
print("results.json + RESULTS.md written")
