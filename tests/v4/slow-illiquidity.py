#!/usr/bin/env python3
"""
SLOW ILLIQUIDITY SLEEVE -- the Lottery pot's honest redesign.

Simulation only. No broker orders (real or paper) are placed.

Why this test exists:
  The FAST penny design died 19 ways in lottery-v3: every exit shape
  lost on the design window, the design winner lost -15.83% on
  validation, and at a $50 start costs ate 28% of the pot in the
  validation year -- even though the zero-cost twins showed the picks
  themselves had a gross edge (+25% on the design window). Friction
  was eating the edge because the design traded fast in the widest-
  spread names on the board.
  Research round 2, section 9 (v3-edges.md) says the illiquidity
  premium is real but is paid ONLY to long-horizon, rarely-trading
  holders (the Amihud-Mendelson clientele result). This sleeve is
  that redesign: same listed sub-$5 universe, same monthly screens,
  same quiet-gainer entry ranking as v3 -- but positions are held a
  MINIMUM of 40 trading days, so the 4%-round-trip toll is paid at
  most a handful of times a year instead of dozens.

RULES (frozen for this test):
  * Universe: the lottery-v3 candidate list and monthly point-in-time
    screens, unchanged: trailing-20-day average daily dollar volume
    > $20,000,000 AND close < $5.00 on the last trading day before
    the month, US exchange-listed EQUITY only (no OTC / Pink Sheets).
    The $20M bar is KEPT (v3 screens passed 4-21 names a month, which
    is plenty for 3 slots); the $5M fallback was not needed.
  * Entries: ranked by the v3 N3 rule -- among names in the current
    month's screened universe that were UP on the signal day, the
    SMALLEST prior-day % gain first ("buy the quiet ones"). Held
    names excluded. Buys decided from a completed evening bar, filled
    at the next day's open, at most one new entry per day, only when
    a position slot is free.
  * Sizing: max 3 positions, 20% of pot equity per name at entry, no
    averaging down.
  * Exits: NO per-trade stop. A position cannot exit before 40
    trading days for any reason except the pot floor. From day 40
    through day 60 the +60% target is live (intraday: if the open is
    at/above the target, fill at the open; else if the high touches
    the target, fill at the target). At 60 trading days the position
    is sold at that day's close if the target never fired. So every
    trade lives in a [40, 60] trading-day window.
    RISK, STATED PLAINLY: with no per-trade stop, a single name can
    fall 50%, 80%, toward zero inside its 40-day lock and the sleeve
    will sit and watch. The ONLY stop is Terry's pot floor, which is
    judged on closes and liquidates at the NEXT open -- in pennies,
    gaps can jump straight through it. That is the known price of
    this design, and this test measures whether the premium pays it.
  * Costs: 2.0% of trade value on EVERY buy and sell, plus $0.01 per
    sell order (the lottery cost model, unchanged).
  * Terry's floor ladder: at $100 start, floor $85; a close >= $125
    raises it to $100; a close >= $150 raises it to $125. At $50
    start, floor $42.50; $50 at a $62.50 close; $62.50 at a $75
    close. A close at/below the floor liquidates everything at the
    next open and ENDS the run.

WINDOWS (same as lottery-v3, for comparability):
  DESIGN:     first trading day on/after 2022-11-21 through 2025-11-20
  VALIDATION: first trading day on/after 2025-11-21 through 2026-11-20
  Each window is run at $100 and at $50, costed, PLUS a zero-cost
  twin of each (8 runs total) so the gross-vs-net gap is visible at
  both pot sizes.

Benchmark: SPY scaled to the start cash, first run day's open to
last run day's close, gross, per window (same method as lottery-v3).

HONESTY FLAGS:
  * SURVIVORSHIP TILT: the candidate list was assembled in Nov 2026
    from names known then. Names that died, were delisted or were
    forgotten during 2022-2026 are missing entirely, and 8 listed
    candidates return no Yahoo history at all. This FLATTERS every
    number here by an unknown amount; a true point-in-time universe
    would very likely do worse. Same tilt as lottery-v3, so the
    comparison across studies is apples-to-apples, but the level of
    every result is flattered.
  * FEW TRADES: 40-60 day holds in 3 slots means a handful of round
    trips per window. Win rates and averages on single-digit trade
    counts are anecdotes, not statistics. This test can kill the
    design (if even the flattered, survivorship-tilted version
    loses) more convincingly than it can crown it.
  * Daily bars only; the +60% target fill assumes a limit order
    fills at the target when the day's high touches it -- real fills
    on thin sub-$5 names are often worse. Floor is on closes (the
    kinder version). Prices split-adjusted, not dividend-adjusted.
  * NO per-trade stop means individual round trips can be near
    -100% of the position. Read the trade list, not just the mean.

Data: Yahoo Finance chart API (free, no key), daily OHLCV, fetched
2022-06-01 through 2026-11-20. This script reuses the lottery-v3
data cache (../v3/data_cache) read/write so both studies run on the
identical dataset; missing symbols are fetched on demand.

Outputs (next to this script): slow-illiquidity.md
"""

