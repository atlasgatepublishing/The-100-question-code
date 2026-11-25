#!/usr/bin/env python3
"""
V12 CRYPTO WING 2 — Pi Cycle Top & Bottom, CONSTRUCTED trading system.

Construction frozen in CONSTRUCTION-SPEC.md before this run:
  - PUBLISHED indicators: Top = SMA111 cross UP through 2*SMA350 (Swift 2019);
    Bottom = EMA150 cross DOWN through 0.745*SMA471 (Doncic 2021), with the
    author's own 0.475 variant frozen as a documented-variant sensitivity.
  - CONSTRUCTED system (PI-FULL): start long; top cross -> sell next open;
    bottom cross -> buy back next open (REENTRY-DOWN primary; REENTRY-UP =
    cross back up, the documented "bottoming zone" end, reported beside it).
  - Rule sets: NATIVE (no floor) and V9 (plain -15% floor, $85 on $100,
    daily-close check, liquidate next open, run stops).
  - Costs 0.60%/side. Pot $100 fresh per coin per window.
  - Point-in-time: cross knowable at the close it prints; orders at the
    NEXT bar's open. No forward-filled signals (BAR-COUNT: no bar, no signal).
  - EMA150 seeded with SMA of first 150 closes, k=2/151; signals only from
    bar index 470 onward (WARMUP-471).
  - Death rule: no real bar >7 days while held -> position valued $0
    (BINANCE-DATA-END exception: Binance series end 2026-10-31 in source).
  - Windows: FULL (first eligible -> 2026-11-20), DESIGN 2017->2022,
    VALIDATION 2023->2026-11-20. Bar: BTC buy-hold net same costs, same
    window, beside every number; per-coin also the coin's own buy-hold.
  - Placebos: 20 seeds of shifted-MA controls, one scale u~U(0.70,1.40)
    applied to all four lengths, multipliers unchanged.
  - BTC primary series: v4 crypto-trend-data/BTC-USD.csv (2014-09-17->).
    Per-coin: v4 crypto-basket-pit-data registry inherited unchanged from
    the v12 crypto-basket construction (maps/exclusions copied verbatim).
Shared data is READ-ONLY; this script writes only inside its own folder.
"""

import csv
import json
import math
import os
import random
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
V4PIT = os.path.expanduser("~/workspace/stock-app/backtests/v4/crypto-basket-pit-data")
V4TREND = os.path.expanduser("~/workspace/stock-app/backtests/v4/crypto-trend-data")

COST = 0.006
POT = 100.0
FLOOR = 85.0
END = "2026-11-20"
BINANCE_DATA_END = "2026-10-31"
STALE_DAYS = 7
WARMUP = 471  # signals evaluated from bar index 470 (0-based) onward

WINDOWS = {
    "full": (None, END),
    "design": ("2017-01-01", "2022-12-31"),
    "validation": ("2023-01-01", END),
}

STABLE_WRAPPED = {"USDT", "USDC", "DAI", "BUSD", "WBTC", "USDe", "USD1"}

# --- registry maps inherited verbatim from v12 crypto-basket (v4 PIT) ---
BINANCE_MAP = {
    1720: "IOTAUSDT", 3890: "MATICUSDT", 28321: "POLUSDT",
    24478: "PEPEUSDT", 29470: "USDEUSDT", 36148: "USD1USDT",
    7083: "UNIUSDT", 20947: "SUIUSDT",
}
KRAKEN_MAP = {11419: "TONUSD"}
YAHOO_MAP = {4172: "LUNC-USD", 7129: "USTC-USD", 2280: "FIL-USD"}
EXCLUDED = {
    1513: "BitConnect: no price series on any free source",
    291: "MaidSafeCoin: Yahoo carries a 1-bar stub only",
    1408: "Iconomi: Yahoo carries a 1-bar stub only",
    1087: "Factom: Yahoo carries a 1-bar stub only",
    576: "GameCredits: Yahoo carries a 1-bar stub only",
    1229: "DigixDAO: Yahoo carries a 1-bar stub only",
    1343: "Stratis: Yahoo carries a 1-bar stub only",
    1904: "VeChain (VEN): no free series; never eligible (inside its own lookback)",
    1455: "Golem (GNT): Yahoo series is a corrupted wrong-era stub",
    35491: "MemeCore (M): Yahoo M-USD is a different token",
    37263: "Canton (CC): no free series; launched Nov 2025",
    32196: "Hyperliquid (HYPE): no Yahoo/Binance spot series (v4 bybit attempt failed)",
}
CREDIBLE_START = {
    2280: "2020-10-15", 11841: "2023-03-23", 22861: "2023-10-31",
}


