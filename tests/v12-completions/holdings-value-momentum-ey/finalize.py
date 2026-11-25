#!/usr/bin/env python3
"""Assemble results.json: full grid + curves + per-period (quarterly)
distributions for winning count (3) and native count (5)."""
import json, os, statistics
from datetime import date
HERE = os.path.dirname(os.path.abspath(__file__))

def period_dist(curve, start_cash=100.0):
    # calendar-quarter snapshots: last curve value in each quarter
    snaps = []
    seen = {}
    for d, v in curve:
        seen[(d[:4], (int(d[5:7])-1)//3)] = (d, v)
    for k in sorted(seen):
        snaps.append(seen[k])
    rets, prev = [], start_cash
    for d, v in snaps:
        rets.append(v/prev - 1.0); prev = v
    n = len(rets)
    # longest losing run
    longest_loss, cur = 0, 0
    for r in rets:
        cur = cur+1 if r < 0 else 0
        longest_loss = max(longest_loss, cur)
    # longest stretch between new highs (in quarterly periods, snapshot series incl. start)
    series = [start_cash] + [v for _, v in snaps]
    dates = [curve[0][0]] + [d for d, _ in snaps]
    peak, peak_i, longest_gap = -1, 0, 0
    for i, v in enumerate(series):
        if v > peak:
            longest_gap = max(longest_gap, i - peak_i); peak, peak_i = v, i
    longest_gap = max(longest_gap, len(series)-1 - peak_i)
    return {"tempo": "quarterly (calendar-quarter snapshots of the daily curve)",
            "n_periods": n,
            "pct_periods_profitable": round(100.0*sum(1 for r in rets if r > 0)/n, 1),
            "median_period_pct": round(statistics.median(rets)*100, 2),
            "best_period_pct": round(max(rets)*100, 2),
            "worst_period_pct": round(min(rets)*100, 2),
            "longest_losing_run_periods": longest_loss,
            "longest_stretch_between_new_highs_periods": longest_gap,
            "average_period_pct_SECONDARY": round(statistics.mean(rets)*100, 2)}

out = {"family": "value-momentum-ey", "program": "v12-holdings-count-sweep",
       "form_used": "published house form (v10 pond chassis): 30-name pond, score=avg percentile(E/P, 12-1 momentum), quarterly cadence, v9 protections (-15% plain floor, 90d sit-out, episode-2 floor), costs 0.10%/side + $0.01/sell, $100 start",
       "native_count": 5, "winning_count": 3,
       "verdict": "FEWER IS BETTER", "variant_candidate": "count 3 (CONFIRMED on PRE2016 and PANDEMIC_ERA windows)",
       "grid": {}, "confirmation": {}, "period_distributions": {}, "curves": {}}
for fn in sorted(os.listdir(os.path.join(HERE, "cells"))):
    if fn.endswith(".json"):
        c = json.load(open(os.path.join(HERE, "cells", fn)))
        out["grid"].setdefault(c["road"], {})[c["count"]] = {
            k: c[k] for k in ("final","cagr_pct","max_dd_pct","costs","orders",
                              "spy_final","placebo_beaten","placebo_median","placebo_finals")}
        out["grid"][c["road"]][c["count"]]["halts"] = len(c["halts"])
        if c["count"] in ("3", "5"):
            out["curves"].setdefault(c["road"], {})[c["count"]] = c["equity_curve"]
            out["period_distributions"].setdefault(c["road"], {})[c["count"]] = period_dist(c["equity_curve"])
cdir = os.path.join(HERE, "confirmation")
for fn in sorted(os.listdir(cdir)):
    if fn.endswith(".json") and "count" in fn:
        c = json.load(open(os.path.join(cdir, fn)))
        out["confirmation"].setdefault(c["road"], {})[c["count"]] = {
            k: c[k] for k in ("final","cagr_pct","max_dd_pct","costs","orders","spy_final","placebo_beaten","placebo_median")}
json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
for road, d in out["period_distributions"].items():
    for cnt, pd_ in d.items():
        print(road, "count", cnt, pd_)
print("grid LONG ALL:", out["grid"]["LONG"].get("ALL"))
