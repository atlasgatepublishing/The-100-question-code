#!/usr/bin/env python3
"""Turn-of-Month V13 BEST RULES run. Spec frozen in BEST-RULES-SPEC.md before this ran.

Rules: published Lakonishok-Smidt window days -1,+1,+2,+3 on SPY, whole $100 pot,
cash (0%) otherwise, NO floor/halt/restart. Buy at close of 2nd-last trading day of
month, sell at close of 3rd trading day of next month. Costs 0.10%/side + $0.01/sell.
Placebos: identical schedule phase-shifted by +5..+14 and -5..-14 trading days (20).
Data: shared read-only pxfull_SPY.json (dividend-adjusted, 2008->2026)."""
import json, os, time, statistics

HERE = os.path.dirname(os.path.abspath(__file__))
PX = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
COST = 0.001; SELL_FEE = 0.01; START = 100.0
SHIFTS = list(range(5, 15)) + list(range(-14, -4))  # 20 phase shifts, frozen in spec

def load():
    j = json.load(open(PX))
    r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i, t in enumerate(ts):
        if q["close"][i] is None or adj[i] is None: continue
        bars.append({"date": time.strftime("%Y-%m-%d", time.gmtime(t)), "close": adj[i]})
    return bars

def schedule(bars, shift=0):
    pairs = []
    months = {}
    for i, b in enumerate(bars): months.setdefault(b["date"][:7], []).append(i)
    keys = sorted(months)
    for k_i in range(len(keys) - 1):
        days = months[keys[k_i]]; ndays = months[keys[k_i + 1]]
        if len(ndays) < 3: continue
        buy = days[-2] + shift; sell = ndays[2] + shift
        if 0 <= buy < sell < len(bars): pairs.append((buy, sell))
    return pairs

def run(bars, start, end, shift=0):
    pairs = [(b, s) for b, s in schedule(bars, shift) if start <= bars[b]["date"] and bars[s]["date"] <= end]
    cash = START; shares = 0.0; costs = 0.0; orders = 0; curve = []
    buy_at = {b: s for b, s in pairs}; sell_at = {s for b, s in pairs}
    idx = [i for i, b in enumerate(bars) if start <= b["date"] <= end]
    for i in idx:
        c = bars[i]["close"]
        if i in buy_at and shares == 0:
            fee = cash * COST; shares = (cash - fee) / c; costs += fee; cash = 0.0; orders += 1
        if i in sell_at and shares > 0:
            gross = shares * c; fee = gross * COST + SELL_FEE; cash = gross - fee; costs += fee; shares = 0.0; orders += 1
        curve.append({"date": bars[i]["date"], "equity": round(cash + shares * c, 4)})
    if shares > 0:
        c = bars[idx[-1]]["close"]; gross = shares * c; fee = gross * COST + SELL_FEE
        cash = gross - fee; costs += fee; orders += 1; curve[-1]["equity"] = round(cash, 4)
    peak = -1; mdd = 0.0
    for pt in curve:
        peak = max(peak, pt["equity"]); mdd = max(mdd, (peak - pt["equity"]) / peak if peak > 0 else 0)
    yrs = (idx[-1] - idx[0]) / 252.0 if len(idx) > 1 else 0
    return {"final": round(cash, 2),
            "cagr_pct": round(((cash / START) ** (1 / yrs) - 1) * 100, 2) if yrs and cash > 0 else None,
            "max_dd_pct": round(mdd * 100, 2), "costs": round(costs, 2), "orders": orders,
            "round_trips": len(pairs), "equity_curve": curve}

def buyhold(bars, start, end):
    idx = [i for i, b in enumerate(bars) if start <= b["date"] <= end]
    sh = (START * (1 - COST)) / bars[idx[0]]["close"]; gross = sh * bars[idx[-1]]["close"]
    return round(gross - gross * COST - SELL_FEE, 2)

def monthly_dist(curve):
    """Period = calendar month. Monthly return from last equity of each month vs prior month-end."""
    month_end = {}
    for pt in curve: month_end[pt["date"][:7]] = pt["equity"]
    keys = sorted(month_end)
    rets = []
    prev = START
    for k in keys:
        rets.append(month_end[k] / prev - 1.0); prev = month_end[k]
    if not rets: return {}
    pos = sum(1 for r in rets if r > 0)
    # longest losing streak
    streak = longest = 0
    for r in rets:
        streak = streak + 1 if r < 0 else 0; longest = max(longest, streak)
    # longest stretch between new highs (months since last month-end new high)
    peak = START; since = worst_gap = 0
    for k in keys:
        if month_end[k] > peak: peak = month_end[k]; since = 0
        else: since += 1; worst_gap = max(worst_gap, since)
    return {"periods": len(rets), "median_pct": round(statistics.median(rets) * 100, 2),
            "share_positive_pct": round(pos / len(rets) * 100, 1),
            "best_pct": round(max(rets) * 100, 2), "worst_pct": round(min(rets) * 100, 2),
            "longest_losing_streak_months": longest,
            "longest_between_highs_months": worst_gap,
            "mean_pct_secondary": round(statistics.mean(rets) * 100, 2)}

def main():
    bars = load()
    roads = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
             "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
    champ = {"LONG": 1415.62, "CONT": 544.47, "VAL": 288.05, "DECADE": 667.35}
    spy_ref = {"LONG": 822.94, "CONT": 313.62, "VAL": 187.77, "DECADE": 367.80}
    out = {"family": "turn-of-month", "program": "v13-best-rules",
           "form": "published window -1..+3, SPY whole pot, cash 0% otherwise, no floor (BEST-RULES-SPEC.md)",
           "placebo_shifts": SHIFTS, "roads": {}}
    for name, (s, e) in roads.items():
        r = run(bars, s, e)
        r["spy_buyhold"] = buyhold(bars, s, e)
        r["champion_vm"] = champ[name]; r["spy_reference"] = spy_ref[name]
        r["beats_champion"] = r["final"] > champ[name]
        r["monthly_distribution"] = monthly_dist(r["equity_curve"])
        pls = []
        for sh in SHIFTS:
            p = run(bars, s, e, shift=sh)
            pls.append({"shift": sh, "final": p["final"], "max_dd_pct": p["max_dd_pct"], "costs": p["costs"]})
        finals = sorted(p["final"] for p in pls)
        r["placebos"] = {"detail": pls, "beaten": sum(1 for f in finals if r["final"] > f),
                         "of": len(finals), "median_final": round(statistics.median(finals), 2),
                         "best_final": finals[-1], "worst_final": finals[0]}
        out["roads"][name] = r
        print(name, "final", r["final"], "DD", r["max_dd_pct"], "costs", r["costs"], "orders", r["orders"],
              "BH", r["spy_buyhold"], "placebos beaten", r["placebos"]["beaten"], "/20",
              "plac median", r["placebos"]["median_final"], "best", r["placebos"]["best_final"])
    out["confirmation_triggered"] = any(v["beats_champion"] for v in out["roads"].values())
    print("confirmation triggered:", out["confirmation_triggered"])
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)

if __name__ == "__main__":
    main()
