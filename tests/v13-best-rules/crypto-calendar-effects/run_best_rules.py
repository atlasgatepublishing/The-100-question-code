#!/usr/bin/env python3
"""crypto-calendar-effects V13 BEST RULES — Calendar-Timed Trend Hold, BTC only.
Spec frozen in BEST-RULES-SPEC.md before this run. Shared data read-only.

System: weekly decision at decision-day close; LONG if close > trailing
200d MA of closes (point-in-time), else CASH. Gate flips execute at the
next bar's open. Native decision day = Sunday (executes Monday open).
Placebos: 20 seeds phase-shifting the decision day to a non-Sunday weekday.
Costs 0.60%/side on actual trades only. No floor. $100 pots."""
import json, os, random, statistics
from datetime import date

DATA = os.path.expanduser("~/workspace/stock-app/backtests/v4/crypto-basket-pit-data/y_BTC-USD.json")
OUT = os.path.dirname(os.path.abspath(__file__))
COST = 0.006
POT = 100.0
END = "2026-11-20"
MA_N = 200
WINDOWS = {"FULL": (None, END), "DESIGN": ("2017-01-01", "2022-12-31"),
           "VALIDATION": ("2023-01-01", END)}

def wd(ds):
    y, m, d = map(int, ds.split("-"))
    return date(y, m, d).weekday()  # Mon=0 .. Sun=6

def max_dd(vals):
    peak, dd = -1.0, 0.0
    for v in vals:
        peak = max(peak, v)
        if peak > 0: dd = min(dd, v / peak - 1)
    return dd

def period_stats(curve):
    """Weekly tempo: sample the daily curve at each Sunday close (+ first/last)."""
    pts = [curve[0]]
    for d, v in curve[1:-1]:
        if wd(d) == 6: pts.append((d, v))
    if curve[-1] != pts[-1]: pts.append(curve[-1])
    vals = [v for _, v in pts]
    rets = [vals[i] / vals[i-1] - 1 for i in range(1, len(vals)) if vals[i-1] > 0]
    if not rets: return None
    wins = sum(1 for r in rets if r > 0)
    streak = longest = 0
    for r in rets:
        streak = streak + 1 if r <= 0 else 0
        longest = max(longest, streak)
    peak = vals[0]; since = 0; gap = 0
    for v in vals[1:]:
        if v > peak: peak = v; since = 0
        else: since += 1; gap = max(gap, since)
    return {"periods": len(rets), "pct_periods_profitable": round(wins / len(rets) * 100, 1),
            "median_period_pct": round(statistics.median(rets) * 100, 3),
            "mean_period_pct_secondary": round(statistics.mean(rets) * 100, 3),
            "best_period_pct": round(max(rets) * 100, 2), "worst_period_pct": round(min(rets) * 100, 2),
            "longest_losing_streak_periods": longest,
            "longest_stretch_between_new_highs_periods": gap}

def simulate(bars, closes_all, idx0, decision_wd):
    """bars: window bars; closes_all: full-series closes (for MA warm-up);
    idx0: global index of bars[0]. Returns final, daily curve, trades, costs."""
    cash = POT; shares = 0.0; trades = 0; cost_paid = 0.0
    pending = None  # target state decided at a close, executed next open: True=long
    curve = []
    for k, b in enumerate(bars):
        gi = idx0 + k
        # execute pending flip at this bar's open
        if pending is not None:
            if pending and shares == 0.0:
                c = cash * COST; cost_paid += c; cash -= c
                shares = cash / b["o"]; cash = 0.0; trades += 1
            elif not pending and shares > 0.0:
                cash = shares * b["o"]; shares = 0.0
                c = cash * COST; cost_paid += c; cash -= c; trades += 1
            pending = None
        curve.append((b["d"], cash + shares * b["c"]))
        # decision at this bar's close
        if wd(b["d"]) == decision_wd and gi >= MA_N - 1:
            ma = sum(closes_all[gi - MA_N + 1: gi + 1]) / MA_N
            want_long = b["c"] > ma
            is_long = shares > 0.0
            if want_long != is_long:
                pending = want_long
    final = cash + shares * bars[-1]["c"]
    return final, curve, trades, round(cost_paid, 2)

def buyhold(bars):
    eq = POT * (1 - COST) * (bars[-1]["c"] / bars[0]["o"]) * (1 - COST)
    curve = [(b["d"], POT * (1 - COST) * (b["c"] / bars[0]["o"])) for b in bars]
    return eq, curve

def main():
    bars_all = json.load(open(DATA))
    bars_all = [b for b in bars_all if b.get("c") and b.get("o") and b["c"] > 0 and b["o"] > 0]
    bars_all.sort(key=lambda b: b["d"])
    closes_all = [b["c"] for b in bars_all]
    index_of = {b["d"]: i for i, b in enumerate(bars_all)}
    results = {"family": "crypto-calendar-effects", "program": "v13-best-rules",
               "system": "Calendar-Timed Trend Hold (BTC only, Sunday decision / Monday-open execution, 200d MA binary gate, no vol scaler, no floor)",
               "cost_per_side": COST, "pot": POT, "coin": "BTC", "windows": {}}
    for wname, (lo, hi) in WINDOWS.items():
        wb = [b for b in bars_all if b["d"] <= hi and (lo is None or b["d"] >= lo)]
        idx0 = index_of[wb[0]["d"]]
        bh_fin, bh_curve = buyhold(wb)
        fin, curve, trades, cp = simulate(wb, closes_all, idx0, 6)
        w = {"bars": len(wb), "first": wb[0]["d"], "last": wb[-1]["d"],
             "system_final": round(fin, 2), "system_trades": trades, "system_costs_paid": cp,
             "system_maxdd_pct": round(max_dd([v for _, v in curve]) * 100, 1),
             "btc_buyhold_final": round(bh_fin, 2),
             "btc_buyhold_maxdd_pct": round(max_dd([v for _, v in bh_curve]) * 100, 1),
             "period_stats_weekly": period_stats(curve),
             "buyhold_period_stats_weekly": period_stats(bh_curve),
             "curve": [[d, round(v, 2)] for d, v in curve],
             "buyhold_curve": [[d, round(v, 2)] for d, v in bh_curve]}
        if wname in ("FULL", "VALIDATION"):
            finals = []
            for seed in range(20):
                rng = random.Random(2000 + seed)
                dw = rng.choice([0, 1, 2, 3, 4, 5])  # phase-shifted decision weekday
                pf, _, _, _ = simulate(wb, closes_all, idx0, dw)
                finals.append(pf)
            pct = sum(1 for f in finals if f < fin) / len(finals) * 100
            w["placebo_phase_shifted_decision_day"] = {
                "seeds": 20, "median": round(statistics.median(finals), 2),
                "min": round(min(finals), 2), "max": round(max(finals), 2),
                "system_percentile": round(pct, 1),
                "finals": [round(f, 2) for f in finals]}
        results["windows"][wname] = w
        print(wname, "system $", round(fin, 2), "trades", trades, "costs $", cp,
              "maxDD%", w["system_maxdd_pct"], "| BTC BH $", round(bh_fin, 2),
              "maxDD%", w["btc_buyhold_maxdd_pct"],
              "| placebo:", w.get("placebo_phase_shifted_decision_day", {}).get("median"),
              w.get("placebo_phase_shifted_decision_day", {}).get("system_percentile"))
    with open(os.path.join(OUT, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("wrote results.json")

if __name__ == "__main__":
    main()
