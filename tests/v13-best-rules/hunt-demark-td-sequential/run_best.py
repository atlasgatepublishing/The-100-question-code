#!/usr/bin/env python3
"""V13 BEST RULES — DeMark TD Sequential, Muse's rules. Frozen spec:
BEST-RULES-SPEC.md in this folder. Simulation only.

Rules implemented (no others):
- Signal: completed BUY SETUP only — 9 consecutive closes each < close 4 bars
  earlier, computed bar-by-bar (point-in-time). Countdown/Intersection/
  Perfection/bar-13 qualifier/recycling/TDST: CUT.
- Guard: entry close > own 200-day SMA.
- Entry at the setup-9 close. Pond chassis: 30 large caps, max 5 concurrent,
  20% of equity per slot, same-day ties alphabetical, one position per name.
  SPY chassis: all-in single position.
- Exits (priority): (1) intraday low < setup-span low -> fill at span low;
  (2) first close after >=1 day held with close > close 4 bars earlier (flip);
  (3) time stop at close of 10th trading day after entry.
- No pot floor. Costs 0.10%/side + $0.01 per sell order. $100 pots.
Data: Yahoo dividend-adjusted OHLC (O/H/L scaled by adjclose/close), cached
in this folder's data/. Placebos: 20 seeds, random guard-passing entry days,
entry-count matched, same sizing/exits (stop anchored on entry bar's low)."""
import json, os, time, random, statistics

HERE = os.path.dirname(os.path.abspath(__file__))
POND = ["AAPL","MSFT","AMZN","GOOGL","META","BRK-B","JPM","XOM","JNJ","PG","V","WMT","HD","BAC","CVX","PFE","VZ","T","DIS","NFLX","INTC","CSCO","GE","IBM","MMM","UNH","MA","KO","PEP","WFC"]
ROADS = {"LONG": ("2010-01-04","2026-11-20"), "DECADE": ("2016-11-21","2026-11-20"),
         "CONT": ("2019-01-02","2026-11-20"), "VAL": ("2023-01-03","2026-11-20")}
COST = 0.001; SELL_FEE = 0.01; START = 100.0; MAXPOS = 5; SLOT = 0.20; TIME_STOP = 10

def load_bars(sym):
    j = json.load(open(os.path.join(HERE, "data", f"pxfull_{sym}.json")))
    r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i, t in enumerate(ts):
        if q["close"][i] is None or adj[i] is None or q["high"][i] is None: continue
        ratio = adj[i] / q["close"][i]
        bars.append({"d": time.strftime("%Y-%m-%d", time.gmtime(t)),
                     "o": q["open"][i]*ratio, "h": q["high"][i]*ratio,
                     "l": q["low"][i]*ratio, "c": adj[i]})
    return bars

def prepare(bars):
    """Add sma200 and setup-completion info, bar-by-bar point-in-time."""
    n = len(bars); C = [b["c"] for b in bars]; L = [b["l"] for b in bars]
    sma = [None]*n; run = 0; setup_done = [False]*n; span_low = [None]*n
    for i in range(n):
        if i >= 199: sma[i] = sum(C[i-199:i+1]) / 200
        if i >= 4 and C[i] < C[i-4]:
            run += 1
            if run == 9:
                setup_done[i] = True; span_low[i] = min(L[i-8:i+1]); run = 0
        else:
            run = 0
    return sma, setup_done, span_low

def build(syms):
    mkt = {}
    for s in syms:
        bars = load_bars(s)
        sma, sd, sl = prepare(bars)
        mkt[s] = {"bars": bars, "idx": {b["d"]: i for i, b in enumerate(bars)},
                  "sma": sma, "setup": sd, "span_low": sl}
    return mkt

