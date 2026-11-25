#!/usr/bin/env python3
"""
One-year backtest of the DISCIPLINED sprint pot for Terry's AI stock app.
Simulation only - no broker orders.

Period: first trading day on/after 2025-11-21 through 2026-11-20.
Universe: SPY, QQQ, IWM, GLD, TLT. Daily OHLCV from the free Yahoo Finance
chart API (split-adjusted, NOT dividend-adjusted).

Rules:
- Monthly selection (start + first trading day of each month), using data
  through the prior trading day's close: eligible = close above 200-day MA.
  Rank eligible by trailing 63-trading-day % return. Hold top 2 at 50/50 of
  pot equity; 1 eligible -> 50% in, 50% cash; 0 eligible -> all cash.
  Rebalance at the selection day's open.
- Trend exit: a held asset closing below its 200-day MA is sold at the next
  open; that cash waits for the next monthly selection.
- Costs: 0.10% of trade value on every buy and sell, + $0.01 per sell order.
- Floor ladder: floor starts at $85. Closing value >= $125 -> floor $100;
  >= $150 -> floor $125. A close at/below the current floor liquidates
  everything at the next open and ENDS the run.
- If it survives, liquidate at the 2026-11-20 close to score.
"""
import csv, json, os, sys, time, urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
os.makedirs(DATA_DIR, exist_ok=True)

TICKERS = ["SPY", "QQQ", "IWM", "GLD", "TLT"]
START = "2025-11-21"
END = "2026-11-20"
FETCH_FROM = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp())
FETCH_TO = int(datetime(2026, 11, 22, tzinfo=timezone.utc).timestamp())
COST_RATE = 0.001
SELL_FEE = 0.01
ET = ZoneInfo("America/New_York")


def fetch(ticker):
    cache = os.path.join(DATA_DIR, f"{ticker}.csv")
    if os.path.exists(cache):
        rows = []
        with open(cache) as f:
            for r in csv.DictReader(f):
                rows.append({k: (r[k] if k == "date" else float(r[k]))
                             for k in r})
        return rows
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={FETCH_FROM}&period2={FETCH_TO}&interval=1d&events=history")
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode())
    except Exception:
        url = url.replace("query1", "query2")
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode())
    result = payload["chart"]["result"][0]
    ts = result["timestamp"]
    q = result["indicators"]["quote"][0]
    rows = []
    for i, t in enumerate(ts):
        vals = [q[k][i] for k in ("open", "high", "low", "close")]
        if any(v is None for v in vals):
            continue
        d = datetime.fromtimestamp(t, tz=ET).strftime("%Y-%m-%d")
        rows.append({"date": d, "open": vals[0], "high": vals[1],
                     "low": vals[2], "close": vals[3],
                     "volume": q["volume"][i] or 0})
    rows.sort(key=lambda r: r["date"])
    with open(cache, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "open", "high", "low",
                                          "close", "volume"])
        w.writeheader()
        w.writerows(rows)
    time.sleep(0.3)
    return rows