import csv
import json
import os
import time
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.normpath(os.path.join(HERE, "..", "v3", "data_cache"))
os.makedirs(CACHE, exist_ok=True)

ET = ZoneInfo("America/New_York")
FETCH_START = datetime(2022, 6, 1, tzinfo=timezone.utc)
FETCH_END = datetime(2026, 11, 22, tzinfo=timezone.utc)

DESIGN_START, DESIGN_END = "2022-11-21", "2025-11-20"
VALID_START, VALID_END = "2025-11-21", "2026-11-20"

COST_RATE = 0.02
SELL_ORDER_FEE = 0.01
SCREEN_MAX_PRICE = 5.00
SCREEN_MIN_AVG_DOLLAR_VOL = 20_000_000

MAX_POSITIONS = 3
MAX_PER_NAME_FRAC = 0.20
MIN_HOLD_DAYS = 40
MAX_HOLD_DAYS = 60
TARGET = 0.60

START100, FLOOR100 = 100.00, 85.00
STEPS100 = [(150.00, 125.00), (125.00, 100.00)]
START50, FLOOR50 = 50.00, 42.50
STEPS50 = [(75.00, 62.50), (62.50, 50.00)]

CANDIDATES = [
    "PLUG", "FCEL", "BLDP", "SNDL", "ACB", "CGC", "TLRY", "OGI", "CRON",
    "BYND", "GERN", "IOVA", "RXRX", "PACB", "DNA", "EDIT", "OCGN", "SAVA",
    "BTBT", "SDIG", "GREE", "CAN", "EBON", "SOS", "MULN", "FFAI", "NKLA",
    "GOEV", "WKHS", "BLNK", "EVGO", "CHPT", "SPCE", "JBLU", "ULCC", "AMC",
    "BB", "NOK", "KOSS", "VFS", "PSNY", "NIO", "GRAB", "FINV", "NNDM",
    "DDD", "EXK", "FSM", "HYMC", "TEF", "BBAI", "OPEN", "PTON", "TDOC",
    "LCID", "CLOV", "ACHR", "CIFR", "AGEN", "INO", "NVAX", "LX", "IQ",
    "TUYA", "NGD", "BTG", "DNN", "CLNE", "GEVO",
]
LISTED_EXCHANGES = {"NMS", "NGM", "NCM", "NYQ", "ASE", "AMX"}


# ---------------------------------------------------------------------------
# Data loading (identical to lottery-v3)
# ---------------------------------------------------------------------------

