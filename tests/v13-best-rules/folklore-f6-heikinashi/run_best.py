#!/usr/bin/env python3
"""
V13 BEST RULES — F-6 Heikin-Ashi. Simulation only. Spec frozen in
BEST-RULES-SPEC.md before this run:
  HA per Valcu. Colour only (no shadow condition).
  Entry: next real open after 3 consecutive green HA candles AND real
    close > 200-day SMA on signal day.
  Exit: next real open after 2 consecutive red HA candles. Doji resets
    both counts. 200d gate blocks entries only.
  $100 pot, 100% in/out, long-only, NO floor. Costs 0.10%/side + $0.01/sell.
  Placebos: 20 seeds, shuffled holding-block design (v7/v11 family control).
Data: read-only ~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json
"""
import json, os, random, time, statistics

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
START = 100.0
COST = 0.001
SELL_FEE = 0.01
WINDOWS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
           "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}

def load_bars():
    j = json.load(open(SRC))
    r = j["chart"]["result"][0]
    ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i, t in enumerate(ts):
        c = q["close"][i]
        if c is None: continue
        a = adj[i] if adj[i] else c
        ratio = a / c
        bars.append({"d": time.strftime("%Y-%m-%d", time.gmtime(t)),
                     "o": q["open"][i] * ratio, "h": q["high"][i] * ratio,
                     "l": q["low"][i] * ratio, "c": a})
    return bars

def signals(bars):
    """Return per-bar: colour (+1 green, -1 red, 0 doji), sma200_ok."""
    out = []
    hao = hac = None
    closes = [b["c"] for b in bars]
    for i, b in enumerate(bars):
        hac = (b["o"] + b["h"] + b["l"] + b["c"]) / 4.0
        hao = (b["o"] + b["c"]) / 2.0 if hao is None else (hao_prev + hac_prev) / 2.0
        col = 1 if hac > hao else (-1 if hac < hao else 0)
        sma_ok = False
        if i >= 199:
            sma = sum(closes[i-199:i+1]) / 200.0
            sma_ok = b["c"] > sma
        out.append((col, sma_ok))
        hao_prev, hac_prev = hao, hac
    return out

def run(bars, sig, ws, we, holds=None, holds_seed=0):
    idx = [i for i, b in enumerate(bars) if ws <= b["d"] <= we]
    cash, shares = START, 0.0
    curve, trades, costs = [], [], 0.0
    in_since = None; entry_cost = 0.0
    if holds is not None:
        total_days = len(idx)
        free = total_days - sum(holds)
        gaps = [0] * (len(holds) + 1)
        rng = random.Random(holds_seed)
        for _ in range(max(free, 0)):
            gaps[rng.randrange(len(gaps))] += 1
        schedule = {}
        pos = gaps[0]
        for k, h in enumerate(holds):
            schedule[pos] = h
            pos += h + (gaps[k + 1] if k + 1 < len(gaps) else 0)
        state_hold_left = 0
    green_run = red_run = 0
    pending = None
    for n, i in enumerate(idx):
        b = bars[i]
        if holds is None:
            if pending == "enter" and shares == 0:
                val = cash / (1 + COST); c_ = val * COST
                shares = val / b["o"]; cash -= val + c_; costs += c_
                in_since, entry_cost = b["d"], val + c_
            elif pending == "exit" and shares > 0:
                val = shares * b["o"]; c_ = val * COST + SELL_FEE
                cash += val - c_; costs += c_
                trades.append({"entry": in_since, "exit": b["d"], "ret_pct": round((val - c_) / entry_cost * 100 - 100, 2)})
                shares = 0.0
            pending = None
        else:
            if shares == 0 and n in schedule:
                val = cash / (1 + COST); c_ = val * COST
                shares = val / b["o"]; cash -= val + c_; costs += c_
                in_since, entry_cost = b["d"], val + c_
                state_hold_left = schedule[n]
            elif shares > 0:
                state_hold_left -= 1
                if state_hold_left <= 0:
                    val = shares * b["o"]; c_ = val * COST + SELL_FEE
                    cash += val - c_; costs += c_
                    trades.append({"entry": in_since, "exit": b["d"], "ret_pct": round((val - c_) / entry_cost * 100 - 100, 2)})
                    shares = 0.0
        v = cash + shares * b["c"]
        curve.append((b["d"], round(v, 4)))
        if holds is None:
            col, sma_ok = sig[i]
            green_run = green_run + 1 if col == 1 else 0
            red_run = red_run + 1 if col == -1 else 0
            if shares == 0 and green_run >= 3 and sma_ok:
                pending = "enter"
            elif shares > 0 and red_run >= 2:
                pending = "exit"
    if shares > 0:
        b = bars[idx[-1]]
        val = shares * b["c"]; c_ = val * COST + SELL_FEE
        cash += val - c_; costs += c_
        trades.append({"entry": in_since, "exit": b["d"], "ret_pct": round((val - c_) / entry_cost * 100 - 100, 2)})
        curve[-1] = (b["d"], round(cash, 4))
    return cash, curve, trades, costs

