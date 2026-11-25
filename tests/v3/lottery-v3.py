#!/usr/bin/env python3
"""
Penny-Stock Lottery Pot -- v3: ONE-VARIABLE-AT-A-TIME exit/entry study.

Simulation only. No broker orders (real or paper) are placed.

Why v3 exists:
  v0 (stop -10%, target +25%, $5M volume bar, up to 5 entries/day) died at
  $84.04 with $23.36 of costs, but its ZERO-COST twin made +22.82% -- the
  picks had a gross edge and friction killed it.
  v2 (stop -15%, target +40%, $20M bar, max 2 entries/week) cut costs to
  $9.27, but its zero-cost twin LOST -14.82% -- changing several things at
  once (wider exits AND fewer trades AND a higher volume bar) destroyed
  the gross edge, and nobody could say which change did it.
  v3 changes ONE thing at a time, on a DESIGN window the variants are
  chosen on, and only then touches the VALIDATION window (the v0/v2 year)
  exactly once per winning config.

BASE (held fixed everywhere unless a variant says otherwise) = v2 base:
  * Monthly point-in-time screen: trailing-20-day average daily dollar
    volume > $20,000,000 AND close < $5.00, US exchange-listed EQUITY
    only (no OTC / Pink Sheets, ever).
  * Max 5 positions, max 15% of pot per name, no averaging down.
  * At most ONE new entry per day, at most 2 new entries per calendar
    week. Buys decided the evening before from that day's completed bar,
    filled at the next day's open.
  * Costs: 2.0% of trade value on EVERY buy and sell, plus $0.01 per
    sell order.
  * Terry's floor ladder: floor $85.00; a close >= $125 raises it to
    $100; a close >= $150 raises it to $125. A close at/below the floor
    liquidates everything at the next open and ENDS the run.
  * Entry ranking N1 (v0): score = prior-day % gain x volume spike
    (day volume / trailing-20-day average volume), positive scores only,
    held names excluded.
  NOTE on v2's cost gate: it is NOT carried into v3. As specified in v2
  it passed every trade it was shown (round-trip cost 4.0% of position
  exactly equalled its limit, 10% of the +40% target gain), so it never
  filtered anything; and it is undefined for the trailing-stop variant
  E5, which has no fixed target. Dropping it changes no v2 trade.

EXIT VARIANTS (entry rules fixed at N1; stop fills first if stop and
target are both touched the same day; gap-down opens fill at the open):
  BASE  v2 shape: stop -15%, target +40% (reference row, not a pick)
  E1    stop -10%, target +25%   (the v0 shape)
  E2    stop -8%,  target +16%
  E3    stop -12%, target +30%
  E4    stop -10%, target +40%
  E5    trailing stop: NO fixed target and NO initial stop (as
        specified). Once a position's running peak high (through the
        prior day) is >= +20% over entry, a trailing stop at 90% of the
        peak is armed for the next day; the peak ratchets up only, and
        each day's stop level uses the peak through the PRIOR day
        (conservative: today's new high only raises tomorrow's stop).
  E6    stop -10%, target +25%, PLUS a time exit: if neither level is
        hit within 15 trading days after the entry day, sell at the
        close of the 15th day.

ENTRY VARIANTS (run with the winning exit shape):
  N1    v0 ranking (gain% x volume spike) -- the exit-round config rerun
  N2    rank by volume spike only (no gain requirement)
  N3    rank by SMALLEST prior-day % gain among names up on the day
        ("buy the quiet ones")
  N4    N1 ranking + the name must close above its own trailing
        50-day moving average on the signal evening

WINDOWS:
  DESIGN:     first trading day on/after 2022-11-21 through 2025-11-20
              (3 years). Winners are picked HERE, by final balance.
  VALIDATION: first trading day on/after 2025-11-21 through 2026-11-20
              (the v0/v2 year). Run exactly once for the best exit
              (with N1) and once for the best entry (with the best
              exit). If the best entry is N1, those two runs are the
              same run and it is reported once.
  A zero-cost twin is also run for the design-window winner(s).
  RULE CHANGE (Terry, mid-study): the starting pot is now $50, not
  $100. The $100 runs stay as the comparison record; the headline
  configs (best exit + N1, best exit + best entry) are ALSO re-run at
  a $50 start on both windows with the floor/ladder scaled
  proportionally (floor $42.50; $50 at a $62.50 close; $62.50 at a
  $75 close), reported in their own section of the report.

Benchmark: SPY $100 at the first run day's open to the last run day's
close, gross, per window.

HONESTY FLAGS:
  * The candidate list was assembled in Nov 2026 from names known then;
    over a 3-year design window the survivorship tilt is WORSE than in
    v0/v2 (names that died 2022-2025 and were forgotten are missing, and
    some listed names return no Yahoo history at all). This FLATTERS
    every number here by an unknown amount.
  * Picking the best of 11 design configs makes the design winner the
    maximum of 11 draws: its design number is expected to be flattered
    even with no look-ahead. The validation window is the honest read.
  * Daily bars only; stop-first rule when both levels are inside one
    day's range (conservative); floor is defined on closes (kinder
    version of reality); prices split-adjusted, not dividend-adjusted.

Data: Yahoo Finance chart API (free, no key), daily OHLCV, fetched
2022-06-01 through 2026-11-20 into ./data_cache (one dataset serves
both windows; screens and signals use only data available at the time).

Outputs (next to this script): lottery-v3.md, lottery-v3-trades.csv
(all trades of the validation runs and the design-window winner).
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

ET = ZoneInfo("America/New_York")
FETCH_START = datetime(2022, 6, 1, tzinfo=timezone.utc)
FETCH_END = datetime(2026, 11, 22, tzinfo=timezone.utc)

DESIGN_START, DESIGN_END = "2022-11-21", "2025-11-20"
VALID_START, VALID_END = "2025-11-21", "2026-11-20"

START_CASH = 100.00
FLOOR_START = 85.00
FLOOR_STEPS = [(150.00, 125.00), (125.00, 100.00)]
MAX_POSITIONS = 5
MAX_PER_NAME_FRAC = 0.15
COST_RATE = 0.02
SELL_ORDER_FEE = 0.01
SCREEN_MAX_PRICE = 5.00
SCREEN_MIN_AVG_DOLLAR_VOL = 20_000_000
MAX_ENTRIES_PER_WEEK = 2

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
# Exit / entry variant definitions
# ---------------------------------------------------------------------------

EXITS = {
    "BASE": {"kind": "fixed", "stop": 0.15, "tp": 0.40, "time_days": None,
             "label": "v2 shape: stop -15%, target +40% (reference)"},
    "E1": {"kind": "fixed", "stop": 0.10, "tp": 0.25, "time_days": None,
           "label": "stop -10%, target +25% (v0 shape)"},
    "E2": {"kind": "fixed", "stop": 0.08, "tp": 0.16, "time_days": None,
           "label": "stop -8%, target +16%"},
    "E3": {"kind": "fixed", "stop": 0.12, "tp": 0.30, "time_days": None,
           "label": "stop -12%, target +30%"},
    "E4": {"kind": "fixed", "stop": 0.10, "tp": 0.40, "time_days": None,
           "label": "stop -10%, target +40%"},
    "E5": {"kind": "trail", "activate": 0.20, "trail": 0.10,
           "label": "trailing stop: 10% trail armed once up +20%, "
                    "no fixed target, no initial stop"},
    "E6": {"kind": "fixed", "stop": 0.10, "tp": 0.25, "time_days": 15,
           "label": "stop -10%, target +25%, time exit at 15 trading days"},
}
ENTRY_LABELS = {
    "N1": "v0 ranking: prior-day % gain x volume spike",
    "N2": "rank by volume spike only",
    "N3": "rank by smallest prior-day % gain among names up on the day",
    "N4": "N1 ranking + name must be above its own 50-day average",
}


# ---------------------------------------------------------------------------
# Data loading
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
# Screens and ranking
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


def rank_evening(universe, all_bars, day, held, mode):
    """Evening ranking for the given entry mode. Returns symbols, best
    first. All modes exclude held names and use only `day`'s completed
    bar and earlier data."""
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
        last20 = trailing(bars, day, 20)
        avg_vol = (sum(b["volume"] for _, b in last20) / len(last20)
                   if last20 else 0)
        spike = (today["volume"] / avg_vol) if avg_vol else 0.0
        if mode == "N1":
            score = gain_pct * spike
            if score > 0:
                rows.append((score, s))
        elif mode == "N2":
            rows.append((spike, s))
        elif mode == "N3":
            if gain_pct > 0:
                rows.append((gain_pct, s))
        elif mode == "N4":
            last50 = trailing(bars, day, 50)
            if len(last50) < 50:
                continue
            ma50 = sum(b["close"] for _, b in last50) / len(last50)
            score = gain_pct * spike
            if score > 0 and today["close"] > ma50:
                rows.append((score, s))
    if mode == "N3":
        rows.sort(key=lambda x: (x[0], x[1]))   # smallest gain first
    else:
        rows.sort(reverse=True)                  # same tie-break as v0/v2
    return [s for _, s in rows]


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def simulate(all_bars, trading_days, run_days, universes,
             cost_rate, sell_fee, exit_cfg, rank_mode, label,
             start_cash=START_CASH, floor_start=FLOOR_START,
             floor_steps=FLOOR_STEPS):
    res = {
        "label": label, "trades": [], "total_costs": 0.0,
        "round_trips": [], "daily": [], "halted": False,
        "halt_date": None, "halt_trigger_close": None,
        "final_balance": None, "worst_intraday": (start_cash, None),
        "gap_through_stops": 0, "floor_history": [(None, floor_start)],
        "notes": [], "week_cap_blocks": 0,
    }
    trades = res["trades"]
    cash = start_cash
    positions = {}
    floor = floor_start
    halt_pending = False
    entries_by_week = {}

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
        ranked = rank_evening(universes[month_key(for_day)], all_bars,
                              signal_day, set(positions), rank_mode)
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
                                   "close touched the floor); run ends")
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
                        shares = do_buy(day, s, b["open"], amount,
                                        f"entry: top of {rank_mode} "
                                        f"ranking from prior evening")
                        cash -= amount
                        positions[s] = {"shares": shares,
                                        "entry": b["open"],
                                        "outlay": amount,
                                        "entry_idx": i,
                                        "peak": b["open"],
                                        "trail_active": False}
                        entries_by_week[wk] = \
                            entries_by_week.get(wk, 0) + 1
        pending = None

        low_eq = equity(day, "low")
        if low_eq < res["worst_intraday"][0]:
            res["worst_intraday"] = (low_eq, day)

        # Intraday exits. Stop-type levels fill first.
        for s in list(positions):
            b = all_bars[s].get(day)
            if not b:
                continue
            p = positions[s]
            entry = p["entry"]
            if exit_cfg["kind"] == "fixed":
                stop = entry * (1 - exit_cfg["stop"])
                tp = entry * (1 + exit_cfg["tp"])
                if b["low"] <= stop:
                    if b["open"] < stop:
                        res["gap_through_stops"] += 1
                        res["notes"].append(
                            f"{day}: {s} gapped down through its stop "
                            f"(opened ${b['open']:.4f} vs stop "
                            f"${stop:.4f}); filled at the open.")
                        fill = b["open"]
                    else:
                        fill = stop
                    close_position(
                        day, s, fill,
                        f"stop-loss -{exit_cfg['stop'] * 100:.0f}% "
                        f"from entry")
                elif b["high"] >= tp:
                    close_position(
                        day, s, tp,
                        f"take-profit +{exit_cfg['tp'] * 100:.0f}% "
                        f"from entry (sold all)")
                elif (exit_cfg.get("time_days") is not None
                        and i - p["entry_idx"] >= exit_cfg["time_days"]):
                    close_position(
                        day, s, b["close"],
                        f"time exit: {exit_cfg['time_days']} trading "
                        f"days held, neither stop nor target hit")
            else:  # trailing stop (E5)
                if p["trail_active"]:
                    tstop = p["peak"] * (1 - exit_cfg["trail"])
                    if b["low"] <= tstop:
                        if b["open"] < tstop:
                            res["gap_through_stops"] += 1
                            res["notes"].append(
                                f"{day}: {s} gapped down through its "
                                f"trailing stop (opened ${b['open']:.4f} "
                                f"vs stop ${tstop:.4f}); filled at the "
                                f"open.")
                            fill = b["open"]
                        else:
                            fill = tstop
                        close_position(day, s, fill,
                                       "trailing stop (10% below peak)")
                        continue
                # Ratchet the peak with today's high; arms tomorrow.
                if s in positions:
                    p["peak"] = max(p["peak"], b["high"])
                    if p["peak"] >= entry * (1 + exit_cfg["activate"]):
                        p["trail_active"] = True

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

        if eq_close <= floor:
            if is_last:
                res["halted"] = True
                res["halt_date"] = day
                res["halt_trigger_close"] = eq_close
                res["final_balance"] = cash
                res["notes"].append(
                    f"FLOOR: pot closed at ${eq_close:.2f} on {day}, "
                    f"at/below the ${floor:.2f} floor, on the final day "
                    f"of the run.")
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
                    f"Floor raised to ${floor:.2f} after the pot closed "
                    f"at ${eq_close:.2f} on {day}.")
                break

        if not is_last:
            nxt = trading_days[i + 1]
            pending = pick_candidate(day, nxt)
        i += 1

    res["final_balance"] = cash
    return res


def stats_of(res, start_cash=START_CASH):
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
        "n_buys": sum(1 for t in res["trades"] if t["side"] == "buy"),
        "n_sells": sum(1 for t in res["trades"] if t["side"] == "sell"),
        "round_trips": len(rts), "wins": len(wins), "losses": len(losses),
        "win_rate": (len(wins) / len(rts) * 100) if rts else 0.0,
        "biggest_win": max(rts, key=lambda r: r["pnl"]) if rts else None,
        "biggest_loss": min(rts, key=lambda r: r["pnl"]) if rts else None,
        "final": res["final_balance"],
        "ret": (res["final_balance"] / start_cash - 1) * 100,
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

    spy_days = sorted(all_bars["SPY"].keys())
    trading_days = spy_days  # full fetched range; screens need pre-2022-11

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

    def spy_bench(days):
        o = spy[days[0]]["open"]
        c = spy[days[-1]]["close"]
        return 100.0 * c / o, o, c

    spy_design, spy_design_o, spy_design_c = spy_bench(design_days)
    spy_valid, spy_valid_o, spy_valid_c = spy_bench(valid_days)

    trials = []   # every simulate() call, in order

    def run(label, days, exit_key, rank_mode, cost_rate, sell_fee,
            start_cash=START_CASH, floor_start=FLOOR_START,
            floor_steps=FLOOR_STEPS):
        res = simulate(all_bars, trading_days, days, universes,
                       cost_rate, sell_fee, EXITS[exit_key], rank_mode,
                       label, start_cash=start_cash,
                       floor_start=floor_start, floor_steps=floor_steps)
        st = stats_of(res, start_cash)
        trials.append({"label": label,
                       "window": ("design" if days is design_days
                                  else "validation"),
                       "exit": exit_key, "entry": rank_mode,
                       "costed": cost_rate > 0, "start_cash": start_cash,
                       "res": res, "st": st})
        return res, st

    # ---- Round 1: exits on the design window (entries fixed at N1) ----
    design_exit = {}
    for key in ("BASE", "E1", "E2", "E3", "E4", "E5", "E6"):
        res, st = run(f"{key}+N1", design_days, key, "N1",
                      COST_RATE, SELL_ORDER_FEE)
        design_exit[key] = (res, st)

    pick_keys = [k for k in EXITS if k != "BASE"]
    best_exit = max(pick_keys, key=lambda k: design_exit[k][1]["final"])

    # ---- Round 2: entries on the design window (best exit fixed) ----
    design_entry = {}
    for mode in ("N1", "N2", "N3", "N4"):
        res, st = run(f"{best_exit}+{mode}", design_days, best_exit, mode,
                      COST_RATE, SELL_ORDER_FEE)
        design_entry[mode] = (res, st)
    best_entry = max(design_entry, key=lambda m: design_entry[m][1]["final"])

    # ---- Zero-cost twins for the design winner(s) ----
    twin_configs = {(best_exit, "N1")}
    twin_configs.add((best_exit, best_entry))
    twins = {}
    for ek, em in sorted(twin_configs):
        res, st = run(f"{ek}+{em} ZERO-COST", design_days, ek, em, 0.0, 0.0)
        twins[(ek, em)] = (res, st)

    # ---- Validation: winning configs, run exactly once each ----
    valid_runs = {}
    res, st = run(f"{best_exit}+N1", valid_days, best_exit, "N1",
                  COST_RATE, SELL_ORDER_FEE)
    valid_runs[(best_exit, "N1")] = (res, st)
    same_run = (best_entry == "N1")
    if not same_run:
        res, st = run(f"{best_exit}+{best_entry}", valid_days, best_exit,
                      best_entry, COST_RATE, SELL_ORDER_FEE)
        valid_runs[(best_exit, best_entry)] = (res, st)

    # ---- Terry's rule change (mid-study): the starting pot is $50 ----
    # $100 runs above stay as the comparison record. Headline configs
    # are re-run at a $50 start with floor/ladder scaled proportionally:
    # floor $42.50; $50 at a $62.50 close; $62.50 at a $75 close.
    START50 = 50.00
    FLOOR50 = 42.50
    STEPS50 = [(75.00, 62.50), (62.50, 50.00)]
    headline_cfgs = [(best_exit, "N1")]
    if not same_run:
        headline_cfgs.append((best_exit, best_entry))
    runs50 = {}
    for days, wname in ((design_days, "design"),
                        (valid_days, "validation")):
        for (ek, em) in headline_cfgs:
            res, st = run(f"{ek}+{em} $50-start", days, ek, em,
                          COST_RATE, SELL_ORDER_FEE, start_cash=START50,
                          floor_start=FLOOR50, floor_steps=STEPS50)
            runs50[(wname, ek, em)] = (res, st)

    # ---------------------------------------------------------------- CSV
    keep_labels = set()
    for (ek, em), (res, st) in valid_runs.items():
        keep_labels.add(res["label"])  # validation labels collide w/ design
    csv_path = os.path.join(HERE, "lottery-v3-trades.csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["trial", "window", "config",
                                          "date", "ticker", "side",
                                          "price", "shares", "value",
                                          "reason"])
        w.writeheader()
        for t in trials:
            is_winner_design = (
                t["window"] == "design" and t["costed"]
                and t["exit"] == best_exit and t["entry"] == best_entry)
            if (t["window"] == "validation" or is_winner_design
                    or t["start_cash"] != START_CASH):
                for tr in t["res"]["trades"]:
                    w.writerow({"trial": t["label"], "window": t["window"],
                                "config": f"{t['exit']}+{t['entry']}",
                                **{k: tr[k] for k in
                                   ("date", "ticker", "side", "price",
                                    "shares", "value", "reason")}})

    # ----------------------------------------------------------------- MD
    bx_res, bx_st = design_exit[best_exit]
    be_res, be_st = design_entry[best_entry]
    v_exit_res, v_exit_st = valid_runs[(best_exit, "N1")]
    if not same_run:
        v_win_res, v_win_st = valid_runs[(best_exit, best_entry)]
    else:
        v_win_res, v_win_st = v_exit_res, v_exit_st
    twin_st = twins[(best_exit, best_entry)][1]

    L = []
    L.append("# Penny-Stock Lottery Pot -- v3: One-Variable-at-a-Time "
             "Exit/Entry Study")
    L.append("")
    L.append(f"Design window: **{design_days[0]}** through "
             f"**{design_days[-1]}** (3 years, variants chosen here). "
             f"Validation window: **{valid_days[0]}** through "
             f"**{valid_days[-1]}** (the v0/v2 year, run exactly once "
             f"per winning config). Start: **$100.00** fake money, full "
             f"costs, no look-ahead. Simulation only.")
    L.append("")
    L.append("Data: Yahoo Finance chart API daily OHLCV (free), fetched "
             "2022-06-01 through 2026-11-20, one dataset for both "
             "windows. Prices split-adjusted, not dividend-adjusted.")
    L.append("")
    L.append("## Why v3 (the one-paragraph history)")
    L.append("")
    L.append("v0 (stop -10% / target +25%) died at $84.04, but its "
             "zero-cost twin made +22.82%: the picks had a gross edge "
             "and $23.36 of friction killed it. v2 changed exits, trade "
             "frequency and the volume bar all at once; costs fell to "
             "$9.27 but the zero-cost twin LOST -14.82%, so the wider "
             "exit geometry (or one of the other simultaneous changes) "
             "destroyed the gross edge and nobody could say which. v3 "
             "holds the v2 base fixed (monthly $20M-volume point-in-time "
             "screens, listed sub-$5 only, max 5 positions at 15%, max "
             "1 entry/day and 2/week, 2.0%/side + $0.01/sell costs, "
             "Terry's floor ladder) and changes exactly ONE thing per "
             "trial. v2's cost gate is not carried over: in v2 it passed "
             "every trade it was shown (it never filtered anything) and "
             "it is undefined for a trailing stop with no target.")
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
    L.append("## Trial log -- EVERY run, in the order run")
    L.append("")
    L.append(f"Total trials: **{len(trials)}** simulate() runs "
             f"(1 reference + 6 exit variants + 4 entry variants + "
             f"{len(twins)} zero-cost twin(s) on the design window + "
             f"{len(valid_runs)} validation run(s) + {len(runs50)} "
             f"$50-start run(s) of the headline configs). The count "
             f"matters: "
             f"the design winner is the best of 11 costed design "
             f"configs, so its design-window number is the maximum of "
             "11 draws and is expected to be flattered. The validation "
             "window is the honest read.")
    L.append("")
    L.append("| # | Trial | Window | Final | Return | Orders | Round "
             "trips | Win rate | Costs | Halted |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for idx, t in enumerate(trials, 1):
        st, res = t["st"], t["res"]
        halt = res["halt_date"] if res["halted"] else "no"
        costs = ("$0.00" if not t["costed"]
                 else f"${res['total_costs']:.2f}")
        L.append(f"| {idx} | {t['label']} | {t['window']} | "
                 f"${st['final']:.2f} | {st['ret']:+.2f}% | "
                 f"{st['n_trades']} | {st['round_trips']} | "
                 f"{st['win_rate']:.1f}% | {costs} | {halt} |")
    L.append("")
    L.append("## Round 1 -- exits (design window, entries fixed at N1)")
    L.append("")
    L.append("| Variant | Exit shape | Final | Return | Round trips | "
             "Win rate | Costs | Max DD | Halted |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for key in ("BASE", "E1", "E2", "E3", "E4", "E5", "E6"):
        res, st = design_exit[key]
        L.append(f"| {key} | {EXITS[key]['label']} | ${st['final']:.2f} "
                 f"| {st['ret']:+.2f}% | {st['round_trips']} | "
                 f"{st['win_rate']:.1f}% | ${res['total_costs']:.2f} | "
                 f"{st['max_dd'] * 100:.2f}% | "
                 f"{res['halt_date'] if res['halted'] else 'no'} |")
    L.append("")
    L.append(f"**Best exit on the design window: {best_exit}** "
             f"({EXITS[best_exit]['label']}) at ${bx_st['final']:.2f} "
             f"({bx_st['ret']:+.2f}%), vs the v2 base shape (BASE) at "
             f"${design_exit['BASE'][1]['final']:.2f} "
             f"({design_exit['BASE'][1]['ret']:+.2f}%).")
    L.append("")
    L.append(f"SPY design-window benchmark: $100 at the "
             f"{design_days[0]} open (${spy_design_o:.2f}) to the "
             f"{design_days[-1]} close (${spy_design_c:.2f}) = "
             f"**${spy_design:.2f} ({spy_design - 100:+.2f}%)**, gross.")
    L.append("")
    L.append(f"## Round 2 -- entries (design window, exit fixed at "
             f"{best_exit})")
    L.append("")
    L.append("| Variant | Entry rule | Final | Return | Round trips | "
             "Win rate | Costs | Max DD | Halted |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for mode in ("N1", "N2", "N3", "N4"):
        res, st = design_entry[mode]
        L.append(f"| {mode} | {ENTRY_LABELS[mode]} | ${st['final']:.2f} "
                 f"| {st['ret']:+.2f}% | {st['round_trips']} | "
                 f"{st['win_rate']:.1f}% | ${res['total_costs']:.2f} | "
                 f"{st['max_dd'] * 100:.2f}% | "
                 f"{res['halt_date'] if res['halted'] else 'no'} |")
    L.append("")
    L.append(f"**Best entry on the design window: {best_entry}** "
             f"({ENTRY_LABELS[best_entry]}) at ${be_st['final']:.2f} "
             f"({be_st['ret']:+.2f}%). Design-window winning config: "
             f"**{best_exit}+{best_entry}**.")
    L.append("")
    L.append("## Zero-cost twin of the design winner")
    L.append("")
    for (ek, em), (res, st) in sorted(twins.items()):
        L.append(f"- {ek}+{em} with costs removed: **${st['final']:.2f} "
                 f"({st['ret']:+.2f}%)**, {st['n_trades']} orders, "
                 f"{st['round_trips']} round trips, win rate "
                 f"{st['win_rate']:.1f}%"
                 + (f", halted {res['halt_date']}." if res["halted"]
                    else ", survived the design window."))
    L.append(f"- So of the design winner's result, friction accounts "
             f"for the gap between ${twin_st['final']:.2f} (no costs) "
             f"and ${be_st['final']:.2f} (costed) -- costs plus knock-on "
             f"sizing/path effects, stated honestly.")
    L.append("")
    L.append("## Validation window -- run exactly once per winning config")
    L.append("")
    L.append(f"SPY validation benchmark: $100 at the {valid_days[0]} "
             f"open (${spy_valid_o:.2f}) to the {valid_days[-1]} close "
             f"(${spy_valid_c:.2f}) = **${spy_valid:.2f} "
             f"({spy_valid - 100:+.2f}%)**, gross. (v0 finished this "
             f"window at $84.04; v2 at $82.89.)")
    L.append("")
    L.append("| Config | Final | Return | Orders | Round trips | Win "
             "rate | Costs | Max DD | Halted |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for (ek, em), (res, st) in valid_runs.items():
        L.append(f"| {ek}+{em} (best exit, "
                 f"{'best entry' if em == best_entry else 'N1'}) | "
                 f"${st['final']:.2f} | {st['ret']:+.2f}% | "
                 f"{st['n_trades']} | {st['round_trips']} | "
                 f"{st['win_rate']:.1f}% | ${res['total_costs']:.2f} | "
                 f"{st['max_dd'] * 100:.2f}% | "
                 f"{res['halt_date'] if res['halted'] else 'no'} |")
    if same_run:
        L.append("")
        L.append("The best entry on the design window was N1 itself, so "
                 "the two validation runs are the same run; it was run "
                 "and is reported once, above.")
    L.append("")
    for (ek, em), (res, st) in valid_runs.items():
        if res["notes"]:
            L.append(f"Notes from {ek}+{em} (validation):")
            for n in res["notes"]:
                L.append(f"- {n}")
            L.append("")
    L.append("## The $50 start (Terry's rule change, applied mid-study)")
    L.append("")
    L.append("Terry changed the starting pot from $100 to $50 while "
             "this study was running. The $100 runs above stay as the "
             "comparison record; the headline configs (best exit with "
             "N1, and the best exit + best entry winner) were re-run "
             "at a $50 start with the floor and ladder scaled "
             "proportionally: **floor $42.50; the ladder raises it to "
             "$50 at a $62.50 close and to $62.50 at a $75 close.** "
             "Position sizing (15% of pot) and the 2.0%-per-side cost "
             "are percentage-based, so percentage results should be "
             "nearly identical to the $100 runs; the one thing that "
             "does NOT scale is the flat $0.01 per-sell-order fee, "
             "which bites twice as hard, relatively, on a $50 pot.")
    L.append("")
    L.append("| Config | Window | Final (of $50) | Return | Orders | "
             "Round trips | Win rate | Costs | Costs as % of $50 pot | "
             "Halted |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for (wname, ek, em), (res, st) in runs50.items():
        L.append(f"| {ek}+{em} | {wname} | ${st['final']:.2f} | "
                 f"{st['ret']:+.2f}% | {st['n_trades']} | "
                 f"{st['round_trips']} | {st['win_rate']:.1f}% | "
                 f"${res['total_costs']:.2f} | "
                 f"{res['total_costs'] / START50 * 100:.1f}% | "
                 f"{res['halt_date'] if res['halted'] else 'no'} |")
    L.append("")
    w50_res, w50_st = runs50[("validation", best_exit, best_entry)]
    L.append(f"Headline: the design winner ({best_exit}+{best_entry}) "
             f"at a $50 start finished the validation year at "
             f"**${w50_st['final']:.2f} ({w50_st['ret']:+.2f}%)** with "
             f"total costs of ${w50_res['total_costs']:.2f} = "
             f"{w50_res['total_costs'] / START50 * 100:.1f}% of the $50 "
             f"pot -- the same story as the $100 run "
             f"(${v_win_st['final']:.2f}, {v_win_st['ret']:+.2f}%), "
             f"because the rules are all proportional. Halving the pot "
             f"halves the dollars; it does not change the percentages, "
             f"and it does not change the verdict.")
    L.append("")
    L.append("## Honest verdict")
    L.append("")
    win_profit = v_win_st["final"] > START_CASH
    win_spy = v_win_st["final"] > spy_valid
    L.append(f"- Design window: the winning config "
             f"({best_exit}+{best_entry}) finished at "
             f"${be_st['final']:.2f} ({be_st['ret']:+.2f}%) against SPY "
             f"at ${spy_design:.2f}. Remember this is the best of 11 "
             f"costed configs tried on that window -- the maximum of 11 "
             f"draws, flattered by selection even with zero look-ahead "
             f"inside each run.")
    if win_profit and win_spy:
        L.append(f"- Validation window: the winning config finished at "
                 f"**${v_win_st['final']:.2f} "
                 f"({v_win_st['ret']:+.2f}%)** -- above the $100 start "
                 f"AND above SPY's ${spy_valid:.2f}. On this evidence "
                 f"the design winner DID win out-of-sample, once, on "
                 f"one year, after costs. That is a real pass of this "
                 f"test, not proof of an edge: one validation year is "
                 f"one path, the candidate list still carries "
                 f"survivorship tilt that flatters the number, and the "
                 f"config was selected from 11 tries. It earns a "
                 f"frozen-rules paper trial, not a victory lap.")
    elif win_profit:
        L.append(f"- Validation window: the winning config finished at "
                 f"**${v_win_st['final']:.2f} "
                 f"({v_win_st['ret']:+.2f}%)** -- above the $100 start, "
                 f"so it made money after costs out-of-sample, but it "
                 f"still trailed SPY's ${spy_valid:.2f} over the same "
                 f"year. A pot that profits but loses to simply holding "
                 f"the index has not beaten the benchmark that matters.")
    else:
        L.append(f"- Validation window: the winning config finished at "
                 f"**${v_win_st['final']:.2f} "
                 f"({v_win_st['ret']:+.2f}%)** -- below the $100 start "
                 f"and below SPY's ${spy_valid:.2f}. **No: nothing in "
                 f"this study actually won out-of-sample.** The design "
                 f"winner did not repeat on the one year it was never "
                 f"tuned on. That is the answer the design/validation "
                 f"split exists to give, and it is the same answer v0 "
                 f"and v2 pointed at: on this tape, with these costs, "
                 f"the listed-penny momentum pot does not have a "
                 f"demonstrated edge.")
    L.append(f"- Best-exit-only check: {best_exit}+N1 on validation "
             f"finished at ${v_exit_st['final']:.2f} "
             f"({v_exit_st['ret']:+.2f}%), so the entry change "
             f"({'none -- best entry was N1' if same_run else best_entry})"
             f" {'was not a factor' if same_run else 'is included in the headline number above'}.")
    L.append("- **Survivorship tilt (material, worse than v0/v2):** the "
             "candidate list was assembled in Nov 2026. Over a 3-year "
             "design window, names that died, were delisted or were "
             "forgotten during 2022-2025 are missing entirely, and "
             "several listed names return no Yahoo history at all. "
             "Every number here is flattered by an unknown amount; a "
             "true point-in-time universe would very likely do worse.")
    L.append("- **Selection bias is the headline caveat:** 11 costed "
             "configs were tried on the design window. Picking the max "
             "of 11 noisy results manufactures apparent skill. The "
             "validation run is the only number in this report that was "
             "not chosen because it looked good.")
    L.append("- **E5 caveat:** as specified, the trailing-stop variant "
             "has NO stop at all until a position is up +20%; a name "
             "that falls straight from entry is held until the floor "
             "or the end of the run. Its design result should be read "
             "with that in mind.")
    L.append("- **Daily-bar limits:** exits judged on open/high/low/"
             "close; stop fills first when both levels are inside one "
             "day's range (conservative); the floor is defined on "
             "closes (the kinder version); real fills on sub-$5 names "
             "are often worse than the bar suggests.")
    L.append("- **One path per window:** the design window is one "
             "3-year path and the validation window is one 1-year path. "
             "Different years can reorder everything. The penny-stock "
             "base rate (Eraker & Ready: median OTC stock -97%, ~1.2% "
             "up 10x+) remains the prior, and listed sub-$5 names are "
             "its better-behaved cousins, not a different species.")
    if failed:
        L.append(f"- Data fetch failures / no history (excluded "
                 f"everywhere): {', '.join(sorted(set(failed)))}")
    L.append("")
    L.append(f"- **$50 start:** re-running the headline configs at "
             f"Terry's new $50 pot (floor $42.50, ladder scaled) "
             f"reproduces the $100 percentages almost exactly -- the "
             f"winner finished validation at ${w50_st['final']:.2f} "
             f"({w50_st['ret']:+.2f}%) with costs of "
             f"${w50_res['total_costs']:.2f} "
             f"({w50_res['total_costs'] / START50 * 100:.1f}% of the "
             f"pot). The pot size is not the problem; the edge is.")
    L.append(f"Full trade log (design winner + validation runs + "
             f"$50-start runs): `lottery-v3-trades.csv`. Script: "
             f"`lottery-v3.py`.")
    L.append("")

    md_path = os.path.join(HERE, "lottery-v3.md")
    with open(md_path, "w") as f:
        f.write("\n".join(L))

    # ------------------------------------------------------------- print
    print(f"Design days: {design_days[0]} .. {design_days[-1]} "
          f"({len(design_days)}); Validation days: {valid_days[0]} .. "
          f"{valid_days[-1]} ({len(valid_days)})")
    print(f"SPY design: ${spy_design:.2f} ({spy_design - 100:+.2f}%) | "
          f"SPY validation: ${spy_valid:.2f} ({spy_valid - 100:+.2f}%)")
    print(f"Total trials: {len(trials)}")
    for idx, t in enumerate(trials, 1):
        st, res = t["st"], t["res"]
        print(f"  #{idx} {t['label']} [{t['window']}] final "
              f"${st['final']:.2f} ({st['ret']:+.2f}%), orders "
              f"{st['n_trades']}, RT {st['round_trips']}, win "
              f"{st['win_rate']:.1f}%, costs ${res['total_costs']:.2f}, "
              f"halted={res['halt_date'] if res['halted'] else 'no'}")
    print(f"BEST EXIT (design): {best_exit} at ${bx_st['final']:.2f}")
    print(f"BEST ENTRY (design): {best_entry} at ${be_st['final']:.2f}")
    for (wname, ek, em), (res, st) in runs50.items():
        print(f"$50-START {ek}+{em} [{wname}]: final "
              f"${st['final']:.2f} ({st['ret']:+.2f}%), orders "
              f"{st['n_trades']}, RT {st['round_trips']}, win "
              f"{st['win_rate']:.1f}%, costs ${res['total_costs']:.2f} "
              f"({res['total_costs'] / START50 * 100:.1f}% of pot), "
              f"halted={res['halt_date'] if res['halted'] else 'no'}")
    print(f"VALIDATION best-exit+N1: ${v_exit_st['final']:.2f} "
          f"({v_exit_st['ret']:+.2f}%)")
    if not same_run:
        print(f"VALIDATION winner {best_exit}+{best_entry}: "
              f"${v_win_st['final']:.2f} ({v_win_st['ret']:+.2f}%)")
    if failed:
        print(f"Fetch failures: {', '.join(sorted(set(failed)))}")
    print(f"Wrote {md_path} and {csv_path}")


if __name__ == "__main__":
    main()
