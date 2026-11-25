#!/usr/bin/env python3
"""v13 BEST-RULES candlestick system — frozen in BEST-RULES-SPEC.md.
Weekly bars; Hammer / Bullish Engulfing / Morning Star only; context =
uptrend (C>SMA50w, SMA50w rising) + pullback (pre-pattern close < SMA10w);
confirmation = weekly close above pattern high within 2 weeks AND volume
>= trailing 20w average, entry next week's first open; initial stop =
pattern low (daily intraday); NO target; exits = weekly close below
SMA10w, or below highest weekly close - 3*ATR14w (next open), or 52-week
time exit; max 5 x 20% slices; costs 0.10%/side + $0.01/sell; NO floor."""
import json, os, random, time
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
COST = 0.001; SELL_FEE = 0.01; START = 100.0
MAX_POS = 5; SLICE = 0.20; VALID_WEEKS = 2; MAX_HOLD_WEEKS = 52

POND30 = ["AAPL", "MSFT", "AMZN", "GOOG", "META", "BRK-B", "JPM", "XOM",
          "JNJ", "PG", "V", "WMT", "HD", "BAC", "CVX", "PFE", "VZ", "T",
          "DIS", "NFLX", "INTC", "CSCO", "GE", "IBM", "MMM", "UNH", "MA",
          "KO", "PEP", "WFC"]
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20"),
         "CONFIRM": ("2010-01-04", "2016-11-18")}

def load_bars(sym):
    j = json.load(open(os.path.join(DATA, f"pxfull_{sym}.json")))
    r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]; vol = q.get("volume") or [0]*len(ts)
    bars = []
    for i, t in enumerate(ts):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if None in (o, h, l, c) or adj[i] is None: continue
        ratio = adj[i] / c if c else 1.0
        bars.append({"d": time.strftime("%Y-%m-%d", time.gmtime(t)),
                     "o": o*ratio, "h": h*ratio, "l": l*ratio, "c": adj[i],
                     "v": (vol[i] or 0)})
    bars.sort(key=lambda b: b["d"])
    return bars

def weekly(bars):
    """Aggregate daily bars into ISO calendar weeks."""
    wk = {}
    for b in bars:
        y, m, d = int(b["d"][:4]), int(b["d"][5:7]), int(b["d"][8:10])
        iso = date(y, m, d).isocalendar()
        key = (iso[0], iso[1])
        if key not in wk:
            wk[key] = {"o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"],
                       "v": b["v"], "first": b["d"], "last": b["d"]}
        else:
            w = wk[key]; w["h"] = max(w["h"], b["h"]); w["l"] = min(w["l"], b["l"])
            w["c"] = b["c"]; w["v"] += b["v"]; w["last"] = b["d"]
    return [wk[k] for k in sorted(wk)]

def prepare(bars):
    W = weekly(bars); n = len(W)
    sma10 = [None]*n; sma50 = [None]*n; atr = [None]*n; vol20 = [None]*n
    closes = [w["c"] for w in W]
    for i in range(n):
        if i >= 9: sma10[i] = sum(closes[i-9:i+1])/10.0
        if i >= 49: sma50[i] = sum(closes[i-49:i+1])/50.0
        if i >= 19: vol20[i] = sum(w["v"] for w in W[i-19:i])/20.0  # trailing, excl current
        if i >= 14:
            trs = []
            for k in range(i-13, i+1):
                pc = closes[k-1]
                trs.append(max(W[k]["h"]-W[k]["l"], abs(W[k]["h"]-pc), abs(W[k]["l"]-pc)))
            atr[i] = sum(trs)/14.0
    bodies = [abs(w["c"]-w["o"]) for w in W]
    meanbody = [None]*n
    for i in range(n):
        if i >= 10: meanbody[i] = sum(bodies[i-10:i])/10.0
    pats = []  # (first_idx, end_idx, high, low, name)
    def context(s):
        if s < 53 or sma50[s] is None or sma10[s] is None: return False
        return closes[s] > sma50[s] and sma50[s] > sma50[s-4] and closes[s] < sma10[s]
    for t in range(n):
        w = W[t]; body = bodies[t]; rng = w["h"]-w["l"]
        if rng > 0 and (min(w["o"], w["c"])-w["l"]) >= 2*max(body, 1e-9) \
           and (w["h"]-max(w["o"], w["c"])) <= 0.1*rng and context(t-1):
            pats.append((t, t, w["h"], w["l"], "hammer"))
        if t >= 1:
            p = W[t-1]
            if p["c"] < p["o"] and w["c"] > w["o"] and w["o"] <= p["c"] and w["c"] >= p["o"] \
               and context(t-2):
                pats.append((t-1, t, max(p["h"], w["h"]), min(p["l"], w["l"]), "engulfing"))
        if t >= 2:
            a, m = W[t-2], W[t-1]
            if a["c"] < a["o"] and meanbody[t-2] is not None and bodies[t-2] > meanbody[t-2] \
               and meanbody[t-1] is not None and bodies[t-1] < meanbody[t-1] \
               and max(m["o"], m["c"]) <= a["c"] \
               and w["c"] > w["o"] and w["c"] > (a["o"]+a["c"])/2 and context(t-3):
                pats.append((t-2, t, max(a["h"], m["h"], w["h"]), min(a["l"], m["l"], w["l"]), "morning_star"))
    return {"W": W, "sma10": sma10, "sma50": sma50, "atr": atr, "vol20": vol20, "pats": pats}

