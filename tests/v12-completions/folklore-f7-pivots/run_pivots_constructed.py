#!/usr/bin/env python3
"""F-7 Pivots CONSTRUCTED form (v12). Implements CONSTRUCTION-SPEC.md exactly:
SPY, daily bars, prior-day classic pivots, Person close>P bullish filter,
limit buy at S1, target P, stop S2 (stop-first on ambiguity), flat at close,
no pot floor, program costs. Placebos: same machinery on levels computed
from a wrong prior day (seeded). Simulation only. INTRADAY FENCE applies:
daily bars prove a level was reached, never the order levels were reached."""
import json, os, time, random

HERE = os.path.dirname(os.path.abspath(__file__))
PX = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
COST = 0.001; SELL_FEE = 0.01; START = 100.0

def load():
    j = json.load(open(PX))
    r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i, t in enumerate(ts):
        if q["close"][i] is None or adj[i] is None or q["high"][i] is None or q["low"][i] is None:
            continue
        ratio = adj[i] / q["close"][i]
        bars.append({"date": time.strftime("%Y-%m-%d", time.gmtime(t)),
                     "open": q["open"][i] * ratio, "high": q["high"][i] * ratio,
                     "low": q["low"][i] * ratio, "close": adj[i]})
    return bars

def pivots(b):
    P = (b["high"] + b["low"] + b["close"]) / 3.0
    return P, 2 * P - b["high"], P - (b["high"] - b["low"])  # P, S1, S2

def run(bars, start, end, placebo_seed=None):
    cash = START; costs = 0.0; trades = []; curve = []; wins = 0; closed = 0
    rng = random.Random(9000 + placebo_seed) if placebo_seed is not None else None
    idx = [i for i, b in enumerate(bars) if start <= b["date"] <= end and i >= 25]
    for i in idx:
        b = bars[i]
        if placebo_seed is None:
            src = bars[i - 1]
        else:
            off = rng.randint(2, 21)  # source day in [i-21, i-2], never i-1
            src = bars[i - off]
        P, S1, S2 = pivots(src)
        bullish = src["close"] > P
        exit_reason = None
        if bullish and b["open"] > S2 and b["low"] <= S1:
            entry = S1 if b["open"] > S1 else b["open"]
            fee = cash * COST; shares = (cash - fee) / entry; costs += fee; cash = 0.0
            if b["low"] <= S2:
                exit_px, exit_reason = S2, "stop_S2"
            elif b["high"] >= P:
                exit_px, exit_reason = P, "target_P"
            else:
                exit_px, exit_reason = b["close"], "close"
            gross = shares * exit_px; fee = gross * COST + SELL_FEE; cash = gross - fee; costs += fee
            closed += 1
            if exit_px > entry: wins += 1
            trades.append({"date": b["date"], "entry": round(entry, 4), "exit": round(exit_px, 4),
                           "exit_reason": exit_reason, "P": round(P, 4), "S1": round(S1, 4), "S2": round(S2, 4)})
        curve.append({"date": b["date"], "equity": round(cash, 4)})
    peak = -1; mdd = 0.0
    for pt in curve:
        peak = max(peak, pt["equity"]); mdd = max(mdd, (peak - pt["equity"]) / peak if peak > 0 else 0)
    return {"final": round(cash, 2), "max_dd_pct": round(mdd * 100, 2), "costs": round(costs, 2),
            "closed_trades": closed, "win_rate_pct": round(100 * wins / closed, 1) if closed else None,
            "exit_reasons": {r: sum(1 for t in trades if t["exit_reason"] == r) for r in ("target_P", "stop_S2", "close")},
            "equity_curve": curve, "trades": trades}

def buyhold(bars, start, end):
    idx = [i for i, b in enumerate(bars) if start <= b["date"] <= end]
    c0 = bars[idx[0]]["close"]; sh = (START * (1 - COST)) / c0
    gross = sh * bars[idx[-1]]["close"]; return round(gross - gross * COST - SELL_FEE, 2)

def main():
    bars = load()
    roads = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
             "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
    out = {"family": "folklore-f7-pivots", "form": "CONSTRUCTED v12: SPY daily-bar Person-filter S1 bounce, target P, stop S2, flat nightly, no floor",
           "intraday_fence": "Daily bars prove a level was reached, never the order; ambiguous days resolved stop-first.",
           "roads": {}}
    for name, (s, e) in roads.items():
        r = run(bars, s, e)
        twins = [run(bars, s, e, placebo_seed=seed)["final"] for seed in range(20)]
        r["spy_buyhold"] = buyhold(bars, s, e)
        r["placebo_finals"] = twins
        r["placebos_beaten"] = sum(1 for t in twins if r["final"] > t)
        out["roads"][name] = r
        print(name, r["final"], "BH", r["spy_buyhold"], "trades", r["closed_trades"], "WR", r["win_rate_pct"],
              "DD", r["max_dd_pct"], "costs", r["costs"], "placebo", r["placebos_beaten"], "/20", r["exit_reasons"])
    folds = {}
    for y in range(2010, 2027):
        s = f"{y}-01-01"; e = f"{y}-12-31" if y < 2026 else "2026-11-20"
        folds[str(y)] = run(bars, s, e)["final"]
    out["year_folds"] = folds
    print("folds", folds)
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)

if __name__ == "__main__":
    main()
