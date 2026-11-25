#!/usr/bin/env python3
"""V13 best-rules run for catalog-taa-keller-paa-gpm.
Spec: BEST-RULES-SPEC.md (frozen before this run).
Reuses the v12 slice engine (read-only) for data/costs/execution plumbing.
Best-rules form = published GPM construction exactly, monthly, NO house floor.
"""
import importlib.util, json, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ENG = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/catalog-taa-keller-paa-gpm/run_engine.py")
spec = importlib.util.spec_from_file_location("v12_engine", ENG)
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

ROADS = E.ROADS
RISKY = ["SPY", "QQQ", "EFA", "EEM", "VNQ", "DBC", "GLD", "TLT", "LQD", "AGG"]
DEF = {"IEF", "BIL"}

def time_in_defense(road):
    start, end = ROADS[road]
    si, ei, evals = E.eval_indices("monthly", start, end)
    exps = []
    for i in evals:
        if i >= ei:
            continue
        tgt = E.w_gpm(i)
        exps.append(sum(w for t, w in tgt.items() if t not in DEF))
    if not exps:
        return {}
    return {
        "months": len(exps),
        "mean_risky_exposure_pct": round(100 * float(np.mean(exps)), 1),
        "share_months_below_full_risky_pct": round(100 * sum(1 for x in exps if x < 0.999) / len(exps), 1),
        "share_months_half_or_less_risky_pct": round(100 * sum(1 for x in exps if x <= 0.501) / len(exps), 1),
        "share_months_fully_defensive_pct": round(100 * sum(1 for x in exps if x < 0.001) / len(exps), 1),
    }

def buyhold(tickers_weights, road):
    start, end = ROADS[road]
    si, ei, _ = E.eval_indices("monthly", start, end)
    eq = []
    for i in range(si, ei + 1):
        v = 0.0
        for t, w in tickers_weights.items():
            a0, a1 = E.ARR[t][si], E.ARR[t][i]
            if not np.isnan(a0) and not np.isnan(a1) and a0 > 0:
                v += 100.0 * w * a1 / a0
        eq.append((E.CAL[i], round(v, 4)))
    peak, mdd = -1.0, 0.0
    for _, v in eq:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1 if peak > 0 else 0)
    return {"final": round(eq[-1][1], 2), "maxDD": round(mdd * 100, 2), "equity": eq}

def main():
    res = {"family": "catalog-taa-keller-paa-gpm", "program": "v13-best-rules",
           "form": "published GPM construction exactly, monthly, no house floor",
           "roads": {}}
    pw = E.placebo_wfun(RISKY, 3)
    for road in ROADS:
        nat = E.run(E.w_gpm, road)  # native == best-rules (no floor in spec)
        finals = [E.run(pw, road, seed=1000 + s)["final"] for s in range(20)]
        ew = buyhold({t: 1.0 / len(RISKY) for t in RISKY}, road)
        spy = buyhold({"SPY": 1.0}, road)
        mix = E.run(lambda i: {"SPY": 0.6, "IEF": 0.4}, road)
        res["roads"][road] = {
            "best_rules": nat,
            "period_distribution_monthly": E.period_stats(nat["equity"]),
            "time_in_defense": time_in_defense(road),
            "placebo_finals": finals,
            "placebos_beaten": sum(1 for f in finals if nat["final"] > f),
            "static_ew10_buyhold": {"final": ew["final"], "maxDD": ew["maxDD"]},
            "spy_buyhold_engine": {"final": spy["final"], "maxDD": spy["maxDD"]},
            "static_6040_spy_ief_monthly_rebal": {"final": mix["final"], "maxDD": mix["maxDD"]},
        }
        print(road, nat["final"], nat["maxDD"], "placebos", res["roads"][road]["placebos_beaten"],
              "EW10", ew["final"], "SPYeng", spy["final"], "6040", mix["final"], flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(res, f, indent=1)
    print("DONE")

if __name__ == "__main__":
    main()
