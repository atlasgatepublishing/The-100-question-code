#!/usr/bin/env python3
"""V13 BEST RULES — Bollinger Squeeze. See BEST-RULES-SPEC.md (frozen pre-run).

Universe: 14 ETFs (SPY from program pxfull cache; 13 fetched into ./data).
Entry: BandWidth 126-session low within last 10 sessions (squeeze on) AND first
close above upper band (20,2) AND close > own 200-day SMA. Max 4 slots, 25% of
equity each; same-day overflow rationed by 126-session momentum (desc).
Exit (first of): close < 20-day midline; 20-session time stop; intraday low <=
entry*0.92 (disaster stop, exit at close). Costs 0.10%/side + $0.01/sell.
Placebos: 20 seeds/road, per-ETF random entries on trend-eligible days
(close > 200 SMA), count-matched, same slots/exits/costs.
Simulation only."""
import json, os, time, random, statistics

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
SPY_PX = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
TICKERS = ["SPY", "QQQ", "DIA", "IWM", "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLB", "XLU", "EEM"]
COST = 0.001; SELL_FEE = 0.01; START = 100.0
MAX_SLOTS = 4; SLOT_FRAC = 0.25; TIME_STOP = 20; DISASTER = 0.92

def load(t):
    path = SPY_PX if t == "SPY" else os.path.join(DATA, f"pxfull_{t}.json")
    j = json.load(open(path))
    r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i, tt in enumerate(ts):
        if q["close"][i] is None or adj[i] is None: continue
        ratio = adj[i] / q["close"][i]
        bars.append({"date": time.strftime("%Y-%m-%d", time.gmtime(tt)),
                     "open": q["open"][i]*ratio, "high": q["high"][i]*ratio,
                     "low": q["low"][i]*ratio, "close": adj[i]})
    return bars

def indicators(bars):
    n = len(bars); closes = [b["close"] for b in bars]
    mid = [None]*n; up = [None]*n; bw = [None]*n; sma200 = [None]*n; mom126 = [None]*n; squeeze = [False]*n
    for i in range(19, n):
        w = closes[i-19:i+1]; m = sum(w)/20; sd = statistics.pstdev(w)
        mid[i] = m; up[i] = m + 2*sd; bw[i] = (4*sd)/m if m else None
    for i in range(199, n):
        sma200[i] = sum(closes[i-199:i+1])/200
    for i in range(126, n):
        mom126[i] = closes[i]/closes[i-126] - 1 if closes[i-126] else None
    for i in range(n):
        if bw[i] is None: continue
        for j in range(max(0, i-9), i+1):
            if bw[j] is not None and j >= 125 and bw[j] <= min(x for x in bw[j-125:j+1] if x is not None):
                squeeze[i] = True; break
    return {"mid": mid, "up": up, "squeeze": squeeze, "sma200": sma200, "mom126": mom126}

