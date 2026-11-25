#!/usr/bin/env python3
"""
Penny-Stock Lottery Pot -- ONE-YEAR backtest.
Run window: first trading day on/after Fri 2025-11-21 through Fri 2026-11-20.

Simulation only. No broker orders (real or paper) are placed.

Method
------
* $100.00 starting pot. Every decision uses only data available at that
  decision point (no look-ahead): buys are decided the evening before from
  that day's completed bar and filled at the next day's open.
* Universe is re-screened MONTHLY, point-in-time: for each calendar month,
  the screen uses bars through the last trading day of the PRIOR month --
  close < $5.00 and trailing-20-day average daily dollar volume > $5,000,000,
  US exchange-listed equity only (NYSE/Nasdaq/NYSE American per feed
  metadata). OTC / Pink Sheet names are never allowed.
* HONESTY FLAG: the candidate list was assembled from names known in
  Nov 2026, so it carries survivorship tilt (names that died during the
  year may be missing). That FLATTERS results and is stated in the report.
* Data: Yahoo Finance chart API (free, no key), daily OHLCV fetched
  2025-06-01 through 2026-11-20, cached in ./data_cache/. Stooq's CSV
  endpoint is behind a JavaScript browser check and returns no data to a
  script. Prices are the feed's daily bars as reported (split-adjusted,
  not dividend-adjusted).
* Rules (same as the one-week test):
    - Each evening rank eligible, not-held names by score = prior-day %
      gain x volume spike (day volume / trailing-20-day average volume).
      Only positive scores are bought.
    - Buy at next open, max 20% of pot equity per name, max 5 positions,
      fractional shares. No averaging down, no adding to a held name.
    - Exits checked daily, conservative stop-first rule if both levels are
      touched the same day: stop -10% from entry (a gap-down open fills at
      the open -- worse, and counted); take-profit +25% from entry -> sell
      ALL (fill at the +25% level even on a gap-up -- conservative).
      Anything still held at run end is sold at the final close.
    - Costs: 2.0% of trade value on EVERY buy and EVERY sell, plus $0.01
      per sell order. A second, identical simulation is run with ZERO
      costs so the report can isolate friction exactly.
    - FLOOR LADDER: floor starts at $85.00. A closing value >= $125 raises
      the floor to $100; a closing value >= $150 raises it to $125. If a
      closing value touches or falls below the floor in effect, everything
      is liquidated at the next open and the run ENDS (date and balance
      recorded). Worst intraday pot value is also tracked, including days
      it dipped below the floor intraday but recovered by the close.
* Benchmark: SPY, $100 at the first run day's open to the 2026-11-20
  close, gross (no costs), as specified.

Outputs (next to this script): lottery-year-trades.csv (the costed run),
lottery-year.md
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
RUN_START = "2025-11-21"          # first trading day on/after this date
RUN_END = "2026-11-20"            # last trading day of the run

START_CASH = 100.00
FLOOR_START = 85.00
FLOOR_STEPS = [(150.00, 125.00), (125.00, 100.00)]  # (close >=, floor ->)
MAX_POSITIONS = 5
MAX_PER_NAME_FRAC = 0.20
STOP_FRAC = 0.10                  # -10% from entry
TP_FRAC = 0.25                    # +25% from entry
COST_RATE = 0.02                  # 2.0% of trade value, buys and sells
SELL_ORDER_FEE = 0.01             # per sell order
SCREEN_MAX_PRICE = 5.00
SCREEN_MIN_AVG_DOLLAR_VOL = 5_000_000

# Candidate list: the one-week test's 54 names plus other well-known listed
# names that traded in sub-$5 territory during 2025-2026. The monthly
# point-in-time screen -- not this list -- decides eligibility each month.
# NOTE (survivorship tilt): this list was assembled in Nov 2026 from names
# known then; names that died mid-year and were forgotten are missing.
CANDIDATES = [
    "PLUG", "FCEL", "BLDP", "SNDL", "ACB", "CGC", "TLRY", "OGI", "CRON",
    "BYND", "GERN", "IOVA", "RXRX", "PACB", "DNA", "EDIT", "OCGN", "SAVA",
    "BTBT", "SDIG", "GREE", "CAN", "EBON", "SOS", "MULN", "FFAI", "NKLA",
    "GOEV", "WKHS", "BLNK", "EVGO", "CHPT", "SPCE", "JBLU", "ULCC", "AMC",
    "BB", "NOK", "KOSS", "VFS", "PSNY", "NIO", "GRAB", "FINV", "NNDM",
    "DDD", "EXK", "FSM", "HYMC", "TEF", "BBAI", "OPEN", "PTON", "TDOC",
    # additions for the year run
    "LCID", "CLOV", "ACHR", "CIFR", "AGEN", "INO", "NVAX", "LX", "IQ",
    "TUYA", "NGD", "BTG", "DNN", "CLNE", "GEVO",
]
LISTED_EXCHANGES = {"NMS", "NGM", "NCM", "NYQ", "ASE", "AMX"}


# --------------------------------------------------------------------------
# Data loading
# --------------------------------------------------------------------------

def fetch_chart(symbol):
    """Daily OHLCV from the Yahoo Finance chart API, cached to disk."""
    path = os.path.join(CACHE, f"{symbol}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    p1 = int(datetime(2025, 6, 1, tzinfo=timezone.utc).timestamp())
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


def parse_bars(symbol):
    """Return (meta dict, {date_str: bar}) with dates in America/New_York."""
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
    """The n bars ending on end_date inclusive, oldest first."""
    days = sorted(d for d in bars if d <= end_date)
    return [(d, bars[d]) for d in days[-n:]]


def last_close_on_or_before(bars, day):
    days = sorted(d for d in bars if d <= day)
    return bars[days[-1]]["close"] if days else None


# --------------------------------------------------------------------------
# Monthly point-in-time screens
# --------------------------------------------------------------------------

def month_key(date_str):
    return date_str[:7]


def run_months(first_day, last_day):
    """Calendar months touched by the run, as 'YYYY-MM' strings."""
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
    """Screen using bars through the last trading day before month mk.

    Returns (screen_date, [passed symbols], {sym: (close, avg_dollar_vol)}).
    """
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


# --------------------------------------------------------------------------
# Ranking
# --------------------------------------------------------------------------

def rank_evening(universe, all_bars, day, held):
    """score = prior-day % gain x volume spike; positive scores only."""
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


# --------------------------------------------------------------------------
# Simulation (parameterised by cost model so the zero-cost twin is exact)
# --------------------------------------------------------------------------

def simulate(all_bars, trading_days, run_days, universes, cost_rate, sell_fee):
    res = {
        "trades": [], "total_costs": 0.0, "round_trips": [],
        "daily": [], "halted": False, "halt_date": None,
        "halt_trigger_close": None, "final_balance": None,
        "worst_intraday": (START_CASH, None), "intraday_floor_dips": [],
        "gap_through_stops": 0, "floor_history": [(None, FLOOR_START)],
        "notes": [],
    }
    trades = res["trades"]
    cash = START_CASH
    positions = {}   # sym -> {"shares", "entry", "outlay"}
    floor = FLOOR_START
    halt_pending = False

    def record(date, sym, side, price, shares, reason):
        trades.append({"date": date, "ticker": sym, "side": side,
                       "price": round(price, 4),
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

    start_idx = trading_days.index(run_days[0])
    end_idx = trading_days.index(run_days[-1])

    # Evening before the first run day: rank on the prior trading day's bar,
    # using the first run day's month universe.
    pending = rank_evening(universes[month_key(run_days[0])], all_bars,
                           trading_days[start_idx - 1], set())

    i = start_idx
    while i <= end_idx:
        day = trading_days[i]
        is_last = (i == end_idx)

        # Floor liquidation at the open ends the run.
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

        # Buys at the open.
        for s in pending:
            if s in positions or len(positions) >= MAX_POSITIONS:
                continue
            b = all_bars[s].get(day)
            if not b or b["open"] <= 0:
                continue
            amount = min(MAX_PER_NAME_FRAC * equity(day, "open"), cash)
            if amount < 1.00:
                continue
            shares = do_buy(day, s, b["open"], amount,
                            "entry: top momentum x volume rank from prior "
                            "evening")
            cash -= amount
            positions[s] = {"shares": shares, "entry": b["open"],
                            "outlay": amount}
        pending = []

        # Worst intraday value (positions marked at today's lows).
        low_eq = equity(day, "low")
        if low_eq < res["worst_intraday"][0]:
            res["worst_intraday"] = (low_eq, day)

        # Intraday exits: stop first, then take-profit.
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
                close_position(day, s, fill, "stop-loss -10% from entry")
            elif b["high"] >= tp:
                close_position(day, s, tp,
                               "take-profit +25% from entry (sold all)")

        # End of run: everything still held exits at the final close.
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

        # Intraday dip below the floor that recovered by the close.
        if low_eq < floor and eq_close > floor:
            res["intraday_floor_dips"].append((day, low_eq, floor))

        # Floor: breach check against the floor in effect, then ladder up.
        if eq_close <= floor:
            if is_last:
                # No next open exists; the end-of-run liquidation above
                # already flattened the pot at this close.
                res["halted"] = True
                res["halt_date"] = day
                res["halt_trigger_close"] = eq_close
                res["final_balance"] = cash
                res["notes"].append(
                    f"FLOOR: pot closed at ${eq_close:.2f} on {day}, at/below "
                    f"the ${floor:.2f} floor, on the final day of the run; "
                    f"positions were liquidated at that close.")
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

        # Evening ranking for the next trading day (that day's month rules).
        if not is_last:
            nxt = trading_days[i + 1]
            pending = rank_evening(universes[month_key(nxt)], all_bars,
                                   day, set(positions))
        i += 1

    res["final_balance"] = cash
    return res


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    # ------------------------------------------------------------- load data
    all_bars, all_meta = {}, {}
    failed = []
    for sym in CANDIDATES + ["SPY"]:
        try:
            meta, bars = parse_bars(sym)
        except Exception:
            meta, bars = {}, {}
            failed.append(sym)
        all_meta[sym], all_bars[sym] = meta, bars

    spy_days = sorted(all_bars["SPY"].keys())
    trading_days = [d for d in spy_days if "2025-06-01" <= d <= RUN_END]
    run_days = [d for d in trading_days if RUN_START <= d <= RUN_END]
    first_day, last_day = run_days[0], run_days[-1]

    # ------------------------------------------------------- monthly screens
    months = run_months(first_day, last_day)
    universes, screen_info = {}, {}
    for mk in months:
        sdate, passed, detail = screen_for_month(mk, trading_days,
                                                 all_bars, all_meta)
        universes[mk] = passed
        screen_info[mk] = (sdate, passed, detail)

    # ------------------------------------------------------------ simulations
    costed = simulate(all_bars, trading_days, run_days, universes,
                      COST_RATE, SELL_ORDER_FEE)
    free = simulate(all_bars, trading_days, run_days, universes, 0.0, 0.0)

    # -------------------------------------------------------------- benchmark
    spy = all_bars["SPY"]
    spy_open = spy[first_day]["open"]
    spy_close = spy[last_day]["close"]
    spy_final = 100.0 * spy_close / spy_open
    spy_ret = spy_final - 100.0

    # ------------------------------------------------------------------ stats
    def stats(res):
        series = [START_CASH] + [eq for _, eq in res["daily"]]
        peak, max_dd = series[0], 0.0
        for v in series:
            peak = max(peak, v)
            max_dd = min(max_dd, v / peak - 1)
        rts = res["round_trips"]
        wins = [r for r in rts if r["pnl"] > 0]
        losses = [r for r in rts if r["pnl"] <= 0]
        biggest_win = max(rts, key=lambda r: r["pnl"]) if rts else None
        biggest_loss = min(rts, key=lambda r: r["pnl"]) if rts else None
        return {
            "series": series, "max_dd": max_dd,
            "n_trades": len(res["trades"]),
            "n_buys": sum(1 for t in res["trades"] if t["side"] == "buy"),
            "n_sells": sum(1 for t in res["trades"] if t["side"] == "sell"),
            "round_trips": len(rts), "wins": len(wins),
            "losses": len(losses),
            "win_rate": (len(wins) / len(rts) * 100) if rts else 0.0,
            "biggest_win": biggest_win, "biggest_loss": biggest_loss,
        }

    cs, fs = stats(costed), stats(free)
    final = costed["final_balance"]
    total_return = (final / START_CASH - 1) * 100
    worst_intra, worst_intra_day = costed["worst_intraday"]
    # Intraday drawdown: worst intraday value vs the highest close before it.
    peak_before = START_CASH
    intra_dd = 0.0
    daily_map = dict(costed["daily"])
    for d in run_days:
        if d == worst_intra_day:
            intra_dd = worst_intra / peak_before - 1 if peak_before else 0.0
        if d in daily_map:
            peak_before = max(peak_before, daily_map[d])

    # Monthly closing balances (last recorded close in each month).
    monthly_bal = []
    for mk in months:
        vals = [(d, eq) for d, eq in costed["daily"] if month_key(d) == mk]
        if vals:
            monthly_bal.append((mk, vals[-1][0], vals[-1][1]))

    # ------------------------------------------------------------- CSV output
    csv_path = os.path.join(HERE, "lottery-year-trades.csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "ticker", "side", "price",
                                          "shares", "value", "reason"])
        w.writeheader()
        w.writerows(costed["trades"])

    # -------------------------------------------------------------- MD output
    lines = []
    lines.append("# Penny-Stock Lottery Pot -- ONE-YEAR Backtest")
    lines.append("")
    lines.append(f"Run window: **{first_day}** (first trading day on/after "
                 f"Fri 2025-11-21) through **{last_day}** (Fri 2026-11-20). "
                 f"Start: **$100.00** fake money, treated like real money "
                 f"(full costs, no look-ahead). Simulation only -- no real "
                 f"or paper broker orders.")
    lines.append("")
    lines.append("Data: Yahoo Finance chart API daily OHLCV (free), fetched "
                 "2025-06-01 through 2026-11-20. Stooq's CSV endpoint is "
                 "behind a JavaScript browser check and returns no data to "
                 "a script, so it could not be used. Prices are the feed's "
                 "daily bars as reported (split-adjusted, not "
                 "dividend-adjusted).")
    lines.append("")
    lines.append("## Rules in force")
    lines.append("")
    lines.append("- Universe re-screened MONTHLY, point-in-time: for each "
                 "month, the screen uses bars through the last trading day "
                 "of the prior month -- US exchange-listed equity, close "
                 "< $5.00, trailing-20-day average daily dollar volume "
                 "> $5,000,000. No OTC/Pink Sheet names, ever.")
    lines.append("- Entries: evening ranking by prior-day % gain x volume "
                 "spike (positive scores only), bought at next open, max "
                 "20% of pot per name, max 5 positions, fractional shares, "
                 "no averaging down.")
    lines.append("- Exits: -10% stop (gap-down opens fill at the open), "
                 "+25% take-profit sells all, stop fills first if both are "
                 "touched the same day; anything held at run end sells at "
                 "the final close.")
    lines.append("- Costs: 2.0% of trade value on every buy and every sell, "
                 "plus $0.01 per sell order.")
    lines.append("- Floor ladder: $85 at start; a close >= $125 raises the "
                 "floor to $100; a close >= $150 raises it to $125. A close "
                 "at/below the floor liquidates everything at the next "
                 "open and ENDS the run.")
    lines.append("")
    lines.append("## Monthly screens (point-in-time)")
    lines.append("")
    lines.append("Screen date = last trading day of the prior month; only "
                 "that month's data existed at decision time.")
    lines.append("")
    lines.append("| Month | Screen date | Names passing | Passing names |")
    lines.append("|---|---|---|---|")
    for mk in months:
        sdate, passed, _ = screen_info[mk]
        lines.append(f"| {mk} | {sdate} | {len(passed)} | "
                     f"{', '.join(passed) if passed else '(none)'} |")
    lines.append("")
    lines.append("## Month-by-month closing balances (costed run)")
    lines.append("")
    lines.append("| Month | Last trading day in run | Closing pot value |")
    lines.append("|---|---|---|")
    lines.append(f"| Start | {first_day} (open) | $100.00 |")
    for mk, d, eq in monthly_bal:
        lines.append(f"| {mk} | {d} | ${eq:.2f} |")
    lines.append("")
    lines.append("## Result (costed run -- the one that counts)")
    lines.append("")
    if costed["halted"]:
        lines.append(f"- **RUN ENDED EARLY on the floor.** The pot closed "
                     f"at ${costed['halt_trigger_close']:.2f}, at/below "
                     f"the floor in effect, and everything was liquidated "
                     f"at the next open ({costed['halt_date']}). "
                     f"**Final balance: ${final:.2f} "
                     f"({total_return:+.2f}%)**.")
    else:
        lines.append(f"- The run survived the full year. **Final balance: "
                     f"${final:.2f} ({total_return:+.2f}%)**.")
    lines.append(f"- Trades: {cs['n_trades']} total ({cs['n_buys']} buys, "
                 f"{cs['n_sells']} sells); {cs['round_trips']} positions "
                 f"opened and closed")
    lines.append(f"- Wins / losses (closed positions, net of all costs): "
                 f"{cs['wins']} / {cs['losses']} -- win rate "
                 f"{cs['win_rate']:.1f}%")
    if cs["biggest_win"]:
        bw, bl = cs["biggest_win"], cs["biggest_loss"]
        lines.append(f"- Biggest win: {bw['ticker']} "
                     f"+${bw['pnl']:.2f} (closed {bw['exit_date']}); "
                     f"biggest loss: {bl['ticker']} ${bl['pnl']:.2f} "
                     f"(closed {bl['exit_date']})")
    lines.append(f"- Max drawdown (closing values): "
                 f"{cs['max_dd'] * 100:.2f}%")
    lines.append(f"- Worst intraday pot value: ${worst_intra:.2f} on "
                 f"{worst_intra_day} (intraday drawdown from the prior "
                 f"peak close: {intra_dd * 100:.2f}%)")
    if costed["intraday_floor_dips"]:
        dips = "; ".join(
            f"{d}: dipped to ${v:.2f} vs floor ${fl:.2f}, recovered by "
            f"the close" for d, v, fl in costed["intraday_floor_dips"])
        lines.append(f"- Days the pot dipped BELOW the floor intraday but "
                     f"recovered by the close (no halt -- the rule is on "
                     f"closes): {dips}")
    else:
        lines.append("- Days the pot dipped below the floor intraday but "
                     "recovered by the close: none.")
    lines.append(f"- Gap-through-stop events (opened below the -10% stop, "
                 f"filled worse): {costed['gap_through_stops']}")
    lines.append(f"- Floor history: " + "; ".join(
        (f"{d}: raised to ${fl:.2f}" if d else f"start ${fl:.2f}")
        for d, fl in costed["floor_history"]))
    lines.append("")
    lines.append("## The cost of friction (zero-cost twin run)")
    lines.append("")
    lines.append(f"- **Total costs paid (costed run): "
                 f"${costed['total_costs']:.2f}** -- 2.0% of trade value on "
                 f"every buy and sell plus $0.01 per sell order. That is "
                 f"{costed['total_costs']:.1f}% of the entire starting pot.")
    if free["halted"]:
        lines.append(f"- The IDENTICAL rules with zero costs were halted "
                     f"on {free['halt_date']} with a final balance of "
                     f"${free['final_balance']:.2f} "
                     f"({(free['final_balance'] / START_CASH - 1) * 100:+.2f}%) "
                     f"after {fs['n_trades']} trades.")
    else:
        lines.append(f"- The IDENTICAL rules with zero costs finished the "
                     f"year at **${free['final_balance']:.2f} "
                     f"({(free['final_balance'] / START_CASH - 1) * 100:+.2f}%)** "
                     f"after {fs['n_trades']} trades.")
    lines.append(f"- Friction gap: ${free['final_balance'] - final:.2f} of "
                 f"ending value consumed by costs and their compounding "
                 f"consequences (in the zero-cost run the pot also risks "
                 f"slightly more dollars per trade, because position size "
                 f"is a percent of a bigger pot -- the gap is therefore "
                 f"costs plus knock-on sizing effects, stated honestly).")
    lines.append("")
    lines.append("## Benchmark (same $100, same dates)")
    lines.append("")
    lines.append(f"- SPY: $100 at the {first_day} open (${spy_open:.2f}) to "
                 f"the {last_day} close (${spy_close:.2f}) = "
                 f"**${spy_final:.2f}** ({spy_ret:+.2f}%), gross, no costs.")
    lines.append(f"- Lottery pot: **${final:.2f}** "
                 f"({total_return:+.2f}%), net of all costs"
                 + (f", run ended {costed['halt_date']}." if costed["halted"]
                    else ", full year."))
    lines.append("")
    if costed["notes"]:
        lines.append("## Notes from the run")
        lines.append("")
        for n in costed["notes"]:
            lines.append(f"- {n}")
        lines.append("")
    lines.append("## What this year does and does not prove (honest section)")
    lines.append("")
    lines.append("- **Survivorship tilt (material):** the candidate list "
                 "was assembled in Nov 2026 from names known then. Listed "
                 "penny names that died, were delisted, or were simply "
                 "forgotten during the year are missing from the candidate "
                 "pool, so the monthly screens never even had the chance "
                 "to reject them. This FLATTERS the result by an unknown "
                 "amount. A truly point-in-time universe (every listed "
                 "sub-$5 name as of each screen date) would very likely "
                 "do worse.")
    lines.append("- **Daily-bar limits:** exits are judged on each day's "
                 "open/high/low/close. When the stop and the take-profit "
                 "are both inside one day's range, the stop is filled "
                 "first (conservative). But a daily bar cannot show a "
                 "midday plunge through the floor that recovered by the "
                 "close, nor a fill worse than the day's low on a halted "
                 "or chaotic name; real fills on sub-$5 names are often "
                 "worse than the bar suggests. Intraday pot values here "
                 "mark holdings at the day's lows and are approximations.")
    lines.append(f"- **Gap-through stops:** {costed['gap_through_stops']} "
                 f"exits opened below their -10% stop and filled at the "
                 f"open, worse than planned. In penny names the stop is a "
                 f"hope with a trigger, not a guarantee -- the year's "
                 "count is the measurement of that.")
    lines.append("- **The floor is defined on closes.** A pot can dip "
                 "below the floor intraday and survive (see above); a "
                 "live account with resting stops could be taken out at "
                 "the intraday low instead. The closing-basis rule is the "
                 "kinder version.")
    lines.append("- **One run, one path:** a year is one draw from history, "
                 "not a distribution. These rules were frozen before the "
                 "run, which is what makes the number honest, but a "
                 "different year (or the same year with the entry ranking "
                 "nudged) can give a very different answer. The research "
                 "base rate for penny stocks (Eraker & Ready: median OTC "
                 "stock -97%, roughly 1.2% up 10x or more) remains the "
                 "prior this single year has to beat, and one year does "
                 "not repeal it.")
    lines.append("- **What it does prove:** the machinery (monthly "
                 "point-in-time screens, evening rankings, floor ladder, "
                 "cost model) runs end to end on real data for a full "
                 "year, and it measures the two things that decide penny "
                 "trading in practice -- how much friction eats, and how "
                 "often stops fail to protect. Judge the pot on those "
                 "measurements, not on hope.")
    lines.append("")
    lines.append(f"Full trade log for the costed run: "
                 f"`lottery-year-trades.csv` ({cs['n_trades']} rows). "
                 f"Script: `lottery-year.py`.")
    if failed:
        lines.append("")
        lines.append(f"Data fetch failures (excluded everywhere): "
                     f"{', '.join(failed)}")
    lines.append("")

    md_path = os.path.join(HERE, "lottery-year.md")
    with open(md_path, "w") as f:
        f.write("\n".join(lines))

    print(f"Run days: {first_day} .. {last_day} ({len(run_days)} trading "
          f"days)")
    print("Monthly screens:")
    for mk in months:
        sdate, passed, _ = screen_info[mk]
        print(f"  {mk} (screen {sdate}): {len(passed)} passed: "
              f"{', '.join(passed)}")
    print(f"COSTED: final ${final:.2f} ({total_return:+.2f}%), halted="
          f"{costed['halted']} halt_date={costed['halt_date']}, trades="
          f"{cs['n_trades']}, round trips={cs['round_trips']}, W/L="
          f"{cs['wins']}/{cs['losses']} ({cs['win_rate']:.1f}%), "
          f"maxDD={cs['max_dd'] * 100:.2f}%, costs="
          f"${costed['total_costs']:.2f}, gaps={costed['gap_through_stops']}")
    print(f"Worst intraday: ${worst_intra:.2f} on {worst_intra_day}; "
          f"intraday floor dips recovered: "
          f"{len(costed['intraday_floor_dips'])}")
    print(f"ZERO-COST: final ${free['final_balance']:.2f} "
          f"({(free['final_balance'] / START_CASH - 1) * 100:+.2f}%), "
          f"halted={free['halted']} halt_date={free['halt_date']}, "
          f"trades={fs['n_trades']}")
    print(f"SPY benchmark: ${spy_final:.2f} ({spy_ret:+.2f}%)")
    print(f"Wrote {csv_path} and {md_path}")


if __name__ == "__main__":
    main()
