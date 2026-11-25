#!/usr/bin/env python3
"""V13 BEST RULES — RSI(2) mean reversion (Connors), Muse's rules.
Frozen spec: BEST-RULES-SPEC.md in this folder. Simulation only.

Rules implemented (no others):
- Universe: SPY, QQQ, DIA, IWM. One slot per ETF; slot = 25% of pot equity at entry.
- Entry (per ETF): close > own SMA200 AND Wilder RSI(2) < 5 -> buy at that close,
  tranche 1 = 60% of slot budget.
- Scale-in (once): first later day position open, close < tranche-1 price AND
  RSI(2) < 10 -> buy tranche 2 = 40% of slot budget (placebo: price condition only).
- Exit: first close by which BOTH a close > SMA5 and an RSI(2) > 65 have occurred
  since entry; OR time stop at close of 7th trading day after entry.
- No price stop, no pot floor. Costs 0.10%/side + $0.01 per sell order.
Data: SPY from shared read-only pxfull cache; QQQ/DIA/IWM fetched from Yahoo into
this folder's data/ with the identical dividend-adjusted construction."""
import json, os, time, random, statistics

HERE = os.path.dirname(os.path.abspath(__file__))
SPY_PX = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
SYMS = ["SPY", "QQQ", "DIA", "IWM"]
COST = 0.001; SELL_FEE = 0.01; START = 100.0
TIME_STOP = 7

def load_bars(path):
    j = json.load(open(path))
    r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    bars = {}
    for i, t in enumerate(ts):
        if q["close"][i] is None or adj[i] is None: continue
        ratio = adj[i] / q["close"][i]
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        bars[d] = {"open": q["open"][i] * ratio, "close": adj[i]}
    return bars

def indicators(closes):
    n = len(closes)
    sma200 = [None]*n; sma5 = [None]*n; rsi2 = [None]*n
    gains = [0.0]; losses = [0.0]
    for i in range(1, n):
        d = closes[i]-closes[i-1]; gains.append(max(d, 0.0)); losses.append(max(-d, 0.0))
    ag = al = None
    for i in range(n):
        if i >= 199: sma200[i] = sum(closes[i-199:i+1])/200
        if i >= 4: sma5[i] = sum(closes[i-4:i+1])/5
        if i == 2:
            ag = sum(gains[1:3])/2; al = sum(losses[1:3])/2
        elif i > 2:
            ag = (ag*1 + gains[i])/2; al = (al*1 + losses[i])/2
        if i >= 2 and ag is not None:
            rsi2[i] = 100.0 if al == 0 else 100 - 100/(1 + ag/al)
    return sma200, sma5, rsi2

def build_market():
    market = {}
    paths = {"SPY": SPY_PX}
    for s in SYMS[1:]:
        paths[s] = os.path.join(HERE, "data", f"pxfull_{s}.json")
    for s in SYMS:
        bars = load_bars(paths[s])
        dates = sorted(bars)
        closes = [bars[d]["close"] for d in dates]
        sma200, sma5, rsi2 = indicators(closes)
        market[s] = {"dates": dates, "idx": {d: i for i, d in enumerate(dates)},
                     "close": closes, "sma200": sma200, "sma5": sma5, "rsi2": rsi2}
    return market

