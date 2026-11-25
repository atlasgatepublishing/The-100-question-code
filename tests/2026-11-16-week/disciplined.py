#!/usr/bin/env python3
"""
DISCIPLINED sprint pot - one-week backtest, test week Mon 2026-11-16 .. Fri 2026-11-20.

Simulation only. No broker orders of any kind (real or paper).

Rules (followed exactly):
  - $100 starting pot, daily OHLCV bars, fractional shares.
  - Signals computed ONLY from data through Friday 2026-11-13's close
    (pretend it is the morning of Mon Nov 16 - no look-ahead):
      (a) close above its 200-day moving average -> eligible
      (b) trailing 3-month (63 trading day) % return -> momentum rank
  - Pick the top 2 eligible assets by momentum, split the pot 50/50,
    buy at Monday Nov 16's open.
  - Hold all week. Exit early ONLY if:
      * an asset closes below its 200-day average -> sell it at next open, or
      * the pot's closing value falls to $85 (-15% floor) -> liquidate
        everything at next open and halt.
  - Otherwise sell everything at Friday Nov 20's close to score the week.
  - Costs: 0.10% of trade value on every buy and every sell, plus $0.01
    per sell order.

Data: free daily bars 2025-01-01..2026-11-20.
  Stooq daily CSV was tried first and is blocked by a JavaScript browser
  verification page (no CSV returned), so the Yahoo Finance chart API
  (query1.finance.yahoo.com/v8/finance/chart) is used for all symbols.
  Raw bars are cached as CSV in ./data/ next to this script.
"""

import csv
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
SYMBOLS = ["SPY", "QQQ", "IWM", "GLD", "TLT"]

START_CASH = 100.0
FLOOR = 85.0               # -15% floor on the $100 pot
COST_RATE = 0.001          # 0.10% of trade value, buys and sells
SELL_FEE = 0.01            # $0.01 per sell order
MA_DAYS = 200
MOM_DAYS = 63              # 3 months of trading days

SIGNAL_DATE = "2026-11-13"  # Friday close - last data allowed for decisions
WEEK = ["2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20"]


