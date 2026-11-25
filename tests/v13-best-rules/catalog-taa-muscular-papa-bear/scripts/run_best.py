#!/usr/bin/env python3
"""V13 Best-Rules run — Papa Bear. Spec: ../BEST-RULES-SPEC.md (frozen before this run).
Best rules: published 13-ETF universe, published 63/126/252-day blended momentum,
top-3 equal weight, always invested, QUARTERLY rebalance, NO floor.
Also run (same data, same engine) for comparison only:
  - published form (monthly, top-3, no floor) — validation vs the v12 record;
  - static equal-weight buy-hold mix of the 13 (initial buys only);
  - 20-seed random-pick placebos at the best-rules (quarterly) cadence.
Costs: engine standard 0.10% of traded value + $0.01 per sell order. $100 pots."""
import sys, os, json, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd
import numpy as np
from engine import simulate, period_stats, ret_td, aligned, ROADS, COST_RATE

HERE = os.path.dirname(os.path.abspath(__file__))
FOLDER = os.path.dirname(HERE)
PAPA_U = ["VTV", "VUG", "VIOV", "VIOG", "VEA", "VWO", "VNQ", "PDBC", "IAU",
          "EDV", "VGIT", "VCLT", "BNDX"]

def papa_scores(date):
    out = {}
    for t in PAPA_U:
        rs = [ret_td(t, date, d) for d in (63, 126, 252)]
        if all(r is not None for r in rs):
            out[t] = sum(rs) / 3.0
    return out

def papa_top3(date, rng=None):
    s = papa_scores(date)
    if not s: return {}
    top = sorted(s, key=s.get, reverse=True)[:3]
    return {t: 1.0 / len(top) for t in top}

def papa_placebo(date, rng=None):
    s = papa_scores(date)
    if not s: return {}
    picks = rng.sample(sorted(s), min(3, len(s)))
    return {t: 1.0 / len(picks) for t in picks}

def period_stats_freq(eq, freq):
    m = eq.resample(freq).last().dropna()
    rets = m.pct_change().dropna()
    if len(rets) == 0: return {}
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; streak = max(streak, cur)
    hi = [i for i in range(len(m)) if m.iloc[i] >= m.iloc[:i + 1].max()]
    longest = 0; prev = 0
    for p in hi: longest = max(longest, p - prev); prev = p
    longest = max(longest, len(m) - 1 - prev)
    dd = (eq / eq.cummax() - 1.0).min()
    unit = 3 if freq == "Q" else 1
    return {"n_periods": int(len(rets)), "share_positive": round(float((rets > 0).mean()), 3),
            "median_pct": round(float(rets.median()) * 100, 2),
            "best_pct": round(float(rets.max()) * 100, 2),
            "worst_pct": round(float(rets.min()) * 100, 2),
            "mean_pct_secondary": round(float(rets.mean()) * 100, 2),
            "longest_losing_streak": int(streak),
            "longest_between_highs_months": int(longest * unit),
            "max_drawdown_pct": round(float(dd) * 100, 1)}

def static_mix(start, end):
    """Equal-weight buy-hold of the universe members already trading at road
    start; initial-buy cost 0.10% of pot; never rebalanced, never sold."""
    days = [d for d in aligned("SPY").index if pd.Timestamp(start) <= d <= pd.Timestamp(end)]
    members = []
    for t in PAPA_U:
        a = aligned(t)
        if not pd.isna(a.loc[days[0]]):
            members.append(t)
    n = len(members)
    val = pd.Series(0.0, index=days)
    for t in members:
        a = aligned(t).loc[days]
        val += (100.0 / n) * (a / a.iloc[0])
    val.iloc[0] = 100.0 - COST_RATE * 100.0
    return val, members

def main():
    out = {}
    for road, (st, en) in ROADS.items():
        res = {}
        # Best rules: quarterly, no floor
        eq, info = simulate(st, en, papa_top3, house=False, rebalance_months=3)
        res["best"] = {"final": round(info["final"], 2), "halts": info["halts"],
                       "periods_quarterly": period_stats_freq(eq, "Q"),
                       "periods_monthly": period_stats(eq),
                       "curve": {str(k.date()): round(float(v), 4) for k, v in eq.items()}}
        # Published form on the same data (validation / grading bar)
        eq2, info2 = simulate(st, en, papa_top3, house=False, rebalance_months=1)
        res["published_same_data"] = {"final": round(info2["final"], 2),
                                      "periods_monthly": period_stats(eq2)}
        # Static mix benchmark
        sm, members = static_mix(st, en)
        res["static_mix"] = {"final": round(float(sm.iloc[-1]), 2), "n_members": len(members),
                             "members": members,
                             "max_drawdown_pct": round(float((sm / sm.cummax() - 1.0).min()) * 100, 1)}
        # Placebos at best-rules cadence
        finals = []
        for seed in range(20):
            rng = random.Random(1000 + seed)
            eqp, infop = simulate(st, en, papa_placebo, house=False, rng=rng, rebalance_months=3)
            finals.append(round(infop["final"], 2))
        finals.sort()
        res["placebo"] = {"median": finals[10], "p90": finals[17], "max": finals[-1],
                          "min": finals[0], "all_finals": finals,
                          "best_beats_of_20": int(sum(1 for f in finals if res["best"]["final"] > f))}
        out[road] = res
        print(road, "best", res["best"]["final"], "pub_same_data", res["published_same_data"]["final"],
              "static", res["static_mix"]["final"], "placebo_med", res["placebo"]["median"],
              "beats", res["placebo"]["best_beats_of_20"], "dd", res["best"]["periods_quarterly"]["max_drawdown_pct"],
              flush=True)
    json.dump(out, open(os.path.join(FOLDER, "results.json"), "w"), indent=1)
    print("WROTE results.json")

if __name__ == "__main__":
    main()
