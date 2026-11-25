#!/usr/bin/env python3
"""Bollinger Method I NATIVE form (v11): SPY, squeeze = BandWidth 126-session low
within last 5 sessions, buy at close above upper band, exit at close on a tag of
the lower band. No invented stop/floor. See NATIVE-SPEC.md. Simulation only."""
import json, os, time, random, statistics

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
        ratio = adj[i] / q["close"][i]
        bars.append({"date": time.strftime("%Y-%m-%d", time.gmtime(t)),
                     "open": q["open"][i]*ratio, "high": q["high"][i]*ratio,
                     "low": q["low"][i]*ratio, "close": adj[i]})
    return bars

def bands(bars):
    closes = [b["close"] for b in bars]; n = len(bars)
    mid = [None]*n; up = [None]*n; lo = [None]*n; bw = [None]*n; squeeze = [False]*n
    for i in range(19, n):
        w = closes[i-19:i+1]; m = sum(w)/20; sd = statistics.pstdev(w)
        mid[i] = m; up[i] = m+2*sd; lo[i] = m-2*sd; bw[i] = (up[i]-lo[i])/m if m else None
    for i in range(n):
        if bw[i] is None: continue
        for j in range(max(0, i-4), i+1):
            if bw[j] is not None and j >= 125 and bw[j] <= min(x for x in bw[j-125:j+1] if x is not None):
                squeeze[i] = True; break
    return mid, up, lo, bw, squeeze

def run(bars, up, lo, squeeze, start, end, entries=None):
    cash = START; shares = 0.0; costs = 0.0; trades = []; curve = []
    entry_price = None; wins = 0
    idx = [i for i, b in enumerate(bars) if start <= b["date"] <= end]
    for i in idx:
        b = bars[i]; c = b["close"]
        if shares == 0:
            sig = (entries is None and squeeze[i] and up[i] is not None and c > up[i]) or \
                  (entries is not None and i in entries)
            if sig:
                fee = cash*COST; shares = (cash-fee)/c; costs += fee; entry_price = c; cash = 0.0
                trades.append({"date": b["date"], "side": "buy", "price": round(c, 4)})
        else:
            if lo[i] is not None and b["low"] <= lo[i]:
                gross = shares*c; fee = gross*COST + SELL_FEE; cash = gross-fee; costs += fee
                if c > entry_price: wins += 1
                trades.append({"date": b["date"], "side": "sell", "price": round(c, 4)}); shares = 0.0
        curve.append({"date": b["date"], "equity": round(cash + shares*c, 4)})
    if shares > 0:
        c = bars[idx[-1]]["close"]; gross = shares*c; fee = gross*COST + SELL_FEE; cash = gross-fee; costs += fee
        if c > entry_price: wins += 1
        trades.append({"date": bars[idx[-1]]["date"], "side": "sell_eod", "price": round(c, 4)})
        curve[-1]["equity"] = round(cash, 4)
    closed = sum(1 for t in trades if t["side"].startswith("sell"))
    peak = -1; mdd = 0.0
    for pt in curve:
        peak = max(peak, pt["equity"]); mdd = max(mdd, (peak-pt["equity"])/peak if peak > 0 else 0)
    yrs = (idx[-1]-idx[0])/252.0 if len(idx) > 1 else 0
    return {"final": round(cash, 2), "cagr_pct": round(((cash/START)**(1/yrs)-1)*100, 2) if yrs and cash > 0 else None,
            "max_dd_pct": round(mdd*100, 2), "costs": round(costs, 2), "orders": len(trades),
            "closed_trades": closed, "win_rate_pct": round(100*wins/closed, 1) if closed else None,
            "equity_curve": curve, "trades": trades}

def buyhold(bars, start, end):
    idx = [i for i, b in enumerate(bars) if start <= b["date"] <= end]
    sh = (START*(1-COST))/bars[idx[0]]["close"]; gross = sh*bars[idx[-1]]["close"]
    return round(gross - gross*COST - SELL_FEE, 2)

def main():
    bars = load(); mid, up, lo, bw, squeeze = bands(bars)
    roads = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
             "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
    out = {"family": "bollinger-squeeze", "form": "native Bollinger Method I: squeeze (BW 126-low within 5 sessions), buy close>upper band, exit close on lower-band tag, no stop/floor", "roads": {}}
    for name, (s, e) in roads.items():
        r = run(bars, up, lo, squeeze, s, e)
        idx = [i for i, b in enumerate(bars) if s <= b["date"] <= e]
        n = sum(1 for t in r["trades"] if t["side"] == "buy")
        twins = []
        for seed in range(20):
            rng = random.Random(2000+seed)
            picks = set(rng.sample(idx, min(n, len(idx)))) if n else set()
            twins.append(run(bars, up, lo, squeeze, s, e, entries=picks)["final"])
        r["spy_buyhold"] = buyhold(bars, s, e); r["placebo_finals"] = twins
        r["placebos_beaten"] = sum(1 for t in twins if r["final"] > t)
        out["roads"][name] = r
    folds = {}
    for y in range(2017, 2027):
        s = f"{y}-01-01"; e = f"{y}-12-31" if y < 2026 else "2026-11-20"
        folds[str(y)] = run(bars, up, lo, squeeze, s, e)["final"]
    out["year_folds_decade_era"] = folds
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    for k, v in out["roads"].items():
        print(k, v["final"], "BH", v["spy_buyhold"], "trades", v["closed_trades"], "WR", v["win_rate_pct"],
              "DD", v["max_dd_pct"], "costs", v["costs"], "placebo", v["placebos_beaten"], "/20")
    print("folds", folds)

if __name__ == "__main__":
    main()