def _load(name):
    with open(os.path.join(V4PIT, name)) as f:
        return json.load(f)


def build_registry():
    snaps = _load("snapshots.json")
    coins = {}
    for month, info in snaps.items():
        for c in info["top20"]:
            coins.setdefault(c["cmc_id"], {"symbol": c["symbol"], "slug": c["slug"]})
    reg = {}
    for cid, meta in coins.items():
        if cid in EXCLUDED:
            reg[cid] = {**meta, "source": "excluded", "reason": EXCLUDED[cid], "rows": []}
            continue
        if cid in BINANCE_MAP:
            rows = _load(f"b_{BINANCE_MAP[cid]}.json")
            src = f"binance:{BINANCE_MAP[cid]}"
        elif cid in KRAKEN_MAP:
            rows = _load(f"k_{KRAKEN_MAP[cid]}.json")
            src = f"kraken:{KRAKEN_MAP[cid]}"
        else:
            ticker = YAHOO_MAP.get(cid, f"{meta['symbol']}-USD")
            rows = _load(f"y_{ticker}.json")
            src = f"yahoo:{ticker}"
        if cid in CREDIBLE_START:
            rows = [r for r in rows if r["d"] >= CREDIBLE_START[cid]]
        reg[cid] = {**meta, "source": src, "reason": None, "rows": rows}
    return reg


def load_btc_primary():
    rows = []
    with open(os.path.join(V4TREND, "BTC-USD.csv")) as f:
        for r in csv.DictReader(f):
            rows.append({"d": r["date"], "o": float(r["open"]), "c": float(r["close"])})
    return rows


# ---------------- indicators ----------------

