#!/usr/bin/env python3
"""
MULTI-ASSET ETF TREND SLEEVE — Terry's AI stock app, simulation only.
Rule per ~/workspace/stock-app/research/v3-edges.md section 7:
  Universe: SPY, QQQ, TLT, IEF, GLD, DBC, UUP (Yahoo daily bars).
  Weekly evaluation (last trading day of each week, i.e. Friday close),
  trades execute at the next trading day's open.
  Trend score per asset = blend of signs of trailing 3-mo (63d), 6-mo (126d),
  12-mo (252d) returns. Hold only assets with >=2 of 3 signals positive
  (score > 0). Weights proportional to 1 / trailing-20-day realized vol,
  capped at 40% per asset (excess redistributed; any remainder is cash).
  No-trade band: an existing position is not adjusted unless its target
  weight moved >20% relative; entries and exits (signal flips) always trade.
  Costs: 0.10% of trade value per side + $0.01 per sell order.
  $100 pot, long only, fractional shares.
  Terry's floor ACTIVE: floor $85; rises to $100 at a $125 close, to $125 at
  a $150 close; close at/below floor -> liquidate all at next open, run ends.
Prices: dividend+split adjusted (adjclose; opens scaled by adjclose/close),
so strategy and benchmarks are on the same total-return basis.
"""
import json, math, os, statistics, sys, urllib.request
from datetime import datetime, timezone

ASSETS = ["SPY", "QQQ", "TLT", "IEF", "GLD", "DBC", "UUP"]
BENCH_EXTRA = ["AGG"]
FETCH_START = "2007-01-01"
FETCH_END = "2026-11-21"  # exclusive-ish; last trading day used is 2026-11-20
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data_etf")
os.makedirs(CACHE, exist_ok=True)

COST_RATE = 0.0010
SELL_FEE = 0.01
START_CASH = 100.0


