#!/usr/bin/env python3
"""V13 Best-Rules run for catalog-taa-keller-paa (Keller PAA).
Spec: ../BEST-RULES-SPEC.md (frozen before this run).
Reuses the v12 slice engine read-only (data cache + run chassis + w_paa).
"""
import json, os, sys, statistics

V12 = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/catalog-taa-keller-paa")
sys.path.insert(0, V12)
import run_engine as E  # loads cached ETF bars, defines run(), w_paa, period_stats

OUT = os.path.expanduser("~/workspace/stock-app/backtests/v13-best-rules/catalog-taa-keller-paa")
RISKY = ["SPY", "EFA", "EEM", "VNQ", "DBC", "TLT"]
CHAMP = {"LONG": 1415.62, "CONT": 544.47, "VAL": 288.05, "DECADE": 667.35}
SPY_REF = {"LONG": 822.94, "CONT": 313.62, "VAL": 187.77, "DECADE": 367.80}

# --- defense tracking wrapper around the published w_paa ---
DEF_LOG = []  # (protection_fraction) per rebalance call, in order
def w_protected(i):
    tgt = E.w_paa(i, topn=3)
    prot = sum(w for t, w in tgt.items() if t not in RISKY)
    DEF_LOG.append(round(prot, 6))
    return tgt

# --- unprotected ablation: SAME book, breadth dial disabled ---
def w_unprotected(i):
    _, sc = E.top_pos(RISKY, i, 3)  # sc = full sorted [(score, ticker)]
    picks = [t for s, t in sc[:3]]
    return {t: 1.0 / len(picks) for t in picks}

# --- static mix comparator: EW across the 6 risky ETFs, monthly, no signal ---
def w_static(i):
    return {t: 1.0 / 6 for t in RISKY}

def spy_buyhold(road):
    start, end = E.ROADS[road]
    si = next(i for i, d in enumerate(E.CAL) if d >= start)
    ei = max(i for i, d in enumerate(E.CAL) if d <= end)
    return round(100.0 * (1 - E.COST) * E.ARR["SPY"][ei] / E.ARR["SPY"][si], 2)

def defense_stats():
    if not DEF_LOG:
        return {}
    n = len(DEF_LOG)
    return {
        "rebalance_months": n,
        "mean_protection_fraction_pct": round(100 * statistics.mean(DEF_LOG), 1),
        "share_months_any_protection_pct": round(100 * sum(1 for p in DEF_LOG if p > 0.001) / n, 1),
        "share_months_fully_protected_pct": round(100 * sum(1 for p in DEF_LOG if p > 0.999) / n, 1),
        "mean_risky_exposure_pct": round(100 * (1 - statistics.mean(DEF_LOG)), 1),
    }

res = {"family": "catalog-taa-keller-paa", "program": "v13-best-rules", "roads": {}}
for road in ("LONG", "DECADE", "CONT", "VAL"):
    DEF_LOG.clear()
    prot = E.run(w_protected, road)
    dstats = defense_stats()
    unprot = E.run(w_unprotected, road)
    static = E.run(w_static, road)
    entry = {
        "protected": prot,
        "unprotected_ablation": unprot,
        "static_mix": static,
        "spy_buyhold_computed": spy_buyhold(road),
        "spy_reference": SPY_REF[road],
        "champion_vm": CHAMP[road],
        "protection_effect_dollars": round(prot["final"] - unprot["final"], 2),
        "time_in_defense": dstats,
        "period_distribution_protected_monthly": E.period_stats(prot["equity"]),
        "period_distribution_unprotected_monthly": E.period_stats(unprot["equity"]),
    }
    res["roads"][road] = entry
    print(road, "protected", prot["final"], "DD", prot["maxDD"],
          "| unprotected", unprot["final"], "DD", unprot["maxDD"],
          "| static", static["final"], "| SPYcalc", entry["spy_buyhold_computed"],
          "| defense", dstats, flush=True)

# placebos: 20 seeds, LONG + DECADE, for protected chassis method and ablation method
pw = E.placebo_wfun(RISKY, 3)
res["placebo_finals"] = {}
for road in ("LONG", "DECADE"):
    finals = [E.run(pw, road, seed=1000 + s)["final"] for s in range(20)]
    res["placebo_finals"][road] = finals
    res["roads"][road]["placebos_beaten_protected"] = sum(
        1 for f in finals if res["roads"][road]["protected"]["final"] > f)
    res["roads"][road]["placebos_beaten_unprotected"] = sum(
        1 for f in finals if res["roads"][road]["unprotected_ablation"]["final"] > f)
    print(road, "placebos beaten: protected",
          res["roads"][road]["placebos_beaten_protected"], "/20, unprotected",
          res["roads"][road]["placebos_beaten_unprotected"], "/20",
          "| placebo median", round(statistics.median(finals), 2), flush=True)

res["champion_beaten_roads"] = [r for r in res["roads"]
                                if res["roads"][r]["protected"]["final"] > CHAMP[r]]
print("champion beaten roads:", res["champion_beaten_roads"], flush=True)

with open(os.path.join(OUT, "results.json"), "w") as f:
    json.dump(res, f, indent=1)
print("WROTE results.json")
