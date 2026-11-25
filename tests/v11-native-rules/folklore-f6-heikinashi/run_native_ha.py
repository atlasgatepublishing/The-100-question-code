#!/usr/bin/env python3
"""
V11 NATIVE — F-6 Heikin-Ashi, Valcu strong-trend form. Simulation only.

Frozen spec: see NATIVE-SPEC.md in this folder. In brief:
  HA formulas per Valcu (2004). Qualifying (strong-trend) candle = green
  (HA-Close > HA-Open) AND no lower shadow (HA-Low == HA-Open).
  Enter SPY at the next REAL open after 2 consecutive qualifying candles.
  Exit at the next REAL open after the first non-qualifying candle.
  $100 pot, 100% in/out, long-only, NO pot floor (none exists natively).
  Costs 0.10%/side + $0.01 per sell order, on real prices.
  Placebos: 20 seeds, shuffled holding-block design (v7 F-6 reading R5):
  the ranked run's holding durations shuffled and re-placed as
  non-overlapping blocks; identical costs/execution.
Data: read-only ~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json
  (dividend-adjusted via adjclose/close ratio, champion convention).
"""
import json, os, random, time

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

def ha_series(bars):
    out = []
    hao = hac = None
    for b in bars:
        hac = (b["o"] + b["h"] + b["l"] + b["c"]) / 4.0
        hao = (b["o"] + b["c"]) / 2.0 if hao is None else (hao_prev + hac_prev) / 2.0
        hal = min(b["l"], hao, hac)
        qual = (hac > hao) and abs(hal - hao) < 1e-9
        out.append(qual)
        hao_prev, hac_prev = hao, hac
    return out

def run(bars, qual, ws, we, holds=None):
    """holds=None -> ranked signal run; holds=list of durations -> placebo blocks."""
    idx = [i for i, b in enumerate(bars) if ws <= b["d"] <= we]
    cash, shares = START, 0.0
    curve, trades, costs = [], [], 0.0
    in_since = None; entry_px = None; entry_cost = 0.0
    if holds is not None:
        # build in/out schedule: place blocks with gaps from multinomial-ish spacing
        total_days = len(idx)
        free = total_days - sum(holds)
        gaps = [0] * (len(holds) + 1)
        rng = random.Random(holds_seed)
        for _ in range(max(free, 0)):
            gaps[rng.randrange(len(gaps))] += 1
        schedule = {}
        pos = gaps[0]
        for k, h in enumerate(holds):
            schedule[pos] = ("enter", h)
            pos += h + (gaps[k + 1] if k + 1 < len(gaps) else 0)
        state_hold_left = 0
    consec = 0
    pending = None  # 'enter' or 'exit' to execute at today's open
    for n, i in enumerate(idx):
        b = bars[i]
        # execute pending at open
        if holds is None:
            if pending == "enter" and shares == 0:
                val = cash / (1 + COST); c_ = val * COST
                shares = val / b["o"]; cash -= val + c_; costs += c_
                in_since, entry_px, entry_cost = b["d"], b["o"], val + c_
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
                in_since, entry_px, entry_cost = b["d"], b["o"], val + c_
                state_hold_left = schedule[n][1]
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
            consec = consec + 1 if qual[i] else 0
            if shares == 0 and consec >= 2:
                pending = "enter"
            elif shares > 0 and not qual[i]:
                pending = "exit"
    if shares > 0:
        b = bars[idx[-1]]
        val = shares * b["c"]; c_ = val * COST + SELL_FEE
        cash += val - c_; costs += c_
        trades.append({"entry": in_since, "exit": b["d"], "ret_pct": round((val - c_) / entry_cost * 100 - 100, 2)})
        curve[-1] = (b["d"], round(cash, 4))
    # holding durations in event days (entry idx -> exit idx) for placebo design:
    return cash, curve, trades, costs

def stats(curve, trades, costs):
    peak, mdd = -1, 0.0
    for _, v in curve:
        peak = max(peak, v); mdd = max(mdd, (peak - v) / peak if peak > 0 else 0)
    years = {}
    prev = START
    for d, v in curve:
        years[d[:4]] = v
    yr = {}
    last = START
    for y in sorted(years):
        yr[y] = round((years[y] / last - 1) * 100, 2); last = years[y]
    worst_year = min(yr.items(), key=lambda kv: kv[1]) if yr else None
    return {"final": round(curve[-1][1], 2), "max_drawdown_pct": round(mdd * 100, 2),
            "costs": round(costs, 2), "trades": len(trades),
            "worst_year": worst_year, "year_returns_pct": yr}

def buy_hold(bars, ws, we):
    idx = [i for i, b in enumerate(bars) if ws <= b["d"] <= we]
    b0 = bars[idx[0]]
    val = START / (1 + COST); sh = val / b0["o"]
    curve = [(bars[i]["d"], round(sh * bars[i]["c"], 4)) for i in idx]
    bl = bars[idx[-1]]; tot = sh * bl["c"]; c_ = tot * COST + SELL_FEE
    curve[-1] = (bl["d"], round(tot - c_, 4))
    return stats(curve, [], 0.0)

def main():
    global holds_seed
    bars = load_bars(); qual = ha_series(bars)
    out = {"strategy": "V11 NATIVE F-6 Heikin-Ashi Valcu strong-trend form (see NATIVE-SPEC.md)",
           "floor": None, "costs": "0.10%/side + $0.01/sell", "windows": {}}
    for name, (ws, we) in WINDOWS.items():
        final, curve, trades, costs = run(bars, qual, ws, we)
        st = stats(curve, trades, costs)
        # holding durations from trades: recompute via day counts in window
        dmap = {d: k for k, (d, _) in enumerate(curve)}
        holds = []
        for t in trades:
            if t["entry"] in dmap and t["exit"] in dmap:
                holds.append(max(dmap[t["exit"]] - dmap[t["entry"]], 1))
        pfin = []
        for seed in range(1, 21):
            holds_seed = seed
            random.seed(seed)
            h = holds[:]; random.shuffle(h)
            pf, pc, pt, pcost = run(bars, qual, ws, we, holds=h)
            pfin.append(round(pf, 2))
        beaten = sum(1 for x in pfin if final > x)
        bh = buy_hold(bars, ws, we)
        out["windows"][name] = {"window": [ws, we], "ranked": st, "curve": curve,
                                "trades_list": trades, "buy_hold_spy": bh,
                                "placebo_finals": sorted(pfin), "placebo_beaten": f"{beaten}/20"}
        print(f"{name}: native HA ${st['final']} (DD {st['max_drawdown_pct']}%, costs ${st['costs']}, "
              f"trades {st['trades']}, worst yr {st['worst_year']}) | SPY BH ${bh['final']} | placebo beaten {beaten}/20", flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE")

if __name__ == "__main__":
    main()
