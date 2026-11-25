#!/usr/bin/env python3
"""V13 BEST RULES — Connors Cumulative RSI. Frozen spec: BEST-RULES-SPEC.md. Simulation only.

Rules implemented (no others):
- Universe: SPY, QQQ, DIA, IWM. One slot per ETF; slot = 25% of pot equity at entry, one tranche.
- Entry (per ETF): close > own SMA200 AND CRSI (sum of last 2 days' Wilder RSI(2)) < 35
  -> buy at that close.
- Exit: first close above own SMA5; OR time stop at close of 10th trading day after entry.
- No price stop, no pot floor, no scale-in. Costs 0.10%/side + $0.01 per sell order.
Data: SPY from shared read-only pxfull cache; QQQ/DIA/IWM pxfull copies in this folder's data/
(identical dividend-adjusted construction, fetched by the sibling rsi2 v13 worker)."""
import json, os, time, random, statistics

HERE = os.path.dirname(os.path.abspath(__file__))
SPY_PX = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
SYMS = ["SPY", "QQQ", "DIA", "IWM"]
COST = 0.001; SELL_FEE = 0.01; START = 100.0
TIME_STOP = 10
ENTRY_THR = 35.0

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
    sma200 = [None]*n; sma5 = [None]*n; rsi2 = [None]*n; crsi = [None]*n
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
        if i >= 3 and rsi2[i] is not None and rsi2[i-1] is not None:
            crsi[i] = rsi2[i] + rsi2[i-1]
    return sma200, sma5, rsi2, crsi

def build_market():
    market = {}
    paths = {"SPY": SPY_PX}
    for s in SYMS[1:]:
        paths[s] = os.path.join(HERE, "data", f"pxfull_{s}.json")
    for s in SYMS:
        bars = load_bars(paths[s])
        dates = sorted(bars)
        closes = [bars[d]["close"] for d in dates]
        sma200, sma5, rsi2, crsi = indicators(closes)
        market[s] = {"dates": dates, "idx": {d: i for i, d in enumerate(dates)},
                     "close": closes, "sma200": sma200, "sma5": sma5, "rsi2": rsi2, "crsi": crsi}
    return market

def run(market, dates, picks=None):
    """picks: None = real CRSI signals; else dict sym->set(dates) placebo entries."""
    cash = START; costs = 0.0; orders = 0
    pos = {}; closed = []; curve = []; days_in = 0
    entries_per_sym = {s: 0 for s in SYMS}

    def equity(date):
        eq = cash
        for s, p in pos.items():
            eq += p["shares"] * market[s]["close"][market[s]["idx"][date]]
        return eq

    for date in dates:
        for s in list(pos.keys()):
            p = pos[s]; m = market[s]; i = m["idx"][date]; c = m["close"][i]
            p["days"] += 1
            reason = None
            if m["sma5"][i] is not None and c > m["sma5"][i]: reason = "sma5_reversion"
            elif p["days"] >= TIME_STOP: reason = "time_stop"
            if reason:
                gross = p["shares"] * c; fee = gross * COST + SELL_FEE
                proceeds = gross - fee; costs += fee; orders += 1
                pnl = proceeds - p["invested"]
                closed.append({"sym": s, "entry": p["entry_date"], "exit": date, "days": p["days"],
                               "reason": reason, "invested": round(p["invested"], 4),
                               "pnl": round(pnl, 4),
                               "pnl_pct": round(100 * pnl / p["invested"], 3) if p["invested"] else None})
                cash += proceeds; del pos[s]
        eq_now = equity(date)
        slot_budget = 0.25 * eq_now
        for s in SYMS:
            if s in pos: continue
            m = market[s]
            if date not in m["idx"]: continue
            i = m["idx"][date]; c = m["close"][i]
            if picks is None:
                sig = (m["sma200"][i] is not None and m["crsi"][i] is not None
                       and c > m["sma200"][i] and m["crsi"][i] < ENTRY_THR)
            else:
                sig = date in picks.get(s, set())
            if sig:
                amt = min(slot_budget, cash)
                if amt <= 0: continue
                fee = amt * COST; sh = (amt - fee) / c; costs += fee; orders += 1
                pos[s] = {"shares": sh, "invested": amt, "entry_date": date, "days": 0}
                cash -= amt; entries_per_sym[s] += 1
        if pos: days_in += 1
        curve.append({"date": date, "equity": round(equity(date), 4)})
    if pos:
        date = dates[-1]
        for s in list(pos.keys()):
            p = pos[s]; m = market[s]; c = m["close"][m["idx"][date]]
            gross = p["shares"] * c; fee = gross * COST + SELL_FEE
            proceeds = gross - fee; costs += fee; orders += 1
            pnl = proceeds - p["invested"]
            closed.append({"sym": s, "entry": p["entry_date"], "exit": date, "days": p["days"],
                           "reason": "eod", "invested": round(p["invested"], 4), "pnl": round(pnl, 4),
                           "pnl_pct": round(100 * pnl / p["invested"], 3) if p["invested"] else None})
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
            "cagr_pct": round(((cash / START) ** (1 / yrs) - 1) * 100, 2) if yrs and cash > 0 else None,
            "max_dd_pct": round(mdd * 100, 2), "costs": round(costs, 2), "orders": orders,
            "closed_trades": len(closed),
            "win_rate_pct": round(100 * len(wins) / len(closed), 1) if closed else None,
            "avg_win": round(statistics.mean([t["pnl"] for t in wins]), 2) if wins else None,
            "avg_loss": round(statistics.mean([t["pnl"] for t in losses]), 2) if losses else None,
            "avg_win_pct": round(statistics.mean([t["pnl_pct"] for t in wins]), 2) if wins else None,
            "avg_loss_pct": round(statistics.mean([t["pnl_pct"] for t in losses]), 2) if losses else None,
            "expectancy_per_trade": round(statistics.mean([t["pnl"] for t in closed]), 2) if closed else None,
            "expectancy_pct": round(statistics.mean([t["pnl_pct"] for t in closed]), 3) if closed else None,
            "time_in_market_pct": round(100 * days_in / len(dates), 1) if dates else None,
            "longest_losing_streak_trades": longest_loss,
            "longest_stretch_between_highs_days": longest_dry,
            "entries_per_sym": entries_per_sym,
            "exit_reasons": {r: sum(1 for t in closed if t["reason"] == r) for r in ("sma5_reversion", "time_stop", "eod")},
            "equity_curve": curve, "trades": closed}

