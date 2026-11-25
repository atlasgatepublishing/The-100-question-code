#!/usr/bin/env python3
"""v12 CONSTRUCTED candlestick system — frozen in CONSTRUCTION-SPEC.md.
Nison vocabulary; EMA10 prior trend (Marshall et al. via Lu-Chen-Hsu 2015);
Bulkowski breakout confirmation (first close above pattern high, entry next
open, 3-day validity); stop at pattern low (Nison's principle); target =
pattern high + pattern height (Bulkowski measure rule); 10-trading-day time
exit; equal slices (max 10 x 10% of equity). Costs 0.10%/side + $0.01/sell.
$100/road. NO pot floor. Simulation only."""
import json, os, random, time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
COST = 0.001; SELL_FEE = 0.01; START = 100.0
MAX_POS = 10; SLICE = 0.10; TIME_EXIT = 10; VALID_DAYS = 3

POND30 = ["AAPL", "MSFT", "AMZN", "GOOG", "META", "BRK-B", "JPM", "XOM",
          "JNJ", "PG", "V", "WMT", "HD", "BAC", "CVX", "PFE", "VZ", "T",
          "DIS", "NFLX", "INTC", "CSCO", "GE", "IBM", "MMM", "UNH", "MA",
          "KO", "PEP", "WFC"]  # GOOG = pond's GOOGL leg (see spec 5)
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20"),
         "CONFIRM": ("2010-01-04", "2016-11-18")}

def load_bars(sym):
    j = json.load(open(os.path.join(DATA, f"pxfull_{sym}.json")))
    r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i, t in enumerate(ts):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if None in (o, h, l, c) or adj[i] is None: continue
        ratio = adj[i] / c if c else 1.0
        bars.append({"d": time.strftime("%Y-%m-%d", time.gmtime(t)),
                     "o": o * ratio, "h": h * ratio, "l": l * ratio, "c": adj[i]})
    bars.sort(key=lambda b: b["d"])
    return bars

def prepare(bars):
    """Add EMA10, trailing mean body, pattern list [(first_idx, end_idx, high, low)]."""
    n = len(bars)
    ema = [None] * n; e = bars[0]["c"]; alpha = 2.0 / 11.0
    for i in range(n):
        e = bars[i]["c"] if i == 0 else alpha * bars[i]["c"] + (1 - alpha) * e
        ema[i] = e
    bodies = [abs(b["c"] - b["o"]) for b in bars]
    meanbody = [None] * n
    for i in range(n):
        if i >= 10: meanbody[i] = sum(bodies[i - 10:i]) / 10.0
    pats = []
    def downtrend(s):  # day before pattern's first candle
        return s >= 0 and bars[s]["c"] < ema[s]
    for t in range(n):
        b = bars[t]; body = bodies[t]; rng = b["h"] - b["l"]
        # Hammer (1d)
        if rng > 0 and (min(b["o"], b["c"]) - b["l"]) >= 2 * max(body, 1e-9) \
           and (b["h"] - max(b["o"], b["c"])) <= 0.1 * rng and downtrend(t - 1):
            pats.append((t, t, b["h"], b["l"]))
        if t >= 1:
            p = bars[t - 1]
            # Bullish Engulfing (2d)
            if p["c"] < p["o"] and b["c"] > b["o"] and b["o"] <= p["c"] and b["c"] >= p["o"] \
               and downtrend(t - 2):
                pats.append((t - 1, t, max(p["h"], b["h"]), min(p["l"], b["l"])))
            # Piercing Line (2d)
            if p["c"] < p["o"] and b["c"] > b["o"] and b["o"] < p["c"] \
               and b["c"] > (p["o"] + p["c"]) / 2 and b["c"] < p["o"] and downtrend(t - 2):
                pats.append((t - 1, t, max(p["h"], b["h"]), min(p["l"], b["l"])))
        if t >= 2:
            a, m = bars[t - 2], bars[t - 1]
            hi3 = max(a["h"], m["h"], b["h"]); lo3 = min(a["l"], m["l"], b["l"])
            # Three White Soldiers
            if a["c"] > a["o"] and m["c"] > m["o"] and b["c"] > b["o"] \
               and a["c"] < m["c"] < b["c"] \
               and a["o"] <= m["o"] <= a["c"] and m["o"] <= b["o"] <= m["c"] \
               and downtrend(t - 3):
                pats.append((t - 2, t, hi3, lo3))
            # Three Inside Up
            if a["c"] < a["o"] and meanbody[t - 2] is not None and bodies[t - 2] > meanbody[t - 2] \
               and min(m["o"], m["c"]) >= a["c"] and max(m["o"], m["c"]) <= a["o"] \
               and b["c"] > b["o"] and b["c"] > a["o"] and downtrend(t - 3):
                pats.append((t - 2, t, hi3, lo3))
            # Three Outside Up
            if a["c"] < a["o"] and m["c"] > m["o"] and m["o"] <= a["c"] and m["c"] >= a["o"] \
               and b["c"] > b["o"] and b["c"] > m["c"] and downtrend(t - 3):
                pats.append((t - 2, t, hi3, lo3))
            # Morning Star
            if a["c"] < a["o"] and meanbody[t - 2] is not None and bodies[t - 2] > meanbody[t - 2] \
               and meanbody[t - 1] is not None and bodies[t - 1] < meanbody[t - 1] \
               and max(m["o"], m["c"]) <= a["c"] \
               and b["c"] > b["o"] and b["c"] > (a["o"] + a["c"]) / 2 and downtrend(t - 3):
                pats.append((t - 2, t, hi3, lo3))
    return ema, pats