def run(market, dates, picks=None):
    """dates: master road date list. picks: None = real signals; else dict sym->set(dates) placebo."""
    cash = START; costs = 0.0; orders = 0
    pos = {}          # sym -> position dict
    closed = []       # closed trade records, in exit order
    curve = []; days_in = 0
    entries_per_sym = {s: 0 for s in SYMS}

    def equity(date):
        eq = cash
        for s, p in pos.items():
            eq += p["shares"] * market[s]["close"][market[s]["idx"][date]]
        return eq

    for date in dates:
        # ---- exits & scale-ins for positions opened on earlier days ----
        for s in list(pos.keys()):
            p = pos[s]; m = market[s]; i = m["idx"][date]
            c = m["close"][i]
            p["days"] += 1
            if m["sma5"][i] is not None and c > m["sma5"][i]: p["sma5_ok"] = True
            if m["rsi2"][i] is not None and m["rsi2"][i] > 65: p["rsi_ok"] = True
            exit_reason = None
            if p["sma5_ok"] and p["rsi_ok"]: exit_reason = "both_confirm"
            elif p["days"] >= TIME_STOP: exit_reason = "time_stop"
            if exit_reason:
                gross = p["shares"] * c; fee = gross * COST + SELL_FEE
                proceeds = gross - fee; costs += fee; orders += 1
                pnl = proceeds - p["invested"]
                closed.append({"sym": s, "entry": p["entry_date"], "exit": date,
                               "days": p["days"], "reason": exit_reason,
                               "invested": round(p["invested"], 4), "pnl": round(pnl, 4),
                               "pnl_pct": round(100 * pnl / p["invested"], 3) if p["invested"] else None,
                               "scaled": p["scaled"]})
                cash += proceeds; del pos[s]; continue
            # scale-in
            if not p["scaled"]:
                cond_price = c < p["t1_price"]
                cond_rsi = True if picks is not None else (m["rsi2"][i] is not None and m["rsi2"][i] < 10)
                if cond_price and cond_rsi:
                    amt = min(p["slot_budget"] * 0.40, cash)
                    if amt > 0:
                        fee = amt * COST; sh = (amt - fee) / c; costs += fee; orders += 1
                        p["shares"] += sh; p["invested"] += amt; p["scaled"] = True; cash -= amt
        # ---- entries ----
        eq_now = equity(date)
        slot_budget = 0.25 * eq_now
        for s in SYMS:
            if s in pos: continue
            m = market[s]
            if date not in m["idx"]: continue
            i = m["idx"][date]; c = m["close"][i]
            if picks is None:
                sig = (m["sma200"][i] is not None and m["rsi2"][i] is not None
                       and c > m["sma200"][i] and m["rsi2"][i] < 5)
            else:
                sig = date in picks.get(s, set())
            if sig:
                amt = min(slot_budget * 0.60, cash)
                if amt <= 0: continue
                fee = amt * COST; sh = (amt - fee) / c; costs += fee; orders += 1
                pos[s] = {"shares": sh, "invested": amt, "entry_date": date, "days": 0,
                          "t1_price": c, "slot_budget": slot_budget,
                          "sma5_ok": False, "rsi_ok": False, "scaled": False}
                cash -= amt; entries_per_sym[s] += 1
        if pos: days_in += 1
        curve.append({"date": date, "equity": round(equity(date), 4)})
    # ---- liquidate at final close ----
    if pos:
        date = dates[-1]
        for s in list(pos.keys()):
            p = pos[s]; m = market[s]; c = m["close"][m["idx"][date]]
            gross = p["shares"] * c; fee = gross * COST + SELL_FEE
            proceeds = gross - fee; costs += fee; orders += 1
            pnl = proceeds - p["invested"]
            closed.append({"sym": s, "entry": p["entry_date"], "exit": date,
                           "days": p["days"], "reason": "eod",
                           "invested": round(p["invested"], 4), "pnl": round(pnl, 4),
                           "pnl_pct": round(100 * pnl / p["invested"], 3) if p["invested"] else None,
                           "scaled": p["scaled"]})
            cash += proceeds; del pos[s]
        curve[-1]["equity"] = round(cash, 4)
    final = round(cash, 2)
    peak = -1.0; mdd = 0.0; last_high = 0; longest_dry = 0
    for k, pt in enumerate(curve):
        if pt["equity"] > peak: peak = pt["equity"]; last_high = k
        if peak > 0: mdd = max(mdd, (peak - pt["equity"]) / peak)
        longest_dry = max(longest_dry, k - last_high)
    wins = [t for t in closed if t["pnl"] > 0]; losses = [t for t in closed if t["pnl"] <= 0]
    streak = longest_loss = 0
    for t in closed:
        if t["pnl"] <= 0: streak += 1; longest_loss = max(longest_loss, streak)
        else: streak = 0
    yrs = len(dates) / 252.0
    return {"final": final,
            "cagr_pct": round(((cash / START) ** (1 / yrs) - 1) * 100, 2) if yrs else None,
            "max_dd_pct": round(mdd * 100, 2), "costs": round(costs, 2), "orders": orders,
            "closed_trades": len(closed),
            "win_rate_pct": round(100 * len(wins) / len(closed), 1) if closed else None,
            "avg_win": round(statistics.mean([t["pnl"] for t in wins]), 2) if wins else None,
            "avg_loss": round(statistics.mean([t["pnl"] for t in losses]), 2) if losses else None,
            "avg_win_pct": round(statistics.mean([t["pnl_pct"] for t in wins]), 2) if wins else None,
            "avg_loss_pct": round(statistics.mean([t["pnl_pct"] for t in losses]), 2) if losses else None,
            "expectancy_per_trade": round(statistics.mean([t["pnl"] for t in closed]), 2) if closed else None,
            "time_in_market_pct": round(100 * days_in / len(dates), 1) if dates else None,
            "longest_losing_streak_trades": longest_loss,
            "longest_stretch_between_highs_days": longest_dry,
            "entries_per_sym": entries_per_sym,
            "exit_reasons": {r: sum(1 for t in closed if t["reason"] == r) for r in ("both_confirm", "time_stop", "eod")},
            "scaled_trades": sum(1 for t in closed if t["scaled"]),
            "equity_curve": curve, "trades": closed}