def run(mkt, start, end, entries_map=None, seed=0):
    """mkt: {ticker: (bars, ind, date->idx)}. entries_map None = real signals;
    else {ticker: set(dates)} placebo entries. Returns result dict."""
    dates = sorted({b["date"] for bars, _, _ in mkt.values() for b in bars if start <= b["date"] <= end})
    rng = random.Random(seed)
    cash = START; positions = {}  # ticker -> dict(shares, entry_price, entry_date, held)
    costs = 0.0; trades = []; curve = []
    for d in dates:
        # --- exits first (on today's bars) ---
        for t in list(positions):
            bars, ind, ix = mkt[t]
            if d not in ix: continue
            i = ix[d]; b = bars[i]; p = positions[t]; p["held"] += 1
            reason = None
            if b["low"] <= p["entry_price"] * DISASTER: reason = "disaster_stop"
            elif ind["mid"][i] is not None and b["close"] < ind["mid"][i]: reason = "midline"
            elif p["held"] >= TIME_STOP: reason = "time_stop"
            if reason:
                gross = p["shares"] * b["close"]; fee = gross*COST + SELL_FEE
                cash += gross - fee; costs += fee
                pnl = (gross - fee) - p["cost_basis"]
                trades.append({"ticker": t, "entry_date": p["entry_date"], "exit_date": d,
                               "entry_price": round(p["entry_price"], 4), "exit_price": round(b["close"], 4),
                               "pnl": round(pnl, 2), "pnl_pct": round(100*pnl/p["cost_basis"], 2),
                               "held_sessions": p["held"], "exit_reason": reason})
                del positions[t]
        # --- entries ---
        equity = cash + sum(positions[t]["shares"] * mkt[t][0][mkt[t][2][d]]["close"]
                            for t in positions if d in mkt[t][2])
        cands = []
        for t, (bars, ind, ix) in mkt.items():
            if t in positions or d not in ix: continue
            i = ix[d]
            if entries_map is None:
                if ind["squeeze"][i] and ind["up"][i] is not None and bars[i]["close"] > ind["up"][i] \
                   and ind["sma200"][i] is not None and bars[i]["close"] > ind["sma200"][i]:
                    cands.append(t)
            else:
                if d in entries_map.get(t, ()): cands.append(t)
        if entries_map is None:
            cands.sort(key=lambda t: (mkt[t][1]["mom126"][mkt[t][2][d]] if mkt[t][1]["mom126"][mkt[t][2][d]] is not None else -9), reverse=True)
        else:
            rng.shuffle(cands)
        for t in cands:
            if len(positions) >= MAX_SLOTS: break
            bars, ind, ix = mkt[t]; i = ix[d]; c = bars[i]["close"]
            slot = min(SLOT_FRAC * equity, cash)
            if slot <= 0: break
            fee = slot * COST; shares = (slot - fee) / c; costs += fee; cash -= slot
            positions[t] = {"shares": shares, "entry_price": c, "entry_date": d,
                            "held": 0, "cost_basis": slot}
        equity = cash + sum(positions[t]["shares"] * mkt[t][0][mkt[t][2][d]]["close"]
                            for t in positions if d in mkt[t][2])
        curve.append({"date": d, "equity": round(equity, 4)})
    # liquidate at end
    last = dates[-1]
    for t in list(positions):
        bars, ind, ix = mkt[t]; i = ix[last]; b = bars[i]; p = positions[t]
        gross = p["shares"] * b["close"]; fee = gross*COST + SELL_FEE
        cash += gross - fee; costs += fee
        pnl = (gross - fee) - p["cost_basis"]
        trades.append({"ticker": t, "entry_date": p["entry_date"], "exit_date": last,
                       "entry_price": round(p["entry_price"], 4), "exit_price": round(b["close"], 4),
                       "pnl": round(pnl, 2), "pnl_pct": round(100*pnl/p["cost_basis"], 2),
                       "held_sessions": p["held"], "exit_reason": "end_of_road"})
        del positions[t]
    if curve: curve[-1]["equity"] = round(cash, 4)
    peak = -1; mdd = 0.0; peak_date = None; last_high_date = curve[0]["date"] if curve else None
    longest_no_high = 0; cur_no_high = 0
    for pt in curve:
        if pt["equity"] > peak:
            peak = pt["equity"]; last_high_date = pt["date"]; cur_no_high = 0
        else:
            cur_no_high += 1; longest_no_high = max(longest_no_high, cur_no_high)
        mdd = max(mdd, (peak - pt["equity"]) / peak if peak > 0 else 0)
    wins = [t for t in trades if t["pnl"] > 0]; losses = [t for t in trades if t["pnl"] <= 0]
    streak = 0; max_streak = 0
    for t in trades:
        if t["pnl"] <= 0: streak += 1; max_streak = max(max_streak, streak)
        else: streak = 0
    return {"final": round(cash, 2), "max_dd_pct": round(mdd*100, 2), "costs": round(costs, 2),
            "closed_trades": len(trades),
            "win_rate_pct": round(100*len(wins)/len(trades), 1) if trades else None,
            "avg_win": round(statistics.mean([t["pnl"] for t in wins]), 2) if wins else None,
            "avg_loss": round(statistics.mean([t["pnl"] for t in losses]), 2) if losses else None,
            "avg_win_pct": round(statistics.mean([t["pnl_pct"] for t in wins]), 2) if wins else None,
            "avg_loss_pct": round(statistics.mean([t["pnl_pct"] for t in losses]), 2) if losses else None,
            "expectancy_per_trade": round(statistics.mean([t["pnl"] for t in trades]), 2) if trades else None,
            "longest_losing_streak_trades": max_streak,
            "longest_sessions_between_highs": longest_no_high,
            "trades": trades, "equity_curve": curve}

