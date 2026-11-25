#!/usr/bin/env python3
"""
AGGRESSIVE sprint pot - ONE-YEAR backtest (simulation only, no broker orders).

Period: $100 start; first trading day on/after 2025-11-21 through 2026-11-20.
Rules (identical to the one-week test, extended with Terry's profit-ladder floor):
  - Each evening rank universe by prior 5-day % gain and prior-day volume vs 20-day avg.
  - Qualifies if: closed at/above prior 10-day high (breakout) OR gained >2% that day
    on volume >1.5x its 20-day average.
  - Buy at next day's open, top 1-2 qualifiers, up to 50% of pot each, max 2 positions,
    fractional shares. No qualifier = hold cash.
  - Exits (daily, high/low; stop fills first if both touched same day):
    hard stop -3% from entry; profit exit +6% from entry; exit at close if the name
    closes below the prior day's low.
  - Costs: 0.10% of trade value on every buy and sell + $0.01 per sell order.
  - No new entries on a day following a day the pot fell 4%+.
  - Floor: starts $85; closing value >= $125 -> floor $100; >= $150 -> floor $125.
    A close at/below the floor -> liquidate all at next open, run ENDS.
  - If the run reaches 2026-11-20, liquidate at that close.
Data: free Yahoo Finance chart API daily OHLCV (split-adjusted, NOT dividend-adjusted).
"""
import csv, json, os, subprocess, sys
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
os.makedirs(DATA, exist_ok=True)
UNIVERSE = ["SPY", "QQQ", "NVDA", "TSLA", "AAPL", "MSFT", "AMZN", "META", "AMD", "AVGO"]
FETCH_START = "2024-06-01"
PERIOD_START = "2025-11-21"
PERIOD_END = "2026-11-20"
START_CASH = 100.0
COST_RATE = 0.001
SELL_FEE = 0.01

