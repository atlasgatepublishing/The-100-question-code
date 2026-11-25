#!/usr/bin/env python3
"""
Penny-Stock Lottery Pot -- one-week backtest, Mon 2026-11-16 to Fri 2026-11-20.

Simulation only. No broker orders (real or paper) are placed.

Method
------
* Pretend it is the morning of Mon 2026-11-16. Every decision uses only data
  that existed at that decision point (no look-ahead): the universe is screened
  on Fri 2026-11-13 data, and each evening's ranking uses that day's completed
  bar to buy at the NEXT day's open.
* Universe screen (as of Fri 2026-11-13 close):
    - US exchange-listed common stock (NYSE / Nasdaq / NYSE American),
      verified from the data feed's exchange + instrument-type metadata.
      OTC / Pink Sheet names are excluded -- the broker cannot trade them.
    - Close on Fri 2026-11-13 < $5.00
    - Average daily dollar volume over the prior 20 trading days
      (20 bars ending 2026-11-13) > $5,000,000
* Data: Yahoo Finance chart API (free, no key). Stooq's CSV endpoint was tried
  first and is behind a JavaScript browser check, so it returns no data to a
  script in 2026. Daily OHLCV bars fetched 2026-01-01 through 2026-11-20 and
  cached in ./data_cache/ next to this script. Prices are the feed's daily
  bars as reported.
* Ranking each evening: score = prior-day % gain x volume spike, where
  volume spike = prior-day volume / trailing 20-day average volume
  (20 bars ending on the ranking day). Only names with a positive score
  (i.e. a positive prior-day gain) are bought.
* Rules (followed exactly):
    - Buy at next day's open, max 20% of pot equity per name, max 5 positions,
      fractional shares. No averaging down, no adding to a held name.
    - Exits checked daily, conservative stop-first rule if both levels are
      touched the same day:
        stop-loss  -10% from entry (if the open gaps below the stop, the fill
                   is the open -- worse, and honest);
        take-profit +25% from entry -> sell ALL (fill at the +25% level even
                   if the open gaps above it -- conservative on gains);
        anything still held is sold at the Friday close.
    - Costs: 2.0% of trade value on EVERY buy and EVERY sell (spread +
      slippage model for listed sub-$5 names), plus $0.01 per sell order.
    - Halt: if the pot's CLOSING value falls to $85.00 (-15%), liquidate
      everything at the next open and stop trading.
* Benchmark: SPY, $100 at Mon 2026-11-16 open to Fri 2026-11-20 close, gross
  (no costs), as specified.

Outputs (written next to this script): lottery-trades.csv, lottery.md
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
SCREEN_DATE = "2026-11-13"        # Friday before the test week
WEEK = ["2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20"]

START_CASH = 100.00
HALT_LEVEL = 85.00
MAX_POSITIONS = 5
MAX_PER_NAME_FRAC = 0.20
STOP_FRAC = 0.10                  # -10% from entry
TP_FRAC = 0.25                    # +25% from entry
COST_RATE = 0.02                  # 2.0% of trade value, buys and sells
SELL_ORDER_FEE = 0.01             # per sell order
SCREEN_MAX_PRICE = 5.00
SCREEN_MIN_AVG_DOLLAR_VOL = 5_000_000

# Well-known US-listed names that trade (or have traded) in penny territory.
# The screen -- not this list -- decides who qualifies. Anything without
# verifiable listed-equity data is excluded and reported in the table.
CANDIDATES = [
    "PLUG", "FCEL", "BLDP", "SNDL", "ACB", "CGC", "TLRY", "OGI", "CRON",
    "BYND", "GERN", "IOVA", "RXRX", "PACB", "DNA", "EDIT", "OCGN", "SAVA",
    "BTBT", "SDIG", "GREE", "CAN", "EBON", "SOS", "MULN", "FFAI", "NKLA",
    "GOEV", "WKHS", "BLNK", "EVGO", "CHPT", "SPCE", "JBLU", "ULCC", "AMC",
    "BB", "NOK", "KOSS", "VFS", "PSNY", "NIO", "GRAB", "FINV", "NNDM",
    "DDD", "EXK", "FSM", "HYMC", "TEF", "BBAI", "OPEN", "PTON", "TDOC",
]
# Yahoo exchange codes for NYSE / Nasdaq / NYSE American listings.
LISTED_EXCHANGES = {"NMS", "NGM", "NCM", "NYQ", "ASE", "AMX"}


def fetch_chart(symbol):
    """Daily OHLCV from the Yahoo Finance chart API, cached to disk."""
    path = os.path.join(CACHE, f"{symbol}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    p1 = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp())
    p2 = int(datetime(2026, 11, 21, tzinfo=timezone.utc).timestamp())
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


def rank_evening(universe, all_bars, day, held):
    """Rank qualifying, not-held names on `day`'s completed bar.

    score = prior-day % gain x (volume / trailing-20-day average volume).
    Only positive scores (a positive prior-day gain) are eligible.
    """
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


def main():
    # ------------------------------------------------------------- load data
    all_bars, all_meta = {}, {}
    for sym in CANDIDATES + ["SPY"]:
        try:
            meta, bars = parse_bars(sym)
        except Exception:
            meta, bars = {}, {}
        all_meta[sym], all_bars[sym] = meta, bars

    # ---------------------------------------------------------------- screen
    screen_rows, universe = [], []
    for sym in CANDIDATES:
        meta, bars = all_meta[sym], all_bars[sym]
        exch = meta.get("exchangeName", "?")
        itype = meta.get("instrumentType", "?")
        bar = bars.get(SCREEN_DATE)
        if bar is None:
            screen_rows.append((sym, exch, None, None, "EXCLUDED",
                                f"no bar on {SCREEN_DATE} (delisted, halted, "
                                f"or no data)"))
            continue
        last20 = trailing(bars, SCREEN_DATE, 20)
        avg_dv = (sum(b["close"] * b["volume"] for _, b in last20) / len(last20)
                  if last20 else 0.0)
        if not (exch in LISTED_EXCHANGES and itype == "EQUITY"):
            verdict, note = "EXCLUDED", (f"not a verified listed equity "
                                         f"(exchange={exch}, type={itype})")
        elif not bar["close"] < SCREEN_MAX_PRICE:
            verdict, note = "EXCLUDED", f"closed at/above ${SCREEN_MAX_PRICE:.2f}"
        elif not avg_dv > SCREEN_MIN_AVG_DOLLAR_VOL:
            verdict, note = "EXCLUDED", "avg daily dollar volume <= $5,000,000"
        else:
            verdict, note = "PASSED", ""
            universe.append(sym)
        screen_rows.append((sym, exch, bar["close"], avg_dv, verdict, note))

    # ---------------------------------------------------------------- trading
    trades, total_costs = [], 0.0
    notes = []

    def record(date, sym, side, price, shares, reason):
        trades.append({"date": date, "ticker": sym,
                       "buy/sell": side, "price": round(price, 4),
                       "shares": round(shares, 6),
                       "value": round(price * shares, 2), "reason": reason})

    cash = START_CASH
    positions = {}     # sym -> {"shares", "entry", "outlay"}
    round_trips = []   # net P/L per closed position (after all costs)

    def do_buy(date, sym, price, amount, reason):
        nonlocal total_costs
        shares = amount / (price * (1 + COST_RATE))
        total_costs += amount - shares * price
        record(date, sym, "buy", price, shares, reason)
        return shares

    def do_sell(date, sym, price, shares, reason):
        nonlocal total_costs
        gross = shares * price
        total_costs += gross * COST_RATE + SELL_ORDER_FEE
        record(date, sym, "sell", price, shares, reason)
        return gross * (1 - COST_RATE) - SELL_ORDER_FEE

    def close_position(date, sym, price, reason):
        nonlocal cash
        p = positions.pop(sym)
        proceeds = do_sell(date, sym, price, p["shares"], reason)
        cash += proceeds
        round_trips.append(proceeds - p["outlay"])

    def equity(day, field):
        eq = cash
        for s, p in positions.items():
            b = all_bars[s].get(day)
            eq += p["shares"] * (b[field] if b else p["entry"])
        return eq

    # Fri Nov 13 evening ranking -> Monday's buys (only Nov 13 data used).
    pending = rank_evening(universe, all_bars, SCREEN_DATE, set())
    halted = False
    daily = []
    intraday_low = START_CASH

    for day in WEEK:
        # halt liquidation at the open (triggered by yesterday's close)
        if halted and positions:
            for s in list(positions):
                b = all_bars[s].get(day)
                if b:
                    close_position(day, s, b["open"],
                                   "HALT liquidation at open (pot closed "
                                   "at/below $85 the prior day)")
        # buys at the open
        if not halted:
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
                                "entry: top momentum x volume rank from "
                                "prior evening")
                cash -= amount
                positions[s] = {"shares": shares, "entry": b["open"],
                                "outlay": amount}
        pending = []
        # intraday exits: stop first, then take-profit
        for s in list(positions):
            b = all_bars[s].get(day)
            if not b:
                continue
            entry = positions[s]["entry"]
            stop, tp = entry * (1 - STOP_FRAC), entry * (1 + TP_FRAC)
            if b["low"] <= stop:
                fill = min(b["open"], stop)  # gap-down fills at the open
                if b["open"] < stop:
                    notes.append(
                        f"{day}: {s} gapped down through its stop (opened "
                        f"${b['open']:.4f} vs stop ${stop:.4f}); filled at "
                        f"the open, worse than the stop level.")
                close_position(day, s, fill, "stop-loss -10% from entry")
            elif b["high"] >= tp:
                close_position(day, s, tp,
                               "take-profit +25% from entry (sold all)")
        # Friday: everything still held exits at the close
        if day == WEEK[-1]:
            for s in list(positions):
                b = all_bars[s].get(day)
                if b:
                    close_position(day, s, b["close"],
                                   "Friday close exit (end of test week)")
        eq_close = equity(day, "close")
        intraday_low = min(intraday_low, equity(day, "low"))
        daily.append((day, eq_close))
        # halt check on the close
        if not halted and eq_close <= HALT_LEVEL and day != WEEK[-1]:
            halted = True
            notes.append(
                f"HALT: pot closed at ${eq_close:.2f} on {day}, at/below the "
                f"$85.00 (-15%) floor. Remaining positions were liquidated at "
                f"the next open and no further buys were made.")
        # evening ranking for tomorrow (today's completed bar only)
        if not halted and day != WEEK[-1]:
            pending = rank_evening(universe, all_bars, day, set(positions))

    final_balance = cash
    total_return = (final_balance / START_CASH - 1) * 100

    # max drawdown on closing equity (starting point $100 included)
    series = [START_CASH] + [eq for _, eq in daily]
    peak, max_dd = series[0], 0.0
    for v in series:
        peak = max(peak, v)
        max_dd = min(max_dd, v / peak - 1)
    wins = sum(1 for x in round_trips if x > 0)
    losses = sum(1 for x in round_trips if x <= 0)
    n_buys = sum(1 for t in trades if t["buy/sell"] == "buy")
    n_sells = sum(1 for t in trades if t["buy/sell"] == "sell")

    # SPY benchmark: $100 Mon open -> Fri close, gross
    spy = all_bars["SPY"]
    spy_result = 100.0 * spy[WEEK[-1]]["close"] / spy[WEEK[0]]["open"]
    spy_return = spy_result - 100.0

    if intraday_low < min(series):
        notes.append(
            f"Intraday honesty check: valuing holdings at each day's LOW, "
            f"the pot's worst intraday value was ${intraday_low:.2f} vs the "
            f"worst close of ${min(series):.2f}. The halt rule is defined on "
            f"closes, so no extra halt was triggered -- but a real account "
            f"watched tick-by-tick, or a stop filled mid-plunge, could have "
            f"done worse than these closing numbers.")

    # ------------------------------------------------------------- CSV output
    csv_path = os.path.join(HERE, "lottery-trades.csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "ticker", "buy/sell",
                                          "price", "shares", "value",
                                          "reason"])
        w.writeheader()
        w.writerows(trades)

    # -------------------------------------------------------------- MD output
    passed = [r for r in screen_rows if r[4] == "PASSED"]
    lines = []
    lines.append("# Penny-Stock Lottery Pot -- Backtest, Week of Mon 2026-11-16 "
                 "to Fri 2026-11-20")
    lines.append("")
    lines.append("Simulation only -- no real or paper broker orders. Start: "
                 "**$100.00** fake money, treated like real money (full costs, "
                 "no look-ahead: the universe was screened on Fri 2026-11-13 "
                 "data and every buy was decided the evening before, using "
                 "only that day's completed bar).")
    lines.append("")
    lines.append("Data: Yahoo Finance chart API daily OHLCV (free). Stooq's "
                 "CSV endpoint was tried first and returns a JavaScript "
                 "browser check instead of data to a script in 2026, so it "
                 "could not be used. Prices are the feed's daily bars as "
                 "reported; candidate names with no verifiable listed-equity "
                 "bar on Fri 2026-11-13 were excluded (see table).")
    lines.append("")
    lines.append("## Screened universe (as of Fri 2026-11-13 close)")
    lines.append("")
    lines.append("Filters: US exchange-listed equity (NYSE/Nasdaq/NYSE "
                 "American), close < $5.00, average daily dollar volume over "
                 "the prior 20 trading days > $5,000,000. OTC/Pink Sheet "
                 "names are not allowed -- the broker cannot trade them.")
    lines.append("")
    lines.append("| Ticker | Exchange (per feed) | Close Fri 2026-11-13 | "
                 "Avg daily $ volume (20d) | Result | Note |")
    lines.append("|---|---|---|---|---|---|")
    for sym, exch, close, adv, verdict, note in screen_rows:
        c = f"${close:.4f}" if close is not None else "-"
        a = f"${adv:,.0f}" if adv is not None else "-"
        lines.append(f"| {sym} | {exch} | {c} | {a} | {verdict} | {note} |")
    lines.append("")
    lines.append(f"**{len(passed)} of {len(CANDIDATES)} candidates passed**: "
                 + (", ".join(r[0] for r in passed) if passed else "none"))
    lines.append("")
    lines.append("## Daily closing balances")
    lines.append("")
    lines.append("| Date | Closing pot value |")
    lines.append("|---|---|")
    lines.append(f"| Start (Fri 2026-11-13) | $100.00 |")
    for d, eq in daily:
        lines.append(f"| {d} | ${eq:.2f} |")
    lines.append("")
    lines.append("## Result")
    lines.append("")
    lines.append(f"- **Final balance: ${final_balance:.2f}** "
                 f"({total_return:+.2f}% on the week)")
    lines.append(f"- Trades: {len(trades)} total ({n_buys} buys, "
                 f"{n_sells} sells); {len(round_trips)} positions opened "
                 f"and closed")
    lines.append(f"- Wins / losses (closed positions, net of all costs): "
                 f"{wins} win{'s' if wins != 1 else ''} / "
                 f"{losses} loss{'es' if losses != 1 else ''}")
    lines.append(f"- Max drawdown (closing values): {max_dd * 100:.2f}%")
    lines.append(f"- **Total costs paid: ${total_costs:.2f}** -- 2.0% of trade "
                 f"value on every buy and every sell, plus $0.01 per sell "
                 f"order. That is {total_costs:.1f}% of the entire starting "
                 f"pot consumed by friction. Without any costs the same "
                 f"trades would have ended at roughly "
                 f"${final_balance + total_costs:.2f}; costs are the "
                 f"difference, and on a $100 pot of sub-$5 names they are "
                 f"a first-order result, not a footnote.")
    lines.append(f"- Halt (-15% / $85 floor): "
                 + ("TRIGGERED -- see notes." if halted else
                    "not triggered on a closing basis."))
    lines.append("")
    lines.append("## Benchmark (same week, same $100)")
    lines.append("")
    lines.append(f"- SPY: $100 at Mon open (${spy[WEEK[0]]['open']:.2f}) to "
                 f"Fri close (${spy[WEEK[-1]]['close']:.2f}) = "
                 f"**${spy_result:.2f}** ({spy_return:+.2f}%), gross, no "
                 f"costs, as specified.")
    lines.append(f"- Lottery pot: **${final_balance:.2f}** "
                 f"({total_return:+.2f}%), net of all costs.")
    lines.append("")
    if notes:
        lines.append("## Notes from the run")
        lines.append("")
        for n in notes:
            lines.append(f"- {n}")
        lines.append("")
    lines.append("## Trade log")
    lines.append("")
    lines.append("Full detail in `lottery-trades.csv`. Summary:")
    lines.append("")
    lines.append("| Date | Ticker | Side | Price | Shares | Value | Reason |")
    lines.append("|---|---|---|---|---|---|---|")
    for t in trades:
        lines.append(f"| {t['date']} | {t['ticker']} | {t['buy/sell']} | "
                     f"${t['price']:.4f} | {t['shares']:.4f} | "
                     f"${t['value']:.2f} | {t['reason']} |")
    lines.append("")
    lines.append("## What this one week does and does not prove")
    lines.append("")
    lines.append("It proves the mechanics work end to end on real data with "
                 "honest fills and full costs, and it shows what one specific "
                 "week did to one specific set of rules. It does NOT prove "
                 "penny trading makes money: one week is a coin flip, the "
                 "universe was screened from names already known to be "
                 "listed and liquid (survivorship tilt -- the thousands of "
                 "OTC pennies that go to zero were never in the building, "
                 "because the broker cannot trade them), and daily bars "
                 "cannot show the intraday moments where a real sub-$5 fill "
                 "would have been worse than the bar's low. The research "
                 "base rate for OTC penny stocks (median return -97% in the "
                 "Eraker & Ready study) has not been repealed by one week. "
                 "Treat this as a dress rehearsal and a cost measurement, "
                 "not a verdict -- the verdict needs the full multi-week run "
                 "and the testing gates in DESIGN.md.")
    lines.append("")

    md_path = os.path.join(HERE, "lottery.md")
    with open(md_path, "w") as f:
        f.write("\n".join(lines))

    print(f"Universe passed: {[r[0] for r in passed]}")
    print(f"Final balance: ${final_balance:.2f} ({total_return:+.2f}%)")
    print(f"Trades: {len(trades)} ({n_buys} buys / {n_sells} sells), "
          f"round trips: {len(round_trips)}, W/L: {wins}/{losses}")
    print(f"Max drawdown (closes): {max_dd * 100:.2f}%  "
          f"Intraday low equity: ${intraday_low:.2f}")
    print(f"Total costs: ${total_costs:.2f}")
    print(f"SPY benchmark: ${spy_result:.2f} ({spy_return:+.2f}%)")
    print(f"Halted: {halted}")
    print(f"Wrote {csv_path} and {md_path}")


if __name__ == "__main__":
    main()
