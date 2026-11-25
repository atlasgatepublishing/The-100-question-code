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
# v9 copy lives in backtests/v9-muse-rules/lottery-v3/; the original
# data cache (read-only) is at backtests/v3/data_cache/.
CACHE = os.path.join(HERE, "..", "..", "v3", "data_cache")
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
             floor_steps=FLOOR_STEPS, protection="his"):
    # protection="v9" applies CLAUDE-RULES PROTECTION SPEC v9: the ENTIRE
    # original protection module (plain floor + profit ladder) is replaced
    # by a plain -15% floor from the episode start (callers pass
    # floor_start = 0.85 * start_cash and floor_steps = []), ONE restart:
    # on the first halt the pot liquidates exactly as the original engine
    # does (next open), sits in cash 90 calendar days, then restarts with
    # the remaining cash at the strategy's next regular decision point
    # (this engine decides entries daily from the prior evening's bar, so
    # the restart day's entry is picked from the prior trading day's
    # close; monthly screens are unaffected). Episode-2 floor is -15%
    # from the restart balance; a second halt ends the run permanently.
    res = {
        "label": label, "trades": [], "total_costs": 0.0,
        "round_trips": [], "daily": [], "halted": False,
        "halt_date": None, "halt_trigger_close": None,
        "final_balance": None, "worst_intraday": (start_cash, None),
        "gap_through_stops": 0, "floor_history": [(None, floor_start)],
        "notes": [], "week_cap_blocks": 0,
        "restarts": [], "episode": 1, "halt_events": [],
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
            res["halt_events"].append(
                {"episode": res["episode"],
                 "trigger_close": res["halt_trigger_close"],
                 "liquidation_date": day,
                 "cash_after_liquidation": round(cash, 2)})
            if protection == "v9" and res["episode"] == 1:
                # v9: sit in cash 90 calendar days, restart with the
                # remaining cash at the next trading day on/after
                # liquidation_date + 90 days, if one exists in the run.
                from datetime import date as _date, timedelta as _td
                liq = _date.fromisoformat(day)
                resume_on = (liq + _td(days=90)).isoformat()
                j = i + 1
                while j <= end_idx and trading_days[j] < resume_on:
                    j += 1
                if j > end_idx:
                    res["restarts"].append(
                        {"liquidation_date": day, "restart_date": None,
                         "restart_balance": round(cash, 2),
                         "note": "90-day sit-out runs past the window "
                                 "end; run ends with liquidation cash."})
                    res["halted"] = True
                    res["halt_date"] = day
                    res["final_balance"] = cash
                    return res
                restart_balance = cash
                floor = 0.85 * restart_balance
                res["floor_history"].append((trading_days[j], floor))
                res["restarts"].append(
                    {"liquidation_date": day,
                     "restart_date": trading_days[j],
                     "restart_balance": round(restart_balance, 2),
                     "episode2_floor": round(floor, 2)})
                res["episode"] = 2
                res["notes"].append(
                    f"V9 RESTART: episode 1 halted; liquidated at the "
                    f"{day} open for ${restart_balance:.2f}; sat in cash "
                    f"90 calendar days; restarting {trading_days[j]} "
                    f"with episode-2 floor ${floor:.2f}.")
                halt_pending = False
                res["halt_trigger_close"] = None
                i = j
                pending = pick_candidate(trading_days[i - 1],
                                         trading_days[i])
                continue
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
                res["halt_events"].append(
                    {"episode": res["episode"],
                     "trigger_close": eq_close,
                     "liquidation_date": None,
                     "cash_after_liquidation": round(cash, 2),
                     "note": "floor touched on the final day of the "
                             "run; no next open exists."})
                if protection == "v9" and res["episode"] == 1:
                    res["restarts"].append(
                        {"liquidation_date": None, "restart_date": None,
                         "restart_balance": round(cash, 2),
                         "note": "first halt fell on the final day; the "
                                 "90-day sit-out runs past the window "
                                 "end, so no restart occurs."})
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
    """v9 driver: re-runs ONLY the costed, ranked-pot configs of the
    original study (every one of them halted under his floor/ladder).
    The two zero-cost diagnostic twins are NOT re-run (ranked pots only;
    they are cost-removed diagnostics, not pots). His-mode replication
    runs first for every config and is checked against the recorded
    finals/halt dates in lottery-v3.md before any v9 number is used."""
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
    print(f"data: failed={failed}")

    spy_days = sorted(all_bars["SPY"].keys())
    trading_days = spy_days
    design_days = [d for d in trading_days
                   if DESIGN_START <= d <= DESIGN_END]
    valid_days = [d for d in trading_days
                  if VALID_START <= d <= VALID_END]
    all_months = run_months(design_days[0], valid_days[-1])
    universes = {}
    for mk in all_months:
        sdate, passed = screen_for_month(mk, trading_days,
                                         all_bars, all_meta)
        universes[mk] = passed

    STEPS50 = [(75.00, 62.50), (62.50, 50.00)]
    # (label, window, exit, entry, start, his_floor, his_steps,
    #  recorded_final, recorded_halt)
    CONFIGS = [
        ("BASE+N1", "design", "BASE", "N1", 100.0, FLOOR_START,
         FLOOR_STEPS, 95.78, "2024-04-16"),
        ("E1+N1", "design", "E1", "N1", 100.0, FLOOR_START,
         FLOOR_STEPS, 83.19, "2023-03-10"),
        ("E2+N1", "design", "E2", "N1", 100.0, FLOOR_START,
         FLOOR_STEPS, 83.90, "2023-05-26"),
        ("E3+N1", "design", "E3", "N1", 100.0, FLOOR_START,
         FLOOR_STEPS, 83.00, "2024-04-16"),
        ("E4+N1", "design", "E4", "N1", 100.0, FLOOR_START,
         FLOOR_STEPS, 97.71, "2024-04-15"),
        ("E5+N1", "design", "E5", "N1", 100.0, FLOOR_START,
         FLOOR_STEPS, 83.29, "2023-03-21"),
        ("E6+N1", "design", "E6", "N1", 100.0, FLOOR_START,
         FLOOR_STEPS, 83.58, "2023-03-10"),
        ("E4+N2", "design", "E4", "N2", 100.0, FLOOR_START,
         FLOOR_STEPS, 97.40, "2023-09-26"),
        ("E4+N3", "design", "E4", "N3", 100.0, FLOOR_START,
         FLOOR_STEPS, 98.65, "2023-03-21"),
        ("E4+N4", "design", "E4", "N4", 100.0, FLOOR_START,
         FLOOR_STEPS, 97.64, "2023-04-19"),
        ("E4+N1", "validation", "E4", "N1", 100.0, FLOOR_START,
         FLOOR_STEPS, 82.27, "2026-03-23"),
        ("E4+N3", "validation", "E4", "N3", 100.0, FLOOR_START,
         FLOOR_STEPS, 84.17, "2026-07-21"),
        ("E4+N1 $50", "design", "E4", "N1", 50.0, 42.50,
         STEPS50, 50.04, "2024-03-06"),
        ("E4+N3 $50", "design", "E4", "N3", 50.0, 42.50,
         STEPS50, 49.21, "2023-03-21"),
        ("E4+N1 $50", "validation", "E4", "N1", 50.0, 42.50,
         STEPS50, 41.02, "2026-03-23"),
        ("E4+N3 $50", "validation", "E4", "N3", 50.0, 42.50,
         STEPS50, 41.91, "2026-07-20"),
    ]
    days_of = {"design": design_days, "validation": valid_days}
    out = {"configs": []}
    for (label, window, ek, em, start, hfloor, hsteps,
         rec_final, rec_halt) in CONFIGS:
        days = days_of[window]
        res_h = simulate(all_bars, trading_days, days, universes,
                         COST_RATE, SELL_ORDER_FEE, EXITS[ek], em, label,
                         start_cash=start, floor_start=hfloor,
                         floor_steps=hsteps, protection="his")
        st_h = stats_of(res_h, start)
        ok = (abs(st_h["final"] - rec_final) < 0.005
              and res_h["halt_date"] == rec_halt)
        print(f"HIS {label} [{window}] ${start:.0f}: "
              f"final {st_h['final']:.2f} (recorded {rec_final}) "
              f"halt {res_h['halt_date']} (recorded {rec_halt}) "
              f"replication={'OK' if ok else 'MISMATCH'}")
        res_v = simulate(all_bars, trading_days, days, universes,
                         COST_RATE, SELL_ORDER_FEE, EXITS[ek], em, label,
                         start_cash=start, floor_start=0.85 * start,
                         floor_steps=[], protection="v9")
        st_v = stats_of(res_v, start)
        series = [start] + [eq for _, eq in res_v["daily"]]
        worst_close = min(series)
        worst_intra = res_v["worst_intraday"][0]
        print(f"V9  {label} [{window}] ${start:.0f}: "
              f"final {st_v['final']:.2f} halted={res_v['halted']} "
              f"halt_date={res_v['halt_date']} "
              f"restarts={res_v['restarts']}")
        out["configs"].append({
            "label": label, "window": window, "exit": ek, "entry": em,
            "start": start,
            "his": {"final": round(st_h["final"], 2),
                    "halt_date": res_h["halt_date"],
                    "round_trips": st_h["round_trips"],
                    "win_rate": round(st_h["win_rate"], 1),
                    "total_costs": round(res_h["total_costs"], 2),
                    "max_dd_pct": round(st_h["max_dd"] * 100, 2),
                    "recorded_final": rec_final,
                    "recorded_halt": rec_halt,
                    "replication_ok": ok},
            "v9": {"final": round(st_v["final"], 2),
                   "halted": res_v["halted"],
                   "halt_date": res_v["halt_date"],
                   "halt_events": res_v["halt_events"],
                   "restarts": res_v["restarts"],
                   "round_trips": st_v["round_trips"],
                   "win_rate": round(st_v["win_rate"], 1),
                   "total_costs": round(res_v["total_costs"], 2),
                   "max_dd_pct": round(st_v["max_dd"] * 100, 2),
                   "worst_total_loss_pct_close_basis":
                       round((worst_close / start - 1) * 100, 2),
                   "worst_intraday_equity": round(worst_intra, 2),
                   "worst_intraday_date": res_v["worst_intraday"][1],
                   "notes": [n for n in res_v["notes"]
                             if "V9 RESTART" in n or "FLOOR" in n]},
        })
    path = os.path.join(HERE, "v9-driver-results.json")
    with open(path, "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