def run_road(mkt, syms, start, end, maxpos, slot_frac, picks=None):
    """picks: None = real setups; else dict sym -> set of entry dates (placebo).
    Returns final, curve [[date, equity]], trades list, costs, orders."""
    master = sorted(d for d in mkt[syms[0]]["idx"] if start <= d <= end)
    cash = START; pos = {}; closed = []; curve = []; costs = 0.0; orders = 0
    def equity(date):
        eq = cash
        for s, p in pos.items():
            eq += p["shares"] * mkt[s]["bars"][mkt[s]["idx"][date]]["c"]
        return eq
    for date in master:
        # exits first (positions opened on earlier days)
        for s in list(pos.keys()):
            m = mkt[s]; i = m["idx"][date]; b = m["bars"][i]; p = pos[s]
            p["days"] += 1
            reason = px = None
            if b["l"] < p["stop"]:
                reason, px = "stop", p["stop"]
            elif i >= 4 and b["c"] > m["bars"][i-4]["c"]:
                reason, px = "flip", b["c"]
            elif p["days"] >= TIME_STOP:
                reason, px = "time", b["c"]
            if reason:
                gross = p["shares"] * px; fee = gross * COST + SELL_FEE
                cash += gross - fee; costs += fee; orders += 1
                closed.append({"sym": s, "entry": p["entry_date"], "exit": date, "days": p["days"],
                               "reason": reason, "invested": round(p["invested"], 4),
                               "pnl": round(gross - fee - p["invested"], 4),
                               "pnl_pct": round(100 * (gross - fee - p["invested"]) / p["invested"], 3)})
                del pos[s]
        # entries
        if len(pos) < maxpos:
            cands = []
            for s in syms:
                if s in pos: continue
                m = mkt[s]
                if date not in m["idx"]: continue
                i = m["idx"][date]
                if picks is None:
                    if not m["setup"][i]: continue
                else:
                    if date not in picks.get(s, ()): continue
                if m["sma"][i] is None or m["bars"][i]["c"] <= m["sma"][i]: continue
                cands.append(s)
            for s in sorted(cands):
                if len(pos) >= maxpos: break
                m = mkt[s]; i = m["idx"][date]; c = m["bars"][i]["c"]
                amt = min(slot_frac * equity(date), cash)
                if amt <= 0: break
                fee = amt * COST; sh = (amt - fee) / c; costs += fee; orders += 1; cash -= amt
                stop = m["span_low"][i] if picks is None else m["bars"][i]["l"]
                pos[s] = {"shares": sh, "invested": amt, "entry_date": date, "days": 0, "stop": stop}
        curve.append([date, round(equity(date), 4)])
    # liquidate at end
    if pos:
        date = master[-1]
        for s in list(pos.keys()):
            m = mkt[s]; c = m["bars"][m["idx"][date]]["c"]; p = pos[s]
            gross = p["shares"] * c; fee = gross * COST + SELL_FEE
            cash += gross - fee; costs += fee; orders += 1
            closed.append({"sym": s, "entry": p["entry_date"], "exit": date, "days": p["days"],
                           "reason": "end", "invested": round(p["invested"], 4),
                           "pnl": round(gross - fee - p["invested"], 4),
                           "pnl_pct": round(100 * (gross - fee - p["invested"]) / p["invested"], 3)})
            del pos[s]
        curve[-1][1] = round(cash, 4)
    return {"final": round(cash, 2), "curve": curve, "trades": closed,
            "costs": round(costs, 2), "orders": orders,
            "time_in_market_pct": None}

def max_dd(curve):
    peak = -1e18; dd = 0.0
    for _, v in curve:
        peak = max(peak, v); dd = min(dd, v / peak - 1)
    return round(100 * dd, 2)