def distribution(curve):
    years = {}
    for d, v in curve:
        years[d[:4]] = v
    yr = {}
    last = START
    for y in sorted(years):
        yr[y] = round((years[y] / last - 1) * 100, 2); last = years[y]
    vals = list(yr.values())
    # longest losing streak of calendar years
    streak = cur = 0
    for v in vals:
        cur = cur + 1 if v < 0 else 0
        streak = max(streak, cur)
    # longest stretch between new highs (trading days)
    peak, peak_i, longest = -1, 0, 0
    for k, (_, v) in enumerate(curve):
        if v >= peak:
            peak, peak_i = v, k
        longest = max(longest, k - peak_i)
    return {"year_returns_pct": yr,
            "median_year_pct": round(statistics.median(vals), 2) if vals else None,
            "share_years_positive_pct": round(100 * sum(1 for v in vals if v > 0) / len(vals), 1) if vals else None,
            "best_year": max(yr.items(), key=lambda kv: kv[1]) if yr else None,
            "worst_year": min(yr.items(), key=lambda kv: kv[1]) if yr else None,
            "longest_losing_year_streak": streak,
            "longest_days_between_new_highs": longest}

def stats(curve, trades, costs):
    peak, mdd = -1, 0.0
    for _, v in curve:
        peak = max(peak, v); mdd = max(mdd, (peak - v) / peak if peak > 0 else 0)
    st = {"final": round(curve[-1][1], 2), "max_drawdown_pct": round(mdd * 100, 2),
          "costs": round(costs, 2), "trades": len(trades)}
    st.update(distribution(curve))
    return st

def buy_hold(bars, ws, we):
    idx = [i for i, b in enumerate(bars) if ws <= b["d"] <= we]
    b0 = bars[idx[0]]
    val = START / (1 + COST); sh = val / b0["o"]
    curve = [(bars[i]["d"], round(sh * bars[i]["c"], 4)) for i in idx]
    bl = bars[idx[-1]]; tot = sh * bl["c"]; c_ = tot * COST + SELL_FEE
    curve[-1] = (bl["d"], round(tot - c_, 4))
    return stats(curve, [], 0.0)

def main():
    bars = load_bars(); sig = signals(bars)
    out = {"strategy": "V13 BEST RULES F-6 Heikin-Ashi (see BEST-RULES-SPEC.md)",
           "floor": None, "costs": "0.10%/side + $0.01/sell", "windows": {}}
    for name, (ws, we) in WINDOWS.items():
        final, curve, trades, costs = run(bars, sig, ws, we)
        st = stats(curve, trades, costs)
        dmap = {d: k for k, (d, _) in enumerate(curve)}
        holds = []
        for t in trades:
            if t["entry"] in dmap and t["exit"] in dmap:
                holds.append(max(dmap[t["exit"]] - dmap[t["entry"]], 1))
        pfin = []
        for seed in range(1, 21):
            h = holds[:]; random.Random(seed).shuffle(h)
            pf, pc, pt, pcost = run(bars, sig, ws, we, holds=h, holds_seed=seed)
            pfin.append(round(pf, 2))
        beaten = sum(1 for x in pfin if final > x)
        bh = buy_hold(bars, ws, we)
        out["windows"][name] = {"window": [ws, we], "ranked": st, "curve": curve,
                                "trades_list": trades, "buy_hold_spy": bh,
                                "placebo_finals": sorted(pfin), "placebo_beaten": f"{beaten}/20",
                                "placebo_median": round(statistics.median(pfin), 2)}
        print(f"{name}: best-rules HA ${st['final']} (DD {st['max_drawdown_pct']}%, costs ${st['costs']}, "
              f"trades {st['trades']}, worst yr {st['worst_year']}) | SPY BH ${bh['final']} | placebo beaten {beaten}/20 (median ${out['windows'][name]['placebo_median']})", flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE")

if __name__ == "__main__":
    main()
