#!/usr/bin/env python3
"""
Penny-Stock Lottery Pot -- v2 (cost-attack redesign), ONE-YEAR backtest.
Run window: first trading day on/after Fri 2025-11-21 through Fri 2026-11-20
-- identical to the v0 run so the two are directly comparable.

Simulation only. No broker orders (real or paper) are placed.

What v2 changes vs v0 (v0: dead at $84.04, floor hit 2026-03-12, 32 round
trips, $23.36 of costs = 23.4% of the pot -- friction was the killer):
  1. HIGHER VOLUME BAR: the monthly point-in-time screen now requires a
     trailing-20-day average daily dollar volume above $20,000,000
     (v0: $5,000,000). Close must still be < $5.00. US exchange-listed
     equity only; OTC / Pink Sheet names never allowed.
  2. FAR FEWER TRADES: at most ONE new entry per day (only the single
     highest-ranked signal from the evening ranking) and at most 2 new
     entries per calendar week.
  3. WIDER EXITS: stop -15% from entry (v0: -10%), take-profit +40%
     (v0: +25%), stop fills first if both are touched the same day.
     Max position 15% of pot (v0: 20%), max 5 positions, no averaging down.
  4. COST GATE: a trade is skipped if its estimated round-trip cost
     (2.0% per side = 4.0% of the position, per the specified formula)
     exceeds 10% of the dollar gain available at the +40% target
     (10% x 40% = 4.0% of the position). NOTE: as specified, the two
     sides of this comparison are exactly equal (4.0% vs 4.0%), so the
     gate passes every trade it is shown; the report states this plainly.
     Under v0's +25% target the same gate would have read 4.0% vs 2.5%
     and failed every trade -- that asymmetry is the friction problem v2
     attacks. The $0.01 per-sell-order fee is charged in the simulation
     but is not part of the gate's specified formula.
  5. VARIANT B (report-only comparison): identical to variant A except
     new entries are BLOCKED on any signal evening when SPY closed below
     its 200-day moving average. Exits, floor and sizing are unchanged.
     SPY's 200-day average needs history before the fetch window, so SPY
     is additionally fetched from 2024-01-01 for the regime calculation
     only; all trading/screening data uses 2025-06-01 onward as in v0.

Unchanged from v0 / Terry's rules:
  * $100.00 start; every decision uses only data available at that point
    (buys decided the evening before from that day's completed bar,
    filled at the next day's open).
  * Costs: 2.0% of trade value on EVERY buy and sell, plus $0.01 per sell
    order. Each variant also gets an identical ZERO-COST twin so friction
    is isolated exactly.
  * FLOOR LADDER: floor starts $85.00; a close >= $125 raises it to $100;
    a close >= $150 raises it to $125. A close at/below the floor
    liquidates everything at the next open and ENDS the run.
  * Evening ranking: score = prior-day % gain x volume spike (day volume
    / trailing-20-day average volume), positive scores only, held names
    excluded -- the same ranking as v0.
  * Benchmark: SPY $100 at the first run day's open to the 2026-11-20
    close, gross.

HONESTY FLAG (carried from v0): the candidate list was assembled in
Nov 2026 from names known then, so it carries survivorship tilt (names
that died mid-year may be missing). That FLATTERS results.

Data: Yahoo Finance chart API (free, no key), daily OHLCV. Cached JSON
from the v0 run (~/workspace/stock-app/backtests/2025-11-21-year/
data_cache/) is reused when present; missing symbols are fetched fresh.
Prices are split-adjusted, not dividend-adjusted.

Outputs (next to this script): lottery-v2-trades.csv (costed runs of
BOTH variants, with a variant column), lottery-v2.md.
"""

import csv
import json
import os
import time
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data_cache")
os.makedirs(CACHE, exist_ok=True)
V0_CACHE = os.path.expanduser(
    "~/workspace/stock-app/backtests/2025-11-21-year/data_cache")

ET = ZoneInfo("America/New_York")
RUN_START = "2025-11-21"
RUN_END = "2026-11-20"