def period_stats(curve):
    """Monthly distribution from daily curve."""
    months = {}
    for d, v in curve: months[d[:7]] = v
    keys = sorted(months); rets = []
    prev = START
    for k in keys:
        rets.append(months[k] / prev - 1); prev = months[k]
    if not rets: return {}
    los = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; los = max(los, cur)
    peak = START; since_high = cur2 = 0
    for _, v in curve:
        if v >= peak: peak = v; cur2 = 0
        else: cur2 += 1
        since_high = max(since_high, cur2)
    return {"periods": len(rets), "median_pct": round(100 * statistics.median(rets), 3),
            "share_positive_pct": round(100 * sum(1 for r in rets if r > 0) / len(rets), 1),
            "best_pct": round(100 * max(rets), 2), "worst_pct": round(100 * min(rets), 2),
            "longest_losing_streak_months": los, "longest_days_between_highs": since_high,
            "mean_pct_secondary": round(100 * statistics.mean(rets), 3)}

def trade_stats(trades):
    if not trades: return {"n": 0}
    wins = [t for t in trades if t["pnl"] > 0]
    return {"n": len(trades), "win_rate_pct": round(100 * len(wins) / len(trades), 1),
            "avg_win_pct": round(statistics.mean([t["pnl_pct"] for t in wins]), 2) if wins else None,
            "avg_loss_pct": round(statistics.mean([t["pnl_pct"] for t in trades if t["pnl"] <= 0]), 2) if len(wins) < len(trades) else None,
            "expectancy_pct": round(statistics.mean([t["pnl_pct"] for t in trades]), 3),
            "by_reason": {r: sum(1 for t in trades if t["reason"] == r) for r in ("stop", "flip", "time", "end")}}

def main():
    res = {"family": "hunt-demark-td-sequential", "form": "v13-best-rules: setup-only, SMA200 guard, flip exit, 10d time stop, span-low stop, no floor"}
    pond = build(POND); spy = build(["SPY"])
    res["pond"] = {}; res["spy"] = {}; res["curves"] = {}
    for road, (s, e) in ROADS.items():
        r = run_road(pond, POND, s, e, MAXPOS, SLOT)
        res["pond"][road] = {"final": r["final"], "maxdd_pct": max_dd(r["curve"]), "costs": r["costs"],
                             "orders": r["orders"], "periods_monthly": period_stats(r["curve"]),
                             "trade_stats": trade_stats(r["trades"]), "trades": r["trades"]}
        res["curves"]["pond_" + road] = r["curve"]
        q = run_road(spy, ["SPY"], s, e, 1, 1.0)
        res["spy"][road] = {"final": q["final"], "maxdd_pct": max_dd(q["curve"]), "costs": q["costs"],
                            "orders": q["orders"], "periods_monthly": period_stats(q["curve"]),
                            "trade_stats": trade_stats(q["trades"]), "trades": q["trades"]}
        res["curves"]["spy_" + road] = q["curve"]
        # placebos on pond chassis: count-matched random guard-passing days
        n_entries = len(r["trades"])
        elig = {}
        for sym in POND:
            m = pond[sym]
            elig[sym] = [b["d"] for j, b in enumerate(m["bars"])
                         if s <= b["d"] <= e and m["sma"][j] is not None and b["c"] > m["sma"][j]]
        finals = []
        for seed in range(1, 21):
            rng = random.Random(seed * 31 + 7)
            picks = {}
            for _ in range(n_entries):
                sym = rng.choice(POND)
                if elig[sym]: picks.setdefault(sym, set()).add(rng.choice(elig[sym]))
            pr = run_road(pond, POND, s, e, MAXPOS, SLOT, picks=picks)
            finals.append(pr["final"])
        res["pond"][road]["placebos"] = {"median": round(statistics.median(finals), 2),
            "n_beaten": sum(1 for f in finals if r["final"] > f), "finals": finals}
        print(road, "pond:", r["final"], "dd", res["pond"][road]["maxdd_pct"], "trades", len(r["trades"]),
              "| SPY-only:", q["final"], "trades", len(q["trades"]),
              "| placebo med", res["pond"][road]["placebos"]["median"], "beaten", res["pond"][road]["placebos"]["n_beaten"], flush=True)
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("DONE")

if __name__ == "__main__":
    main()
