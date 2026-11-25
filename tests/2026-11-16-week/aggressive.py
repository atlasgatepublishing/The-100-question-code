#!/usr/bin/env python3
"""
AGGRESSIVE sprint-pot backtest - one week, Terry's AI stock app (simulation only).

Week: Mon 2026-11-16 .. Fri 2026-11-20. Start: $100 cash, pretend it is the
morning of Mon Nov 16. Signals for each day are computed ONLY from bars up to
and including the prior trading day (no look-ahead). Daily OHLCV bars only.

Rules (Terry's aggressive style, followed exactly):
- Each evening, rank the universe by (a) prior 5-trading-day % gain and
  (b) prior-day volume vs its 20-day average volume.
- A name qualifies if it closed at/above its prior 10-day high (breakout) OR
  gained >2% on the prior day with volume >1.5x its 20-day average.
- Buy at the NEXT day's open: top 1-2 qualifying names, up to 50% of pot each,
  max 2 positions, fractional shares allowed. Nothing qualifies -> hold cash.
- Exits, checked each day with that day's high/low; if stop and target are
  both touched the same day, the STOP fills first (conservative):
  hard stop -3% from entry; profit exit +6% from entry; also exit at the
  close if the name closes below the prior day's low ("fade").
- Costs: 0.10% of trade value on every buy and every sell, plus a $0.01
  sell fee per order (regulatory).
- Risk: if the pot's closing value ever falls to $85 (-15%), halt - no new
  trades, liquidate at next open. No new entries on a day after the pot is
  down 4%+ from its prior close.

Data: free daily bars, 2026-01-01..2026-11-20 (lead-in for indicators).
Primary source tried: Stooq daily CSV. Fallback: Yahoo Finance chart API.
The source actually used per symbol is recorded in the report.
"""

import csv
import io
import json
import os
import urllib.request
from datetime import datetime, timezone

UNIVERSE = ["SPY", "QQQ", "NVDA", "TSLA", "AAPL", "MSFT", "AMZN", "META", "AMD", "AVGO"]
START_CASH = 100.0
WEEK = ["2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20"]
COST_RATE = 0.001          # 0.10% of trade value, buy and sell
SELL_FEE = 0.01            # $0.01 regulatory fee per sell order
HALT_LEVEL = 85.0          # -15% of $100
STOP_PCT = 0.03
TARGET_PCT = 0.06
OUT_DIR = os.path.dirname(os.path.abspath(__file__))

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"}


def fetch_stooq(sym):
    url = f"https://stooq.com/q/d/l/?s={sym.lower()}.us&i=d"
    req = urllib.request.Request(url, headers=UA)
    text = urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "replace")
    if not text.startswith("Date,"):
        raise ValueError("Stooq did not return CSV (blocked/challenge page)")
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        if r["Date"] < "2026-01-01" or r["Date"] > "2026-11-20":
            continue
        rows.append({"date": r["Date"], "open": float(r["Open"]), "high": float(r["High"]),
                     "low": float(r["Low"]), "close": float(r["Close"]),
                     "volume": float(r["Volume"])})
    if len(rows) < 60:
        raise ValueError("Stooq returned too few rows")
    return rows