def signals_for(bars, pats, start, end, cal_next):
    """Return {entry_date: [(sym_stop, target)]} values keyed later by symbol.
    Here returns list of (entry_date, stop, target)."""
    by_date = {b["d"]: i for i, b in enumerate(bars)}
    out = []
    seen = set()
    for (f, e, hi, lo) in pats:
        if bars[f]["d"] < start or bars[e]["d"] > end: continue
        for k in range(e + 1, min(e + 1 + VALID_DAYS, len(bars))):
            if bars[k]["d"] > end: break
            if bars[k]["c"] > hi:
                nd = cal_next.get(bars[k]["d"])
                if nd is not None and nd <= end and (nd, round(lo, 4)) not in seen:
                    seen.add((nd, round(lo, 4)))
                    out.append((nd, lo, hi + (hi - lo)))
                break
    return out

def simulate(cal, symbars, entries, start, end):
    """entries: {date: [(sym, stop, target)]} filled at that date's open."""
    cash = START; pos = {}; costs = 0.0; orders = 0; buys = 0
    closed = 0; wins = 0; curve = []; trades = []
    idx = [d for d in cal if start <= d <= end]
    def bar(sym, d): return symbars[sym]["by"].get(d)
    def mark(d, field="c"):
        v = cash
        for s, p in pos.items():
            b = bar(s, d)
            v += p["shares"] * (b[field] if b else p["last_c"])
        return v
    for d in idx:
        # 1) fills at open
        todays = sorted(entries.get(d, []))
        if todays:
            eq_open = cash + sum(p["shares"] * (bar(s, d)["o"] if bar(s, d) else p["last_c"])
                                 for s, p in pos.items())
            for sym, stop, target in todays:
                if sym in pos or len(pos) >= MAX_POS: continue
                b = bar(sym, d)
                if b is None: continue
                val = SLICE * eq_open
                if cash < val * (1 + COST) or val < 1.0: continue
                fee = val * COST; cash -= val + fee; costs += fee; orders += 1; buys += 1
                pos[sym] = {"shares": val / b["o"], "entry": b["o"], "stop": stop,
                            "target": target, "held": 0, "last_c": b["c"]}
                trades.append({"date": d, "sym": sym, "side": "buy", "price": round(b["o"], 4)})
        # 2) intraday + time exits
        for sym in list(pos):
            p = pos[sym]; b = bar(sym, d)
            if b is None: continue
            p["last_c"] = b["c"]; p["held"] += 1
            fill = None; why = None
            if b["o"] <= p["stop"]: fill, why = b["o"], "stop_gap"
            elif b["o"] >= p["target"]: fill, why = b["o"], "target_gap"
            elif b["l"] <= p["stop"] and b["h"] >= p["target"]: fill, why = p["stop"], "stop_first"
            elif b["l"] <= p["stop"]: fill, why = p["stop"], "stop"
            elif b["h"] >= p["target"]: fill, why = p["target"], "target"
            elif p["held"] >= TIME_EXIT: fill, why = b["c"], "time"
            if fill is not None:
                val = p["shares"] * fill; fee = val * COST + SELL_FEE
                cash += val - fee; costs += fee; orders += 1; closed += 1
                if fill > p["entry"]: wins += 1
                trades.append({"date": d, "sym": sym, "side": "sell_" + why, "price": round(fill, 4)})
                del pos[sym]
        curve.append([d, round(mark(d), 4)])
    # end of road: names whose bars ended -> zero (spec 5); rest liquidated at last close
    if pos:
        d = idx[-1]
        for sym in list(pos):
            p = pos[sym]; b = bar(sym, d)
            if b is None:  # bars ended mid-holding: written to zero
                closed += 1; trades.append({"date": d, "sym": sym, "side": "sell_zero", "price": 0.0})
            else:
                val = p["shares"] * b["c"]; fee = val * COST + SELL_FEE
                cash += val - fee; costs += fee; orders += 1; closed += 1
                if b["c"] > p["entry"]: wins += 1
                trades.append({"date": d, "sym": sym, "side": "sell_eod", "price": round(b["c"], 4)})
            del pos[sym]
        curve[-1][1] = round(cash, 4)
    peak = -1.0; mdd = 0.0
    for _, v in curve:
        peak = max(peak, v); mdd = max(mdd, (peak - v) / peak if peak > 0 else 0)
    yrs = max((time.mktime(time.strptime(end, "%Y-%m-%d")) -
               time.mktime(time.strptime(start, "%Y-%m-%d"))) / (365.25 * 86400), 0.01)
    return {"final": round(cash, 2),
            "cagr_pct": round(((cash / START) ** (1 / yrs) - 1) * 100, 2) if cash > 0 else -100.0,
            "max_dd_pct": round(mdd * 100, 2), "costs": round(costs, 2), "orders": orders,
            "buys": buys, "closed_trades": closed,
            "win_rate_pct": round(100 * wins / closed, 1) if closed else None,
            "equity_curve": curve, "trades": trades}

