"""V13 best-rules run: Larry Williams Volatility Breakout.
Spec: BEST-RULES-SPEC.md (frozen before this run).
Chassis functions (simulate_trades / simulate_states / buy_hold / period_stats /
placebo convention / costs) copied from the v12 folder's run_vb.py, unchanged.
New code is only BUILD_TRADES, implementing the frozen v13 rules."""
import json, os, time, random, statistics
from datetime import date

START = 100.0
STK_COST = 0.001; STK_SELL_FEE = 0.01
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
PXDIR = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")

def load_stock(sym):
    j = json.load(open(os.path.join(PXDIR, f"pxfull_{sym}.json")))
    r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i, t in enumerate(ts):
        if None in (q["close"][i], adj[i], q["open"][i], q["high"][i], q["low"][i]):
            continue
        ratio = adj[i] / q["close"][i]
        bars.append({"d": time.strftime("%Y-%m-%d", time.gmtime(t)),
                     "o": q["open"][i]*ratio, "h": q["high"][i]*ratio,
                     "l": q["low"][i]*ratio, "c": adj[i]})
    bars.sort(key=lambda b: b["d"])
    return bars

def simulate_trades(bars, trades, start, end, cost, sell_fee, chassis=False):
    days = [i for i, b in enumerate(bars) if b["d"] >= start and b["d"] <= end]
    if not days: return None
    dayset = set(days)
    tl = sorted([t for t in trades if t["entry_idx"] in dayset], key=lambda t: t["entry_idx"])
    cash, shares = START, 0.0
    costs = 0.0; done = []; curve = []
    active = None
    ti = 0
    days_invested = 0
    for n, i in enumerate(days):
        b = bars[i]
        if active is not None and i == active[0]:
            val = shares * active[1]; fee = val * cost + sell_fee
            cash += val - fee; costs += fee; shares = 0.0
            done.append([b["d"], "SELL", round(active[1], 4), round(val, 2), round(fee, 2)])
            active = None
        while ti < len(tl) and tl[ti]["entry_idx"] == i:
            t = tl[ti]; ti += 1
            if active is None and shares == 0.0 and cash > 0:
                bv = cash / (1 + cost); fee = bv * cost
                shares = bv / t["entry_px"]; cash -= bv + fee; costs += fee
                active = (t["exit_idx"], t["exit_px"])
                done.append([b["d"], "BUY-" + t["kind"], round(t["entry_px"], 4), round(bv, 2), round(fee, 2)])
        while ti < len(tl) and tl[ti]["entry_idx"] < i:
            ti += 1
        eq = cash + shares * b["c"]
        if shares > 0: days_invested += 1
        curve.append([b["d"], round(eq, 4)])
    if shares > 0 and active is not None:
        last = bars[days[-1]]; val = shares * last["c"]; fee = val * cost + sell_fee
        cash += val - fee; costs += fee; shares = 0.0
        done.append([last["d"], "SELL-END", round(last["c"], 4), round(val, 2), round(fee, 2)])
        curve[-1] = [last["d"], round(cash, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0: maxdd = max(maxdd, (peak - v) / peak)
    ntr = sum(1 for t in done if t[1].startswith("BUY"))
    return {"final": round(cash, 2), "max_dd_pct": round(maxdd*100, 2),
            "costs": round(costs, 2), "orders": len(done), "trades_taken": ntr,
            "trades": done, "invested_pct": round(100.0*days_invested/len(days), 1) if days else 0.0,
            "equity_curve": curve}

def simulate_states(bars, states, start, end, cost, sell_fee, shift_seed=None):
    idx = [i for i, b in enumerate(bars) if b["d"] >= start and b["d"] <= end]
    if not idx: return None
    st = list(states)
    if shift_seed is not None:
        seg = [states[i] for i in idx]
        pre = states[idx[0]-1] if idx[0] > 0 else 0
        rng = random.Random(shift_seed)
        if len(seg) > 1:
            k = rng.randrange(1, len(seg))
            seg = seg[k:] + seg[:k]
        for j, i in enumerate(idx): st[i] = seg[j]
        entry_state = pre
    else:
        entry_state = states[idx[0]-1] if idx[0] > 0 else 0
    cash, shares, costs = START, 0.0, 0.0
    trades, curve = [], []
    pending = entry_state
    days_invested = 0
    for n, i in enumerate(idx):
        b = bars[i]
        if pending is not None:
            if pending == 1 and shares == 0.0 and cash > 0:
                bv = cash / (1 + cost); fee = bv * cost
                shares = bv / b["o"]; cash -= bv + fee; costs += fee
                trades.append([b["d"], "BUY", round(b["o"], 4), round(bv, 2), round(fee, 2)])
            elif pending == 0 and shares > 0:
                val = shares * b["o"]; fee = val * cost + sell_fee
                cash += val - fee; costs += fee; shares = 0.0
                trades.append([b["d"], "SELL", round(b["o"], 4), round(val, 2), round(fee, 2)])
            pending = None
        if st[i] != (1 if shares > 0 else 0):
            pending = st[i]
        eq = cash + shares * b["c"]
        if shares > 0: days_invested += 1
        curve.append([b["d"], round(eq, 4)])
    if shares > 0:
        last = bars[idx[-1]]; val = shares * last["c"]; fee = val * cost + sell_fee
        cash += val - fee; costs += fee; shares = 0.0
        trades.append([last["d"], "SELL-END", round(last["c"], 4), round(val, 2), round(fee, 2)])
        curve[-1] = [last["d"], round(cash, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0: maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(cash, 2), "max_dd_pct": round(maxdd*100, 2),
            "costs": round(costs, 2), "orders": len(trades), "trades": trades,
            "invested_pct": round(100.0*days_invested/len(idx), 1) if idx else 0.0,
            "equity_curve": curve}

def buy_hold(bars, start, end, cost, sell_fee):
    days = [b for b in bars if (start is None or b["d"] >= start) and b["d"] <= end]
    if not days: return None
    sh = (START / (1 + cost)) / days[0]["o"]
    curve = [[b["d"], round(sh * b["c"], 4)] for b in days]
    val = sh * days[-1]["c"]; final = val - (val * cost + sell_fee)
    curve[-1] = [days[-1]["d"], round(final, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0: maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(final, 2), "max_dd_pct": round(maxdd*100, 2), "equity_curve": curve}

def period_stats(curve, tempo="monthly"):
    if not curve: return None
    if tempo == "daily":
        vals = [v for _, v in curve]
    else:
        seen = {}
        for d, v in curve:
            if tempo == "monthly": k = d[:7]
            elif tempo == "quarterly": k = d[:4] + "Q" + str((int(d[5:7])-1)//3)
            else: k = d[:7]
            seen[k] = v
        vals = [seen[k] for k in sorted(seen)]
    series = [START] + vals
    if len(series) < 2: return None
    rets = [(series[i]/series[i-1] - 1.0)*100.0 if series[i-1] > 0 else 0.0
            for i in range(1, len(series))]
    pos = sum(1 for r in rets if r > 0)
    streak = worst = 0
    for r in rets:
        if r < 0: streak += 1; worst = max(worst, streak)
        else: streak = 0
    peak = series[0]; last_high = 0; longest = 0
    for i, v in enumerate(series):
        if v >= peak: peak = v; longest = max(longest, i - last_high); last_high = i
    longest = max(longest, len(series)-1-last_high)
    return {"tempo": tempo, "periods": len(rets),
            "pct_positive": round(100.0*pos/len(rets), 1),
            "median_pct": round(statistics.median(rets), 3),
            "mean_pct_secondary_average_only": round(statistics.mean(rets), 3),
            "best_pct": round(max(rets), 2), "worst_pct": round(min(rets), 2),
            "longest_losing_streak_periods": worst,
            "longest_between_highs_periods": longest}

def placebo_states(bars, states, start, end, cost, sell_fee, n=20):
    finals = []
    for seed in range(1, n+1):
        r = simulate_states(bars, states, start, end, cost, sell_fee, shift_seed=seed)
        finals.append(r["final"] if r else None)
    return finals

def trades_to_states(bars, trades):
    st = [0]*len(bars)
    for t in trades:
        for i in range(t["entry_idx"], min(t["exit_idx"], len(bars))):
            st[i] = 1
    return st

# ---------------- V13 BEST-RULES trade builder (the frozen spec) ----------------
K = 0.5            # Williams' published central coefficient — NOT re-tuned
MAX_HOLD = 10      # trading days, pre-committed cap from the spec

def BUILD_TRADES(bars):
    """Long stop at Open_t + 0.5 x prior-day range; taken only if prior close >
    200d SMA of prior closes (point-in-time). Enter at stop (gap-through at the
    open). Exit at next open after first close below the ENTRY day's low, or at
    the open of day entry+10, whichever first. Single position."""
    n = len(bars)
    closes = [b["c"] for b in bars]
    sma200 = [None]*n
    run = 0.0
    for i, c in enumerate(closes):
        run += c
        if i >= 200: run -= closes[i-200]
        if i >= 199: sma200[i] = run/200.0
    trades = []
    t = 1
    while t < n - 1:
        prev = sma200[t-1]
        if prev is None or closes[t-1] <= prev:
            t += 1; continue
        rng = bars[t-1]["h"] - bars[t-1]["l"]
        level = bars[t]["o"] + K * rng
        if bars[t]["h"] < level:
            t += 1; continue
        entry_px = max(level, bars[t]["o"])
        entry_low = bars[t]["l"]
        exit_idx = min(t + MAX_HOLD, n - 1)
        exit_px = bars[exit_idx]["o"]
        for s in range(t+1, min(t + MAX_HOLD, n - 1)):
            if closes[s] < entry_low:
                exit_idx = s + 1; exit_px = bars[s+1]["o"]
                break
        if exit_idx <= t:  # data edge: exit at last close
            exit_idx = t; exit_px = bars[t]["c"]
        trades.append({"entry_idx": t, "entry_px": entry_px,
                       "exit_idx": exit_idx, "exit_px": exit_px, "kind": "VB13"})
        t = exit_idx  # single position: next possible entry is the exit day itself onward
    return trades

def trade_pnls(bars, trades, start, end):
    """Per-trade net returns (%) for trades entered inside the road, at program
    costs on a notional pot share — expectancy evidence (win rate is secondary)."""
    idx = [i for i, b in enumerate(bars) if b["d"] >= start and b["d"] <= end]
    dayset = set(idx)
    out = []
    for t in trades:
        if t["entry_idx"] not in dayset: continue
        gross = t["exit_px"]/t["entry_px"] - 1.0
        net = (1+gross)*(1-STK_COST) - STK_SELL_FEE/ (100.0)  # approx fee drag on $100 scale
        out.append(round(((1+gross)*(1-2*STK_COST) - 1.0)*100.0, 3))
    return out

def main():
    out = {"family": "hunt-williams-volatility-breakout (Larry Williams Volatility Breakout) — V13 BEST RULES",
           "spec": "BEST-RULES-SPEC.md frozen before run; k=0.5 published; 200d-SMA prior-close regime gate; exit = next open after first close below entry-day low, or open of entry+10; NO floor; SPY only",
           "chassis": "$100 pot; stocks 0.10%/side + $0.01 sell fee; daily-bar approximation of an intraday trigger (named in spec)",
           "champions_vm": CHAMP, "spy_ref": SPYREF}
    bars = load_stock("SPY")
    trades = BUILD_TRADES(bars)
    states = trades_to_states(bars, trades)
    out["data_range"] = f"{bars[0]['d']} -> {bars[-1]['d']}"
    out["signals_total_full_history"] = len(trades)
    out["roads"] = {}
    for name, (s, e) in ROADS.items():
        r = simulate_trades(bars, trades, s, e, STK_COST, STK_SELL_FEE)
        bh = buy_hold(bars, s, e, STK_COST, STK_SELL_FEE)
        pf = placebo_states(bars, states, s, e, STK_COST, STK_SELL_FEE)
        pnls = trade_pnls(bars, trades, s, e)
        wins = sum(1 for p in pnls if p > 0)
        rec = {"my_rules": {**r, "period_stats_monthly": period_stats(r["equity_curve"], "monthly")},
               "benchmark_hold": {"name": "SPY buy-and-hold", "final": bh["final"], "max_dd_pct": bh["max_dd_pct"]},
               "champion_vm": CHAMP[name], "spy_program_ref": SPYREF[name],
               "placebo": {"seed_finals": pf, "beaten_of_20": sum(1 for p in pf if r["final"] > p),
                           "design": "circular shift of holding-state series within road, fills at opens (v12 chassis convention)"},
               "trade_stats": {"n": len(pnls),
                               "win_rate_pct_secondary": round(100.0*wins/len(pnls), 1) if pnls else None,
                               "mean_net_pct_per_trade": round(statistics.mean(pnls), 3) if pnls else None,
                               "median_net_pct_per_trade": round(statistics.median(pnls), 3) if pnls else None}}
        out["roads"][name] = rec
        print(f"{name}: my-rules ${r['final']} (DD {r['max_dd_pct']}%, trades {r['trades_taken']}, costs ${r['costs']}, invested {r['invested_pct']}%) "
              f"hold ${bh['final']} champ ${CHAMP[name]} placebos {rec['placebo']['beaten_of_20']}/20", flush=True)
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE")

if __name__ == "__main__":
    main()
