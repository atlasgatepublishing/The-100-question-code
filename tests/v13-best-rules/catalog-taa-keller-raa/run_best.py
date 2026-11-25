#!/usr/bin/env python3
"""V13 Best Rules — catalog-taa-keller-raa.
Construction EXACTLY as published (v12 w_raa); chassis per BEST-RULES-SPEC.md:
monthly cadence, NO external floor. Reuses the v12 shared engine read-only.
"""
import json, os, sys
import numpy as np

V12 = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/catalog-taa-keller-raa")
sys.path.insert(0, V12)
import run_engine as E  # loads cached ETF bars, defines w_raa / run / period_stats

OUT = os.path.expanduser("~/workspace/stock-app/backtests/v13-best-rules/catalog-taa-keller-raa")
RISKY = ["SPY", "VGK", "EWJ", "EEM", "VNQ", "RWX", "IEF", "TLT", "DBC", "GLD"]
CHAMP = {"LONG": 1415.62, "CONT": 544.47, "VAL": 288.05, "DECADE": 667.35}
SPY_REF = {"LONG": 822.94, "CONT": 313.62, "VAL": 187.77, "DECADE": 367.80}
COST = E.COST


def buy_hold(tickers_weights, road):
    """Buy at road-start close (first trading day), hold to road end. Cost on buys."""
    start, end = E.ROADS[road]
    si = next(i for i, d in enumerate(E.CAL) if d >= start)
    ei = max(i for i, d in enumerate(E.CAL) if d <= end)
    eq = []
    shares = {}
    for t, w in tickers_weights.items():
        p = E.ARR[t][si]
        shares[t] = (w * 100.0 * (1 - COST)) / p
    for i in range(si, ei + 1):
        v = sum(sh * E.ARR[t][i] for t, sh in shares.items() if not np.isnan(E.ARR[t][i]))
        eq.append((E.CAL[i], round(float(v), 4)))
    peak, mdd = -1.0, 0.0
    for _, v in eq:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1 if peak > 0 else 0)
    return {"final": round(eq[-1][1], 2), "maxDD": round(mdd * 100, 2), "equity": eq}


def half_windows(wfun, road):
    """Split road at its midpoint date; run each half fresh with $100."""
    start, end = E.ROADS[road]
    si = next(i for i, d in enumerate(E.CAL) if d >= start)
    ei = max(i for i, d in enumerate(E.CAL) if d <= end)
    mid = E.CAL[(si + ei) // 2]
    saved = dict(E.ROADS)
    try:
        E.ROADS["H1"] = (start, mid)
        E.ROADS["H2"] = (mid, end)
        h1 = E.run(wfun, "H1", cadence="monthly", house=False)
        h2 = E.run(wfun, "H2", cadence="monthly", house=False)
        s1 = buy_hold({"SPY": 1.0}, "H1")
        s2 = buy_hold({"SPY": 1.0}, "H2")
    finally:
        E.ROADS.clear(); E.ROADS.update(saved)
    return {"H1": {"final": h1["final"], "maxDD": h1["maxDD"], "spy_final": s1["final"]},
            "H2": {"final": h2["final"], "maxDD": h2["maxDD"], "spy_final": s2["final"]}}


def main():
    res = {"family": "catalog-taa-keller-raa", "program": "v13-best-rules",
           "spec": "monthly cadence, no external floor, published construction exactly",
           "roads": {}, "confirmation": {}}
    pw = E.placebo_wfun(RISKY, 5)
    for road in ("LONG", "DECADE", "CONT", "VAL"):
        r = E.run(E.w_raa, road, cadence="monthly", house=False)
        spy = buy_hold({"SPY": 1.0}, road)
        mix = buy_hold({t: 0.1 for t in RISKY}, road)
        entry = {"strategy": r, "spy_buyhold": spy, "static_mix_ew10": mix,
                 "champion_vm": CHAMP[road], "spy_reference_published": SPY_REF[road],
                 "period_distribution_monthly": E.period_stats(r["equity"])}
        if road in ("LONG", "DECADE"):
            finals = [E.run(pw, road, seed=1000 + s)["final"] for s in range(20)]
            entry["placebo_finals"] = finals
            entry["placebos_beaten"] = sum(1 for f in finals if r["final"] > f)
        res["roads"][road] = entry
        print(road, "strategy", r["final"], "maxDD", r["maxDD"],
              "| SPY", spy["final"], "| mix", mix["final"],
              "| placebos_beaten", entry.get("placebos_beaten"), flush=True)
        if r["final"] > CHAMP[road]:
            res["confirmation"][road] = half_windows(E.w_raa, road)
            print("  CHAMPION BEAT — confirmation half-windows:", res["confirmation"][road], flush=True)
    json.dump(res, open(os.path.join(OUT, "results.json"), "w"), indent=1)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