def buyhold(bars, start, end):
    idx = [b for b in bars if start <= b["d"] <= end]
    sh = START / (idx[0]["o"] * (1 + COST))
    val = sh * idx[-1]["c"]
    return round(val - val * COST - SELL_FEE, 2)

def main():
    spy = load_bars("SPY")
    cal = [b["d"] for b in spy]
    cal_next = {cal[i]: cal[i + 1] for i in range(len(cal) - 1)}
    all_syms = sorted(f[7:-5] for f in os.listdir(DATA)
                      if f.startswith("pxfull_") and f != "pxfull_SPY.json")
    universes = {"POND30": POND30, "BROAD154": all_syms}
    cache = {}
    def get(sym):
        if sym not in cache:
            bars = load_bars(sym)
            _, pats = prepare(bars)
            cache[sym] = {"bars": bars, "by": {b["d"]: b for b in bars}, "pats": pats}
        return cache[sym]
    out = {"family": "candlestick-patterns", "form": "v12 CONSTRUCTED (see CONSTRUCTION-SPEC.md)",
           "universes": {}}
    for uname, syms in universes.items():
        out["universes"][uname] = {"n_symbols": len(syms), "roads": {}}
        for sym in syms: get(sym)
        for rname, (s, e) in ROADS.items():
            entries = {}
            for sym in syms:
                g = get(sym)
                for (ed, stop, target) in signals_for(g["bars"], g["pats"], s, e, cal_next):
                    entries.setdefault(ed, []).append((sym, stop, target))
            symbars = {sym: get(sym) for sym in syms}
            r = simulate(cal, symbars, entries, s, e)
            # placebos: same number of buys, random (day, sym), drawn bar = 1-day pattern
            road_days = [d for d in cal if s <= d <= e]
            draw_days = road_days[:-11]
            twins = []
            for seed in range(20):
                rng = random.Random(12000 + seed)
                pent = {}
                for _ in range(r["buys"]):
                    d0 = rng.choice(draw_days); sym = rng.choice(syms)
                    b = get(sym)["by"].get(d0)
                    if b is None: continue
                    nd = cal_next.get(d0)
                    if nd is None or nd > e: continue
                    pent.setdefault(nd, []).append((sym, b["l"], b["h"] + (b["h"] - b["l"])))
                twins.append(simulate(cal, symbars, pent, s, e)["final"])
            r["placebo_finals"] = twins
            r["placebo_beaten"] = sum(1 for t in twins if r["final"] > t)
            r["spy_buyhold"] = buyhold(spy, s, e)
            out["universes"][uname]["roads"][rname] = r
            print(f"{uname} {rname:7s} final ${r['final']:9.2f} CAGR {r['cagr_pct']:+7.2f}% "
                  f"maxDD {r['max_dd_pct']:6.2f}% buys {r['buys']:4d} win {r['win_rate_pct']}% "
                  f"costs ${r['costs']:7.2f} placebo beaten {r['placebo_beaten']}/20 SPY ${r['spy_buyhold']:.2f}",
                  flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as fh:
        json.dump(out, fh, indent=1)
    print("wrote results.json")

if __name__ == "__main__":
    main()