def buyhold_spy(mkt, start, end):
    bars, ind, ix = mkt["SPY"]
    idx = [i for i, b in enumerate(bars) if start <= b["date"] <= end]
    sh = (START*(1-COST)) / bars[idx[0]]["close"]; gross = sh * bars[idx[-1]]["close"]
    return round(gross - gross*COST - SELL_FEE, 2)

def main():
    mkt = {}
    for t in TICKERS:
        bars = load(t); ind = indicators(bars)
        ix = {b["date"]: i for i, b in enumerate(bars)}
        mkt[t] = (bars, ind, ix)
    roads = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
             "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
    out = {"family": "bollinger-squeeze", "program": "v13-best-rules",
           "form": "14-ETF basket; squeeze = BW 126-low within 10 sessions; entry first close>upper band AND close>200DMA; 4 slots x 25% equity, momentum rationing; exit first of close<20d midline / 20-session time stop / -8% disaster stop at close; no pot floor",
           "roads": {}}
    for name, (s, e) in roads.items():
        r = run(mkt, s, e)
        counts = {}
        for tr in r["trades"]: counts[tr["ticker"]] = counts.get(tr["ticker"], 0) + 1
        twins = []
        for seed in range(20):
            rng = random.Random(13000 + seed)
            emap = {}
            for t, (bars, ind, ix) in mkt.items():
                n = counts.get(t, 0)
                if not n: continue
                elig = [b["date"] for i, b in enumerate(bars)
                        if s <= b["date"] <= e and ind["sma200"][i] is not None and b["close"] > ind["sma200"][i]]
                emap[t] = set(rng.sample(elig, min(n, len(elig))))
            twins.append(run(mkt, s, e, entries_map=emap, seed=seed)["final"])
        r["spy_buyhold"] = buyhold_spy(mkt, s, e)
        r["placebo_finals"] = twins
        r["placebos_beaten"] = sum(1 for x in twins if r["final"] > x)
        r["entries_by_ticker"] = counts
        out["roads"][name] = r
        print(name, r["final"], "BH", r["spy_buyhold"], "trades", r["closed_trades"], "WR", r["win_rate_pct"],
              "DD", r["max_dd_pct"], "costs", r["costs"], "placebo", r["placebos_beaten"], "/20", flush=True)
    folds = {}
    for y in range(2010, 2027):
        s = f"{y}-01-01"; e = f"{y}-12-31" if y < 2026 else "2026-11-20"
        folds[str(y)] = run(mkt, s, e)["final"]
    out["year_folds"] = folds
    pos = [v for v in folds.values() if v > 100]
    out["fold_stats"] = {"median": round(statistics.median(folds.values()), 2),
                         "share_positive_pct": round(100*len(pos)/len(folds), 1),
                         "best": max(folds.values()), "worst": min(folds.values()),
                         "mean_labeled_secondary": round(statistics.mean(folds.values()), 2)}
    print("folds", folds); print("fold_stats", out["fold_stats"])
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)

if __name__ == "__main__":
    main()