def main():
    bars = {t: fetch(t) for t in TICKERS}
    by_date = {t: {r["date"]: r for r in rows} for t, rows in bars.items()}
    closes = {t: [r["close"] for r in rows] for t, rows in bars.items()}
    dates_all = [r["date"] for r in bars["SPY"]]
    idx_of = {t: {r["date"]: i for i, r in enumerate(rows)}
              for t, rows in bars.items()}

    def ma200(t, date):
        i = idx_of[t][date]
        if i < 199:
            return None
        return sum(closes[t][i - 199:i + 1]) / 200.0

    def mom63(t, date):
        i = idx_of[t][date]
        if i < 63:
            return None
        return closes[t][i] / closes[t][i - 63] - 1.0

    period = [d for d in dates_all if START <= d <= END]
    assert period, "no trading days in period"
    first_day, last_day = period[0], period[-1]
    prior_day = {d: dates_all[dates_all.index(d) - 1] for d in period}

    selection_days = set()
    seen_months = set()
    for d in period:
        ym = d[:7]
        if d == first_day or ym not in seen_months:
            selection_days.add(d)
        seen_months.add(ym)

    cash = 100.0
    shares = {t: 0.0 for t in TICKERS}
    trades = []
    total_costs = 0.0
    floor = 85.0
    pending_exits = set()
    liquidate_next_open = False
    halt_trigger_date = None
    halted = False
    final_balance = None
    selections = []
    daily = []          # (date, close_equity, n_positions)
    last_ref = None     # last reference (prior) day used for trend checks

    def equity(price_map):
        return cash + sum(shares[t] * price_map[t] for t in TICKERS)

    def do_sell(t, date, price, reason, n=None):
        nonlocal cash, total_costs
        n = shares[t] if n is None else min(n, shares[t])
        if n <= 1e-12 or price <= 0:
            return
        value = n * price
        cost = value * COST_RATE + SELL_FEE
        cash += value - cost
        total_costs += cost
        shares[t] -= n
        trades.append({"date": date, "ticker": t, "side": "sell",
                       "price": round(price, 4), "shares": round(n, 6),
                       "value": round(value, 2), "reason": reason})

    def do_buy(t, date, price, value, reason):
        nonlocal cash, total_costs
        if value <= 0.005 or price <= 0:
            return
        cost = value * COST_RATE
        if value + cost > cash + 1e-9:
            value = cash / (1 + COST_RATE)
            cost = value * COST_RATE
        n = value / price
        cash -= value + cost
        total_costs += cost
        shares[t] += n
        trades.append({"date": date, "ticker": t, "side": "buy",
                       "price": round(price, 4), "shares": round(n, 6),
                       "value": round(value, 2), "reason": reason})

    for d in period:
        opens = {t: by_date[t][d]["open"] for t in TICKERS}
        closes_today = {t: by_date[t][d]["close"] for t in TICKERS}

        # 1) floor liquidation at the open ends the run
        if liquidate_next_open:
            for t in TICKERS:
                if shares[t] > 0:
                    do_sell(t, d, opens[t], "floor-liquidation")
            halted = True
            final_balance = cash
            daily.append((d, cash, 0))
            break

        # 2) scheduled trend exits at the open
        for t in sorted(pending_exits):
            if shares[t] > 0:
                do_sell(t, d, opens[t], "trend-exit")
        pending_exits = set()

        # 3) monthly selection / rebalance at the open
        if d in selection_days:
            ref = prior_day[d]
            last_ref = ref
            info = {}
            for t in TICKERS:
                ma = ma200(t, ref)
                c = by_date[t][ref]["close"]
                info[t] = {"close": c, "ma200": ma,
                           "eligible": (ma is not None and c > ma),
                           "mom63": mom63(t, ref)}
            eligible = [t for t in TICKERS if info[t]["eligible"]]
            eligible.sort(key=lambda t: info[t]["mom63"], reverse=True)
            picks = eligible[:2]
            selections.append({"date": d, "ref": ref, "info": info,
                               "picks": picks})
            eq_open = equity(opens)
            targets = {t: 0.5 * eq_open for t in picks}
            # sells first: dropouts and trims
            for t in TICKERS:
                if shares[t] <= 0:
                    continue
                cur = shares[t] * opens[t]
                tgt = targets.get(t, 0.0)
                if cur > tgt + 0.005:
                    reason = ("monthly-sell-dropout" if t not in targets
                              else "monthly-rebalance-trim")
                    do_sell(t, d, opens[t], reason, (cur - tgt) / opens[t])
            # buys: entrants and adds, scaled to available cash
            wants = {}
            for t in picks:
                cur = shares[t] * opens[t]
                if targets[t] > cur + 0.005:
                    wants[t] = targets[t] - cur
            total_want_cost = sum(v * (1 + COST_RATE) for v in wants.values())
            scale = 1.0
            if total_want_cost > cash and total_want_cost > 0:
                scale = max(cash, 0.0) / total_want_cost
            for t in picks:
                if t in wants:
                    reason = ("monthly-buy" if by_date and shares[t] == 0
                              else "monthly-rebalance-add")
                    do_buy(t, d, opens[t], wants[t] * scale, reason)

        # positions held during the day (after open trades)
        n_pos = sum(1 for t in TICKERS if shares[t] > 1e-9)
        eq_close = equity(closes_today)
        daily.append((d, eq_close, n_pos))

        # 4) floor ladder + breach check at the close
        if eq_close >= 150.0:
            floor = max(floor, 125.0)
        elif eq_close >= 125.0:
            floor = max(floor, 100.0)
        if eq_close <= floor:
            if d == last_day:
                for t in TICKERS:
                    if shares[t] > 0:
                        do_sell(t, d, closes_today[t], "floor-liquidation")
                halted = True
                halt_trigger_date = d
                final_balance = cash
            else:
                liquidate_next_open = True
                halt_trigger_date = d
            daily[-1] = (d, eq_close, n_pos)
            if halted:
                break
            continue

        # 5) trend-exit check at the close
        for t in TICKERS:
            if shares[t] > 1e-9:
                ma = ma200(t, d)
                if ma is not None and closes_today[t] < ma:
                    pending_exits.add(t)

    if not halted:
        # survived: liquidate at the final close to score
        closes_last = {t: by_date[t][last_day]["close"] for t in TICKERS}
        for t in TICKERS:
            if shares[t] > 0:
                do_sell(t, last_day, closes_last[t], "final-liquidation")
        final_balance = cash

    # ---- stats ----
    peak, max_dd = 100.0, 0.0
    peak_date, trough_date, run_peak_date = START, None, START
    for dte, eq, _ in daily:
        if eq > peak:
            peak, run_peak_date = eq, dte
        dd = (peak - eq) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd, peak_date, trough_date = dd, run_peak_date, dte
    n_days = len(daily)
    full = sum(1 for _, _, n in daily if n == 2)
    half = sum(1 for _, _, n in daily if n == 1)
    zero = sum(1 for _, _, n in daily if n == 0)

    spy_open = by_date["SPY"][first_day]["open"]
    spy_close = by_date["SPY"][END]["close"]
    bench_gross = 100.0 / spy_open * spy_close
    b_shares = 100.0 / (spy_open * (1 + COST_RATE))
    bench_net = b_shares * spy_close * (1 - COST_RATE) - SELL_FEE

    month_end = {}
    for d, eq, _ in daily:
        month_end[d[:7]] = (d, eq)

    ret = final_balance / 100.0 - 1.0
    out = {
        "first_day": first_day, "last_day": last_day,
        "halted": halted, "halt_trigger_date": halt_trigger_date,
        "final_balance": round(final_balance, 2), "return_pct": round(ret * 100, 2),
        "total_trades": len(trades), "total_costs": round(total_costs, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "dd_peak_date": peak_date, "dd_trough_date": trough_date,
        "peak_close_equity": round(peak, 2),
        "final_floor": floor,
        "days": n_days, "pct_full": round(100 * full / n_days, 1),
        "pct_half": round(100 * half / n_days, 1),
        "pct_cash": round(100 * zero / n_days, 1),
        "bench_gross": round(bench_gross, 2), "bench_net": round(bench_net, 2),
        "bench_gross_pct": round((bench_gross / 100 - 1) * 100, 2),
        "bench_net_pct": round((bench_net / 100 - 1) * 100, 2),
        "spy_open": spy_open, "spy_close": spy_close,
        "month_end": {k: [v[0], round(v[1], 2)] for k, v in month_end.items()},
        "selections": [{
            "date": s["date"], "ref": s["ref"], "picks": s["picks"],
            "info": {t: {"close": round(s["info"][t]["close"], 2),
                         "ma200": (round(s["info"][t]["ma200"], 2)
                                   if s["info"][t]["ma200"] else None),
                         "eligible": s["info"][t]["eligible"],
                         "mom63_pct": (round(s["info"][t]["mom63"] * 100, 2)
                                       if s["info"][t]["mom63"] is not None
                                       else None)}
                     for t in TICKERS}} for s in selections],
    }

    with open(os.path.join(HERE, "disciplined-year-trades.csv"), "w",
              newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "ticker", "side", "price",
                                          "shares", "value", "reason"])
        w.writeheader()
        w.writerows(trades)
    with open(os.path.join(HERE, "disciplined-year-results.json"), "w") as f:
        json.dump(out, f, indent=2)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
