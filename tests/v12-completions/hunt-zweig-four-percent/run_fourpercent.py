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

def ew_pond_weekly():
    """Equal-weight pond weekly-close index (CONSTRUCTED fallback signal series
    for the Value Line Geometric Index, frozen in the Zweig specs): chained
    weekly returns = mean of available pond names' weekly returns each week.
    Returns [(week_close_date, index_value)]."""
    weekly = {}  # sym -> {weekkey: (date, close)}
    for sym in pond_symbols() + ["SPY"]:
        try: bars = load_stock(sym)
        except Exception: continue
        wk = {}
        for b in bars:
            y, m, dd = map(int, b["d"].split("-"))
            key = date(y, m, dd).isocalendar()[:2]
            wk[key] = (b["d"], b["c"])
        weekly[sym] = wk
    all_keys = sorted({k for wk in weekly.values() for k in wk})
    series = []
    idx_val = 100.0
    prev = {}
    for k in all_keys:
        rets = []
        wk_date = None
        for sym, wk in weekly.items():
            if k in wk:
                d, c = wk[k]
                wk_date = max(wk_date, d) if wk_date else d
                if sym in prev and prev[sym] > 0:
                    rets.append(c / prev[sym] - 1.0)
                prev[sym] = c
        if rets:
            idx_val *= (1.0 + statistics.mean(rets))
            series.append((wk_date, idx_val))
    return series

def four_percent_states(weekly_series):
    """Zweig Four Percent Model state machine on a weekly close series.
    Returns (targets {week_close_date: state}, events). State starts OUT with
    the low-water mark at the first close; buy when a weekly close rises
    >= +4% from the low-water mark since the sell state began; sell when a
    weekly close falls >= -4% from the high-water mark since the buy."""
    targets = {}
    events = []
    state = 0
    lo = hi = weekly_series[0][1]
    for d, v in weekly_series:
        if state == 0:
            lo = min(lo, v)
            if v >= lo * 1.04:
                state = 1; hi = v
                events.append([d, "BUY", round(v, 2)])
        else:
            hi = max(hi, v)
            if v <= hi * 0.96:
                state = 0; lo = v
                events.append([d, "SELL", round(v, 2)])
        targets[d] = state
    return targets, events

def weekly_series_of(bars):
    wk = {}
    for b in bars:
        y, m, dd = map(int, b["d"].split("-"))
        key = date(y, m, dd).isocalendar()[:2]
        wk[key] = (b["d"], b["c"])
    return [wk[k] for k in sorted(wk)]


FAMILY = "hunt-zweig-four-percent (Zweig Four Percent Model, 1986)"

def shifted_weekly_targets(targets, seed):
    dates = sorted(targets); vals = [targets[d] for d in dates]
    rng = random.Random(seed)
    k = rng.randrange(1, len(vals))
    vals = vals[k:] + vals[:k]
    return dict(zip(dates, vals))

def run_spy_four(spy, targets):
    out = {"roads": {}}
    for name, (s, e) in ROADS.items():
        rec = {}
        for form, ch in (("native", False), ("house_v9", True)):
            r = simulate_targets(spy, targets, s, e, STK_COST, STK_SELL_FEE, chassis=ch)
            rec[form] = {**r, "period_stats_weekly": period_stats(r["equity_curve"], "weekly"),
                         "period_stats_monthly": period_stats(r["equity_curve"], "monthly")}
        bh = buy_hold(spy, s, e, STK_COST, STK_SELL_FEE)
        rec["benchmark_hold"] = {"name": "SPY buy-and-hold", "final": bh["final"], "max_dd_pct": bh["max_dd_pct"],
                                 "period_stats_weekly": period_stats(bh["equity_curve"], "weekly")}
        pf = []
        for seed in range(1, 21):
            st = shifted_weekly_targets(targets, seed)
            pf.append(simulate_targets(spy, st, s, e, STK_COST, STK_SELL_FEE)["final"])
        rec["placebo_native"] = {"seed_finals": pf, "beaten_of_20": sum(1 for p in pf if rec["native"]["final"] > p),
                                 "design": "circular shift of the weekly in/out state series (20 seeds), matched-holding timer placebo"}
        rec["champion_vm"] = CHAMP[name]; rec["spy_program_ref"] = SPYREF[name]
        out["roads"][name] = rec
    return out

COIN_ROADS = {"FULL": (None, "2026-11-20"), "CONT": ("2019-01-01", "2026-11-20"), "VAL": ("2023-01-01", "2026-11-20")}