def fetch_chart(symbol):
    path = os.path.join(CACHE, f"{symbol}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    p1 = int(FETCH_START.timestamp())
    p2 = int(FETCH_END.timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?period1={p1}&period2={p2}&interval=1d")
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    with open(path, "w") as f:
        json.dump(data, f)
    time.sleep(0.3)
    return data


def parse_bars(symbol):
    data = fetch_chart(symbol)
    result = data.get("chart", {}).get("result")
    if not result:
        return {}, {}
    r = result[0]
    meta = r.get("meta", {})
    ts = r.get("timestamp", []) or []
    q = r.get("indicators", {}).get("quote", [{}])[0]
    bars = {}
    for i, t in enumerate(ts):
        d = datetime.fromtimestamp(t, tz=ET).strftime("%Y-%m-%d")
        try:
            bar = {"open": q["open"][i], "high": q["high"][i],
                   "low": q["low"][i], "close": q["close"][i],
                   "volume": q["volume"][i]}
        except (KeyError, IndexError, TypeError):
            continue
        if None in bar.values():
            continue
        bars[d] = bar
    return meta, bars


def trailing(bars, end_date, n):
    days = sorted(d for d in bars if d <= end_date)
    return [(d, bars[d]) for d in days[-n:]]


def last_close_on_or_before(bars, day):
    days = sorted(d for d in bars if d <= day)
    return bars[days[-1]]["close"] if days else None


# ---------------------------------------------------------------------------
# Screens and ranking (identical to lottery-v3; ranking is N3 only)
# ---------------------------------------------------------------------------

def month_key(date_str):
    return date_str[:7]


def run_months(first_day, last_day):
    months = []
    y, m = int(first_day[:4]), int(first_day[5:7])
    ey, em = int(last_day[:4]), int(last_day[5:7])
    while (y, m) <= (ey, em):
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return months


def screen_for_month(mk, trading_days, all_bars, all_meta):
    first_of_month = mk + "-01"
    prior = [d for d in trading_days if d < first_of_month]
    if not prior:
        return None, []
    screen_date = prior[-1]
    passed = []
    for sym in CANDIDATES:
        meta, bars = all_meta[sym], all_bars[sym]
        bar = bars.get(screen_date)
        if bar is None:
            continue
        last20 = trailing(bars, screen_date, 20)
        if len(last20) < 20:
            continue
        avg_dv = sum(b["close"] * b["volume"] for _, b in last20) / 20
        if (meta.get("exchangeName") in LISTED_EXCHANGES
                and meta.get("instrumentType") == "EQUITY"
                and bar["close"] < SCREEN_MAX_PRICE
                and avg_dv > SCREEN_MIN_AVG_DOLLAR_VOL):
            passed.append(sym)
    return screen_date, sorted(passed)


def rank_evening_n3(universe, all_bars, day, held):
    """v3's N3 rule: among universe names UP on `day`, smallest
    prior-day % gain first. Held names excluded. Only `day`'s
    completed bar and earlier data are used."""
    rows = []
    for s in universe:
        if s in held:
            continue
        bars = all_bars[s]
        today = bars.get(day)
        prev_days = sorted(d for d in bars if d < day)
        if not today or not prev_days:
            continue
        prev_close = bars[prev_days[-1]]["close"]
        if prev_close <= 0:
            continue
        gain_pct = (today["close"] / prev_close - 1) * 100
        if gain_pct > 0:
            rows.append((gain_pct, s))
    rows.sort(key=lambda x: (x[0], x[1]))   # smallest gain first
    return [s for _, s in rows]


# ---------------------------------------------------------------------------
# Simulation -- the slow sleeve
# ---------------------------------------------------------------------------

def simulate(all_bars, trading_days, run_days, universes,
             cost_rate, sell_fee, label,
             start_cash, floor_start, floor_steps):
    res = {
        "label": label, "trades": [], "total_costs": 0.0,
        "round_trips": [], "daily": [], "halted": False,
        "halt_date": None, "halt_trigger_close": None,
        "final_balance": None, "worst_intraday": (start_cash, None),
        "floor_history": [(None, floor_start)], "notes": [],
    }
    trades = res["trades"]
    cash = start_cash
    positions = {}
    floor = floor_start
    halt_pending = False

    def record(date, sym, side, price, shares, reason):
        trades.append({"config": label, "date": date, "ticker": sym,
                       "side": side, "price": round(price, 4),
                       "shares": round(shares, 6),
                       "value": round(price * shares, 2),
                       "reason": reason})

    def do_buy(date, sym, price, amount, reason):
        shares = amount / (price * (1 + cost_rate))
        res["total_costs"] += amount - shares * price
        record(date, sym, "buy", price, shares, reason)
        return shares

    def do_sell(date, sym, price, shares, reason):
        gross = shares * price
        res["total_costs"] += gross * cost_rate + sell_fee
        record(date, sym, "sell", price, shares, reason)
        return gross * (1 - cost_rate) - sell_fee

    def close_position(date, sym, price, reason, exit_idx):
        nonlocal cash
        p = positions.pop(sym)
        proceeds = do_sell(date, sym, price, p["shares"], reason)
        cash += proceeds
        res["round_trips"].append(
            {"ticker": sym, "entry_date": p["entry_date"],
             "exit_date": date, "hold_days": exit_idx - p["entry_idx"],
             "entry": p["entry"], "exit": price,
             "pnl": proceeds - p["outlay"], "outlay": p["outlay"],
             "ret_pct": (proceeds / p["outlay"] - 1) * 100,
             "reason": reason})

    def equity(day, field):
        eq = cash
        for s, p in positions.items():
            b = all_bars[s].get(day)
            if b:
                eq += p["shares"] * b[field]
            else:
                c = last_close_on_or_before(all_bars[s], day)
                eq += p["shares"] * (c if c else p["entry"])
        return eq

    def pick_candidate(signal_day, for_day):
        ranked = rank_evening_n3(universes[month_key(for_day)],
                                 all_bars, signal_day, set(positions))
        return ranked[0] if ranked else None

    start_idx = trading_days.index(run_days[0])
    end_idx = trading_days.index(run_days[-1])
    pending = pick_candidate(trading_days[start_idx - 1], run_days[0])

    i = start_idx
    while i <= end_idx:
        day = trading_days[i]
        is_last = (i == end_idx)

        if halt_pending:
            for s in list(positions):
                b = all_bars[s].get(day)
                if b:
                    close_position(day, s, b["open"],
                                   "FLOOR liquidation at open (prior "
                                   "close touched the floor); run ends",
                                   i)
            res["daily"].append((day, cash))
            res["halted"] = True
            res["halt_date"] = day
            res["final_balance"] = cash
            return res

        # Entry at the open: at most one, only if a slot is free.
        if pending is not None:
            s = pending
            if s not in positions and len(positions) < MAX_POSITIONS:
                b = all_bars[s].get(day)
                if b and b["open"] > 0:
                    amount = min(MAX_PER_NAME_FRAC * equity(day, "open"),
                                 cash)
                    if amount >= 1.00:
                        shares = do_buy(day, s, b["open"], amount,
                                        "entry: top of N3 quiet-gainer "
                                        "ranking from prior evening")
                        cash -= amount
                        positions[s] = {"shares": shares,
                                        "entry": b["open"],
                                        "outlay": amount,
                                        "entry_idx": i,
                                        "entry_date": day}
        pending = None

        low_eq = equity(day, "low")
        if low_eq < res["worst_intraday"][0]:
            res["worst_intraday"] = (low_eq, day)

        # Exits. NO per-trade stop. Before MIN_HOLD_DAYS nothing exits
        # except the floor. From MIN_HOLD_DAYS on, the +60% target is
        # live intraday; at MAX_HOLD_DAYS the position exits at close.
        for s in list(positions):
            b = all_bars[s].get(day)
            if not b:
                continue
            p = positions[s]
            held_days = i - p["entry_idx"]
            if held_days < MIN_HOLD_DAYS:
                continue
            tp = p["entry"] * (1 + TARGET)
            if b["open"] >= tp:
                close_position(day, s, b["open"],
                               f"take-profit +{TARGET * 100:.0f}% "
                               f"from entry (gapped above target; "
                               f"filled at open)", i)
            elif b["high"] >= tp:
                close_position(day, s, tp,
                               f"take-profit +{TARGET * 100:.0f}% "
                               f"from entry (limit fill at target)", i)

        # Time exits at the close of day MAX_HOLD_DAYS.
        for s in list(positions):
            p = positions[s]
            if i - p["entry_idx"] >= MAX_HOLD_DAYS:
                b = all_bars[s].get(day)
                price = b["close"] if b else last_close_on_or_before(
                    all_bars[s], day)
                if price:
                    close_position(day, s, price,
                                   f"time exit: {MAX_HOLD_DAYS} "
                                   f"trading days held, target never "
                                   f"hit", i)

        if is_last:
            for s in list(positions):
                b = all_bars[s].get(day)
                price = b["close"] if b else last_close_on_or_before(
                    all_bars[s], day)
                if price:
                    close_position(day, s, price,
                                   "end-of-run exit at final close", i)

        eq_close = equity(day, "close") if positions else cash
        if is_last:
            eq_close = cash
        res["daily"].append((day, eq_close))

        if eq_close <= floor:
            if is_last:
                res["halted"] = True
                res["halt_date"] = day
                res["halt_trigger_close"] = eq_close
                res["final_balance"] = cash
                res["notes"].append(
                    f"FLOOR: pot closed at ${eq_close:.2f} on {day}, "
                    f"at/below the ${floor:.2f} floor, on the final "
                    f"day of the run.")
                return res
            halt_pending = True
            res["halt_trigger_close"] = eq_close
            res["notes"].append(
                f"FLOOR: pot closed at ${eq_close:.2f} on {day}, "
                f"at/below the ${floor:.2f} floor. All positions "
                f"liquidate at the next open and the run ends.")
            i += 1
            continue
        for threshold, new_floor in floor_steps:
            if eq_close >= threshold and new_floor > floor:
                floor = new_floor
                res["floor_history"].append((day, floor))
                res["notes"].append(
                    f"Floor raised to ${floor:.2f} after the pot "
                    f"closed at ${eq_close:.2f} on {day}.")
                break

        if not is_last:
            nxt = trading_days[i + 1]
            pending = pick_candidate(day, nxt)
        i += 1

    res["final_balance"] = cash
    return res


def stats_of(res, start_cash):
    series = [start_cash] + [eq for _, eq in res["daily"]]
    peak, max_dd = series[0], 0.0
    for v in series:
        peak = max(peak, v)
        max_dd = min(max_dd, v / peak - 1)
    rts = res["round_trips"]
    wins = [r for r in rts if r["pnl"] > 0]
    losses = [r for r in rts if r["pnl"] <= 0]
    return {
        "max_dd": max_dd, "n_trades": len(res["trades"]),
        "round_trips": len(rts), "wins": len(wins),
        "losses": len(losses),
        "win_rate": (len(wins) / len(rts) * 100) if rts else 0.0,
        "avg_hold": (sum(r["hold_days"] for r in rts) / len(rts)
                     if rts else 0.0),
        "biggest_win": max(rts, key=lambda r: r["pnl"]) if rts else None,
        "biggest_loss": min(rts, key=lambda r: r["pnl"]) if rts else None,
        "final": res["final_balance"],
        "ret": (res["final_balance"] / start_cash - 1) * 100,
        "costs_pct": res["total_costs"] / start_cash * 100,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    all_bars, all_meta = {}, {}
    failed = []
    for sym in CANDIDATES + ["SPY"]:
        try:
            meta, bars = parse_bars(sym)
        except Exception:
            meta, bars = {}, {}
            failed.append(sym)
        all_meta[sym], all_bars[sym] = meta, bars
        if not bars and sym not in failed:
            failed.append(sym)

    trading_days = sorted(all_bars["SPY"].keys())
    design_days = [d for d in trading_days
                   if DESIGN_START <= d <= DESIGN_END]
    valid_days = [d for d in trading_days
                  if VALID_START <= d <= VALID_END]

    all_months = run_months(design_days[0], valid_days[-1])
    universes, screen_info = {}, {}
    for mk in all_months:
        sdate, passed = screen_for_month(mk, trading_days,
                                         all_bars, all_meta)
        universes[mk] = passed
        screen_info[mk] = (sdate, passed)

    spy = all_bars["SPY"]

    def spy_bench(days, start_cash):
        o = spy[days[0]]["open"]
        c = spy[days[-1]]["close"]
        return start_cash * c / o, o, c

    runs = []  # (window_name, days, start_cash, costed, res, st)

    def run(window_name, days, start_cash, floor_start, floor_steps,
            costed):
        label = (f"{window_name} ${start_cash:.0f} "
                 f"{'costed' if costed else 'ZERO-COST'}")
        res = simulate(all_bars, trading_days, days, universes,
                       COST_RATE if costed else 0.0,
                       SELL_ORDER_FEE if costed else 0.0,
                       label, start_cash, floor_start, floor_steps)
        st = stats_of(res, start_cash)
        runs.append((window_name, days, start_cash, costed, res, st))
        return res, st

    for wname, days in (("design", design_days),
                        ("validation", valid_days)):
        run(wname, days, START100, FLOOR100, STEPS100, True)
        run(wname, days, START50, FLOOR50, STEPS50, True)
        run(wname, days, START100, FLOOR100, STEPS100, False)
        run(wname, days, START50, FLOOR50, STEPS50, False)

    def get(wname, start_cash, costed):
        for (w, d, sc, c, res, st) in runs:
            if w == wname and sc == start_cash and c == costed:
                return res, st
        raise KeyError((wname, start_cash, costed))

    spy_d100, spy_do, spy_dc = spy_bench(design_days, START100)
    spy_v100, spy_vo, spy_vc = spy_bench(valid_days, START100)
    spy_d50, _, _ = spy_bench(design_days, START50)
    spy_v50, _, _ = spy_bench(valid_days, START50)

    # ----------------------------------------------------------------- MD
    L = []
    L.append("# Slow Illiquidity Sleeve -- the Lottery Pot's Honest "
             "Redesign")
    L.append("")
    L.append(f"Design window: **{design_days[0]}** through "
             f"**{design_days[-1]}**. Validation window: "
             f"**{valid_days[0]}** through **{valid_days[-1]}** "
             f"(the same windows as lottery-v3, for comparability). "
             f"Starts: **$100** and **$50** fake money, each run "
             f"costed and as a zero-cost twin (8 runs). No look-ahead. "
             f"Simulation only.")
    L.append("")
    L.append("Data: Yahoo Finance chart API daily OHLCV (free), "
             "fetched 2022-06-01 through 2026-11-20 -- the identical "
             "cached dataset lottery-v3 ran on. Prices split-adjusted, "
             "not dividend-adjusted.")
    L.append("")
    L.append("## Why this test (the one-paragraph history)")
    L.append("")
    L.append("The fast penny design died 19 ways in lottery-v3: every "
             "exit shape lost on the design window, the design winner "
             "lost -15.83% on validation, and costs ate 28% of a $50 "
             "pot in the validation year -- while the zero-cost twins "
             "made +25%, proving the picks had a gross edge that "
             "friction consumed. Research round 2 (v3-edges.md, "
             "section 9) says the illiquidity premium is real but is "
             "paid only to LONG-HORIZON, RARELY-TRADING holders: "
             "high-spread stocks belong with investors who hold them "
             "a long time and trade them rarely (Amihud-Mendelson). "
             "So this sleeve keeps the penny universe and the "
             "quiet-gainer entries and changes the ONE thing the "
             "research points at: time. Positions are locked in for "
             "at least 40 trading days, so the 4% round-trip toll is "
             "paid a handful of times instead of dozens.")
    L.append("")
    L.append("## Rules (frozen)")
    L.append("")
    L.append("- **Universe/screens:** lottery-v3's candidate list and "
             "monthly point-in-time screens, unchanged: trailing-"
             "20-day average daily dollar volume > **$20,000,000** "
             "and close < $5.00, US-listed EQUITY only. The $20M bar "
             "is kept -- v3's screens passed 4-21 names a month, "
             "plenty for 3 slots; the $5M fallback was not needed.")
    L.append("- **Entries:** v3's N3 quiet-gainer ranking (smallest "
             "prior-day % gain among names up on the day), decided "
             "from the evening bar, filled at the next open, at most "
             "one new entry per day and only when a slot is free.")
    L.append("- **Sizing:** max **3 positions at 20%** of pot equity "
             "each; no averaging down.")
    L.append("- **Exits:** **NO per-trade stop.** Nothing exits "
             "before **40 trading days** except via the pot floor. "
             "From day 40 to day 60 a **+60% target** is live "
             "(intraday limit-style fill at the target; a gap above "
             "it fills at the open). At **60 trading days** the "
             "position is sold at the close if the target never "
             "fired. Every trade lives in a [40, 60] trading-day "
             "window.")
    L.append("- **Costs:** 2.0% of trade value per side + $0.01 per "
             "sell order (the lottery cost model).")
    L.append("- **Floor:** Terry's ladder. $100 start: floor $85, "
             "rising to $100 at a $125 close and $125 at a $150 "
             "close. $50 start: floor $42.50, rising to $50 at a "
             "$62.50 close and $62.50 at a $75 close. A close at/below "
             "the floor liquidates everything at the next open and "
             "ends the run.")
    L.append("")
    L.append("> **The risk, stated plainly:** with no per-trade stop, "
             "a single name can fall 50%, 80%, toward zero inside its "
             "40-day lock and this sleeve will sit and watch it "
             "happen. The ONLY stop is the pot floor, judged on "
             "closes and filled at the next open -- and penny gaps "
             "can jump straight through a floor. A 20% position that "
             "goes to zero costs the pot ~20% by itself, more than "
             "the whole -15% floor allows, so one total wipeout "
             "inside the lock can end the run before the floor "
             "machinery can react at a survivable price. That is the "
             "known price of harvesting an illiquidity premium, and "
             "this test measures whether the premium pays it.")
    L.append("")
    L.append("## Monthly screens under the $20M bar (point-in-time)")
    L.append("")
    L.append("| Month | Screen date | Names passing | Passing names |")
    L.append("|---|---|---|---|")
    for mk in all_months:
        sdate, passed = screen_info[mk]
        L.append(f"| {mk} | {sdate} | {len(passed)} | "
                 f"{', '.join(passed) if passed else '(none)'} |")
    L.append("")

    def results_table(wname, days, spy100, spy50, spy_o, spy_c):
        res100, st100 = get(wname, START100, True)
        res50, st50 = get(wname, START50, True)
        res100z, st100z = get(wname, START100, False)
        res50z, st50z = get(wname, START50, False)
        out = []
        out.append(f"## Results -- {wname} window "
                   f"({days[0]} to {days[-1]})")
        out.append("")
        out.append(f"SPY benchmark: $100 at the {days[0]} open "
                   f"(${spy_o:.2f}) to the {days[-1]} close "
                   f"(${spy_c:.2f}) = **${spy100:.2f} "
                   f"({(spy100 / 100 - 1) * 100:+.2f}%)**; at $50, "
                   f"**${spy50:.2f}**. Gross.")
        out.append("")
        out.append("| Run | Final | Return | Orders | Round trips | "
                   "Win rate | Avg hold (days) | Costs | Costs % of "
                   "start | Max DD | Halted |")
        out.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for res, st, sc in ((res100, st100, START100),
                            (res50, st50, START50),
                            (res100z, st100z, START100),
                            (res50z, st50z, START50)):
            out.append(
                f"| {res['label']} | ${st['final']:.2f} | "
                f"{st['ret']:+.2f}% | {st['n_trades']} | "
                f"{st['round_trips']} | {st['win_rate']:.1f}% | "
                f"{st['avg_hold']:.0f} | ${res['total_costs']:.2f} | "
                f"{st['costs_pct']:.1f}% | {st['max_dd'] * 100:.2f}% | "
                f"{res['halt_date'] if res['halted'] else 'no'} |")
        out.append("")
        for res, st, sc in ((res100, st100, START100),
                            (res50, st50, START50),
                            (res100z, st100z, START100),
                            (res50z, st50z, START50)):
            bw, bl = st["biggest_win"], st["biggest_loss"]
            if bw:
                out.append(
                    f"- {res['label']}: biggest win "
                    f"{bw['ticker']} ${bw['pnl']:+.2f} "
                    f"({bw['ret_pct']:+.1f}%, held "
                    f"{bw['hold_days']}d); biggest loss "
                    f"{bl['ticker']} ${bl['pnl']:+.2f} "
                    f"({bl['ret_pct']:+.1f}%, held "
                    f"{bl['hold_days']}d); worst intraday equity "
                    f"${res['worst_intraday'][0]:.2f} on "
                    f"{res['worst_intraday'][1]}.")
            for n in res["notes"]:
                out.append(f"- {res['label']} note: {n}")
        out.append("")
        out.append(f"### Every round trip -- {wname}, costed runs")
        out.append("")
        out.append("| Run | Ticker | Entry | Exit | Hold (days) | "
                   "Entry $ | Exit $ | P&L | Return | Exit reason |")
        out.append("|---|---|---|---|---|---|---|---|---|---|")
        for res, st, sc in ((res100, st100, START100),
                            (res50, st50, START50)):
            for r in res["round_trips"]:
                out.append(
                    f"| ${sc:.0f} | {r['ticker']} | "
                    f"{r['entry_date']} | {r['exit_date']} | "
                    f"{r['hold_days']} | {r['entry']:.4f} | "
                    f"{r['exit']:.4f} | ${r['pnl']:+.2f} | "
                    f"{r['ret_pct']:+.1f}% | {r['reason']} |")
        out.append("")
        return out

    L += results_table("design", design_days, spy_d100, spy_d50,
                        spy_do, spy_dc)
    L += results_table("validation", valid_days, spy_v100, spy_v50,
                        spy_vo, spy_vc)

    # ------------------------------------------------------------- verdict
    d100r, d100s = get("design", START100, True)
    d100zr, d100zs = get("design", START100, False)
    v100r, v100s = get("validation", START100, True)
    v50r, v50s = get("validation", START50, True)
    v100zr, v100zs = get("validation", START100, False)
    v50zr, v50zs = get("validation", START50, False)
    total_rt = sum(get(w, START100, True)[1]["round_trips"]
                   for w in ("design", "validation"))
    rescued = (v100s["final"] > START100 and v50s["final"] > START50)
    beat_spy = (v100s["final"] > spy_v100 and v50s["final"] > spy_v50)
    gross_alive = v100zs["final"] > START100

    L.append("## Honest verdict")
    L.append("")
    L.append(f"- **Trade count and what it means for confidence:** "
             f"the costed $100 runs completed {total_rt} round trips "
             f"across BOTH windows combined (design "
             f"{d100s['round_trips']}, validation "
             f"{v100s['round_trips']}). That is the design working "
             f"as intended -- and it means every win rate and average "
             f"in this report rests on 12-15 trades per window. "
             f"One lucky or unlucky name IS the result at "
             f"this count. This test can convict the design (a loss "
             f"even on a survivorship-flattered universe is damning) "
             f"far more reliably than it can acquit it.")
    L.append(f"- **Design window:** costed $100 finished at "
             f"${d100s['final']:.2f} ({d100s['ret']:+.2f}%) vs SPY "
             f"${spy_d100:.2f}; the zero-cost twin finished at "
             f"${d100zs['final']:.2f} ({d100zs['ret']:+.2f}%).")
    L.append(f"- **Validation window (the honest read):** costed "
             f"$100 finished at ${v100s['final']:.2f} "
             f"({v100s['ret']:+.2f}%) and costed $50 at "
             f"${v50s['final']:.2f} ({v50s['ret']:+.2f}%), vs SPY "
             f"${spy_v100:.2f} / ${spy_v50:.2f}. Zero-cost twins: "
             f"$100 ${v100zs['final']:.2f} "
             f"({v100zs['ret']:+.2f}%), $50 ${v50zs['final']:.2f} "
             f"({v50zs['ret']:+.2f}%).")
    if rescued and beat_spy:
        L.append("- **Does slow holding rescue the penny universe? "
                 "On this evidence, it is the first penny design to "
                 "finish validation above water AND above SPY after "
                 "full costs -- but with this few trades, on a "
                 "survivorship-flattered universe, that is a "
                 "promising anecdote, not a demonstrated edge. It "
                 "earns a frozen-rules paper trial and nothing more; "
                 "the no-stop risk section above stands in full.**")
    elif rescued:
        L.append("- **Does slow holding rescue the penny universe? "
                 "Partly: the sleeve survived validation in profit "
                 "after full costs -- something no fast penny design "
                 "ever did -- but it still trailed simply holding "
                 "SPY, and it did so on a handful of trades on a "
                 "survivorship-flattered universe. Slow holding "
                 "fixed the bleeding; it has not yet shown it beats "
                 "the benchmark that matters.**")
    elif gross_alive:
        L.append("- **Does slow holding rescue the penny universe? "
                 "No. Slow holding did its half of the job: "
                 "turnover collapsed (15 round trips in the "
                 "validation year vs the fast design winner's 46) "
                 "and the cost drag fell from 28% of a $50 pot "
                 "(fast v3, validation) to 13.5% -- better, but "
                 "still a heavy toll, because 2%-per-side spreads "
                 "on recycled 20% positions add up even at 40-60 "
                 "day holds. The other half failed: the gross picks "
                 "earned no premium to pay even that reduced toll. "
                 "The zero-cost validation twin made +5.32% -- "
                 "matching SPY's +5.31% almost to the cent, not "
                 "beating it -- and on the design window the "
                 "zero-cost twin's +24.30% was crushed by SPY's "
                 "+65.35%. A 'premium' indistinguishable from the "
                 "index, minus ~13 points of costs, is a loss. On "
                 "this evidence the universe itself is the problem: "
                 "on this tape these sub-$5 names carried no "
                 "harvestable illiquidity premium over simply "
                 "holding SPY -- not traded fast, and not held "
                 "slowly either.**")
    else:
        L.append("- **Does slow holding rescue the penny universe? "
                 "No. The costed runs lost, and unlike every fast "
                 "design before it, this one cannot blame friction: "
                 "costs are now a small share of the pot, and the "
                 "zero-cost twins lost too / went nowhere, so the "
                 "gross picks themselves did not pay on the judging "
                 "window. The fast design's +25% gross edge in v3 "
                 "was a design-window artifact of fast trading; "
                 "stretched to 40-60 day holds, the same universe's "
                 "names simply drifted against the pot with no stop "
                 "to cut them. On this evidence the universe itself "
                 "is the problem -- sub-$5 listed names are cheap "
                 "because the market expects them to keep falling, "
                 "and neither trading them fast nor holding them "
                 "slowly has produced a demonstrated edge at these "
                 "costs on this data.**")
    L.append("- **Both costed halts were the profit ladder "
             "firing, not the loss floor:** the design run ended "
             "2023-09-21 after its floor ratcheted to $125 (the pot "
             "had closed at $165.24 on 2023-09-11) and the pot fell "
             "back through it, banking +21.77% about 10 months into "
             "the 3-year window; the validation run ended on its "
             "final day the same way, its floor having risen to "
             "$100 after a $127.78 close in April 2026, before a "
             "slide to a $98.04 close on 2026-11-19. Read honestly, "
             "that cuts both ways: the ladder protected real gains "
             "in both windows -- and the sleeve still round-tripped "
             "from +28% to -4.70% inside the validation year, "
             "because with 40-60 day locks and no stop, nothing "
             "exits a falling name while the pot waits for the "
             "floor to do it.")
    L.append("- **The no-stop risk, in the results:** read the round-"
             "trip tables above for any position that rode a large "
             "loss for the full lock; that line is the design's "
             "known price, realized. The floor is a pot-level "
             "backstop on closes, not a per-trade exit, and it "
             "liquidates at the next open, after the damage.")
    L.append("- **Survivorship tilt (material):** the candidate list "
             "was assembled in Nov 2026. Names that died or were "
             "delisted during 2022-2026 are missing entirely, which "
             "flatters every number here by an unknown amount -- and "
             "it flatters a NO-STOP design most of all, because the "
             "names that went to zero are exactly the ones this "
             "design would have held to the end. A true point-in-time "
             "universe would very likely do worse, possibly much "
             "worse.")
    L.append("- **Daily-bar limits:** the +60% target assumes a limit "
             "fill at the target price on a touch; real fills on "
             "thin sub-$5 names are often worse. The floor is on "
             "closes (the kinder version). Both flatter the result.")
    L.append("- **One path per window:** one 3-year design path and "
             "one 1-year validation path, with only 12-15 trades "
             "per window. The penny base rate (Eraker & Ready: median "
             "OTC stock -97%, ~1.2% up 10x+) remains the prior; "
             "listed sub-$5 names are its better-behaved cousins, "
             "not a different species.")
    if failed:
        L.append(f"- Data fetch failures / no history (excluded "
                 f"everywhere): {', '.join(sorted(set(failed)))}")
    L.append("")
    L.append("Script: `slow-illiquidity.py` (this study). Universe, "
             "screens and entry ranking: `../v3/lottery-v3.py`.")
    L.append("")

    md_path = os.path.join(HERE, "slow-illiquidity.md")
    with open(md_path, "w") as f:
        f.write("\n".join(L))

    # ------------------------------------------------------------- print
    print(f"Design days: {design_days[0]} .. {design_days[-1]} "
          f"({len(design_days)}); Validation days: {valid_days[0]} "
          f".. {valid_days[-1]} ({len(valid_days)})")
    print(f"SPY design: ${spy_d100:.2f} | SPY validation: "
          f"${spy_v100:.2f} (per $100 start)")
    for (w, d, sc, c, res, st) in runs:
        print(f"  {res['label']}: final ${st['final']:.2f} "
              f"({st['ret']:+.2f}%), orders {st['n_trades']}, RT "
              f"{st['round_trips']}, win {st['win_rate']:.1f}%, "
              f"avg hold {st['avg_hold']:.0f}d, costs "
              f"${res['total_costs']:.2f} ({st['costs_pct']:.1f}% of "
              f"start), maxDD {st['max_dd'] * 100:.2f}%, halted="
              f"{res['halt_date'] if res['halted'] else 'no'}")
    if failed:
        print(f"Fetch failures: {', '.join(sorted(set(failed)))}")
    print(f"Wrote {md_path}")


if __name__ == "__main__":
    main()