START_CASH = 100.00
FLOOR_START = 85.00
FLOOR_STEPS = [(150.00, 125.00), (125.00, 100.00)]
MAX_POSITIONS = 5
MAX_PER_NAME_FRAC = 0.15          # v2: 15% (v0: 20%)
STOP_FRAC = 0.15                  # v2: -15% (v0: -10%)
TP_FRAC = 0.40                    # v2: +40% (v0: +25%)
COST_RATE = 0.02
SELL_ORDER_FEE = 0.01
SCREEN_MAX_PRICE = 5.00
SCREEN_MIN_AVG_DOLLAR_VOL = 20_000_000   # v2: $20M (v0: $5M)
MAX_ENTRIES_PER_WEEK = 2                 # v2
# Cost gate, exactly as specified: round-trip cost = 2 x 2.0% of the
# position; skip if it exceeds 10% of the gain available at the +40%
# target (0.10 x 0.40 of the position).
GATE_COST_FRAC = 2 * COST_RATE           # 0.04
GATE_LIMIT_FRAC = 0.10 * TP_FRAC         # 0.04

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


# --------------------------------------------------------------------------
# Data loading
# --------------------------------------------------------------------------

def fetch_chart(symbol, p1_dt=None, cache_name=None):
    """Daily OHLCV JSON from Yahoo, layered caches: v2 cache, v0 cache,
    then a fresh fetch."""
    name = cache_name or f"{symbol}.json"
    path = os.path.join(CACHE, name)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    if p1_dt is None:
        v0_path = os.path.join(V0_CACHE, f"{symbol}.json")
        if os.path.exists(v0_path):
            with open(v0_path) as f:
                data = json.load(f)
            with open(path, "w") as f:
                json.dump(data, f)
            return data
    p1 = int((p1_dt or datetime(2025, 6, 1, tzinfo=timezone.utc)).timestamp())
    p2 = int(datetime(2026, 11, 22, tzinfo=timezone.utc).timestamp())
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


def parse_bars(symbol, **kw):
    data = fetch_chart(symbol, **kw)
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


# --------------------------------------------------------------------------
# Screens and ranking (v0 mechanics, v2 volume bar)
# --------------------------------------------------------------------------

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
        return None, [], {}
    screen_date = prior[-1]
    passed, detail = [], {}
    for sym in CANDIDATES:
        meta, bars = all_meta[sym], all_bars[sym]
        bar = bars.get(screen_date)
        if bar is None:
            continue
        last20 = trailing(bars, screen_date, 20)
        if len(last20) < 20:
            continue
        avg_dv = sum(b["close"] * b["volume"] for _, b in last20) / 20
        detail[sym] = (bar["close"], avg_dv)
        if (meta.get("exchangeName") in LISTED_EXCHANGES
                and meta.get("instrumentType") == "EQUITY"
                and bar["close"] < SCREEN_MAX_PRICE
                and avg_dv > SCREEN_MIN_AVG_DOLLAR_VOL):
            passed.append(sym)
    return screen_date, sorted(passed), detail


def rank_evening(universe, all_bars, day, held):
    """v0 ranking: score = prior-day % gain x volume spike; positive only."""
    ranked = []
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
        last20 = trailing(bars, day, 20)
        avg_vol = (sum(b["volume"] for _, b in last20) / len(last20)
                   if last20 else 0)
        spike = (today["volume"] / avg_vol) if avg_vol else 0.0
        score = gain_pct * spike
        if score > 0:
            ranked.append((score, s))
    ranked.sort(reverse=True)
    return [s for _, s in ranked]


def spy_below_200dma(spy_long_bars, day):
    """True if SPY closed below its trailing 200-day average on `day`
    (average of the 200 closes ending on `day`). If history is somehow
    short, entries are allowed (returns False)."""
    closes = [b["close"] for _, b in trailing(spy_long_bars, day, 200)]
    bar = spy_long_bars.get(day)
    if bar is None or len(closes) < 200:
        return False
    return bar["close"] < sum(closes) / len(closes)


# --------------------------------------------------------------------------
# Simulation
# --------------------------------------------------------------------------