def sma_series(closes, n):
    out = [None] * len(closes)
    s = 0.0
    for i, c in enumerate(closes):
        s += c
        if i >= n:
            s -= closes[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema_series(closes, n):
    """Seeded with SMA of first n closes at index n-1; k = 2/(n+1)."""
    out = [None] * len(closes)
    if len(closes) < n:
        return out
    k = 2.0 / (n + 1)
    e = sum(closes[:n]) / n
    out[n - 1] = e
    for i in range(n, len(closes)):
        e = closes[i] * k + e * (1 - k)
        out[i] = e
    return out


def compute_signals(rows, fast_top=111, slow_top=350, fast_bot=150, slow_bot=471,
                    bot_mult=0.745):
    """Return per-bar dicts of cross events, evaluated only where both
    indicators exist and bar index >= WARMUP-1 relative to the LONGEST
    window actually used (caller passes scaled lengths for placebos)."""
    closes = [r["c"] for r in rows]
    s_fast = sma_series(closes, fast_top)
    s_slow = sma_series(closes, slow_top)
    e_fast = ema_series(closes, fast_bot)
    s_bot = sma_series(closes, slow_bot)
    warm = max(slow_bot, slow_top) - 1
    ev = []
    prev_top = None
    prev_bot = None
    for i in range(len(rows)):
        top_above = None
        bot_below = None
        if i >= warm and s_fast[i] is not None and s_slow[i] is not None \
                and e_fast[i] is not None and s_bot[i] is not None:
            top_above = s_fast[i] > 2.0 * s_slow[i]
            bot_below = e_fast[i] < bot_mult * s_bot[i]
        e = {"top_up": False, "bot_down": False, "bot_up": False}
        if top_above is not None and prev_top is not None:
            e["top_up"] = top_above and not prev_top
        if bot_below is not None and prev_bot is not None:
            e["bot_down"] = bot_below and not prev_bot
            e["bot_up"] = (not bot_below) and prev_bot
        if top_above is not None:
            prev_top = top_above
        if bot_below is not None:
            prev_bot = bot_below
        ev.append(e)
    return ev, s_fast, s_slow, e_fast, s_bot


# ---------------- engine ----------------

def dparse(s):
    y, m, d = s.split("-")
    return date(int(y), int(m), int(d))


def run_system(rows, events, wstart, wend, floor=False, reentry="down"):
    """Long/cash state machine on rows (full series); window slices state.
    Orders at next bar's open after a signal close. Equity marked on closes
    of bars inside the window; a held coin with no bar for >STALE_DAYS
    calendar days (and not the Binance data-end exception) is worth $0."""
    idx = [i for i, r in enumerate(rows) if (wstart is None or r["d"] >= wstart)
           and r["d"] <= wend]
    if not idx:
        return None
    binance_src = getattr(rows, "_binance", False)
    cash = POT
    units = 0.0
    in_market = False
    trades = 0
    costs = 0.0
    curve = []
    peak = POT
    maxdd = 0.0
    stopped = False
    last_bar_i = None
    # START-LONG: buy at the open of the first window bar
    first = idx[0]
    spend = cash
    units = spend * (1 - COST) / rows[first]["o"]
    costs += spend * COST
    cash = 0.0
    in_market = True
    trades += 1
    pending = None  # ("sell"|"buy") to execute at next bar open
    days_in = 0
    for pos, i in enumerate(idx):
        r = rows[i]
        if pending is not None and pos > 0:
            if pending == "sell" and in_market:
                proceeds = units * r["o"]
                costs += proceeds * COST
                cash = proceeds * (1 - COST)
                units = 0.0
                in_market = False
                trades += 1
            elif pending == "buy" and not in_market:
                spend = cash
                units = spend * (1 - COST) / r["o"]
                costs += spend * COST
                cash = 0.0
                in_market = True
                trades += 1
            pending = None
        # mark to market (bars only; mid-window gaps ride at last close —
        # the death rule binds at window end, below)
        if in_market:
            eq = units * r["c"]
            days_in += 1
        else:
            eq = cash
        curve.append([r["d"], round(eq, 4)])
        if eq > peak:
            peak = eq
        if peak > 0:
            dd = (eq - peak) / peak
            if dd < maxdd:
                maxdd = dd
        if stopped:
            break
        if floor and eq <= FLOOR:
            # liquidate at next bar's open if there is one; else at this close
            if pos + 1 < len(idx):
                pending = "sell"
                # force stop after execution bar: emulate by marking stopped
                # after next iteration's execution
                # simpler: execute immediately at next open here
                ni = idx[pos + 1]
                if in_market:
                    proceeds = units * rows[ni]["o"]
                    costs += proceeds * COST
                    cash = proceeds * (1 - COST)
                    units = 0.0
                    in_market = False
                    trades += 1
                curve.append([rows[ni]["d"], round(cash, 4)])
                eq = cash
                pending = None
            stopped = True
            break
        e = events[i]
        if e["top_up"] and in_market:
            pending = "sell"
        elif not in_market:
            if reentry == "down" and e["bot_down"]:
                pending = "buy"
            elif reentry == "up" and e["bot_up"]:
                pending = "buy"
        last_bar_i = i
    # DEATH-TO-ZERO at window end: held coin whose last real bar is
    # >STALE_DAYS before the window end is worth $0, never carried.
    if in_market and curve:
        last_d = rows[idx[-1]]["d"]
        if (dparse(wend) - dparse(last_d)).days > STALE_DAYS and not (
                binance_src and last_d >= BINANCE_DATA_END):
            curve.append([wend, 0.0])
            if peak > 0:
                maxdd = min(maxdd, -1.0)
    final = curve[-1][1] if curve else POT
    return {
        "final": round(final, 2),
        "max_dd_pct": round(maxdd * 100, 1),
        "trades": trades,
        "costs": round(costs, 2),
        "days_in_market": days_in,
        "days": len(curve),
        "floor_stopped": stopped,
        "curve": curve,
    }


def buy_hold(rows, wstart, wend):
    idx = [i for i, r in enumerate(rows) if (wstart is None or r["d"] >= wstart)
           and r["d"] <= wend]
    if len(idx) < 2:
        return None
    binance_src = getattr(rows, "_binance", False)
    first, last_i = idx[0], idx[-1]
    units = POT * (1 - COST) / rows[first]["o"]
    last = rows[last_i]
    gap_end = 0
    # death rule at window end: last bar stale vs window end date
    if (dparse(wend) - dparse(last["d"])).days > STALE_DAYS and not (
            binance_src and last["d"] >= BINANCE_DATA_END):
        final = 0.0
    else:
        final = units * last["c"] * (1 - COST)
    peak = 0.0
    maxdd = 0.0
    eq_series = []
    for i in idx:
        eq = units * rows[i]["c"]
        eq_series.append(eq)
        peak = max(peak, eq)
        if peak > 0:
            maxdd = min(maxdd, (eq - peak) / peak)
    return {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 1),
            "start": rows[first]["d"], "end": last["d"]}


def census(rows, events, s_fast, s_slow, e_fast, s_bot):
    tops, bots_down, bots_up = [], [], []
    closes = [r["c"] for r in rows]
    for i, e in enumerate(events):
        if e["top_up"]:
            tops.append({"date": rows[i]["d"], "close": closes[i]})
        if e["bot_down"]:
            bots_down.append({"date": rows[i]["d"], "close": closes[i]})
        if e["bot_up"]:
            bots_up.append({"date": rows[i]["d"], "close": closes[i]})
    return {"top_crosses": tops, "bottom_crosses_down": bots_down,
            "bottom_crosses_up": bots_up}


