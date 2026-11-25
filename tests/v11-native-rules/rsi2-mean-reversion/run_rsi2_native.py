#!/usr/bin/env python3
"""Connors RSI(2) NATIVE form (v11): SPY, RSI(2)<5, buy AT close, exit at close
when close>SMA5, no stop/no floor. See NATIVE-SPEC.md. Simulation only."""
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
                     "open": q["open"][i] * ratio, "close": adj[i]})
    return bars

def indicators(bars):
    closes = [b["close"] for b in bars]
    sma200 = [None]*len(bars); sma5 = [None]*len(bars); rsi2 = [None]*len(bars)
    gains = [0.0]; losses = [0.0]
    for i in range(1, len(bars)):
        d = closes[i]-closes[i-1]; gains.append(max(d, 0.0)); losses.append(max(-d, 0.0))
    ag = al = None
    for i in range(len(bars)):
        if i >= 199: sma200[i] = sum(closes[i-199:i+1])/200
        if i >= 4: sma5[i] = sum(closes[i-4:i+1])/5
        if i == 2:
            ag = sum(gains[1:3])/2; al = sum(losses[1:3])/2
        elif i > 2:
            ag = (ag*1 + gains[i])/2; al = (al*1 + losses[i])/2
        if i >= 2 and ag is not None:
            rsi2[i] = 100.0 if al == 0 else 100 - 100/(1 + ag/al)
    return sma200, sma5, rsi2

def run(bars, sma200, sma5, rsi2, start, end, entries=None):
    """entries: None = real signals; else a set of bar indexes to enter on (placebo)."""
    cash = START; shares = 0.0; costs = 0.0; trades = []; curve = []
    entry_price = None; wins = 0; entry_count = 0
    idx = [i for i, b in enumerate(bars) if start <= b["date"] <= end]
    for i in idx:
        b = bars[i]; c = b["close"]
        if shares == 0:
            sig = (entries is None and sma200[i] is not None and rsi2[i] is not None
                   and c > sma200[i] and rsi2[i] < 5) or (entries is not None and i in entries)
            if sig:
                amt = cash; fee = amt*COST; shares = (amt-fee)/c; costs += fee
                entry_price = c; entry_count += 1; cash = 0.0
                trades.append({"date": b["date"], "side": "buy", "price": round(c, 4)})
        else:
            if sma5[i] is not None and c > sma5[i]:
                gross = shares*c; fee = gross*COST + SELL_FEE; cash = gross-fee; costs += fee
                if c > entry_price: wins += 1
                trades.append({"date": b["date"], "side": "sell", "price": round(c, 4)})
                shares = 0.0
        curve.append({"date": b["date"], "equity": round(cash + shares*c, 4)})
    if shares > 0:
        c = bars[idx[-1]]["close"]; gross = shares*c; fee = gross*COST + SELL_FEE
        cash = gross-fee; costs += fee
        if c > entry_price: wins += 1
        trades.append({"date": bars[idx[-1]]["date"], "side": "sell_eod", "price": round(c, 4)})
        curve[-1]["equity"] = round(cash, 4)
    closed = sum(1 for t in trades if t["side"].startswith("sell"))
    peak = -1; mdd = 0.0
    for pt in curve:
        peak = max(peak, pt["equity"]); mdd = max(mdd, (peak-pt["equity"])/peak if peak > 0 else 0)
    yrs = (idx[-1]-idx[0])/252.0 if len(idx) > 1 else 0
    return {"final": round(cash, 2), "cagr_pct": round(((cash/START)**(1/yrs)-1)*100, 2) if yrs else None,
            "max_dd_pct": round(mdd*100, 2), "costs": round(costs, 2), "orders": len(trades),
            "closed_trades": closed, "win_rate_pct": round(100*wins/closed, 1) if closed else None,
            "equity_curve": curve, "trades": trades}

def buyhold(bars, start, end):
    idx = [i for i, b in enumerate(bars) if start <= b["date"] <= end]
    c0 = bars[idx[0]]["close"]; sh = (START*(1-COST))/c0
    gross = sh*bars[idx[-1]]["close"]; return round(gross - gross*COST - SELL_FEE, 2)

def main():
    bars = load(); sma200, sma5, rsi2 = indicators(bars)
    date2idx = {b["date"]: i for i, b in enumerate(bars)}
    roads = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
             "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
    out = {"family": "rsi2-mean-reversion", "form": "native Connors SPY RSI(2)<5 buy-at-close, exit close>SMA5, no stop/floor", "roads": {}}
    for name, (s, e) in roads.items():
        r = run(bars, sma200, sma5, rsi2, s, e)
        # placebo twins: same number of entries, random days inside window where trend filter holds
        idx = [i for i, b in enumerate(bars) if s <= b["date"] <= e]
        n = sum(1 for t in r["trades"] if t["side"] == "buy")
        elig = [i for i in idx if sma200[i] is not None and bars[i]["close"] > sma200[i]]
        twins = []
        for seed in range(20):
            rng = random.Random(1000+seed)
            picks = set(rng.sample(elig, min(n, len(elig)))) if n else set()
            twins.append(run(bars, sma200, sma5, rsi2, s, e, entries=picks)["final"])
        r["spy_buyhold"] = buyhold(bars, s, e)
        r["placebo_finals"] = twins
        r["placebos_beaten"] = sum(1 for t in twins if r["final"] > t)
        out["roads"][name] = r
    # year folds on decade
    folds = {}
    for y in range(2017, 2027):
        s = f"{y}-01-01"; e = f"{y}-12-31" if y < 2026 else "2026-11-20"
        folds[str(y)] = run(bars, sma200, sma5, rsi2, s, e)["final"]
    out["year_folds_decade_era"] = folds
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    for k, v in out["roads"].items():
        print(k, v["final"], "BH", v["spy_buyhold"], "trades", v["closed_trades"], "WR", v["win_rate_pct"],
              "DD", v["max_dd_pct"], "costs", v["costs"], "placebo", v["placebos_beaten"], "/20")
    print("folds", folds)

if __name__ == "__main__":
    main()