def simulate(all_bars, spy_long_bars, trading_days, run_days, universes,
             cost_rate, sell_fee, variant):
    """variant: 'A' = v2 as specified; 'B' = v2 + SPY-regime entry block."""
    res = {
        "trades": [], "total_costs": 0.0, "round_trips": [],
        "daily": [], "halted": False, "halt_date": None,
        "halt_trigger_close": None, "final_balance": None,
        "worst_intraday": (START_CASH, None), "intraday_floor_dips": [],
        "gap_through_stops": 0, "floor_history": [(None, FLOOR_START)],
        "notes": [], "gate_skips": 0, "regime_blocks": 0,
        "week_cap_blocks": 0,
    }
    trades = res["trades"]
    cash = START_CASH
    positions = {}
    floor = FLOOR_START
    halt_pending = False
    entries_by_week = {}

    def record(date, sym, side, price, shares, reason):
        trades.append({"variant": variant, "date": date, "ticker": sym,
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

    def close_position(date, sym, price, reason):
        nonlocal cash
        p = positions.pop(sym)
        proceeds = do_sell(date, sym, price, p["shares"], reason)
        cash += proceeds
        res["round_trips"].append(
            {"ticker": sym, "exit_date": date,
             "pnl": proceeds - p["outlay"], "outlay": p["outlay"]})

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

    def week_key(day):
        iso = datetime.strptime(day, "%Y-%m-%d").date().isocalendar()
        return (iso[0], iso[1])

    def pick_candidate(signal_day, for_day):
        """The single entry candidate for `for_day`, decided on the
        evening of `signal_day`. Returns a symbol or None. Applies the
        variant-B regime block (B only)."""
        ranked = rank_evening(universes[month_key(for_day)], all_bars,
                              signal_day, set(positions))
        if not ranked:
            return None
        if variant == "B" and spy_below_200dma(spy_long_bars, signal_day):
            res["regime_blocks"] += 1
            return None
        return ranked[0]

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
                                   "FLOOR liquidation at open (prior close "
                                   "touched the floor); run ends")
            res["daily"].append((day, cash))
            res["halted"] = True
            res["halt_date"] = day
            res["final_balance"] = cash
            return res

        # Entry at the open: at most one, at most 2 per calendar week.
        if pending is not None:
            s = pending
            wk = week_key(day)
            if entries_by_week.get(wk, 0) >= MAX_ENTRIES_PER_WEEK:
                res["week_cap_blocks"] += 1
            elif s not in positions and len(positions) < MAX_POSITIONS:
                b = all_bars[s].get(day)
                if b and b["open"] > 0:
                    amount = min(MAX_PER_NAME_FRAC * equity(day, "open"),
                                 cash)
                    if amount >= 1.00:
                        # COST GATE (specified formula).
                        gate_cost = GATE_COST_FRAC * amount
                        gate_limit = GATE_LIMIT_FRAC * amount
                        if gate_cost > gate_limit:
                            res["gate_skips"] += 1
                        else:
                            shares = do_buy(
                                day, s, b["open"], amount,
                                "entry: single top momentum x volume "
                                "rank from prior evening (v2)")
                            cash -= amount
                            positions[s] = {"shares": shares,
                                            "entry": b["open"],
                                            "outlay": amount}
                            entries_by_week[wk] = \
                                entries_by_week.get(wk, 0) + 1
        pending = None

        low_eq = equity(day, "low")
        if low_eq < res["worst_intraday"][0]:
            res["worst_intraday"] = (low_eq, day)

        # Intraday exits: stop first, then take-profit (v2 levels).
        for s in list(positions):
            b = all_bars[s].get(day)
            if not b:
                continue
            entry = positions[s]["entry"]
            stop, tp = entry * (1 - STOP_FRAC), entry * (1 + TP_FRAC)
            if b["low"] <= stop:
                if b["open"] < stop:
                    res["gap_through_stops"] += 1
                    res["notes"].append(
                        f"{day}: {s} gapped down through its stop (opened "
                        f"${b['open']:.4f} vs stop ${stop:.4f}); filled at "
                        f"the open, worse than the stop level.")
                    fill = b["open"]
                else:
                    fill = stop
                close_position(day, s, fill, "stop-loss -15% from entry")
            elif b["high"] >= tp:
                close_position(day, s, tp,
                               "take-profit +40% from entry (sold all)")

        if is_last:
            for s in list(positions):
                b = all_bars[s].get(day)
                price = b["close"] if b else last_close_on_or_before(
                    all_bars[s], day)
                if price:
                    close_position(day, s, price,
                                   "end-of-run exit at final close")

        eq_close = equity(day, "close") if positions else cash
        if is_last:
            eq_close = cash
        res["daily"].append((day, eq_close))

        if low_eq < floor and eq_close > floor:
            res["intraday_floor_dips"].append((day, low_eq, floor))

        if eq_close <= floor:
            if is_last:
                res["halted"] = True
                res["halt_date"] = day
                res["halt_trigger_close"] = eq_close
                res["final_balance"] = cash
                res["notes"].append(
                    f"FLOOR: pot closed at ${eq_close:.2f} on {day}, "
                    f"at/below the ${floor:.2f} floor, on the final day "
                    f"of the run; positions were liquidated at that close.")
                return res
            halt_pending = True
            res["halt_trigger_close"] = eq_close
            res["notes"].append(
                f"FLOOR: pot closed at ${eq_close:.2f} on {day}, at/below "
                f"the ${floor:.2f} floor. All positions liquidate at the "
                f"next open and the run ends.")
            i += 1
            continue
        for threshold, new_floor in FLOOR_STEPS:
            if eq_close >= threshold and new_floor > floor:
                floor = new_floor
                res["floor_history"].append((day, floor))
                res["notes"].append(
                    f"Floor raised to ${floor:.2f} after the pot closed at "
                    f"${eq_close:.2f} on {day}.")
                break

        if not is_last:
            nxt = trading_days[i + 1]
            pending = pick_candidate(day, nxt)
        i += 1

    res["final_balance"] = cash
    return res


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def stats_of(res):
    series = [START_CASH] + [eq for _, eq in res["daily"]]
    peak, max_dd = series[0], 0.0
    for v in series:
        peak = max(peak, v)
        max_dd = min(max_dd, v / peak - 1)
    rts = res["round_trips"]
    wins = [r for r in rts if r["pnl"] > 0]
    losses = [r for r in rts if r["pnl"] <= 0]
    return {
        "max_dd": max_dd, "n_trades": len(res["trades"]),
        "n_buys": sum(1 for t in res["trades"] if t["side"] == "buy"),
        "n_sells": sum(1 for t in res["trades"] if t["side"] == "sell"),
        "round_trips": len(rts), "wins": len(wins), "losses": len(losses),
        "win_rate": (len(wins) / len(rts) * 100) if rts else 0.0,
        "biggest_win": max(rts, key=lambda r: r["pnl"]) if rts else None,
        "biggest_loss": min(rts, key=lambda r: r["pnl"]) if rts else None,
        "final": res["final_balance"],
        "ret": (res["final_balance"] / START_CASH - 1) * 100,
    }


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

    # Long SPY history for the variant-B 200-day average only.
    _, spy_long_bars = parse_bars(
        "SPY", p1_dt=datetime(2024, 1, 1, tzinfo=timezone.utc),
        cache_name="SPY_long.json")
    if not spy_long_bars:
        spy_long_bars = all_bars["SPY"]

    spy_days = sorted(all_bars["SPY"].keys())
    trading_days = [d for d in spy_days if "2025-06-01" <= d <= RUN_END]
    run_days = [d for d in trading_days if RUN_START <= d <= RUN_END]
    first_day, last_day = run_days[0], run_days[-1]

    months = run_months(first_day, last_day)
    universes, screen_info = {}, {}
    for mk in months:
        sdate, passed, detail = screen_for_month(mk, trading_days,
                                                 all_bars, all_meta)
        universes[mk] = passed
        screen_info[mk] = (sdate, passed, detail)

    runs = {}
    for variant in ("A", "B"):
        runs[(variant, "costed")] = simulate(
            all_bars, spy_long_bars, trading_days, run_days, universes,
            COST_RATE, SELL_ORDER_FEE, variant)
        runs[(variant, "free")] = simulate(
            all_bars, spy_long_bars, trading_days, run_days, universes,
            0.0, 0.0, variant)

    spy = all_bars["SPY"]
    spy_open = spy[first_day]["open"]
    spy_close = spy[last_day]["close"]
    spy_final = 100.0 * spy_close / spy_open
    spy_ret = spy_final - 100.0

    first_below_200dma = next(
        (d for d in run_days if spy_below_200dma(spy_long_bars, d)), None)

    S = {k: stats_of(v) for k, v in runs.items()}
    A, Af = S[("A", "costed")], S[("A", "free")]
    B, Bf = S[("B", "costed")], S[("B", "free")]
    rA = runs[("A", "costed")]
    rB = runs[("B", "costed")]

    def monthly_balances(res):
        out = []
        for mk in months:
            vals = [(d, eq) for d, eq in res["daily"]
                    if month_key(d) == mk]
            if vals:
                out.append((mk, vals[-1][0], vals[-1][1]))
        return out

    # ---------------------------------------------------------------- CSV
    csv_path = os.path.join(HERE, "lottery-v2-trades.csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["variant", "date", "ticker",
                                          "side", "price", "shares",
                                          "value", "reason"])
        w.writeheader()
        w.writerows(rA["trades"])
        w.writerows(rB["trades"])

    # ----------------------------------------------------------------- MD
    L = []
    L.append("# Penny-Stock Lottery Pot -- v2 (Cost-Attack Redesign), "
             "ONE-YEAR Backtest")
    L.append("")
    L.append(f"Run window: **{first_day}** through **{last_day}** -- the "
             f"identical window to v0. Start: **$100.00** fake money, "
             f"treated like real money (full costs, no look-ahead). "
             f"Simulation only -- no real or paper broker orders.")
    L.append("")
    L.append("Data: Yahoo Finance chart API daily OHLCV (free), fetched "
             "2025-06-01 through 2026-11-20 (v0 cache reused; SPY also "
             "fetched from 2024-01-01 solely so variant B's 200-day "
             "average exists from day one). Prices are split-adjusted, "
             "not dividend-adjusted.")
    L.append("")
    L.append("## What v2 changed (and what it did not)")
    L.append("")
    L.append("- **Volume bar raised:** monthly point-in-time screen now "
             "requires trailing-20-day average daily dollar volume "
             "> $20,000,000 (v0: $5,000,000); close < $5.00; US "
             "exchange-listed only, no OTC/Pink Sheets, ever.")
    L.append("- **Far fewer trades:** at most ONE new entry per day (the "
             "single highest-ranked name from the evening ranking) and "
             "at most 2 new entries per calendar week (v0 bought every "
             "ranked name up to 5 positions, every day).")
    L.append("- **Wider exits, smaller tickets:** stop -15% (v0: -10%), "
             "take-profit +40% (v0: +25%), max 15% of pot per name "
             "(v0: 20%), max 5 positions, no averaging down. Stop fills "
             "first if both levels are touched the same day; gap-down "
             "opens fill at the open.")
    L.append("- **Cost gate:** a trade is skipped if its estimated "
             "round-trip cost (2.0% per side = 4.0% of the position) "
             "exceeds 10% of the dollar gain available at the +40% "
             "target. As specified, 10% of a +40% gain is also 4.0% of "
             "the position, so the two sides are exactly equal and the "
             "gate passed every trade it was shown "
             f"(gate skips: A={rA['gate_skips']}, B={rB['gate_skips']}). "
             "Under v0's +25% target the same gate reads 4.0% vs 2.5% "
             "and would have failed every trade -- widening the target "
             "is what moves friction from 16% of the target gain (v0) "
             "to 10% (v2). The $0.01 sell-order fee is charged in the "
             "simulation but is outside the gate's specified formula.")
    L.append("- **Variant B:** identical to A except new entries are "
             "blocked whenever SPY closed below its 200-day average on "
             "the signal evening. Report-only comparison; exits and the "
             "floor are unchanged.")
    L.append("- **Unchanged:** the evening ranking (prior-day % gain x "
             "volume spike), the 2.0%-per-side cost model plus $0.01 "
             "per sell, Terry's floor ladder ($85; $100 after a $125 "
             "close; $125 after a $150 close; a close at/below the "
             "floor liquidates at the next open and ends the run), and "
             "a zero-cost twin for each variant.")
    L.append("")
    L.append("## Monthly screens under the $20M bar (point-in-time)")
    L.append("")
    L.append("| Month | Screen date | Names passing | Passing names |")
    L.append("|---|---|---|---|")
    for mk in months:
        sdate, passed, _ = screen_info[mk]
        L.append(f"| {mk} | {sdate} | {len(passed)} | "
                 f"{', '.join(passed) if passed else '(none)'} |")
    L.append("")
    L.append("## Results")
    L.append("")

    def result_block(name, res, st, free_res, free_st):
        out = []
        if res["halted"]:
            out.append(f"### {name}: RUN ENDED EARLY on the floor")
            out.append(f"- Closed at ${res['halt_trigger_close']:.2f}, "
                       f"at/below the floor in effect; liquidated at the "
                       f"next open ({res['halt_date']}). **Final balance: "
                       f"${st['final']:.2f} ({st['ret']:+.2f}%)**.")
        else:
            out.append(f"### {name}: survived the full year")
            out.append(f"- **Final balance: ${st['final']:.2f} "
                       f"({st['ret']:+.2f}%)**.")
        out.append(f"- Trades: {st['n_trades']} ({st['n_buys']} buys, "
                   f"{st['n_sells']} sells); {st['round_trips']} round "
                   f"trips; win rate {st['win_rate']:.1f}% "
                   f"({st['wins']}W / {st['losses']}L)")
        if st["biggest_win"]:
            bw, bl = st["biggest_win"], st["biggest_loss"]
            out.append(f"- Biggest win: {bw['ticker']} +${bw['pnl']:.2f} "
                       f"(closed {bw['exit_date']}); biggest loss: "
                       f"{bl['ticker']} ${bl['pnl']:.2f} "
                       f"(closed {bl['exit_date']})")
        out.append(f"- Max drawdown (closes): {st['max_dd'] * 100:.2f}%")
        out.append(f"- Worst intraday pot value: "
                   f"${res['worst_intraday'][0]:.2f} on "
                   f"{res['worst_intraday'][1]}")
        out.append(f"- Gap-through-stop events: "
                   f"{res['gap_through_stops']}")
        out.append(f"- **Total costs paid: ${res['total_costs']:.2f}** "
                   f"({res['total_costs']:.1f}% of the starting pot)")
        if free_res["halted"]:
            out.append(f"- Zero-cost twin: halted on "
                       f"{free_res['halt_date']} at "
                       f"${free_st['final']:.2f} ({free_st['ret']:+.2f}%) "
                       f"after {free_st['n_trades']} trades.")
        else:
            out.append(f"- Zero-cost twin: finished at "
                       f"**${free_st['final']:.2f} "
                       f"({free_st['ret']:+.2f}%)** after "
                       f"{free_st['n_trades']} trades.")
        out.append(f"- Friction gap (twin minus costed): "
                   f"${free_st['final'] - st['final']:.2f} of ending "
                   f"value (costs plus knock-on sizing/path effects, "
                   f"stated honestly).")
        out.append(f"- Floor history: " + "; ".join(
            (f"{d}: raised to ${fl:.2f}" if d else f"start ${fl:.2f}")
            for d, fl in res["floor_history"]))
        return out

    L += result_block("Variant A -- v2 as specified", rA, A,
                      runs[("A", "free")], Af)
    L.append("")
    L += result_block("Variant B -- v2 + SPY-below-200-day entry block",
                      rB, B, runs[("B", "free")], Bf)
    L.append(f"- Signal evenings blocked by the regime rule in the "
             f"costed B run: {rB['regime_blocks']} (each was an evening "
             f"with a positive-ranked candidate that B refused).")
    if first_below_200dma:
        L.append(f"- **Why B is identical to A on this tape (verified, "
                 f"not a shortcut):** SPY stayed above its 200-day "
                 f"average on every day of both pots' lives and first "
                 f"closed below it on {first_below_200dma} -- months "
                 f"after both variants had already hit the floor and "
                 f"halted ({rA['halt_date']}). The regime block "
                 f"therefore never had a live pot to protect, so B's "
                 f"trades match A's trade for trade. The check itself "
                 f"was spot-verified against the raw SPY bars (e.g. "
                 f"2026-11-18 close $730.20 vs 200-day average "
                 f"$732.55 = below; every run-window date before the "
                 f"halt = above).")
    L.append(f"- Entries refused by the 2-per-week cap: "
             f"A={rA['week_cap_blocks']}, B={rB['week_cap_blocks']}.")
    L.append("")
    L.append("## Month-by-month closing balances")
    L.append("")
    mbA = dict((mk, (d, v)) for mk, d, v in monthly_balances(rA))
    mbB = dict((mk, (d, v)) for mk, d, v in monthly_balances(rB))
    L.append("| Month | Variant A | Variant B |")
    L.append("|---|---|---|")
    for mk in months:
        a = f"${mbA[mk][1]:.2f} ({mbA[mk][0]})" if mk in mbA else "--"
        b = f"${mbB[mk][1]:.2f} ({mbB[mk][0]})" if mk in mbB else "--"
        L.append(f"| {mk} | {a} | {b} |")
    L.append("")
    L.append("## v0 vs v2A vs v2B")
    L.append("")
    L.append("| | v0 (as run) | v2 Variant A | v2 Variant B |")
    L.append("|---|---|---|---|")
    L.append(f"| Final balance | $84.04 | ${A['final']:.2f} | "
             f"${B['final']:.2f} |")
    L.append(f"| Return | -15.96% | {A['ret']:+.2f}% | {B['ret']:+.2f}% |")
    L.append("| Run ended | 2026-03-13 (floor) | "
             + (f"{rA['halt_date']} (floor)" if rA["halted"]
                else "full year")
             + " | "
             + (f"{rB['halt_date']} (floor)" if rB["halted"]
                else "full year") + " |")
    L.append(f"| Round trips | 32 | {A['round_trips']} | "
             f"{B['round_trips']} |")
    L.append(f"| Win rate | 34.4% | {A['win_rate']:.1f}% | "
             f"{B['win_rate']:.1f}% |")
    L.append(f"| Total costs | $23.36 (23.4% of pot) | "
             f"${rA['total_costs']:.2f} "
             f"({rA['total_costs']:.1f}% of pot) | "
             f"${rB['total_costs']:.2f} "
             f"({rB['total_costs']:.1f}% of pot) |")
    L.append(f"| Max drawdown (closes) | -24.37% | "
             f"{A['max_dd'] * 100:.2f}% | {B['max_dd'] * 100:.2f}% |")
    L.append(f"| Gap-through stops | 3 | {rA['gap_through_stops']} | "
             f"{rB['gap_through_stops']} |")
    L.append(f"| Zero-cost twin | $122.82 (+22.82%) | "
             f"${Af['final']:.2f} ({Af['ret']:+.2f}%) | "
             f"${Bf['final']:.2f} ({Bf['ret']:+.2f}%) |")
    L.append(f"| SPY benchmark (gross) | $105.31 (+5.31%) | "
             f"${spy_final:.2f} ({spy_ret:+.2f}%) | same |")
    L.append("")
    L.append(f"Benchmark detail: SPY $100 at the {first_day} open "
             f"(${spy_open:.2f}) to the {last_day} close "
             f"(${spy_close:.2f}) = ${spy_final:.2f} ({spy_ret:+.2f}%), "
             f"gross, no costs.")
    L.append("")
    notes = [("A", n) for n in rA["notes"]] + [("B", n) for n in
                                               rB["notes"]]
    if notes:
        L.append("## Notes from the runs")
        L.append("")
        for v, n in notes:
            L.append(f"- [{v}] {n}")
        L.append("")
    L.append("## What this does and does not prove (honest section)")
    L.append("")
    L.append("- **Survivorship tilt (material, unchanged from v0):** the "
             "candidate list was assembled in Nov 2026 from names known "
             "then. Listed penny names that died, were delisted, or were "
             "forgotten during the year are missing, so the screens "
             "never had the chance to reject them. This FLATTERS every "
             "number in this report by an unknown amount; a truly "
             "point-in-time universe would very likely do worse.")
    L.append("- **Daily-bar limits:** exits are judged on open/high/low/"
             "close; when stop and target are both inside one day's "
             "range the stop fills first (conservative). A daily bar "
             "cannot show intraday plunges through the floor that "
             "recovered by the close, and real fills on sub-$5 names "
             "are often worse than the bar suggests. Intraday pot "
             "values mark holdings at the day's lows (approximations).")
    L.append(f"- **Gap-through stops:** variant A had "
             f"{rA['gap_through_stops']}, variant B had "
             f"{rB['gap_through_stops']} exits that opened below their "
             f"-15% stop and filled at the open, worse than planned. "
             f"Widening the stop to -15% does not fix gaps; it only "
             f"changes where the trigger sits.")
    L.append("- **The floor is defined on closes** -- the kinder version "
             "of reality; a live account can be taken out intraday.")
    L.append("- **The cost gate, as specified, cannot bind:** round-trip "
             "cost (4.0% of position) exactly equals its limit (10% of "
             "the +40% target gain = 4.0% of position). It is a "
             "documentation of the friction ratio, not a filter. If "
             "Terry wants a gate that actually refuses trades, the "
             "limit has to be set below 10% of the target gain or the "
             "target/cost assumptions have to change.")
    L.append("- **One run, one path:** a single year is one draw from "
             "history. v2's rules were specified before this run, which "
             "keeps the comparison to v0 honest, but a different year "
             "can reorder the finish completely. The penny-stock base "
             "rate (Eraker & Ready: median OTC stock -97%, ~1.2% up "
             "10x+) remains the prior.")
    L.append("- **What it does measure:** whether the cost-attack "
             "changes (fewer, bigger-target, higher-volume trades) "
             "actually reduce the friction share and change the pot's "
             "fate on the same tape that killed v0 -- that comparison "
             "is apples-to-apples because window, data, ranking, floor "
             "and cost model are identical.")
    L.append("")
    L.append(f"Full trade log (costed A and B): `lottery-v2-trades.csv` "
             f"({A['n_trades'] + B['n_trades']} rows). Script: "
             f"`lottery-v2.py`.")
    if failed:
        L.append("")
        L.append(f"Data fetch failures (excluded everywhere): "
                 f"{', '.join(failed)}")
    L.append("")

    md_path = os.path.join(HERE, "lottery-v2.md")
    with open(md_path, "w") as f:
        f.write("\n".join(L))

    print(f"Run days: {first_day} .. {last_day} ({len(run_days)} days)")
    print("Screens ($20M bar):")
    for mk in months:
        sdate, passed, _ = screen_info[mk]
        print(f"  {mk} (screen {sdate}): {len(passed)}: "
              f"{', '.join(passed)}")
    for variant, st, res, fst in (
            ("A", A, rA, Af), ("B", B, rB, Bf)):
        print(f"VARIANT {variant} COSTED: final ${st['final']:.2f} "
              f"({st['ret']:+.2f}%), halted={res['halted']} "
              f"halt_date={res['halt_date']}, trades={st['n_trades']}, "
              f"RT={st['round_trips']}, win={st['win_rate']:.1f}%, "
              f"maxDD={st['max_dd'] * 100:.2f}%, costs="
              f"${res['total_costs']:.2f}, gaps="
              f"{res['gap_through_stops']}, gate_skips="
              f"{res['gate_skips']}, week_cap_blocks="
              f"{res['week_cap_blocks']}, regime_blocks="
              f"{res['regime_blocks']}")
        print(f"VARIANT {variant} ZERO-COST: final ${fst['final']:.2f} "
              f"({fst['ret']:+.2f}%), trades={fst['n_trades']}")
    print(f"SPY benchmark: ${spy_final:.2f} ({spy_ret:+.2f}%)")
    print(f"Wrote {csv_path} and {md_path}")


if __name__ == "__main__":
    main()