def signals_for(g, start, end):
    """Return list of (entry_date, stop, entry_week_idx). Entry week = week after confirmation week."""
    W = g["W"]; out = []; seen = set()
    for (f, e, hi, lo, _name) in g["pats"]:
        if W[f]["first"] < start or W[e]["last"] > end: continue
        for k in range(e+1, min(e+1+VALID_WEEKS, len(W))):
            if W[k]["last"] > end: break
            if W[k]["c"] > hi and g["vol20"][k] is not None and W[k]["v"] >= g["vol20"][k]:
                if k+1 < len(W):
                    ed = W[k+1]["first"]
                    if ed <= end and (ed, round(lo, 4)) not in seen:
                        seen.add((ed, round(lo, 4))); out.append((ed, lo, k+1))
                break
    return out

def simulate(cal, symdata, entries, start, end):
    """entries: {date: [(sym, stop, entry_week_idx)]}. symdata[sym] has bars/by/W/sma10/atr."""
    cash = START; pos = {}; costs = 0.0; orders = 0; buys = 0
    curve = []; trades = []; closed_rets = []
    pending_exit = {}  # date -> [sym] sell at open, reason
    idx = [d for d in cal if start <= d <= end]
    def bar(sym, d): return symdata[sym]["by"].get(d)
    for d in idx:
        # 1) weekly-decision exits at open
        for sym in pending_exit.pop(d, []):
            if sym not in pos: continue
            b = bar(sym, d)
            if b is None: continue
            p = pos.pop(sym); fill = b["o"]
            val = p["shares"]*fill; fee = val*COST + SELL_FEE
            cash += val - fee; costs += fee; orders += 1
            closed_rets.append((fill/p["entry"]-1)*100)
            trades.append({"date": d, "sym": sym, "side": "sell_"+p["exit_reason"], "price": round(fill, 4)})
        # 2) entries at open
        todays = sorted(entries.get(d, []))
        if todays:
            eq_open = cash + sum(p["shares"]*(bar(s, d)["o"] if bar(s, d) else p["last_c"])
                                 for s, p in pos.items())
            for sym, stop, ewidx in todays:
                if sym in pos or len(pos) >= MAX_POS: continue
                b = bar(sym, d)
                if b is None: continue
                val = SLICE*eq_open
                if cash < val*(1+COST) or val < 1.0: continue
                fee = val*COST; cash -= val+fee; costs += fee; orders += 1; buys += 1
                pos[sym] = {"shares": val/b["o"], "entry": b["o"], "stop": stop,
                            "last_c": b["c"], "ewidx": ewidx, "weeks": 0,
                            "hi_close": -1.0, "exit_reason": "time"}
                trades.append({"date": d, "sym": sym, "side": "buy", "price": round(b["o"], 4)})
        # 3) intraday initial stop + daily mark
        for sym in list(pos):
            p = pos[sym]; b = bar(sym, d)
            if b is None: continue
            p["last_c"] = b["c"]
            fill = None
            if b["o"] <= p["stop"]: fill = b["o"]
            elif b["l"] <= p["stop"]: fill = p["stop"]
            if fill is not None:
                val = p["shares"]*fill; fee = val*COST + SELL_FEE
                cash += val-fee; costs += fee; orders += 1
                closed_rets.append((fill/p["entry"]-1)*100)
                trades.append({"date": d, "sym": sym, "side": "sell_stop", "price": round(fill, 4)})
                del pos[sym]
        # 4) weekly-close decisions (per symbol, on its week's last daily bar)
        for sym in list(pos):
            g = symdata[sym]; p = pos[sym]
            wi = None
            # find weekly index whose last == d and >= entry week
            m = g["wlast"].get(d)
            if m is None or m < p["ewidx"]: continue
            wi = m; w = g["W"][wi]
            p["weeks"] += 1; p["hi_close"] = max(p["hi_close"], w["c"])
            reason = None
            if p["weeks"] >= MAX_HOLD_WEEKS: reason = "time"
            elif g["sma10"][wi] is not None and w["c"] < g["sma10"][wi]: reason = "trendbreak"
            elif g["atr"][wi] is not None and w["c"] < p["hi_close"] - 3*g["atr"][wi]: reason = "trail"
            if reason:
                nd = g["next_first"].get(wi)
                if nd is not None and nd <= end:
                    p["exit_reason"] = reason
                    pending_exit.setdefault(nd, []).append(sym)
                elif reason == "time":
                    fill = w["c"]; val = p["shares"]*fill; fee = val*COST + SELL_FEE
                    cash += val-fee; costs += fee; orders += 1
                    closed_rets.append((fill/p["entry"]-1)*100)
                    trades.append({"date": d, "sym": sym, "side": "sell_time", "price": round(fill, 4)})
                    del pos[sym]
        v = cash + sum(p["shares"]*p["last_c"] for p in pos.values())
        curve.append([d, round(v, 4)])
    if pos:
        d = idx[-1]
        for sym in list(pos):
            p = pos[sym]; b = bar(sym, d)
            if b is None:
                trades.append({"date": d, "sym": sym, "side": "sell_zero", "price": 0.0})
                closed_rets.append(-100.0)
            else:
                val = p["shares"]*b["c"]; fee = val*COST + SELL_FEE
                cash += val-fee; costs += fee; orders += 1
                closed_rets.append((b["c"]/p["entry"]-1)*100)
                trades.append({"date": d, "sym": sym, "side": "sell_eod", "price": round(b["c"], 4)})
            del pos[sym]
        if curve: curve[-1][1] = round(cash, 4)
    peak = -1.0; mdd = 0.0
    for _, v in curve:
        peak = max(peak, v); mdd = max(mdd, (peak-v)/peak if peak > 0 else 0)
    yrs = max((time.mktime(time.strptime(end, "%Y-%m-%d")) -
               time.mktime(time.strptime(start, "%Y-%m-%d")))/(365.25*86400), 0.01)
    wins = [r for r in closed_rets if r > 0]; losses = [r for r in closed_rets if r <= 0]
    # per-period (calendar year) distribution
    yv = {}
    for d, v in curve: yv.setdefault(d[:4], []).append((d, v))
    years = sorted(yv); yret = []; prev = START
    for y in years:
        last = yv[y][-1][1]; yret.append(round((last/prev-1)*100, 2)); prev = last
    yret_sorted = sorted(yret)
    med = yret_sorted[len(yret_sorted)//2] if len(yret_sorted) % 2 else round((yret_sorted[len(yret_sorted)//2-1]+yret_sorted[len(yret_sorted)//2])/2, 2)
    neg_streak = cur = 0
    for r in yret:
        cur = cur+1 if r < 0 else 0; neg_streak = max(neg_streak, cur)
    # longest stretch between new highs (calendar days)
    peak = -1; peak_d = None; longest = 0
    for d, v in curve:
        if v > peak:
            if peak_d:
                dd = (date.fromisoformat(d)-date.fromisoformat(peak_d)).days; longest = max(longest, dd)
            peak = v; peak_d = d
    if curve and peak_d:
        longest = max(longest, (date.fromisoformat(curve[-1][0])-date.fromisoformat(peak_d)).days)
    return {"final": round(cash, 2),
            "cagr_pct": round(((cash/START)**(1/yrs)-1)*100, 2) if cash > 0 else -100.0,
            "max_dd_pct": round(mdd*100, 2), "costs": round(costs, 2), "orders": orders,
            "buys": buys, "closed_trades": len(closed_rets),
            "win_rate_pct": round(100*len(wins)/len(closed_rets), 1) if closed_rets else None,
            "avg_win_pct": round(sum(wins)/len(wins), 2) if wins else None,
            "avg_loss_pct": round(sum(losses)/len(losses), 2) if losses else None,
            "payoff_ratio": round((sum(wins)/len(wins))/abs(sum(losses)/len(losses)), 2) if wins and losses else None,
            "expectancy_pct": round(sum(closed_rets)/len(closed_rets), 2) if closed_rets else None,
            "year_returns_pct": dict(zip(years, yret)),
            "period_median_pct": med,
            "period_share_positive_pct": round(100*sum(1 for r in yret if r > 0)/len(yret), 1) if yret else None,
            "period_best_pct": max(yret) if yret else None,
            "period_worst_pct": min(yret) if yret else None,
            "longest_negative_year_streak": neg_streak,
            "longest_days_between_new_highs": longest,
            "equity_curve": curve, "trades": trades}

def buyhold(bars, start, end):
    idx = [b for b in bars if start <= b["d"] <= end]
    sh = START/(idx[0]["o"]*(1+COST)); val = sh*idx[-1]["c"]
    return round(val - val*COST - SELL_FEE, 2)

def main():
    spy = load_bars("SPY"); cal = [b["d"] for b in spy]
    all_syms = sorted(f[7:-5] for f in os.listdir(DATA)
                      if f.startswith("pxfull_") and f != "pxfull_SPY.json")
    universes = {"POND30": POND30, "BROAD154": all_syms}
    cache = {}
    def get(sym):
        if sym not in cache:
            bars = load_bars(sym); g = prepare(bars)
            g["bars"] = bars; g["by"] = {b["d"]: b for b in bars}
            g["wlast"] = {w["last"]: i for i, w in enumerate(g["W"])}
            g["next_first"] = {i: g["W"][i+1]["first"] for i in range(len(g["W"])-1)}
            cache[sym] = g
        return cache[sym]
    out = {"family": "candlestick-patterns", "form": "v13 BEST-RULES (see BEST-RULES-SPEC.md)", "universes": {}}
    for uname, syms in universes.items():
        out["universes"][uname] = {"n_symbols": len(syms), "roads": {}}
        for sym in syms: get(sym)
        symdata = {sym: get(sym) for sym in syms}
        for rname, (s, e) in ROADS.items():
            entries = {}
            for sym in syms:
                for (ed, stop, ew) in signals_for(get(sym), s, e):
                    entries.setdefault(ed, []).append((sym, stop, ew))
            r = simulate(cal, symdata, entries, s, e)
            road_weeks = []
            for sym in syms:
                g = get(sym)
                for i, w in enumerate(g["W"]):
                    if s <= w["first"] and w["last"] <= e: road_weeks.append((sym, i))
            twins = []
            for seed in range(20):
                rng = random.Random(13000+seed); pent = {}
                for _ in range(r["buys"]):
                    sym, wi = rng.choice(road_weeks); g = get(sym)
                    if wi+1 >= len(g["W"]): continue
                    nd = g["W"][wi+1]["first"]
                    if nd > e: continue
                    pent.setdefault(nd, []).append((sym, g["W"][wi]["l"], wi+1))
                twins.append(simulate(cal, symdata, pent, s, e)["final"])
            r["placebo_finals"] = twins
            r["placebo_beaten"] = sum(1 for t in twins if r["final"] > t)
            r["spy_buyhold"] = buyhold(spy, s, e)
            out["universes"][uname]["roads"][rname] = r
            print(f"{uname} {rname:7s} final ${r['final']:9.2f} CAGR {r['cagr_pct']:+7.2f}% "
                  f"maxDD {r['max_dd_pct']:6.2f}% buys {r['buys']:4d} win {r['win_rate_pct']}% "
                  f"avgW {r['avg_win_pct']} avgL {r['avg_loss_pct']} exp {r['expectancy_pct']} "
                  f"costs ${r['costs']:7.2f} placebo {r['placebo_beaten']}/20 SPY ${r['spy_buyhold']:.2f}", flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as fh:
        json.dump(out, fh, indent=1)
    print("wrote results.json")

if __name__ == "__main__":
    main()