# ---------------------------------------------------------------- data fetch
def fetch_yahoo(symbol):
    p1 = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp())
    p2 = int(datetime(2026, 11, 21, tzinfo=timezone.utc).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?period1={p1}&period2={p2}&interval=1d")
    out = subprocess.run(
        ["curl", "-s", "-m", "60", "-A", "Mozilla/5.0 (X11; Linux x86_64)",
         url], capture_output=True, text=True)
    payload = json.loads(out.stdout)
    result = payload["chart"]["result"][0]
    q = result["indicators"]["quote"][0]
    rows = []
    for ts, o, h, l, c, v in zip(result["timestamp"], q["open"], q["high"],
                                 q["low"], q["close"], q["volume"]):
        if None in (o, h, l, c):
            continue
        d = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        rows.append({"date": d, "open": o, "high": h, "low": l,
                     "close": c, "volume": v or 0})
    rows.sort(key=lambda r: r["date"])
    return rows


def load_data():
    os.makedirs(DATA_DIR, exist_ok=True)
    data, sources = {}, {}
    for sym in SYMBOLS:
        cache = os.path.join(DATA_DIR, f"{sym}.csv")
        if os.path.exists(cache):
            with open(cache) as f:
                rows = [{"date": r["date"], "open": float(r["open"]),
                         "high": float(r["high"]), "low": float(r["low"]),
                         "close": float(r["close"]),
                         "volume": int(float(r["volume"]))}
                        for r in csv.DictReader(f)]
            sources[sym] = "cache (Yahoo Finance chart API)"
        else:
            try:
                rows = fetch_yahoo(sym)
                sources[sym] = "Yahoo Finance chart API"
            except Exception as e:  # symbol dropped, reported in the writeup
                print(f"WARNING: could not fetch {sym}: {e}", file=sys.stderr)
                continue
            with open(cache, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=["date", "open", "high",
                                                  "low", "close", "volume"])
                w.writeheader()
                w.writerows(rows)
        data[sym] = rows
    return data, sources


# ------------------------------------------------------------------- helpers
def idx_on_or_before(rows, date):
    idx = None
    for i, r in enumerate(rows):
        if r["date"] <= date:
            idx = i
        else:
            break
    return idx


def bar_on(rows, date):
    for r in rows:
        if r["date"] == date:
            return r
    return None


def ma200(rows, i):
    return sum(r["close"] for r in rows[i - MA_DAYS + 1: i + 1]) / MA_DAYS


# ---------------------------------------------------------------------- main
def main():
    data, sources = load_data()
    trades = []          # date, ticker, side, price, shares, value, reason
    total_costs = 0.0

    # ---- signals as of Friday 2026-11-13 close (no data after this date)
    signals = {}
    for sym, rows in data.items():
        i = idx_on_or_before(rows, SIGNAL_DATE)
        close = rows[i]["close"]
        ma = ma200(rows, i)
        mom = close / rows[i - MOM_DAYS]["close"] - 1.0
        signals[sym] = {"date": rows[i]["date"], "close": close, "ma": ma,
                        "above": close > ma, "mom": mom}

    eligible = [s for s in signals if signals[s]["above"]]
    eligible.sort(key=lambda s: signals[s]["mom"], reverse=True)
    picks = eligible[:2]

    # ---- Monday Nov 16: buy picks at the open, 50% of pot each
    cash = START_CASH
    positions = {}       # sym -> shares
    for sym in picks:
        bar = bar_on(data[sym], WEEK[0])
        alloc = START_CASH * 0.50
        gross = alloc / (1 + COST_RATE)      # buy cost comes out of the sleeve
        cost = gross * COST_RATE
        shares = gross / bar["open"]
        positions[sym] = shares
        cash -= gross + cost
        total_costs += cost
        trades.append({"date": WEEK[0], "ticker": sym, "side": "buy",
                       "price": bar["open"], "shares": shares, "value": gross,
                       "reason": "initial buy - top-2 momentum, above 200-day MA"})

    def pot_value(date):
        v = cash
        for sym, sh in positions.items():
            v += sh * bar_on(data[sym], date)["close"]
        return v

    def sell(sym, date, price, reason):
        nonlocal cash, total_costs
        sh = positions.pop(sym)
        gross = sh * price
        cost = gross * COST_RATE + SELL_FEE
        cash += gross - cost
        total_costs += cost
        trades.append({"date": date, "ticker": sym, "side": "sell",
                       "price": price, "shares": sh, "value": gross,
                       "reason": reason})

    # ---- walk the week
    daily = []
    halted = False
    for di, date in enumerate(WEEK):
        last_day = di == len(WEEK) - 1
        value = pot_value(date)
        daily.append((date, value if not (last_day and not halted) else None))

        if last_day:
            break

        nxt = WEEK[di + 1]
        # floor check at this close -> liquidate everything at next open
        if value <= FLOOR and positions:
            for sym in list(positions):
                sell(sym, nxt, bar_on(data[sym], nxt)["open"],
                     "exit - pot closing value hit $85 (-15% floor), halt")
            halted = True
            # remaining days are all cash
            for rest in WEEK[di + 1:]:
                daily.append((rest, cash))
            break

        # per-asset trend check at this close -> sell that asset at next open
        for sym in list(positions):
            rows = data[sym]
            i = idx_on_or_before(rows, date)
            if rows[i]["close"] < ma200(rows, i):
                sell(sym, nxt, bar_on(data[sym], nxt)["open"],
                     "exit - closed below its 200-day moving average")

    # ---- Friday Nov 20: liquidate anything left at the close, score the week
    if not halted:
        for sym in list(positions):
            sell(sym, WEEK[-1], bar_on(data[sym], WEEK[-1])["close"],
                 "final liquidation - end of test week")
        daily[-1] = (WEEK[-1], cash)

    final_balance = cash
    balances = [START_CASH] + [v for _, v in daily]
    peak, max_dd = balances[0], 0.0
    for v in balances:
        peak = max(peak, v)
        max_dd = max(max_dd, (peak - v) / peak)

    # ---- benchmark: $100 into SPY, Mon open -> Fri close
    spy = data["SPY"]
    o = bar_on(spy, WEEK[0])["open"]
    c = bar_on(spy, WEEK[-1])["close"]
    bench_gross = START_CASH * c / o
    b_gross_buy = START_CASH / (1 + COST_RATE)
    b_shares = b_gross_buy / o
    bench_net = b_shares * c * (1 - COST_RATE) - SELL_FEE
    bench_costs = START_CASH - b_gross_buy + b_shares * c * COST_RATE + SELL_FEE

    # ---- trades CSV
    trades_path = os.path.join(HERE, "disciplined-trades.csv")
    with open(trades_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "ticker", "side", "price",
                                          "shares", "value", "reason"])
        w.writeheader()
        for t in trades:
            w.writerow({**t, "price": f"{t['price']:.4f}",
                        "shares": f"{t['shares']:.6f}",
                        "value": f"{t['value']:.2f}"})

    # ---- report
    ret = final_balance / START_CASH - 1.0
    lines = []
    lines.append("# DISCIPLINED Sprint Pot - One-Week Backtest")
    lines.append("")
    lines.append(f"Test week: Monday 2026-11-16 through Friday 2026-11-20. "
                 f"Starting pot: $100.00. Simulation only - no broker orders.")
    lines.append("")
    lines.append("Data source: Stooq daily CSV was tried first and returned a "
                 "JavaScript browser-verification page instead of data, so all "
                 "bars came from the free Yahoo Finance chart API "
                 "(2025-01-01 through 2026-11-20, cached in ./data/). "
                 "Symbols used: " + ", ".join(sorted(data.keys())) + ".")
    dropped = [s for s in SYMBOLS if s not in data]
    if dropped:
        lines.append(f"Symbols dropped (data unavailable): {', '.join(dropped)}.")
    lines.append("")
    lines.append(f"## Signals as of Friday 2026-11-13 close (the only data the "
                 f"pot was allowed to see before Monday's open)")
    lines.append("")
    lines.append("| Asset | Close | 200-day MA | Above MA? | 3-month (63d) momentum |")
    lines.append("|---|---|---|---|---|")
    for sym in sorted(signals, key=lambda s: signals[s]["mom"], reverse=True):
        s = signals[sym]
        lines.append(f"| {sym} | ${s['close']:.2f} | ${s['ma']:.2f} | "
                     f"{'YES' if s['above'] else 'no'} | {s['mom'] * 100:+.2f}% |")
    lines.append("")
    if picks:
        why = "; ".join(
            f"{p} ({signals[p]['mom'] * 100:+.2f}% momentum, close "
            f"${signals[p]['close']:.2f} above its 200-day MA "
            f"${signals[p]['ma']:.2f})" for p in picks)
        lines.append(f"**Picked:** {why}. The pot split 50/50 across the top "
                     f"{len(picks)} eligible asset(s) by 3-month momentum and "
                     f"bought at Monday Nov 16's open, fractional shares.")
        if len(picks) == 1:
            lines.append(f"Only one asset was eligible, so only its $50 half "
                         f"was invested; the other $50 stayed in cash all week. "
                         f"That cash cushion is the trend filter doing its job "
                         f"in a falling market, not a bug.")
    else:
        lines.append("**Picked:** nothing - no asset was above its 200-day "
                     "average, so the pot stayed in cash all week.")
    inelig = [s for s in signals if not signals[s]["above"]]
    if inelig:
        lines.append(f"**Not eligible** (below their 200-day averages): "
                     + ", ".join(inelig) + ".")
    lines.append("")
    lines.append("## Trades")
    lines.append("")
    if trades:
        lines.append("| Date | Ticker | Side | Price | Shares | Value | Reason |")
        lines.append("|---|---|---|---|---|---|---|")
        for t in trades:
            lines.append(f"| {t['date']} | {t['ticker']} | {t['side']} | "
                         f"${t['price']:.2f} | {t['shares']:.4f} | "
                         f"${t['value']:.2f} | {t['reason']} |")
    else:
        lines.append("No trades - the pot held cash all week.")
    lines.append("")
    lines.append("## Daily closing balances")
    lines.append("")
    lines.append("| Day | Closing balance |")
    lines.append("|---|---|")
    lines.append(f"| Start (Fri Nov 13) | ${START_CASH:.2f} |")
    names = {"2026-11-16": "Mon Nov 16", "2026-11-17": "Tue Nov 17",
             "2026-11-18": "Wed Nov 18", "2026-11-19": "Thu Nov 19",
             "2026-11-20": "Fri Nov 20"}
    final_liq = any(t["side"] == "sell" and t["date"] == WEEK[-1]
                    and t["reason"].startswith("final liquidation")
                    for t in trades)
    for date, v in daily:
        note = ""
        if date == WEEK[-1]:
            note = (" (after final liquidation, net of all costs)" if final_liq
                    else " (all cash - position already exited earlier in the week)")
        lines.append(f"| {names[date]} | ${v:.2f}{note} |")
    lines.append("")
    lines.append("## Scorecard")
    lines.append("")
    lines.append(f"- Final balance: **${final_balance:.2f}**")
    lines.append(f"- Week return: **{ret * 100:+.2f}%**")
    lines.append(f"- Max drawdown (daily closes, incl. start): **{max_dd * 100:.2f}%**")
    lines.append(f"- Total costs paid: **${total_costs:.2f}** "
                 f"(0.10% of trade value on every buy/sell + $0.01 per sell order)")
    lines.append(f"- -15% floor ($85) hit? **{'YES - pot halted' if halted else 'No'}**")
    lines.append("")
    lines.append("## Benchmark - $100 into SPY, Mon open to Fri close")
    lines.append("")
    lines.append(f"- SPY: bought at Mon open ${o:.2f}, Fri close ${c:.2f}.")
    lines.append(f"- Gross (no costs): **${bench_gross:.2f}** "
                 f"({(bench_gross / START_CASH - 1) * 100:+.2f}%)")
    lines.append(f"- Net of the same costs (${bench_costs:.2f}): "
                 f"**${bench_net:.2f}** ({(bench_net / START_CASH - 1) * 100:+.2f}%)")
    verdict = ("beat" if final_balance > bench_net else
               "trailed" if final_balance < bench_net else "matched")
    lines.append(f"- The DISCIPLINED pot **{verdict}** the SPY benchmark this week "
                 f"(${final_balance:.2f} vs ${bench_net:.2f} net).")
    lines.append("")
    lines.append("## Honest note - what one week can and cannot show")
    lines.append("")
    lines.append("This strategy is built to be slow: a 200-day trend filter and "
                 "3-month momentum change their minds over months, not days. In a "
                 "single week it is essentially a buy-and-hold of whichever two "
                 "assets were already trending, so this week mostly measures what "
                 "those two assets happened to do Mon-Fri - luck of the calendar, "
                 "not skill. It CAN show the machinery works: signals computed "
                 "with no look-ahead, fills at real opens/closes, costs charged, "
                 "the -15% floor and trend exits wired up. It CANNOT show whether "
                 "the strategy makes money - that verdict needs the full gates "
                 "from the design (walk-forward out-of-sample testing, an "
                 "untouched holdout, 2x cost stress, and a 60-90 day frozen "
                 "paper trial). One week, win or lose, is an anecdote, and the "
                 "scoreboard treats it as one.")
    lines.append("")

    md_path = os.path.join(HERE, "disciplined.md")
    with open(md_path, "w") as f:
        f.write("\n".join(lines))

    print(f"Picks: {picks}")
    print(f"Final balance: ${final_balance:.2f} ({ret * 100:+.2f}%)")
    print(f"Max drawdown: {max_dd * 100:.2f}%  Total costs: ${total_costs:.2f}")
    print(f"SPY benchmark net: ${bench_net:.2f}  gross: ${bench_gross:.2f}")
    print(f"Wrote {trades_path} and {md_path}")


if __name__ == "__main__":
    main()
