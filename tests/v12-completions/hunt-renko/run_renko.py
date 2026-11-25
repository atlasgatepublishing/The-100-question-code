#!/usr/bin/env python3
"""Renko (hunt-renko, v12 Deep-Hunt, HUNT-FOUND) — implements SPEC-FROZEN.md
EXACTLY. Simulation only. No parameter changes, no additions.

Published (Nison, Beyond Candlesticks, 1994; Achelis): close-based bricks of
fixed height B; continuation brick needs one full B beyond the far edge of
the last brick; a reversal brick requires a 2B move from the last brick's
extreme. New white brick = uptrend; new black brick = downtrend.
CONSTRUCTED (frozen in spec): B = 1% of the instrument's price at chart
start, fixed for that chart; single-asset timer — long at the CLOSE that
completes the first white brick after a black brick, exit to cash at the
CLOSE that completes the first black brick after a white brick; all-in,
$100 pot.
Forms: NATIVE (no floor; drawdown printed) and HOUSE (v9 chassis: -15%
floor on daily closes vs episode start; first breach liquidates at next
open and halts 90 days; second breach ends the run).
Stocks: SPY + the program's standard 30-name pond, individually; program
costs 0.10%/side + $0.01 sell fee. Roads LONG/DECADE/CONT/VAL.
Coins: every PIT CoinMarketCap top-20 coin with an honest series (v4
cache, read-only), per coin, FULL + RECENT(2023+) windows, crypto cost
0.60%/side (inside the program's measured 0.40-0.80%/side retail band).
A coin whose series stops >30 days before the data end and is held at
that point is written to ZERO (program convention). BTC buy-and-hold is
printed beside every coin number, plus the coin's own buy-and-hold.
Placebos: 20-seed circular shift of the in/out state series within the
window (native form), SPY per road + pooled pond + pooled coins.
"""
import json, os, time, random, statistics
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
PXDIR = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
CBASE = os.path.expanduser("~/workspace/stock-app/backtests/v4/crypto-basket-pit-data")
START = 100.0
STK_COST = 0.001; STK_SELL_FEE = 0.01
CRY_COST = 0.006
DATA_END_ORD = date(2026, 11, 21).toordinal()
ROADS = {"LONG": ("2010-01-01", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-01", "2026-11-20"), "VAL": ("2023-01-01", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
POND = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "BRK-B", "JPM", "XOM",
        "JNJ", "PG", "V", "WMT", "HD", "BAC", "CVX", "PFE", "VZ", "T",
        "DIS", "NFLX", "INTC", "CSCO", "GE", "IBM", "MMM", "UNH", "MA",
        "KO", "PEP", "WFC"]
FILEMAP_STK = {"GOOGL": "GOOG"}

# ------------------------------------------------------------------ loaders

def load_stock(tkr):
    fn = FILEMAP_STK.get(tkr, tkr)
    p = os.path.join(PXDIR, f"pxfull_{fn}.json")
    if not os.path.exists(p):
        return None
    j = json.load(open(p))
    r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        o, c = q["open"][i], q["close"][i]
        if o is None or c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        dstr = time.strftime("%Y-%m-%d", time.gmtime(t))
        bars.append({"d": dstr, "ord": date.fromisoformat(dstr).toordinal(),
                     "o": o * ratio, "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars

COIN_FILEMAP = {"LUNA": "y_LUNC-USD.json", "UST": "y_USTC-USD.json",
                "MATIC": "b_MATICUSDT.json", "MIOTA": "b_IOTAUSDT.json",
                "PEPE": "b_PEPEUSDT.json", "POL": "b_POLUSDT.json",
                "SUI": "b_SUIUSDT.json", "UNI": "b_UNIUSDT.json",
                "USD1": "b_USD1USDT.json", "USDe": "b_USDEUSDT.json",
                "TON": "k_TONUSD.json"}
COIN_NO_DATA = ["BCC", "CC", "DGD", "FCT", "GAME", "GNT", "GRAM", "HYPE", "ICN",
                "M", "MAID", "STRAT", "VEN",
                "HC", "MIN", "PAY", "TAGZ5", "NANO", "SNGLS"]

def load_coin_universe():
    snap = json.load(open(os.path.join(CBASE, "snapshots.json")))
    coins = set()
    for v in snap.values():
        for e in v["top20"]:
            coins.add(e["symbol"])
    return sorted(coins)

def load_coin(sym):
    fn = COIN_FILEMAP.get(sym, f"y_{sym}-USD.json")
    p = os.path.join(CBASE, fn)
    if not os.path.exists(p):
        return None
    raw = json.load(open(p))
    rows, seen = [], set()
    for r in raw:
        y, m, d = map(int, r["d"].split("-"))
        o_ord = date(y, m, d).toordinal()
        op, cl = float(r["o"]), float(r["c"])
        if op > 0 and cl > 0 and o_ord not in seen:
            seen.add(o_ord)
            rows.append({"d": r["d"], "ord": o_ord, "o": op, "c": cl})
    rows.sort(key=lambda b: b["ord"])
    if len(rows) < 10:
        return None
    return rows

# ------------------------------------------------------------------ renko

def renko_states(closes):
    """Returns (states, n_bricks, box). states[i] = 1 if last completed
    brick after close i is white (up), else 0. B = 1% of closes[0]."""
    n = len(closes)
    B = 0.01 * closes[0]
    states = [0] * n
    level = closes[0]      # far edge of last brick (top if up, bottom if down)
    direction = 0          # 0 none, +1 last brick white, -1 last brick black
    bricks = 0
    for i, c in enumerate(closes):
        if direction == 0:
            while c >= level + B:
                level += B; direction = 1; bricks += 1
            while c <= level - B:
                level -= B; direction = -1; bricks += 1
        elif direction == 1:
            while c >= level + B:
                level += B; bricks += 1
            if c <= level - 2 * B:
                level -= 2 * B; direction = -1; bricks += 1
                while c <= level - B:
                    level -= B; bricks += 1
        else:
            while c <= level - B:
                level -= B; bricks += 1
            if c >= level + 2 * B:
                level += 2 * B; direction = 1; bricks += 1
                while c >= level + B:
                    level += B; bricks += 1
        states[i] = 1 if direction == 1 else 0
    return states, bricks, B

# ------------------------------------------------------------------ engine

def simulate(bars, states, start_ord, end_ord, cost, sell_fee, chassis=False,
             shift_seed=None):
    """Signal trades execute AT the close completing the brick (spec).
    Floor liquidation (house only) at next open. Dead-series fence: if the
    series ends >30 days before the global data end while holding, the
    position is written to ZERO instead of liquidated."""
    idx = [i for i, b in enumerate(bars) if start_ord <= b["ord"] <= end_ord]
    if not idx:
        return None
    seg_states = [states[i] for i in idx]
    if shift_seed is not None and len(seg_states) > 1:
        rng = random.Random(shift_seed)
        k = rng.randrange(1, len(seg_states))
        seg_states = seg_states[k:] + seg_states[:k]
    cash, shares, costs, orders = START, 0.0, 0.0, 0
    curve = []
    ep_start, halts, halt_until, ended = START, 0, None, False
    pending_liq = False
    dead_end = (end_ord - bars[idx[-1]]["ord"] > 30)
    invested = 0
    for pos, i in enumerate(idx):
        b = bars[i]
        if pending_liq:
            if shares > 0:
                val = shares * b["o"]; fee = val * cost + sell_fee
                cash += val - fee; costs += fee; shares = 0.0; orders += 1
            pending_liq = False
            if halts == 1:
                halt_until = b["ord"] + 90
            else:
                ended = True
        if halt_until is not None and b["ord"] >= halt_until:
            halt_until = None; ep_start = cash
        if halt_until is None and not ended:
            want = seg_states[pos]
            if want == 1 and shares == 0.0 and cash > 0:
                bv = cash / (1 + cost); fee = bv * cost
                shares = bv / b["c"]; cash -= bv + fee; costs += fee; orders += 1
            elif want == 0 and shares > 0:
                val = shares * b["c"]; fee = val * cost + sell_fee
                cash += val - fee; costs += fee; shares = 0.0; orders += 1
        eq = cash + shares * b["c"]
        if shares > 0:
            invested += 1
        curve.append([b["d"], round(eq, 4)])
        if chassis and not ended and halt_until is None and eq <= 0.85 * ep_start:
            halts += 1; pending_liq = True
    if shares > 0:
        if dead_end:
            shares = 0.0  # vanished coin: written to ZERO, never carried
            curve[-1] = [curve[-1][0], round(cash, 4)]
        else:
            val = shares * bars[idx[-1]]["c"]; fee = val * cost + sell_fee
            cash += val - fee; costs += fee; shares = 0.0; orders += 1
            curve[-1] = [curve[-1][0], round(cash, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(cash, 2), "max_dd_pct": round(maxdd * 100, 2),
            "costs": round(costs, 2), "orders": orders, "halts": halts,
            "invested_pct": round(100.0 * invested / len(idx), 1),
            "dead_end_zeroed": bool(dead_end and curve and curve[-1][1] == round(cash, 4) and cash < START),
            "curve": curve}

def buy_hold(bars, start_ord, end_ord, cost, sell_fee):
    idx = [i for i, b in enumerate(bars) if start_ord <= b["ord"] <= end_ord]
    if not idx:
        return None
    o = bars[idx[0]]["o"]
    sh = (START / (1 + cost)) / o
    dead_end = (end_ord - bars[idx[-1]]["ord"] > 30)
    curve = [[bars[i]["d"], round(sh * bars[i]["c"], 4)] for i in idx]
    if dead_end:
        final = 0.0
        curve[-1] = [curve[-1][0], 0.0]
    else:
        val = sh * bars[idx[-1]]["c"]
        final = val - (val * cost + sell_fee)
        curve[-1] = [curve[-1][0], round(final, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 2), "curve": curve}

# ------------------------------------------------------------------ stats

def period_stats_daily(curve):
    if not curve or len(curve) < 2:
        return None
    series = [START] + [v for _, v in curve]
    rets = [(series[i] / series[i - 1] - 1.0) * 100.0 if series[i - 1] > 0 else 0.0
            for i in range(1, len(series))]
    pos = sum(1 for r in rets if r > 0)
    streak = worst_streak = 0
    for r in rets:
        if r < 0:
            streak += 1; worst_streak = max(worst_streak, streak)
        else:
            streak = 0
    peak = series[0]; last_high = 0; longest = 0
    for i, v in enumerate(series):
        if v >= peak:
            peak = v; longest = max(longest, i - last_high); last_high = i
    longest = max(longest, len(series) - 1 - last_high)
    return {"periods": len(rets), "pct_positive": round(100.0 * pos / len(rets), 1),
            "median_pct": round(statistics.median(rets), 3),
            "mean_pct_secondary_average_only": round(statistics.mean(rets), 3),
            "best_pct": round(max(rets), 2), "worst_pct": round(min(rets), 2),
            "longest_losing_streak_days": worst_streak,
            "longest_between_highs_days": longest}

def ord_of(s):
    return date.fromisoformat(s).toordinal()

# ------------------------------------------------------------------ stocks

def run_stocks():
    out = {"instruments": {}}
    data = {}
    for tkr in POND + ["SPY"]:
        bars = load_stock(tkr)
        if bars:
            data[tkr] = bars
    states_map = {}
    for tkr, bars in data.items():
        st, bricks, B = renko_states([b["c"] for b in bars])
        states_map[tkr] = st
        out["instruments"][tkr] = {"bars": len(bars),
                                   "range": f"{bars[0]['d']} -> {bars[-1]['d']}",
                                   "box_size": round(B, 4), "bricks_total": bricks,
                                   "roads": {}}
    for road, (s, e) in ROADS.items():
        so, eo = ord_of(s), ord_of(e)
        spy_hold = buy_hold(data["SPY"], so, eo, STK_COST, STK_SELL_FEE)
        for tkr in POND + ["SPY"]:
            if tkr not in data:
                continue
            bars, st = data[tkr], states_map[tkr]
            rec = {}
            for form, chassis in (("native", False), ("house_v9", True)):
                r = simulate(bars, st, so, eo, STK_COST, STK_SELL_FEE, chassis=chassis)
                if r is None:
                    rec[form] = None; continue
                rec[form] = {k: r[k] for k in ("final", "max_dd_pct", "costs", "orders",
                                               "halts", "invested_pct")}
                if tkr == "SPY":
                    rec[form]["period_stats_daily"] = period_stats_daily(r["curve"])
                    rec[form]["curve"] = r["curve"]
            bh = buy_hold(bars, so, eo, STK_COST, STK_SELL_FEE)
            rec["own_hold"] = {"final": bh["final"], "max_dd_pct": bh["max_dd_pct"]} if bh else None
            rec["spy_hold_same_plumbing"] = {"final": spy_hold["final"],
                                             "max_dd_pct": spy_hold["max_dd_pct"]}
            rec["spy_program_ref"] = SPYREF[road]
            rec["champion_vm"] = CHAMP[road]
            out["instruments"][tkr]["roads"][road] = rec
        # placebos: SPY per road + pooled pond (native)
        spy_bars, spy_st = data["SPY"], states_map["SPY"]
        base = simulate(spy_bars, spy_st, so, eo, STK_COST, STK_SELL_FEE)
        twins = [simulate(spy_bars, spy_st, so, eo, STK_COST, STK_SELL_FEE,
                          shift_seed=sd)["final"] for sd in range(1, 21)]
        pond_twins = []
        for sd in range(1, 21):
            finals = []
            for tkr in POND:
                if tkr not in data:
                    continue
                r = simulate(data[tkr], states_map[tkr], so, eo,
                             STK_COST, STK_SELL_FEE, shift_seed=sd)
                if r:
                    finals.append(r["final"])
            pond_twins.append(round(statistics.mean(finals), 2) if finals else None)
        pond_native = [out["instruments"][t]["roads"][road]["native"]["final"]
                       for t in POND if t in data and out["instruments"][t]["roads"][road].get("native")]
        pond_mean = round(statistics.mean(pond_native), 2)
        out.setdefault("placebos", {})[road] = {
            "spy_native_final": base["final"],
            "spy_seed_finals": twins,
            "spy_beaten_of_20": sum(1 for x in twins if base["final"] > x),
            "pond_native_mean_final": pond_mean,
            "pond_seed_mean_finals": pond_twins,
            "pond_beaten_of_20": sum(1 for x in pond_twins if x is not None and pond_mean > x),
            "design": "circular shift of each instrument's daily in/out state series within the road; 20 seeds; preserves invested fraction and episode lengths"}
        print(f"STOCKS {road}: SPY native ${base['final']} placebo "
              f"{out['placebos'][road]['spy_beaten_of_20']}/20 | pond mean "
              f"${pond_mean} placebo {out['placebos'][road]['pond_beaten_of_20']}/20")
    # SPY year folds (native) — confirmation material
    folds = {}
    spy_bars, spy_st = data["SPY"], states_map["SPY"]
    for y in range(2010, 2027):
        s = ord_of(f"{y}-01-01"); e = ord_of("2026-11-20") if y == 2026 else ord_of(f"{y}-12-31")
        rn = simulate(spy_bars, spy_st, s, e, STK_COST, STK_SELL_FEE)
        bh = buy_hold(spy_bars, s, e, STK_COST, STK_SELL_FEE)
        folds[str(y)] = {"native": rn["final"], "spy_hold": bh["final"],
                         "beat_hold": rn["final"] > bh["final"]}
    out["spy_year_folds_native"] = folds
    return out

# ------------------------------------------------------------------ coins

def run_coins():
    universe = load_coin_universe()
    data = {}
    for sym in universe:
        s = load_coin(sym)
        if s is not None:
            data[sym] = s
    out = {"universe_pit_symbols": len(universe), "coins_with_series": len(data),
           "no_data_closure": COIN_NO_DATA, "cost_per_side": CRY_COST,
           "coins": {}}
    btc = data["BTC"]
    btc_st, btc_bricks, btc_B = renko_states([b["c"] for b in btc])
    windows = {"FULL": (None, DATA_END_ORD),
               "RECENT_2023": (ord_of("2023-01-01"), DATA_END_ORD)}
    btc_holds = {}
    for wname, (so, eo) in windows.items():
        s_ord = so if so is not None else btc[0]["ord"]
        btc_holds[wname] = buy_hold(btc, s_ord, eo, CRY_COST, 0.0)
    pooled_items = []
    for sym, bars in data.items():
        st, bricks, B = renko_states([b["c"] for b in bars])
        rec = {"bars": len(bars), "range": f"{bars[0]['d']} -> {bars[-1]['d']}",
               "box_size": B, "bricks_total": bricks, "windows": {}}
        for wname, (so, eo) in windows.items():
            s_ord = so if so is not None else bars[0]["ord"]
            if bars[-1]["ord"] < s_ord or len([b for b in bars if b["ord"] >= s_ord]) < 30:
                rec["windows"][wname] = None
                continue
            w = {}
            for form, chassis in (("native", False), ("house_v9", True)):
                r = simulate(bars, st, s_ord, eo, CRY_COST, 0.0, chassis=chassis)
                w[form] = {k: r[k] for k in ("final", "max_dd_pct", "costs", "orders",
                                             "halts", "invested_pct", "dead_end_zeroed")}
                if sym == "BTC" and wname == "FULL":
                    w[form]["period_stats_daily"] = period_stats_daily(r["curve"])
                    w[form]["curve_weekly_sample"] = r["curve"][::7]
            bh = buy_hold(bars, s_ord, eo, CRY_COST, 0.0)
            w["own_hold"] = {"final": bh["final"], "max_dd_pct": bh["max_dd_pct"]}
            w["btc_hold_same_window"] = {"final": btc_holds[wname]["final"],
                                         "max_dd_pct": btc_holds[wname]["max_dd_pct"]}
            w["beat_btc_hold_native"] = w["native"]["final"] > btc_holds[wname]["final"]
            rec["windows"][wname] = w
            if wname == "FULL":
                pooled_items.append((bars, st))
        out["coins"][sym] = rec
    # pooled summaries
    for wname in windows:
        finals = [c["windows"][wname]["native"]["final"] for c in out["coins"].values()
                  if c["windows"].get(wname)]
        hfinals = [c["windows"][wname]["house_v9"]["final"] for c in out["coins"].values()
                   if c["windows"].get(wname)]
        holds = [c["windows"][wname]["own_hold"]["final"] for c in out["coins"].values()
                 if c["windows"].get(wname)]
        out.setdefault("pooled", {})[wname] = {
            "coins": len(finals),
            "native_mean_final": round(statistics.mean(finals), 2),
            "native_median_final": round(statistics.median(finals), 2),
            "house_mean_final": round(statistics.mean(hfinals), 2),
            "house_median_final": round(statistics.median(hfinals), 2),
            "own_hold_median_final": round(statistics.median(holds), 2),
            "btc_hold_final": btc_holds[wname]["final"],
            "coins_beating_btc_hold_native": sum(
                1 for c in out["coins"].values()
                if c["windows"].get(wname) and c["windows"][wname]["beat_btc_hold_native"]),
            "coins_beating_own_hold_native": sum(
                1 for c in out["coins"].values()
                if c["windows"].get(wname) and
                c["windows"][wname]["native"]["final"] > c["windows"][wname]["own_hold"]["final"])}
    # pooled placebo (FULL, native): shift each coin's state series, 20 seeds
    twins = []
    for sd in range(1, 21):
        finals = []
        for bars, st in pooled_items:
            r = simulate(bars, st, bars[0]["ord"], DATA_END_ORD, CRY_COST, 0.0,
                         shift_seed=sd)
            if r:
                finals.append(r["final"])
        twins.append(round(statistics.mean(finals), 2))
    real_mean = out["pooled"]["FULL"]["native_mean_final"]
    out["placebo_FULL_native"] = {
        "seed_mean_finals": twins,
        "real_mean_final": real_mean,
        "beaten_of_20": sum(1 for x in twins if real_mean > x),
        "design": "circular shift of each coin's daily in/out state series over its full window; 20 seeds; pooled mean final compared"}
    print(f"COINS FULL pooled native mean ${real_mean} median "
          f"${out['pooled']['FULL']['native_median_final']} | BTC hold "
          f"${btc_holds['FULL']['final']} | placebo beaten "
          f"{out['placebo_FULL_native']['beaten_of_20']}/20")
    return out

def main():
    out = {"family": "hunt-renko (Renko brick chart, Nison 1994)",
           "ledger_disposition": "HUNT-FOUND (source: deep-hunt-nonus TERRITORY-LOG)",
           "spec": "SPEC-FROZEN.md — B = 1% of price at chart start (CONSTRUCTED scaling); long at close completing first white brick after black; exit at close completing first black brick after white; all-in $100",
           "stock_costs": "0.10%/side + $0.01 sell fee",
           "crypto_cost_per_side": CRY_COST,
           "crypto_cost_note": "0.60%/side — inside the program's measured retail band 0.40-0.80%/side",
           "holdings_sweep": "NOT-APPLICABLE — single-asset timer, holds 0 or 1 instrument (spec (d))",
           "stocks": run_stocks(),
           "coins": run_coins()}
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE")

if __name__ == "__main__":
    main()