def main():
    out = {"family": FAMILY, "ledger_disposition": "HUNT-FOUND (deep-hunt-newsletters)",
           "signal_series": "CONSTRUCTED fallback per frozen spec: ^VLG (Value Line Geometric) not obtainable free (Yahoo chart API returns Not Found; Stooq JS-walled — see HUNT-LOG.md); equal-weight pond weekly-close index used, labelled CONSTRUCTED, bias printed in RESULTS.md",
           "chassis": "$100; stocks 0.10%/side + $0.01 sell fee; crypto 0.60%/side; native = no floor; house = v9 chassis; signal on weekly close, trade next session open",
           "holdings_grid": "NOT-APPLICABLE — single-asset timer, no selection"}
    ws = ew_pond_weekly()
    targets, events = four_percent_states(ws)
    out["signal_series_range"] = f"{ws[0][0]} -> {ws[-1][0]} ({len(ws)} weeks)"
    out["signal_events"] = events
    spy = load_stock("SPY")
    out["stocks_spy"] = run_spy_four(spy, targets)
    for name, rec in out["stocks_spy"]["roads"].items():
        print(f"SPY {name}: native ${rec['native']['final']} house ${rec['house_v9']['final']} hold ${rec['benchmark_hold']['final']} placebos {rec['placebo_native']['beaten_of_20']}/20", flush=True)
    per_coin = {}
    agg = {name: {"native": [], "house_v9": [], "hold": [], "beat": 0, "n": 0} for name in COIN_ROADS}
    btc_detail = None
    for sym in coin_universe():
        bars, proxy = load_coin(sym)
        if bars is None:
            per_coin[sym] = {"status": "NO FREE DATA in program PIT cache (named closure class)"}; continue
        cws = weekly_series_of(bars)
        if len(cws) < 30:
            per_coin[sym] = {"status": "history too short for a weekly swing system (<30 weekly closes)"}; continue
        ct, cev = four_percent_states(cws)
        rec = {"events": len(cev)}
        for name, (s, e) in COIN_ROADS.items():
            rn = simulate_targets(bars, ct, s or bars[0]["d"], e, CRY_COST, 0.0)
            rh = simulate_targets(bars, ct, s or bars[0]["d"], e, CRY_COST, 0.0, chassis=True)
            bh = buy_hold(bars, s, e, CRY_COST, 0.0)
            if not rn or not bh: continue
            rec[name] = {"native": rn["final"], "house_v9": rh["final"], "hold": bh["final"], "native_dd": rn["max_dd_pct"]}
            a = agg[name]; a["native"].append(rn["final"]); a["house_v9"].append(rh["final"]); a["hold"].append(bh["final"]); a["n"] += 1
            if rn["final"] > bh["final"]: a["beat"] += 1
        per_coin[sym] = rec
        if sym == "BTC":
            det = {"roads": {}}
            for name, (s, e) in COIN_ROADS.items():
                rr = {}
                for form, ch in (("native", False), ("house_v9", True)):
                    r = simulate_targets(bars, ct, s or bars[0]["d"], e, CRY_COST, 0.0, chassis=ch)
                    rr[form] = {**r, "period_stats_weekly": period_stats(r["equity_curve"], "weekly")}
                bh = buy_hold(bars, s, e, CRY_COST, 0.0)
                rr["benchmark_hold"] = {"name": "BTC buy-and-hold", "final": bh["final"], "max_dd_pct": bh["max_dd_pct"]}
                pf = []
                for seed in range(1, 21):
                    st = shifted_weekly_targets(ct, seed)
                    pf.append(simulate_targets(bars, st, s or bars[0]["d"], e, CRY_COST, 0.0)["final"])
                rr["placebo_native"] = {"seed_finals": pf, "beaten_of_20": sum(1 for p in pf if rr["native"]["final"] > p)}
                det["roads"][name] = rr
            btc_detail = det
    out["coins"] = {"per_coin": per_coin, "btc_detail": btc_detail,
                    "summary": {name: {"coins": a["n"], "native_median": round(statistics.median(a["native"]), 2),
                                       "house_median": round(statistics.median(a["house_v9"]), 2),
                                       "hold_median": round(statistics.median(a["hold"]), 2),
                                       "share_beating_own_hold_pct": round(100.0*a["beat"]/a["n"], 1)}
                                for name, a in agg.items() if a["n"]},
                    "no_data_coins": COIN_NO_DATA}
    print("COINS:", out["coins"]["summary"], flush=True)
    if btc_detail:
        for name, rec in btc_detail["roads"].items():
            print(f"BTC {name}: native ${rec['native']['final']} house ${rec['house_v9']['final']} hold ${rec['benchmark_hold']['final']} placebos {rec['placebo_native']['beaten_of_20']}/20", flush=True)
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE")
if __name__ == "__main__":
    main()