def period_stats(curve):
    months = {}
    for c in curve: months[c["date"][:7]] = c["equity"]
    ks = sorted(months); rets = []; prev = START
    for k in ks:
        rets.append(months[k] / prev - 1 if prev > 0 else 0.0); prev = months[k]
    if not rets: return {}
    pos_n = sum(1 for r in rets if r > 0)
    streak = worst = 0
    for r in rets:
        streak = streak + 1 if r < 0 else 0; worst = max(worst, streak)
    vals = [START] + [months[k] for k in ks]
    peak = vals[0]; since = 0; longest = 0
    for v in vals:
        if v >= peak: peak = v; since = 0
        else: since += 1; longest = max(longest, since)
    return {"tempo": "monthly", "n_periods": len(rets),
            "share_positive_pct": round(100 * pos_n / len(rets), 1),
            "median_pct": round(statistics.median(rets) * 100, 3),
            "best_pct": round(max(rets) * 100, 3), "worst_pct": round(min(rets) * 100, 3),
            "longest_losing_streak": worst, "longest_between_highs_periods": longest,
            "average_pct_secondary": round(statistics.mean(rets) * 100, 3)}

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
    champ = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
    out = {"family": "hunt-connors-cumulative-rsi", "program": "v13-best-rules",
           "form": "4-ETF basket (SPY/QQQ/DIA/IWM), 25% slots one tranche, CRSI<35 entry at close w/ SMA200 filter, exit first close>SMA5 or 10-day time stop, no floor",
           "roads": {}}
    for name, (s, e) in roads.items():
        dates = [d for d in spy_dates if s <= d <= e]
        r = run(market, dates)
        r["spy_buyhold_this_data"] = buyhold_spy(market, dates)
        r["periods_monthly"] = period_stats(r["equity_curve"])
        twins = []
        for seed in range(20):
            rng = random.Random(47000 + seed)
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
        r["placebo_median"] = round(statistics.median(twins), 2) if twins else None
        r["beats_champion"] = r["final"] > champ[name]
        out["roads"][name] = r
        print(name, r["final"], "BH", r["spy_buyhold_this_data"], "trades", r["closed_trades"],
              "WR", r["win_rate_pct"], "avgW", r["avg_win"], "avgL", r["avg_loss"],
              "exp$", r["expectancy_per_trade"], "exp%", r["expectancy_pct"],
              "DD", r["max_dd_pct"], "costs", r["costs"], "TiM", r["time_in_market_pct"],
              "placebo", r["placebos_beaten"], "/20 med", r["placebo_median"],
              "exits", r["exit_reasons"])
    # Confirmation block runs ONLY if a road beat the champion (spec-frozen bars).
    beaten = [n for n in roads if out["roads"][n]["beats_champion"]]
    out["champion_roads_beaten"] = beaten
    if beaten:
        conf = {}
        for y in range(2010, 2017):
            s = f"{y}-01-01"; e = f"{y}-12-31"
            dates = [d for d in spy_dates if s <= d <= e]
            conf[str(y)] = run(market, dates)["final"]
        out["confirmation_year_folds_2010_2016"] = conf
        hw = {}
        for name in beaten:
            s, e = roads[name]
            dates = [d for d in spy_dates if s <= d <= e]
            mid = dates[len(dates)//2]
            hw[name] = {"first_half": run(market, dates[:len(dates)//2 + 1])["final"],
                        "second_half": run(market, [dates[0]] and dates[len(dates)//2:])["final"],
                        "split_date": mid}
        out["confirmation_half_windows"] = hw
        print("CONFIRMATION folds", conf); print("half windows", hw)
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("done")

if __name__ == "__main__":
    main()