def fetch(sym):
    path = os.path.join(DATA, f"{sym}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    p1 = int(datetime(2024, 6, 1, tzinfo=timezone.utc).timestamp())
    p2 = int(datetime(2026, 11, 22, tzinfo=timezone.utc).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
           f"?period1={p1}&period2={p2}&interval=1d")
    out = subprocess.run(["curl", "-s", "-A", "Mozilla/5.0", url],
                         capture_output=True, text=True)
    data = json.loads(out.stdout)
    with open(path, "w") as f:
        json.dump(data, f)
    return data

def bars(sym):
    res = fetch(sym)["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    rows = []
    for i, t in enumerate(ts):
        if q["close"][i] is None or q["open"][i] is None:
            continue
        d = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
        rows.append({"date": d, "open": q["open"][i], "high": q["high"][i],
                     "low": q["low"][i], "close": q["close"][i],
                     "volume": q["volume"][i] or 0})
    return rows

def main():
    data = {s: bars(s) for s in UNIVERSE}
    # Trading calendar from SPY
    spy = data["SPY"]
    cal = [r["date"] for r in spy if PERIOD_START <= r["date"] <= PERIOD_END]
    start_date, end_date = cal[0], cal[-1]
    idx = {s: {r["date"]: i for i, r in enumerate(data[s])} for s in UNIVERSE}

    def bar(s, date):
        i = idx[s].get(date)
        return data[s][i] if i is not None else None

    def prev_bar(s, date):
        i = idx[s].get(date)
        return data[s][i - 1] if i is not None and i > 0 else None

    cash = START_CASH
    positions = {}   # sym -> {shares, entry_price, entry_date, cost_in}
    trades = []      # csv rows
    round_trips = [] # {sym, pnl}
    equity_curve = []  # (date, equity)
    floor = 85.0
    total_costs = 0.0
    halted = None    # (trigger_date, liquidation_date, final_balance)
    prev_equity = START_CASH
    no_entry_today = False
    days_invested = 0
    days_cash = 0

    def equity_at_close(date):
        eq = cash
        for s, p in positions.items():
            b = bar(s, date)
            if b:
                eq += p["shares"] * b["close"]
        return eq

    def sell(sym, date, price, reason):
        nonlocal cash, total_costs
        p = positions.pop(sym)
        gross = p["shares"] * price
        cost = gross * COST_RATE + SELL_FEE
        total_costs += cost
        cash += gross - cost
        pnl = (gross - cost) - p["cost_in"]
        round_trips.append({"sym": sym, "pnl": pnl})
        trades.append([date, sym, "SELL", f"{price:.4f}", f"{p['shares']:.6f}",
                       f"{gross:.2f}", reason])

    for di, date in enumerate(cal):
        last_day = (date == end_date)
        # ---- entries at open (signals from prior evening) ----
        if di > 0 or True:
            # signals computed from the previous trading day on the calendar
            # (for the first day, the trading day just before the period start)
            if di == 0:
                prev_date = None
                # find SPY bar just before start_date
                for r in spy:
                    if r["date"] < start_date:
                        prev_date = r["date"]
            else:
                prev_date = cal[di - 1]
            if prev_date and not no_entry_today and len(positions) < 2:
                quals = []
                for s in UNIVERSE:
                    if s in positions:
                        continue
                    i = idx[s].get(prev_date)
                    if i is None or i < 20:
                        continue
                    rows = data[s]
                    b = rows[i]
                    prior10_high = max(r["high"] for r in rows[i - 10:i])
                    gain5 = (b["close"] / rows[i - 5]["close"] - 1) * 100
                    day_gain = (b["close"] / rows[i - 1]["close"] - 1) * 100
                    vol20 = sum(r["volume"] for r in rows[i - 20:i]) / 20
                    vol_ratio = (b["volume"] / vol20) if vol20 else 0
                    breakout = b["close"] >= prior10_high
                    momentum = day_gain > 2.0 and vol_ratio > 1.5
                    if breakout or momentum:
                        quals.append((s, gain5, vol_ratio))
                quals.sort(key=lambda x: (-x[1], -x[2]))
                slots = 2 - len(positions)
                eq_prev = prev_equity
                for s, g5, vr in quals[:slots]:
                    b = bar(s, date)
                    if b is None:
                        continue
                    alloc = min(0.50 * eq_prev, cash)
                    if alloc < 1.0:
                        break
                    price = b["open"]
                    shares = alloc / (price * (1 + COST_RATE))
                    cost_in = shares * price * (1 + COST_RATE)
                    total_costs += shares * price * COST_RATE
                    cash -= cost_in
                    positions[s] = {"shares": shares, "entry_price": price,
                                    "entry_date": date, "cost_in": cost_in}
                    trades.append([date, s, "BUY", f"{price:.4f}",
                                   f"{shares:.6f}", f"{shares*price:.2f}",
                                   "signal: " + ("breakout/momentum")])
        # ---- intraday + close exits ----
        for s in list(positions.keys()):
            b = bar(s, date)
            if b is None:
                continue
            p = positions[s]
            stop = p["entry_price"] * 0.97
            target = p["entry_price"] * 1.06
            hit_stop = b["low"] <= stop
            hit_target = b["high"] >= target
            if hit_stop:
                fill = b["open"] if b["open"] < stop else stop
                sell(s, date, fill, "stop -3%")
            elif hit_target:
                fill = b["open"] if b["open"] > target else target
                sell(s, date, fill, "target +6%")
            else:
                pb = prev_bar(s, date)
                if pb and b["close"] < pb["low"]:
                    sell(s, date, b["close"], "close below prior day low")
        # ---- end of day ----
        eq = equity_at_close(date)
        equity_curve.append((date, eq))
        if positions:
            days_invested += 1
        else:
            days_cash += 1
        # ladder (floor only rises)
        if eq >= 150:
            floor = max(floor, 125.0)
        elif eq >= 125:
            floor = max(floor, 100.0)
        # floor breach -> liquidate at next open, run ends
        if eq <= floor and not last_day:
            nxt = cal[di + 1]
            for s in list(positions.keys()):
                nb = bar(s, nxt)
                if nb:
                    sell(s, nxt, nb["open"], "FLOOR breach liquidation")
            halted = (date, nxt, cash)
            equity_curve.append((nxt, cash))
            break
        # daily -4% rule for tomorrow
        if prev_equity > 0 and (eq / prev_equity - 1) <= -0.04:
            no_entry_today = True
        else:
            no_entry_today = False
        prev_equity = eq
        # final day liquidation at close
        if last_day:
            for s in list(positions.keys()):
                b = bar(s, date)
                if b:
                    sell(s, date, b["close"], "end of period liquidation")
            equity_curve[-1] = (date, cash)

    final_balance = cash
    if halted:
        final_balance = halted[2]

    # ---- benchmark: SPY buy & hold ----
    spy_open = bar("SPY", start_date)["open"]
    spy_close = bar("SPY", end_date)["close"]
    bench_gross = START_CASH / spy_open * spy_close
    sh = START_CASH / (spy_open * (1 + COST_RATE))
    bench_net = sh * spy_close * (1 - COST_RATE) - SELL_FEE

    # ---- stats ----
    wins = [r["pnl"] for r in round_trips if r["pnl"] > 0]
    losses = [r["pnl"] for r in round_trips if r["pnl"] <= 0]
    peak, max_dd = START_CASH, 0.0
    for d, e in equity_curve:
        peak = max(peak, e)
        max_dd = max(max_dd, (peak - e) / peak * 100)
    monthly = {}
    for d, e in equity_curve:
        monthly[d[:7]] = e  # last recorded value in the month wins (curve is ordered)
    total_days = days_invested + days_cash

    with open(os.path.join(BASE, "aggressive-year-trades.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "ticker", "side", "price", "shares", "value", "reason"])
        w.writerows(trades)

    ret_pct = (final_balance / START_CASH - 1) * 100
    stats = {
        "start_date": start_date, "end_date": end_date,
        "final_balance": round(final_balance, 2), "return_pct": round(ret_pct, 2),
        "halted": halted, "total_orders": len(trades),
        "round_trips": len(round_trips), "wins": len(wins), "losses": len(losses),
        "win_rate": round(len(wins) / len(round_trips) * 100, 1) if round_trips else 0,
        "avg_win": round(sum(wins) / len(wins), 2) if wins else 0,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0,
        "biggest_win": round(max(wins), 2) if wins else 0,
        "biggest_loss": round(min(losses), 2) if losses else 0,
        "max_drawdown_pct": round(max_dd, 2),
        "total_costs": round(total_costs, 2),
        "days_invested": days_invested, "days_cash": days_cash,
        "bench_gross": round(bench_gross, 2), "bench_net": round(bench_net, 2),
        "bench_gross_pct": round((bench_gross / START_CASH - 1) * 100, 2),
        "bench_net_pct": round((bench_net / START_CASH - 1) * 100, 2),
        "final_floor": floor,
    }
    with open(os.path.join(BASE, "aggressive-year-stats.json"), "w") as f:
        json.dump({"stats": stats, "monthly": monthly,
                   "equity_curve": equity_curve}, f, indent=1)
    print(json.dumps(stats, indent=1, default=str))
    print("MONTHLY:", json.dumps(monthly, indent=1))

if __name__ == "__main__":
    main()