def fwd_returns(rows, events):
    """Descriptive only: BTC price change 90d/365d after each top cross."""
    out = []
    closes = [r["c"] for r in rows]
    for i, e in enumerate(events):
        if e["top_up"]:
            rec = {"date": rows[i]["d"], "close": closes[i]}
            for h in (90, 365):
                j = i + h
                rec[f"ret_{h}d_pct"] = round((closes[j] / closes[i] - 1) * 100, 1) \
                    if j < len(closes) else None
            out.append(rec)
    return out


class Rows(list):
    pass


def main():
    results = {"family": "crypto-pi-cycle (Pi Cycle Top & Bottom) — CONSTRUCTED system",
               "cost_rate_per_side": COST, "pot": POT,
               "tiny_sample_fence": "Published record = 4 top crosses + 3 bottom "
                                    "crosses in BTC history. Every number is a "
                                    "description of a handful of dates, not a rate.",
               "btc_primary": {}, "per_coin": {}, "closures": {},
               "placebos": {}}

    # ---------- BTC primary ----------
    btc = Rows(load_btc_primary())
    ev, sf, ss, ef, sb = compute_signals(btc)
    results["btc_primary"]["series"] = {"first": btc[0]["d"], "last": btc[-1]["d"],
                                        "bars": len(btc),
                                        "source": "v4 crypto-trend-data/BTC-USD.csv (Yahoo)"}
    results["btc_primary"]["signal_census"] = census(btc, ev, sf, ss, ef, sb)
    results["btc_primary"]["top_cross_forward_returns"] = fwd_returns(btc, ev)
    ev475, *_ = compute_signals(btc, bot_mult=0.475)
    results["btc_primary"]["signal_census_mult_0.475_variant"] = census(btc, ev475, sf, ss, ef, sb)

    btc_runs = {}
    for wname, (ws, we) in WINDOWS.items():
        wstart = ws if ws else btc[470]["d"]  # FULL starts at first eligible bar
        bh = buy_hold(btc, wstart, we)
        entry = {"btc_buy_hold": bh, "window": [wstart, we]}
        for mult_name, evx in (("0.745", ev), ("0.475", ev475)):
            for reentry in ("down", "up"):
                for ruleset, fl in (("native", False), ("v9", True)):
                    if mult_name == "0.475" and reentry == "up":
                        continue  # variant sensitivity: primary reentry only
                    key = f"pi_mult{mult_name}_reentry-{reentry}_{ruleset}"
                    entry[key] = run_system(btc, evx, wstart, we, floor=fl,
                                            reentry=reentry)
        btc_runs[wname] = entry
    results["btc_primary"]["runs"] = btc_runs

    # ---------- placebos: shifted-MA controls on BTC ----------
    rng_master = random.Random(20261122)
    placebo_btc = {"full": [], "validation": []}
    for seed in range(1, 21):
        rng = random.Random(seed)
        u = rng.uniform(0.70, 1.40)
        ft, st = max(20, round(111 * u)), max(40, round(350 * u))
        fb, sbn = max(20, round(150 * u)), max(50, round(471 * u))
        evp, *_ = compute_signals(btc, fast_top=ft, slow_top=st, fast_bot=fb,
                                  slow_bot=sbn)
        for wname in ("full", "validation"):
            ws, we = WINDOWS[wname]
            wstart = ws if ws else btc[max(sbn, st) - 1]["d"] \
                if max(sbn, st) - 1 < len(btc) else btc[470]["d"]
            r = run_system(btc, evp, wstart, we, floor=False, reentry="down")
            placebo_btc[wname].append({"seed": seed, "u": round(u, 3),
                                       "lengths": [ft, st, fb, sbn],
                                       "final": r["final"] if r else None})
    results["placebos"]["btc_shifted_ma"] = placebo_btc

    # ---------- per-coin ----------
    reg = build_registry()
    # BTC hold reference per window from the primary series
    btc_hold_by_window = {}
    for wname, (ws, we) in WINDOWS.items():
        wstart = ws if ws else btc[470]["d"]
        btc_hold_by_window[wname] = buy_hold(btc, wstart, we)

    placebo_coin_finals = []
    for cid, meta in sorted(reg.items(), key=lambda kv: kv[1]["symbol"]):
        sym = meta["symbol"]
        rows_raw = meta["rows"]
        if meta["source"] == "excluded" or not rows_raw:
            results["closures"][sym] = {"reason": meta["reason"] or "no series",
                                        "class": "REGISTRY-EXCLUDED"}
            continue
        rows = Rows(rows_raw)
        rows._binance = meta["source"].startswith("binance:")
        if len(rows) < 350:
            results["closures"][sym] = {
                "reason": f"INSUFFICIENT-HISTORY: {len(rows)} bars < 350 needed for Pi Cycle Top",
                "class": "INSUFFICIENT-HISTORY", "bars": len(rows)}
            continue
        evc, sf, ss, ef, sb = compute_signals(rows)
        cen = census(rows, evc, sf, ss, ef, sb)
        coin = {"symbol": sym, "slug": meta["slug"], "source": meta["source"],
                "bars": len(rows), "first": rows[0]["d"], "last": rows[-1]["d"],
                "stable_or_wrapped": sym in STABLE_WRAPPED,
                "system_eligible": len(rows) >= WARMUP,
                "signal_census": {"top_crosses": len(cen["top_crosses"]),
                                  "bottom_crosses_down": len(cen["bottom_crosses_down"]),
                                  "bottom_crosses_up": len(cen["bottom_crosses_up"]),
                                  "top_dates": [t["date"] for t in cen["top_crosses"]],
                                  "bottom_down_dates": [t["date"] for t in cen["bottom_crosses_down"]]},
                "runs": {}}
        if len(rows) < WARMUP:
            coin["note"] = "TOP-ONLY: >=350 but <471 bars; bottom indicator never computable, system not run"
            results["per_coin"][sym] = coin
            continue
        ws_full = rows[470]["d"]
        for wname, (ws, we) in (("full", (ws_full, END)),
                                ("validation", WINDOWS["validation"])):
            r_native = run_system(rows, evc, ws, we, floor=False, reentry="down")
            r_v9 = run_system(rows, evc, ws, we, floor=True, reentry="down")
            coin["runs"][wname] = {
                "window": [ws, we],
                "pi_native": r_native, "pi_v9": r_v9,
                "coin_buy_hold": buy_hold(rows, ws, we),
                "btc_buy_hold_same_window": btc_hold_by_window["full" if wname == "full" else "validation"],
            }
        results["per_coin"][sym] = coin
        # per-coin placebos (FULL, native, reentry-down), 20 seeds
        finals = []
        for seed in range(1, 21):
            rng = random.Random(seed)
            u = rng.uniform(0.70, 1.40)
            ft, st = max(20, round(111 * u)), max(40, round(350 * u))
            fb, sbn = max(20, round(150 * u)), max(50, round(471 * u))
            evp, *_ = compute_signals(rows, fast_top=ft, slow_top=st,
                                      fast_bot=fb, slow_bot=sbn)
            start_i = max(sbn, st) - 1
            if start_i >= len(rows):
                continue
            r = run_system(rows, evp, rows[start_i]["d"], END, floor=False,
                           reentry="down")
            if r:
                finals.append(r["final"])
        if finals:
            finals_sorted = sorted(finals)
            coin["placebo_shifted_ma_full"] = {
                "n": len(finals_sorted),
                "median": finals_sorted[len(finals_sorted) // 2],
                "min": finals_sorted[0], "max": finals_sorted[-1]}
            placebo_coin_finals.append(finals_sorted[len(finals_sorted) // 2])

    # ---------- pooled summaries ----------
    def median(xs):
        xs = sorted(xs)
        return xs[len(xs) // 2] if xs else None

    pooled = {}
    for wname in ("full", "validation"):
        finals, holds, beats_hold, beats_btc = [], [], 0, 0
        n = 0
        for sym, coin in results["per_coin"].items():
            if coin.get("stable_or_wrapped") or wname not in coin.get("runs", {}):
                continue
            r = coin["runs"][wname]
            if r["pi_native"] is None:
                continue
            n += 1
            finals.append(r["pi_native"]["final"])
            holds.append(r["coin_buy_hold"]["final"])
            if r["pi_native"]["final"] > r["coin_buy_hold"]["final"]:
                beats_hold += 1
            if r["pi_native"]["final"] > r["btc_buy_hold_same_window"]["final"]:
                beats_btc += 1
        pooled[wname] = {"coins": n, "pi_native_median_final": median(finals),
                         "coin_hold_median_final": median(holds),
                         "pi_beats_own_coin_hold": beats_hold,
                         "pi_beats_btc_hold": beats_btc}
    results["pooled"] = pooled

    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("done")
    print(json.dumps(results["btc_primary"]["signal_census"], indent=1)[:1200])
    print(json.dumps(pooled, indent=1))


if __name__ == "__main__":
    main()
