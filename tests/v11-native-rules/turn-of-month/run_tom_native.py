#!/usr/bin/env python3
"""Turn-of-Month NATIVE form (v11): Lakonishok-Smidt window days -1,+1,+2,+3.
Buy SPY at close of 2nd-last trading day of month, sell at close of 3rd trading
day of next month. No stop/floor (none published). See NATIVE-SPEC.md."""
import json, os, time

HERE = os.path.dirname(os.path.abspath(__file__))
PX = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
COST = 0.001; SELL_FEE = 0.01; START = 100.0

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
    """Return set of (buy_idx, sell_idx) earning days -1,+1,+2,+3 (shifted by `shift` trading days)."""
    pairs = []
    months = {}
    for i, b in enumerate(bars): months.setdefault(b["date"][:7], []).append(i)
    keys = sorted(months)
    for k_i in range(len(keys)-1):
        days = months[keys[k_i]]; ndays = months[keys[k_i+1]]
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
            fee = cash*COST; shares = (cash-fee)/c; costs += fee; cash = 0.0; orders += 1
        if i in sell_at and shares > 0:
            gross = shares*c; fee = gross*COST + SELL_FEE; cash = gross-fee; costs += fee; shares = 0.0; orders += 1
        curve.append({"date": bars[i]["date"], "equity": round(cash + shares*c, 4)})
    if shares > 0:
        c = bars[idx[-1]]["close"]; gross = shares*c; fee = gross*COST + SELL_FEE; cash = gross-fee; costs += fee; orders += 1
        curve[-1]["equity"] = round(cash, 4)
    peak = -1; mdd = 0.0
    for pt in curve:
        peak = max(peak, pt["equity"]); mdd = max(mdd, (peak-pt["equity"])/peak if peak > 0 else 0)
    yrs = (idx[-1]-idx[0])/252.0 if len(idx) > 1 else 0
    return {"final": round(cash, 2), "cagr_pct": round(((cash/START)**(1/yrs)-1)*100, 2) if yrs and cash > 0 else None,
            "max_dd_pct": round(mdd*100, 2), "costs": round(costs, 2), "orders": orders,
            "round_trips": len(pairs), "equity_curve": curve}

def buyhold(bars, start, end):
    idx = [i for i, b in enumerate(bars) if start <= b["date"] <= end]
    sh = (START*(1-COST))/bars[idx[0]]["close"]; gross = sh*bars[idx[-1]]["close"]
    return round(gross - gross*COST - SELL_FEE, 2)

def main():
    bars = load()
    roads = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
             "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
    out = {"family": "turn-of-month", "form": "native Lakonishok-Smidt window -1..+3, SPY, no stop/floor", "roads": {}}
    for name, (s, e) in roads.items():
        r = run(bars, s, e); twin = run(bars, s, e, shift=10)
        r["spy_buyhold"] = buyhold(bars, s, e); r["shifted_twin_final"] = twin["final"]
        r["beats_twin"] = r["final"] > twin["final"]
        out["roads"][name] = r
    folds = {}
    for y in range(2017, 2027):
        s = f"{y}-01-01"; e = f"{y}-12-31" if y < 2026 else "2026-11-20"
        folds[str(y)] = run(bars, s, e)["final"]
    out["year_folds_decade_era"] = folds
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    for k, v in out["roads"].items():
        print(k, v["final"], "BH", v["spy_buyhold"], "twin", v["shifted_twin_final"], "DD", v["max_dd_pct"], "costs", v["costs"], "orders", v["orders"])
    print("folds", folds)

if __name__ == "__main__":
    main()