def fetch_yahoo(sym):
    p1 = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp())
    p2 = int(datetime(2026, 11, 21, tzinfo=timezone.utc).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
           f"?period1={p1}&period2={p2}&interval=1d&events=history")
    req = urllib.request.Request(url, headers=UA)
    data = json.loads(urllib.request.urlopen(req, timeout=25).read())
    res = data["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    rows = []
    for i, t in enumerate(ts):
        if None in (q["open"][i], q["high"][i], q["low"][i], q["close"][i]):
            continue
        d = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
        if d < "2026-01-01" or d > "2026-11-20":
            continue
        rows.append({"date": d, "open": q["open"][i], "high": q["high"][i],
                     "low": q["low"][i], "close": q["close"][i],
                     "volume": q["volume"][i] or 0})
    if len(rows) < 60:
        raise ValueError("Yahoo returned too few rows")
    return rows


def load_data():
    data, sources, dropped = {}, {}, []
    for sym in UNIVERSE:
        try:
            data[sym] = fetch_stooq(sym)
            sources[sym] = "Stooq daily CSV"
        except Exception:
            try:
                data[sym] = fetch_yahoo(sym)
                sources[sym] = "Yahoo Finance chart API"
            except Exception as e:
                dropped.append(f"{sym} ({e})")
    for sym in data:
        data[sym].sort(key=lambda r: r["date"])
    return data, sources, dropped


def index_by_date(rows):
    return {r["date"]: i for i, r in enumerate(rows)}


def compute_signals(data, idx, signal_date):
    """Evening signal scan using bars up to and including signal_date only."""
    out = []
    for sym, rows in data.items():
        i = idx[sym].get(signal_date)
        if i is None or i < 21:
            continue
        close = rows[i]["close"]
        gain_5d = close / rows[i - 5]["close"] - 1.0
        avg_vol_20 = sum(r["volume"] for r in rows[i - 20:i]) / 20.0
        vol_ratio = rows[i]["volume"] / avg_vol_20 if avg_vol_20 > 0 else 0.0
        prior_10_high = max(r["high"] for r in rows[i - 10:i])
        breakout = close >= prior_10_high
        day_gain = close / rows[i - 1]["close"] - 1.0
        momentum = day_gain > 0.02 and vol_ratio > 1.5
        if breakout or momentum:
            out.append({"ticker": sym, "gain_5d": gain_5d, "vol_ratio": vol_ratio,
                        "breakout": breakout, "momentum": momentum})
    out.sort(key=lambda s: (-s["gain_5d"], -s["vol_ratio"]))
    return out


def run():
    data, sources, dropped = load_data()
    if "SPY" not in data:
        raise SystemExit("SPY data unavailable - cannot run")
    idx = {s: index_by_date(r) for s, r in data.items()}
    spy_rows = data["SPY"]
    spy_idx = idx["SPY"]
    # Prior trading day (signal day) for Monday Nov 16:
    mon_i = spy_idx[WEEK[0]]
    prev_signal_date = spy_rows[mon_i - 1]["date"]

    cash = START_CASH
    positions = {}   # ticker -> {shares, entry_price, buy_total_cost}
    trades = []      # csv rows
    total_costs = 0.0
    round_trips = [] # pnl per closed position
    daily = []       # (date, closing equity)
    equity_hist = [START_CASH, START_CASH]  # pre-week closes: pot was all cash
    pending = compute_signals(data, idx, prev_signal_date)
    halt_pending = False
    halted = False
    notes = []

    def bar(sym, date):
        return data[sym][idx[sym][date]]

    def sell(date, sym, price, reason):
        nonlocal cash, total_costs
        pos = positions.pop(sym)
        proceeds = pos["shares"] * price
        cost = COST_RATE * proceeds + SELL_FEE
        cash += proceeds - cost
        total_costs += cost
        round_trips.append(proceeds - cost - pos["buy_total_cost"])
        trades.append({"date": date, "ticker": sym, "side": "SELL",
                       "price": round(price, 4), "shares": round(pos["shares"], 6),
                       "value": round(proceeds, 2), "reason": reason})

    for day in WEEK:
        if halted:
            daily.append((day, round(cash, 2)))
            equity_hist.append(cash)
            continue
        if halt_pending:
            # Liquidate everything at today's open, then stop for good.
            for sym in list(positions):
                sell(day, sym, bar(sym, day)["open"], "halt")
            halted = True
            notes.append(f"HALT: pot liquidated at the open on {day}; no further trades.")
            daily.append((day, round(cash, 2)))
            equity_hist.append(cash)
            continue

        # --- Entries at the open, from last evening's signals ---
        down_day_block = (equity_hist[-1] / equity_hist[-2] - 1.0) <= -0.04
        if pending and not down_day_block:
            equity_open = cash + sum(p["shares"] * bar(s, day)["open"]
                                     for s, p in positions.items())
            slots = 2 - len(positions)
            for sig in pending:
                if slots <= 0:
                    break
                sym = sig["ticker"]
                if sym in positions:
                    continue
                open_price = bar(sym, day)["open"]
                target_value = 0.50 * equity_open
                gross = min(target_value, cash / (1.0 + COST_RATE))
                if gross < 1.0:
                    continue
                shares = gross / open_price
                cost = COST_RATE * gross
                cash -= gross + cost
                total_costs += cost
                positions[sym] = {"shares": shares, "entry_price": open_price,
                                  "buy_total_cost": gross + cost}
                trades.append({"date": day, "ticker": sym, "side": "BUY",
                               "price": round(open_price, 4), "shares": round(shares, 6),
                               "value": round(gross, 2), "reason": "signal"})
                slots -= 1
        elif pending and down_day_block:
            notes.append(f"{day}: entries skipped - pot was down 4%+ from its prior close.")

        # --- Intraday exits (stop checked before target if both touched) ---
        for sym in list(positions):
            b = bar(sym, day)
            entry = positions[sym]["entry_price"]
            stop = entry * (1 - STOP_PCT)
            target = entry * (1 + TARGET_PCT)
            if b["low"] <= stop:
                sell(day, sym, stop, "stop")
            elif b["high"] >= target:
                sell(day, sym, target, "target")

        # --- Fade exit at the close: close below prior day's low ---
        for sym in list(positions):
            rows = data[sym]
            i = idx[sym][day]
            if rows[i]["close"] < rows[i - 1]["low"]:
                sell(day, sym, rows[i]["close"], "fade")

        # --- Closing equity ---
        equity = cash + sum(p["shares"] * bar(s, day)["close"]
                            for s, p in positions.items())
        daily.append((day, round(equity, 2)))
        equity_hist.append(equity)

        if equity <= HALT_LEVEL and not halt_pending:
            halt_pending = True
            notes.append(f"HALT TRIGGERED at the close on {day}: pot at ${equity:.2f} "
                         f"(<= $85). Liquidation is set for the next open.")
        # Evening: signals for tomorrow, from today's bars only.
        pending = compute_signals(data, idx, day)

    final = daily[-1][1]
    peak, max_dd = START_CASH, 0.0
    for _, eq in [(None, START_CASH)] + daily:
        peak = max(peak, eq)
        max_dd = min(max_dd, eq / peak - 1.0)
    wins = sum(1 for p in round_trips if p > 0)
    losses = sum(1 for p in round_trips if p <= 0)
    open_pos = {s: p["shares"] for s, p in positions.items()}

    # --- SPY benchmark: $100 in at Mon open, out at Fri close ---
    spy_open = bar("SPY", WEEK[0])["open"]
    spy_close = bar("SPY", WEEK[-1])["close"]
    bench_gross = START_CASH * spy_close / spy_open
    b_gross_val = START_CASH / (1.0 + COST_RATE)
    b_shares = b_gross_val / spy_open
    b_proceeds = b_shares * spy_close
    bench_net = b_proceeds - (COST_RATE * b_proceeds + SELL_FEE)

    # --- Trades CSV ---
    with open(os.path.join(OUT_DIR, "aggressive-trades.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "ticker", "side", "price",
                                          "shares", "value", "reason"])
        w.writeheader()
        w.writerows(trades)

    src_lines = "\n".join(f"- {s}: {sources[s]}" for s in sorted(sources))
    dropped_line = ("; ".join(dropped) if dropped else "none")
    daily_lines = "\n".join(f"| {d} | ${v:,.2f} |" for d, v in daily)
    note_lines = "\n".join(f"- {n}" for n in notes) if notes else "- none"
    open_line = (", ".join(f"{s} x {sh:.4f} shares (marked at Fri close, exit cost not charged)"
                           for s, sh in open_pos.items()) if open_pos else "none - pot ended in cash")

    md = f"""# Aggressive Sprint Pot - One-Week Backtest

**Week:** Monday 2026-11-16 to Friday 2026-11-20 (5 trading days)
**Start:** $100.00 cash. **Style:** Aggressive (Terry's rules, daily bars, no look-ahead -
every buy signal uses only bars up to the prior trading day's close).
**Universe:** {", ".join(UNIVERSE)}

## Result

| Day | Closing balance |
|---|---|
{daily_lines}

- **Final balance: ${final:,.2f}** ({(final / START_CASH - 1) * 100:+.2f}% on the week)
- **Orders:** {len(trades)} total ({sum(1 for t in trades if t['side'] == 'BUY')} buys, {sum(1 for t in trades if t['side'] == 'SELL')} sells); **closed positions:** {len(round_trips)} - **wins {wins}, losses {losses}**
- **Max drawdown (daily closes, incl. $100 start):** {max_dd * 100:.2f}%
- **Total costs paid:** ${total_costs:,.2f} (0.10% of value on every buy/sell + $0.01 per sell order)
- **Positions still open at Fri close:** {open_line}

## Benchmark - $100 of SPY, Mon open to Fri close

- Gross: **${bench_gross:,.2f}** ({(bench_gross / START_CASH - 1) * 100:+.2f}%)
- Net of the same costs: **${bench_net:,.2f}** ({(bench_net / START_CASH - 1) * 100:+.2f}%)
- Aggressive pot vs net SPY: **{"BEAT" if final > bench_net else "DID NOT BEAT"}** by ${abs(final - bench_net):,.2f}

## Events / notes

{note_lines}

## Data

Sources actually used:
{src_lines}
- Dropped symbols (data unobtainable): {dropped_line}
- Stooq's daily CSV endpoint was tried first for every symbol; it returned a
  bot-check HTML page instead of CSV, so the Yahoo Finance chart API supplied
  the bars. Yahoo chart prices are split-adjusted but NOT dividend-adjusted;
  no dividends are credited in this test (SPY paid no dividend inside this
  specific week in the data used, and the pot's names are marked on price only).
- Lead-in data from 2026-01-01 was used only for indicators (10-day highs,
  20-day volume averages, 5-day gains). Only the 5 test days were traded.

## What daily bars cannot capture (honest limits)

- **Intraday order of events is unknowable from a daily bar.** When a day's
  range touched both the -3% stop and the +6% target, this test always filled
  the stop first (the conservative choice). In live trading the real sequence
  could have been kinder - or worse.
- **The open print is assumed fillable** at the quoted open price for the
  pot's small size. Real fills can slip, especially in the first minutes.
- **No intraday signals:** gap-and-go moves, VWAP, and intraday momentum -
  core aggressive tactics - do not exist in daily bars. This test only
  captures the overnight-signal / next-open-entry skeleton of the style.
- **Costs are a flat model** (0.10% per side). Real spreads vary by name and
  minute; liquid names here usually cost less, stressed markets cost more.
- **One week is five days.** This is a smoke test of the machinery and the
  rules, not evidence the strategy makes money. A result either way would
  need the full walk-forward and paper-trial gates before it meant anything.
"""
    with open(os.path.join(OUT_DIR, "aggressive.md"), "w") as f:
        f.write(md)

    print(json.dumps({
        "final_balance": final,
        "return_pct": round((final / START_CASH - 1) * 100, 2),
        "orders": len(trades),
        "closed": len(round_trips), "wins": wins, "losses": losses,
        "max_drawdown_pct": round(max_dd * 100, 2),
        "total_costs": round(total_costs, 2),
        "bench_gross": round(bench_gross, 2), "bench_net": round(bench_net, 2),
        "beat_spy_net": final > bench_net,
        "daily": daily, "dropped": dropped,
        "sources": sources, "open_positions": list(open_pos),
    }, indent=2))


if __name__ == "__main__":
    run()