def fetch(ticker):
    path = os.path.join(CACHE, f"{ticker}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    p1 = int(datetime(2007, 1, 1, tzinfo=timezone.utc).timestamp())
    p2 = int(datetime(2026, 11, 21, tzinfo=timezone.utc).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={p1}&period2={p2}&interval=1d&events=div,splits")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    with open(path, "w") as f:
        json.dump(data, f)
    return data


def load_series(ticker):
    """Return dict date->(adj_open, adj_close) and sorted date list."""
    data = fetch(ticker)
    res = data["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = None
    if "adjclose" in res["indicators"]:
        adj = res["indicators"]["adjclose"][0]["adjclose"]
    out = {}
    for i, t in enumerate(ts):
        d = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
        c = q["close"][i]
        o = q["open"][i]
        if c is None or o is None:
            continue
        if adj is not None and adj[i]:
            ratio = adj[i] / c
            out[d] = (o * ratio, adj[i])
        else:
            out[d] = (o, c)
    return out


SERIES = {t: load_series(t) for t in ASSETS + BENCH_EXTRA}
CAL = sorted(SERIES["SPY"].keys())          # master calendar = SPY trading days
CAL_IDX = {d: i for i, d in enumerate(CAL)}


def close_on(ticker, date):
    """Forward-filled adjusted close on a master-calendar date."""
    s = SERIES[ticker]
    if date in s:
        return s[date][1]
    i = CAL_IDX[date]
    for j in range(i - 1, -1, -1):
        if CAL[j] in s:
            return s[CAL[j]][1]
    return None


def open_on(ticker, date):
    s = SERIES[ticker]
    if date in s:
        return s[date][0]
    return close_on(ticker, date)


def closes_window(ticker, end_date, n):
    """Last n adjusted closes up to and including end_date (master calendar)."""
    i = CAL_IDX[end_date]
    vals = []
    for j in range(i, -1, -1):
        v = close_on(ticker, CAL[j])
        if v is not None:
            vals.append(v)
        if len(vals) >= n:
            break
    vals.reverse()
    return vals


def trend_and_vol(ticker, date):
    """Return (n_positive_signals, realized_vol_20d) or None if not enough data."""
    closes = closes_window(ticker, date, 253)
    if len(closes) < 253:
        return None
    last = closes[-1]
    signs = []
    for lag in (63, 126, 252):
        r = last / closes[-1 - lag] - 1.0
        signs.append(1 if r > 0 else (-1 if r < 0 else 0))
    rets = [closes[k] / closes[k - 1] - 1.0 for k in range(len(closes) - 20, len(closes))]
    vol = statistics.pstdev(rets) if len(rets) >= 20 else None
    return sum(1 for s in signs if s > 0), vol


def capped_inv_vol_weights(vols):
    """vols: {ticker: vol}. Weights prop to 1/vol, capped at 0.40 iteratively."""
    inv = {t: 1.0 / v for t, v in vols.items() if v and v > 0}
    if not inv:
        return {}
    weights = {}
    remaining = dict(inv)
    budget = 1.0
    while remaining:
        tot = sum(remaining.values())
        over = [t for t in remaining if budget * remaining[t] / tot > 0.40]
        if not over:
            for t in remaining:
                weights[t] = budget * remaining[t] / tot
            break
        for t in over:
            weights[t] = 0.40
            budget -= 0.40
            del remaining[t]
        if budget <= 0:
            break
    return weights


def simulate(start, end, start_cash=START_CASH, floor0=85.0,
             ladder=((125.0, 100.0), (150.0, 125.0))):
    """Run the sleeve from first trading day >= start to last trading day <= end.
    ladder: (close trigger, new floor) pairs, applied highest-first."""
    days = [d for d in CAL if start <= d <= end]
    cash = start_cash
    shares = {t: 0.0 for t in ASSETS}
    floor = floor0
    orders = 0
    total_costs = 0.0
    trades_log = []
    curve = []  # (date, close equity)
    pending = None  # (trade_set, target_weights) decided at an eval close
    halted = None
    liquidate_next_open = False

    # weekly eval days: last trading day of each ISO week within the run
    eval_days = set()
    by_week = {}
    for d in days:
        dt = datetime.strptime(d, "%Y-%m-%d")
        by_week.setdefault(dt.isocalendar()[:2], []).append(d)
    for wk, ds in by_week.items():
        eval_days.add(max(ds))

    def equity_at(date, price_fn):
        eq = cash
        for t in ASSETS:
            if shares[t] > 0:
                p = price_fn(t, date)
                if p:
                    eq += shares[t] * p
        return eq

    for di, d in enumerate(days):
        # --- execute pending orders at today's open ---
        if liquidate_next_open or pending is not None:
            if liquidate_next_open:
                trade_set = {t for t in ASSETS if shares[t] > 0}
                targets = {}
            else:
                trade_set, targets = pending
            eq_open = equity_at(d, open_on)
            # sells first
            for t in sorted(trade_set):
                tgt_val = targets.get(t, 0.0) * eq_open
                cur_val = shares[t] * open_on(t, d)
                diff = cur_val - tgt_val
                if diff > 0.01 and shares[t] > 0:
                    sell_val = min(diff, cur_val)
                    sh = sell_val / open_on(t, d)
                    cost = sell_val * COST_RATE + SELL_FEE
                    cash += sell_val - cost
                    shares[t] -= sh
                    if shares[t] < 1e-9:
                        shares[t] = 0.0
                    orders += 1
                    total_costs += cost
                    trades_log.append((d, "SELL", t, round(sell_val, 2)))
            # then buys
            buy_list = []
            for t in sorted(trade_set):
                tgt_val = targets.get(t, 0.0) * eq_open
                cur_val = shares[t] * open_on(t, d)
                diff = tgt_val - cur_val
                if diff > 0.01:
                    buy_list.append((t, diff))
            tot_buy = sum(v for _, v in buy_list)
            if tot_buy > 0:
                scale = min(1.0, cash / (tot_buy * (1 + COST_RATE))) if tot_buy > 0 else 0
                for t, diff in buy_list:
                    buy_val = diff * scale
                    if buy_val < 0.01:
                        continue
                    cost = buy_val * COST_RATE
                    cash -= buy_val + cost
                    shares[t] += buy_val / open_on(t, d)
                    orders += 1
                    total_costs += cost
                    trades_log.append((d, "BUY", t, round(buy_val, 2)))
            pending = None
            if liquidate_next_open:
                halted = d
                liquidate_next_open = False
                eq = equity_at(d, close_on)
                curve.append((d, eq))
                break

        # --- mark to close, update floor, check breach ---
        eq_close = equity_at(d, close_on)
        curve.append((d, eq_close))
        for trigger, new_floor in sorted(ladder, reverse=True):
            if eq_close >= trigger:
                floor = max(floor, new_floor)
                break
        if eq_close <= floor:
            if di + 1 < len(days):
                liquidate_next_open = True
                continue
            else:
                halted = d
                break

        # --- weekly evaluation at today's close ---
        if d in eval_days and di + 1 < len(days):
            targets = {}
            vols = {}
            for t in ASSETS:
                tv = trend_and_vol(t, d)
                if tv is None:
                    continue
                npos, vol = tv
                if npos >= 2 and vol:
                    vols[t] = vol
            targets = capped_inv_vol_weights(vols)
            # decide trade set: flips always; adjustments only outside the band
            trade_set = set()
            eq_c = eq_close
            for t in ASSETS:
                cur_w = (shares[t] * close_on(t, d) / eq_c) if eq_c > 0 else 0.0
                tgt_w = targets.get(t, 0.0)
                held = shares[t] > 0
                if held and tgt_w == 0.0:
                    trade_set.add(t)          # exit flip
                elif not held and tgt_w > 0.0:
                    trade_set.add(t)          # entry flip
                elif held and tgt_w > 0.0:
                    if abs(tgt_w - cur_w) / tgt_w > 0.20:
                        trade_set.add(t)      # band breach
            if trade_set:
                pending = (trade_set, targets)

    final_eq = curve[-1][1] if curve else start_cash
    return {
        "final": final_eq, "curve": curve, "orders": orders,
        "costs": total_costs, "halted": halted, "trades": trades_log,
        "days": days, "start_cash": start_cash,
    }


def metrics(res, start, end):
    days = res["days"]
    yrs = (datetime.strptime(days[-1], "%Y-%m-%d") - datetime.strptime(days[0], "%Y-%m-%d")).days / 365.25
    cagr = (res["final"] / res["start_cash"]) ** (1 / yrs) - 1 if yrs > 0 else 0.0
    peak, maxdd = -1e18, 0.0
    for _, eq in res["curve"]:
        peak = max(peak, eq)
        if peak > 0:
            maxdd = min(maxdd, eq / peak - 1.0)
    return {"cagr": cagr, "maxdd": maxdd, "years": yrs}


def buy_hold(tickers_weights, start, end):
    """Static buy-hold, net of costs, on adjusted prices. Returns final value of $100."""
    days = [d for d in CAL if start <= d <= end]
    d0, d1 = days[0], days[-1]
    total = 0.0
    for t, w in tickers_weights.items():
        amt = START_CASH * w
        buy_cost = amt * COST_RATE
        sh = (amt - buy_cost) / open_on(t, d0)
        val = sh * close_on(t, d1)
        total += val - (val * COST_RATE + SELL_FEE)
    return total


def year_returns(curve):
    """Calendar-year returns from a (date, equity) curve."""
    by_year = {}
    for d, eq in curve:
        by_year.setdefault(d[:4], []).append((d, eq))
    out = {}
    prev_last = None
    for y in sorted(by_year):
        last_eq = by_year[y][-1][1]
        if prev_last is not None:
            out[y] = last_eq / prev_last - 1.0
        prev_last = last_eq
    return out


def spy_year_return(year):
    days = [d for d in CAL if d[:4] == str(year)]
    prev = [d for d in CAL if d[:4] == str(year - 1)]
    if not days or not prev:
        return None
    return close_on("SPY", days[-1]) / close_on("SPY", prev[-1]) - 1.0


def fmt_run(name, res, start, end):
    m = metrics(res, start, end)
    print(f"\n== {name} ({start} -> {end}) ==")
    print(f"final=${res['final']:.2f}  total_return={res['final']/res['start_cash']-1:+.2%}  "
          f"CAGR={m['cagr']:+.2%}  maxDD={m['maxdd']:.2%}  costs=${res['costs']:.2f} "
          f"({res['costs']/res['start_cash']:.2%} of start pot)  "
          f"orders={res['orders']}  halted={res['halted']}")
    return m


def main():
    out = {}
    # Window A: full continuous
    a = simulate("2016-11-21", "2026-11-20")
    ma = fmt_run("A FULL", a, "2016-11-21", "2026-11-20")
    spy_a = buy_hold({"SPY": 1.0}, "2016-11-21", "2026-11-20")
    sf_a = buy_hold({"SPY": 0.6, "AGG": 0.4}, "2016-11-21", "2026-11-20")
    print(f"SPY buy-hold net: ${spy_a:.2f} ({spy_a/100-1:+.2%})")
    print(f"60/40 SPY/AGG buy-hold net: ${sf_a:.2f} ({sf_a/100-1:+.2%})")
    yr = year_returns(a["curve"])
    print("\nPer-year (sleeve, calendar-year):")
    bal = {}
    last = None
    for d, eq in a["curve"]:
        last = (d, eq)
        bal[d[:4]] = eq
    prev = 100.0
    for y in sorted(bal):
        r = yr.get(y)
        print(f"  {y}: end=${bal[y]:.2f}" + (f"  return={r:+.2%}" if r is not None else "  (partial, from start)"))
    spy22 = spy_year_return(2022)
    print(f"\n2022 crisis check: sleeve {yr.get('2022', float('nan')):+.2%} vs SPY {spy22:+.2%}")

    # Window B: design vs validation
    b1 = simulate("2016-11-21", "2022-12-31")
    mb1 = fmt_run("B DESIGN", b1, "2016-11-21", "2022-12-31")
    spy_b1 = buy_hold({"SPY": 1.0}, "2016-11-21", "2022-12-31")
    sf_b1 = buy_hold({"SPY": 0.6, "AGG": 0.4}, "2016-11-21", "2022-12-31")
    print(f"SPY buy-hold net: ${spy_b1:.2f} ({spy_b1/100-1:+.2%}) | 60/40: ${sf_b1:.2f} ({sf_b1/100-1:+.2%})")

    b2 = simulate("2023-01-01", "2026-11-20")
    mb2 = fmt_run("B VALIDATION", b2, "2023-01-01", "2026-11-20")
    spy_b2 = buy_hold({"SPY": 1.0}, "2023-01-01", "2026-11-20")
    sf_b2 = buy_hold({"SPY": 0.6, "AGG": 0.4}, "2023-01-01", "2026-11-20")
    print(f"SPY buy-hold net: ${spy_b2:.2f} ({spy_b2/100-1:+.2%}) | 60/40: ${sf_b2:.2f} ({sf_b2/100-1:+.2%})")

    # Terry's rule change (2026-11-21): $50 start, floor/ladder scaled by half.
    LAD50 = ((62.50, 50.0), (75.0, 62.50))
    a50 = simulate("2016-11-21", "2026-11-20", start_cash=50.0, floor0=42.50, ladder=LAD50)
    ma50 = fmt_run("A FULL $50 START", a50, "2016-11-21", "2026-11-20")
    yr50 = year_returns(a50["curve"])
    print(f"$50 run 2022: {yr50.get('2022', float('nan')):+.2%} (SPY 2022: {spy22:+.2%})")
    b2_50 = simulate("2023-01-01", "2026-11-20", start_cash=50.0, floor0=42.50, ladder=LAD50)
    mb2_50 = fmt_run("B VALIDATION $50 START", b2_50, "2023-01-01", "2026-11-20")

    summary = {
        "A": {"final": a["final"], **ma, "costs": a["costs"], "orders": a["orders"], "halted": a["halted"],
              "spy": spy_a, "sf": sf_a, "years_table": {y: bal[y] for y in sorted(bal)},
              "year_returns": yr, "spy_2022": spy22},
        "B_design": {"final": b1["final"], **mb1, "costs": b1["costs"], "orders": b1["orders"],
                     "halted": b1["halted"], "spy": spy_b1, "sf": sf_b1},
        "B_validation": {"final": b2["final"], **mb2, "costs": b2["costs"], "orders": b2["orders"],
                         "halted": b2["halted"], "spy": spy_b2, "sf": sf_b2},
        "A_50start": {"final": a50["final"], **ma50, "costs": a50["costs"], "orders": a50["orders"],
                      "halted": a50["halted"], "year_returns": yr50},
        "B_validation_50start": {"final": b2_50["final"], **mb2_50, "costs": b2_50["costs"],
                                 "orders": b2_50["orders"], "halted": b2_50["halted"]},
    }
    with open(os.path.join(HERE, "etf-trend-sleeve-results.json"), "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print("\nSaved etf-trend-sleeve-results.json")


if __name__ == "__main__":
    main()