def buyhold_spy(market, dates):
    m = market["SPY"]; c0 = m["close"][m["idx"][dates[0]]]
    sh = (START * (1 - COST)) / c0
    gross = sh * m["close"][m["idx"][dates[-1]]]
    return round(gross - gross * COST - SELL_FEE, 2)

def main():
    market = build_market()
    spy_dates = market["SPY"]["dates"]
    roads = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
             "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
    out = {"family": "rsi2-mean-reversion", "program": "v13-best-rules",
           "form": "4-ETF basket (SPY/QQQ/DIA/IWM), 25% slots, RSI(2)<5 entry at close, 60/40 scale-in, exit on both SMA5-cross & RSI(2)>65, 7-day time stop, no floor",
           "roads": {}}
    for name, (s, e) in roads.items():
        dates = [d for d in spy_dates if s <= d <= e]
        r = run(market, dates)
        r["spy_buyhold"] = buyhold_spy(market, dates)
        twins = []
        for seed in range(20):
            rng = random.Random(31000 + seed)
            picks = {}
            for sym in SYMS:
                m = market[sym]
                elig = [d for d in dates if d in m["idx"] and m["sma200"][m["idx"][d]] is not None
                        and m["close"][m["idx"][d]] > m["sma200"][m["idx"][d]]]
                n = r["entries_per_sym"][sym]
                picks[sym] = set(rng.sample(elig, min(n, len(elig)))) if n else set()
            twins.append(run(market, dates, picks=picks)["final"])
        r["placebo_finals"] = twins
        r["placebos_beaten"] = sum(1 for t in twins if r["final"] > t)
        r["placebo_best"] = max(twins) if twins else None
        r["placebo_median"] = statistics.median(twins) if twins else None
        out["roads"][name] = r
        print(name, r["final"], "BH", r["spy_buyhold"], "trades", r["closed_trades"], "WR", r["win_rate_pct"],
              "avgW", r["avg_win"], "avgL", r["avg_loss"], "exp", r["expectancy_per_trade"],
              "DD", r["max_dd_pct"], "costs", r["costs"], "TiM", r["time_in_market_pct"],
              "placebo", r["placebos_beaten"], "/20", "exits", r["exit_reasons"], "scaled", r["scaled_trades"])
    folds = {}
    for y in range(2017, 2027):
        s = f"{y}-01-01"; e = f"{y}-12-31" if y < 2026 else "2026-11-20"
        dates = [d for d in spy_dates if s <= d <= e]
        folds[str(y)] = run(market, dates)["final"]
    out["year_folds"] = folds
    vals = list(folds.values())
    out["fold_distribution"] = {"median": round(statistics.median(vals), 2),
                                "share_positive_pct": round(100 * sum(1 for v in vals if v > 100) / len(vals), 1),
                                "best": max(vals), "worst": min(vals),
                                "mean_secondary": round(statistics.mean(vals), 2)}
    print("folds", folds); print("fold dist", out["fold_distribution"])
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)

if __name__ == "__main__":
    main()
