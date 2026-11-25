"""Shared v12 slice-8 engine core (copied into each family folder's run script).
Program standard: $100 pot; stocks 0.10%/side + $0.01 sell fee; crypto 0.60%/side.
House v9 chassis: -15% floor vs episode start on daily closes; breach -> liquidate
next open, halt 90 days; second breach ends the run (coppock precedent)."""
import json, os, time, random, statistics
from datetime import date

START = 100.0
STK_COST = 0.001; STK_SELL_FEE = 0.01; CRY_COST = 0.006
ROADS = {"LONG": ("2010-01-01", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-01", "2026-11-20"), "VAL": ("2023-01-01", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
PXDIR = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
CRYPTO_PIT = os.path.expanduser("~/workspace/stock-app/backtests/v4/crypto-basket-pit-data")
CRYPTO_TREND = os.path.expanduser("~/workspace/stock-app/backtests/v4/crypto-trend-data")

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

def pond_symbols():
    return sorted(f[7:-5] for f in os.listdir(PXDIR)
                  if f.startswith("pxfull_") and f[7:-5] != "SPY")

COIN_FILEMAP = {"LUNA": "y_LUNC-USD.json", "UST": "y_USTC-USD.json",
                "MATIC": "b_MATICUSDT.json", "MIOTA": "b_IOTAUSDT.json",
                "PEPE": "b_PEPEUSDT.json", "POL": "b_POLUSDT.json",
                "SUI": "b_SUIUSDT.json", "UNI": "b_UNIUSDT.json",
                "USD1": "b_USD1USDT.json", "USDe": "b_USDEUSDT.json",
                "TON": "k_TONUSD.json"}
COIN_NO_DATA = ["BCC","CC","DGD","FCT","GAME","GNT","GRAM","HYPE","ICN","M","MAID",
                "STRAT","VEN","HC","MIN","PAY","TAGZ5","NANO","SNGLS"]

def coin_universe():
    snap = json.load(open(os.path.join(CRYPTO_PIT, "snapshots.json")))
    coins = set()
    for v in snap.values():
        for e in v["top20"]:
            coins.add(e["symbol"])
    return sorted(coins)

def load_coin(sym):
    """Returns bars with o/h/l/c; h/l are OC-range proxies except BTC/ETH (true OHLC)."""
    if sym in ("BTC", "ETH"):
        p = os.path.join(CRYPTO_TREND, f"{sym}-USD.csv")
        bars = []
        with open(p) as f:
            next(f)
            for line in f:
                pp = line.strip().split(",")
                if len(pp) < 5: continue
                bars.append({"d": pp[0], "o": float(pp[1]), "h": float(pp[2]),
                             "l": float(pp[3]), "c": float(pp[4])})
        bars.sort(key=lambda b: b["d"])
        return bars, False
    fn = COIN_FILEMAP.get(sym, f"y_{sym}-USD.json")
    p = os.path.join(CRYPTO_PIT, fn)
    if not os.path.exists(p): return None, True
    raw = json.load(open(p))
    bars, seen = [], set()
    for r in raw:
        if r["d"] in seen: continue
        seen.add(r["d"])
        o, c = float(r["o"]), float(r["c"])
        if o <= 0 or c <= 0: continue
        bars.append({"d": r["d"], "o": o, "h": max(o, c), "l": min(o, c), "c": c})
    bars.sort(key=lambda b: b["d"])
    if len(bars) < 10: return None, True
    return bars, True

def simulate_states(bars, states, start, end, cost, sell_fee, chassis=False,
                    shift_seed=None):
    """states[t] in {0,1} decided at close of bar t (full-history aligned).
    Executes changes at the NEXT bar's open. Road entry state = last state
    before the road. shift_seed: circular-shift the road-segment states
    (placebo, matched-holding timer convention)."""
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
    ep_start, halts, halt_until, ended = START, 0, None, False
    days_invested = 0
    pos_days = idx
    for n, i in enumerate(pos_days):
        b = bars[i]
        if halt_until is not None and b["d"] >= halt_until:
            halt_until = None; ep_start = cash + shares * b["o"]
        if pending is not None and halt_until is None and not ended:
            if pending == 1 and shares == 0.0 and cash > 0:
                bv = cash / (1 + cost); fee = bv * cost
                shares = bv / b["o"]; cash -= bv + fee; costs += fee
                trades.append([b["d"], "BUY", round(b["o"], 4), round(bv, 2), round(fee, 2)])
            elif pending == 0 and shares > 0:
                val = shares * b["o"]; fee = val * cost + sell_fee
                cash += val - fee; costs += fee; shares = 0.0
                trades.append([b["d"], "SELL", round(b["o"], 4), round(val, 2), round(fee, 2)])
            pending = None
        if st[i] != (1 if shares > 0 else 0) and halt_until is None and not ended:
            pending = st[i]
        eq = cash + shares * b["c"]
        if shares > 0: days_invested += 1
        curve.append([b["d"], round(eq, 4)])
        if chassis and not ended and halt_until is None and eq <= 0.85 * ep_start:
            halts += 1
            if n + 1 < len(pos_days):
                nb = bars[pos_days[n+1]]
                if shares > 0:
                    val = shares * nb["o"]; fee = val * cost + sell_fee
                    cash += val - fee; costs += fee; shares = 0.0
                    trades.append([nb["d"], "SELL-FLOOR", round(nb["o"], 4), round(val, 2), round(fee, 2)])
                    curve.append([nb["d"], round(cash, 4)]) if False else None
            if halts == 1:
                halt_until = date.fromordinal(date.fromisoformat(b["d"]).toordinal() + 90).isoformat()
            else:
                ended = True
    if shares > 0:
        last = bars[pos_days[-1]]; val = shares * last["c"]; fee = val * cost + sell_fee
        cash += val - fee; costs += fee; shares = 0.0
        trades.append([last["d"], "SELL-END", round(last["c"], 4), round(val, 2), round(fee, 2)])
        curve[-1] = [last["d"], round(cash, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0: maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(cash, 2), "max_dd_pct": round(maxdd*100, 2),
            "costs": round(costs, 2), "orders": len(trades), "trades": trades,
            "invested_pct": round(100.0*days_invested/len(pos_days), 1) if pos_days else 0.0,
            "halts": halts, "equity_curve": curve}

def simulate_targets(bars, targets, start, end, cost, sell_fee, chassis=False):
    """targets: dict date->0/1, the desired state decided at that date's close;
    changes execute at the next bar's open. Entry state = last target before road."""
    days = [b for b in bars if b["d"] >= start and b["d"] <= end]
    if not days: return None
    by = {b["d"]: b for b in bars}
    desired = 0
    for d in sorted(targets):
        if d < days[0]["d"]: desired = targets[d]
    cash, shares, costs = START, 0.0, 0.0
    trades, curve = [], []
    pending = desired if desired else None
    ep_start, halts, halt_until, ended = START, 0, None, False
    days_invested = 0
    for n, b in enumerate(days):
        if halt_until is not None and b["d"] >= halt_until:
            halt_until = None; ep_start = cash + shares * b["o"]
        if pending is not None and halt_until is None and not ended:
            if pending == 1 and shares == 0.0 and cash > 0:
                bv = cash / (1 + cost); fee = bv * cost
                shares = bv / b["o"]; cash -= bv + fee; costs += fee
                trades.append([b["d"], "BUY", round(b["o"], 4), round(bv, 2), round(fee, 2)])
            elif pending == 0 and shares > 0:
                val = shares * b["o"]; fee = val * cost + sell_fee
                cash += val - fee; costs += fee; shares = 0.0
                trades.append([b["d"], "SELL", round(b["o"], 4), round(val, 2), round(fee, 2)])
            pending = None
        if b["d"] in targets:
            t = targets[b["d"]]
            if t != (1 if shares > 0 else 0) and halt_until is None and not ended:
                pending = t
            desired = t
        eq = cash + shares * b["c"]
        if shares > 0: days_invested += 1
        curve.append([b["d"], round(eq, 4)])
        if chassis and not ended and halt_until is None and eq <= 0.85 * ep_start:
            halts += 1
            if n + 1 < len(days):
                nb = days[n+1]
                if shares > 0:
                    val = shares * nb["o"]; fee = val * cost + sell_fee
                    cash += val - fee; costs += fee; shares = 0.0
                    trades.append([nb["d"], "SELL-FLOOR", round(nb["o"], 4), round(val, 2), round(fee, 2)])
            if halts == 1:
                halt_until = date.fromordinal(date.fromisoformat(b["d"]).toordinal() + 90).isoformat()
            else:
                ended = True
    if shares > 0:
        last = days[-1]; val = shares * last["c"]; fee = val * cost + sell_fee
        cash += val - fee; costs += fee; shares = 0.0
        trades.append([last["d"], "SELL-END", round(last["c"], 4), round(val, 2), round(fee, 2)])
        curve[-1] = [last["d"], round(cash, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0: maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(cash, 2), "max_dd_pct": round(maxdd*100, 2),
            "costs": round(costs, 2), "orders": len(trades), "trades": trades,
            "invested_pct": round(100.0*days_invested/len(days), 1) if days else 0.0,
            "halts": halts, "equity_curve": curve}

def buy_hold(bars, start, end, cost, sell_fee):
    days = [b for b in bars if (start is None or b["d"] >= start) and b["d"] <= end]
    if not days: return None
    by = {b["d"]: b for b in days}
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
    """Resample equity curve to period-end values at the given tempo and
    report the program distribution (median is the headline)."""
    if not curve: return None
    if tempo == "daily":
        vals = [v for _, v in curve]; keys = [d for d, _ in curve]
    else:
        seen = {}
        for d, v in curve:
            if tempo == "monthly": k = d[:7]
            elif tempo == "weekly":
                y, m, dd = map(int, d.split("-"))
                k = str(date(y, m, dd).isocalendar()[:2])
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

FAMILY = "hunt-williams-oops (Larry Williams Oops! pattern + Smash Day variant, 1979/1999)"
def BUILD_TRADES(bars):
    """FORM A (Oops!): open below prior low AND same-day high reaches the prior
    low -> enter at prior low x 1.001 (frozen +0.1% tick translation); exit at
    next day's open. The published stop (below the entry day's low) cannot bind
    before the next-open exit on daily bars — named approximation, printed.
    VARIANT B (Smash Day): day closes below prior low -> next day, if high >
    smash-day high, enter at that high (gap-through fills at the open);
    exit at the following day's open. Both variants in one trade stream,
    one position at a time (simulator skips overlaps)."""
    n = len(bars)
    trades = []
    for t in range(1, n - 1):
        o, h, l = bars[t]["o"], bars[t]["h"], bars[t]["l"]
        pl = bars[t-1]["l"]
        if o < pl and h >= pl:
            trades.append({"entry_idx": t, "entry_px": pl * 1.001,
                           "exit_idx": t + 1, "exit_px": bars[t+1]["o"], "kind": "OOPS-A"})
    for t in range(1, n - 2):
        if bars[t]["c"] < bars[t-1]["l"]:
            sh = bars[t]["h"]
            if bars[t+1]["h"] > sh:
                trades.append({"entry_idx": t + 1, "entry_px": max(sh, bars[t+1]["o"]),
                               "exit_idx": t + 2, "exit_px": bars[t+2]["o"], "kind": "SMASH-B"})
    trades.sort(key=lambda x: x["entry_idx"])
    return trades


# BUILD_TRADES(bars) -> list of dicts {entry_idx, entry_px, exit_idx, exit_px, kind}
# aligned to the bars list passed in. Inserted above this line.

def simulate_trades(bars, trades, start, end, cost, sell_fee, chassis=False):
    days = [i for i, b in enumerate(bars) if b["d"] >= start and b["d"] <= end]
    if not days: return None
    dayset = set(days)
    tl = sorted([t for t in trades if t["entry_idx"] in dayset], key=lambda t: t["entry_idx"])
    cash, shares = START, 0.0
    costs = 0.0; done = []; curve = []
    active = None  # (exit_idx, exit_px)
    ep_start, halts, halt_until, ended = START, 0, None, False
    ti = 0
    days_invested = 0
    for n, i in enumerate(days):
        b = bars[i]
        if halt_until is not None and b["d"] >= halt_until:
            halt_until = None; ep_start = cash + shares * b["o"]
        # exit at today's open-priced exit (exit_px precomputed; exit at bar open events use exit_idx bar)
        if active is not None and i == active[0]:
            val = shares * active[1]; fee = val * cost + sell_fee
            cash += val - fee; costs += fee; shares = 0.0
            done.append([b["d"], "SELL", round(active[1], 4), round(val, 2), round(fee, 2)])
            active = None
        # entries
        while ti < len(tl) and tl[ti]["entry_idx"] == i:
            t = tl[ti]; ti += 1
            if active is None and shares == 0.0 and cash > 0 and not ended and halt_until is None:
                bv = cash / (1 + cost); fee = bv * cost
                shares = bv / t["entry_px"]; cash -= bv + fee; costs += fee
                active = (t["exit_idx"], t["exit_px"])
                done.append([b["d"], "BUY-" + t["kind"], round(t["entry_px"], 4), round(bv, 2), round(fee, 2)])
        while ti < len(tl) and tl[ti]["entry_idx"] < i:
            ti += 1
        eq = cash + shares * b["c"]
        if shares > 0: days_invested += 1
        curve.append([b["d"], round(eq, 4)])
        if chassis and not ended and halt_until is None and eq <= 0.85 * ep_start:
            halts += 1
            if active is not None and n + 1 < len(days):
                nb = bars[days[n+1]]
                val = shares * nb["o"]; fee = val * cost + sell_fee
                cash += val - fee; costs += fee; shares = 0.0
                done.append([nb["d"], "SELL-FLOOR", round(nb["o"], 4), round(val, 2), round(fee, 2)])
                active = None
            if halts == 1:
                halt_until = date.fromordinal(date.fromisoformat(b["d"]).toordinal() + 90).isoformat()
            else:
                ended = True
    if shares > 0 and active is not None:
        # position still open past road end: mark out at last close
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
            "halts": halts, "equity_curve": curve}

def trades_to_states(bars, trades):
    st = [0]*len(bars)
    for t in trades:
        for i in range(t["entry_idx"], min(t["exit_idx"], len(bars))):
            st[i] = 1
    return st

def run_asset_events(bars, cost, sell_fee, roads, bench_name, detail=False):
    trades = BUILD_TRADES(bars)
    out = {"data_range": f"{bars[0]['d']} -> {bars[-1]['d']}",
           "signals_total": len(trades), "roads": {}}
    states = trades_to_states(bars, trades)
    for name, (s, e) in roads.items():
        s0 = s or bars[0]["d"]
        rec = {}
        for form, ch in (("native", False), ("house_v9", True)):
            r = simulate_trades(bars, trades, s0, e, cost, sell_fee, chassis=ch)
            rec[form] = {**r, "period_stats_monthly": period_stats(r["equity_curve"], "monthly"),
                         "period_stats_daily": period_stats(r["equity_curve"], "daily")}
        bh = buy_hold(bars, s, e, cost, sell_fee)
        rec["benchmark_hold"] = {"name": bench_name, "final": bh["final"], "max_dd_pct": bh["max_dd_pct"],
                                 "period_stats_monthly": period_stats(bh["equity_curve"], "monthly")}
        pf = placebo_states(bars, states, s0, e, cost, sell_fee)
        rec["placebo_native"] = {"seed_finals": pf,
                                 "beaten_of_20": sum(1 for p in pf if rec["native"]["final"] > p),
                                 "design": "circular shift of the holding-day state series within the road, fills at opens (matched-exposure placebo; the real run uses the frozen event fills)"}
        out["roads"][name] = rec
    return out

def run_pond_events():
    agg = {name: {"native": [], "house_v9": [], "hold": [], "beat": 0, "n": 0} for name in ROADS}
    per_name = {}
    for sym in pond_symbols():
        try: bars = load_stock(sym)
        except Exception: continue
        if len(bars) < 300: continue
        trades = BUILD_TRADES(bars)
        per_name[sym] = {}
        for name, (s, e) in ROADS.items():
            rn = simulate_trades(bars, trades, s, e, STK_COST, STK_SELL_FEE)
            rh = simulate_trades(bars, trades, s, e, STK_COST, STK_SELL_FEE, chassis=True)
            bh = buy_hold(bars, s, e, STK_COST, STK_SELL_FEE)
            if not rn or not bh: continue
            per_name[sym][name] = {"native": rn["final"], "house_v9": rh["final"],
                                   "hold": bh["final"], "trades": rn["trades_taken"]}
            a = agg[name]
            a["native"].append(rn["final"]); a["house_v9"].append(rh["final"]); a["hold"].append(bh["final"])
            a["n"] += 1
            if rn["final"] > bh["final"]: a["beat"] += 1
    summary = {}
    for name, a in agg.items():
        if a["n"]:
            summary[name] = {"names": a["n"], "native_median": round(statistics.median(a["native"]), 2),
                             "house_median": round(statistics.median(a["house_v9"]), 2),
                             "hold_median": round(statistics.median(a["hold"]), 2),
                             "share_names_beating_own_hold_native_pct": round(100.0*a["beat"]/a["n"], 1)}
    return {"per_name": per_name, "summary": summary}

COIN_ROADS = {"FULL": (None, "2026-11-20"), "CONT": ("2019-01-01", "2026-11-20"),
              "VAL": ("2023-01-01", "2026-11-20")}

def run_coins_events():
    per_coin = {}
    agg = {name: {"native": [], "house_v9": [], "hold": [], "beat": 0, "n": 0} for name in COIN_ROADS}
    btc_detail = None
    for sym in coin_universe():
        bars, proxy = load_coin(sym)
        if bars is None:
            per_coin[sym] = {"status": "NO FREE DATA in program PIT cache (named closure class)"}
            continue
        trades = BUILD_TRADES(bars)
        rec = {"proxy_hl": proxy, "signals_total": len(trades)}
        for name, (s, e) in COIN_ROADS.items():
            rn = simulate_trades(bars, trades, s or bars[0]["d"], e, CRY_COST, 0.0)
            rh = simulate_trades(bars, trades, s or bars[0]["d"], e, CRY_COST, 0.0, chassis=True)
            bh = buy_hold(bars, s, e, CRY_COST, 0.0)
            if not rn or not bh: continue
            rec[name] = {"native": rn["final"], "house_v9": rh["final"], "hold": bh["final"],
                         "trades": rn["trades_taken"], "native_dd": rn["max_dd_pct"]}
            a = agg[name]
            a["native"].append(rn["final"]); a["house_v9"].append(rh["final"]); a["hold"].append(bh["final"])
            a["n"] += 1
            if rn["final"] > bh["final"]: a["beat"] += 1
        per_coin[sym] = rec
        if sym == "BTC":
            btc_detail = run_asset_events(bars, CRY_COST, 0.0, COIN_ROADS, "BTC buy-and-hold")
    summary = {}
    for name, a in agg.items():
        if a["n"]:
            summary[name] = {"coins": a["n"], "native_median": round(statistics.median(a["native"]), 2),
                             "house_median": round(statistics.median(a["house_v9"]), 2),
                             "hold_median": round(statistics.median(a["hold"]), 2),
                             "share_coins_beating_own_hold_native_pct": round(100.0*a["beat"]/a["n"], 1)}
    return {"per_coin": per_coin, "summary": summary, "btc_detail": btc_detail, "no_data_coins": COIN_NO_DATA}

def main():
    out = {"family": FAMILY, "ledger_disposition": "HUNT-FOUND (deep-hunt-futures)",
            "chassis": "frozen spec run exactly; $100; stocks 0.10%/side + $0.01 sell fee; crypto 0.60%/side; native = no floor; house = v9 chassis",
            "holdings_grid": "NOT-APPLICABLE — single-asset event system, no selection"}
    spy = load_stock("SPY")
    out["stocks_spy"] = run_asset_events(spy, STK_COST, STK_SELL_FEE, ROADS, "SPY buy-and-hold")
    for name, rec in out["stocks_spy"]["roads"].items():
        rec["champion_vm"] = CHAMP[name]; rec["spy_program_ref"] = SPYREF[name]
        print(f"SPY {name}: native ${rec['native']['final']} house ${rec['house_v9']['final']} hold ${rec['benchmark_hold']['final']} trades {rec['native']['trades_taken']} placebos {rec['placebo_native']['beaten_of_20']}/20", flush=True)
    out["stocks_pond"] = run_pond_events()
    print("POND:", out["stocks_pond"]["summary"], flush=True)
    out["coins"] = run_coins_events()
    print("COINS:", out["coins"]["summary"], flush=True)
    if out["coins"]["btc_detail"]:
        for name, rec in out["coins"]["btc_detail"]["roads"].items():
            print(f"BTC {name}: native ${rec['native']['final']} house ${rec['house_v9']['final']} hold ${rec['benchmark_hold']['final']} trades {rec['native']['trades_taken']} placebos {rec['placebo_native']['beaten_of_20']}/20", flush=True)
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE")
if __name__ == "__main__":
    main()
