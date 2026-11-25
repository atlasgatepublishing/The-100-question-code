#!/usr/bin/env python3
"""
V13 BEST RULES - v0-aggressive. Implements BEST-RULES-SPEC.md exactly
(frozen before this run):

  - Universe (10): SPY QQQ NVDA TSLA AAPL MSFT AMZN META AMD AVGO.
  - Daily signals from the prior trading day's bars only; entries at the
    next day's open.
  - Qualifier: signal-day close >= highest high of the prior 20 bars
    (>=20 prior bars required). Ranked by 20-day return desc, then
    5-day gain desc.
  - Max 2 positions; each buy = min(50% of prior-close pot equity,
    available cash), grossed down for the buy cost.
  - Exits (daily): hard stop -8% from entry (gap-through fills at the
    open; stop before channel if both apply). Channel exit at the close
    if the name closes below the lowest low of its prior 20 bars.
    NO profit target. NO floor / ladder / restart. NO regime gate.
  - Costs: 0.10% of trade value per side + $0.01 per sell order.
  - $100 pots, fractional shares, long only. Window end: liquidate at
    the final close.

ROADS: LONG 2010-01-04, DECADE 2016-11-21, CONT 2019-01-02,
VAL 2023-01-03, all -> 2026-11-20. Placebos: 20 seeds per road, twins
replay the real run's entry-count schedule with random name choice,
identical sizing / exits / costs.

CONFIRMATION (frozen in the spec; run only if a road beats champion
V+M): fresh $100 pots on CONF_A 2012-01-03->2015-12-31 and CONF_B
2020-01-02->2022-12-30 (each must finish > $100 and > SPY price-only
net on its window) + fresh calendar-year pots across the beaten road
(median year must be > $100).

DATA (read-only program caches, Yahoo chart payloads, split-adjusted,
NOT dividend-adjusted - the v0 convention; same sources as v12):
  SPY AAPL MSFT AMZN NVDA TSLA AVGO META : backtests/v7/long-hold/data/pxfull_*
  AMD : backtests/v10-retest/quality-momentum/data/pxfull_AMD.json
  QQQ : backtests/v3/data_etf/QQQ.json
"""
import json, os, random, statistics, sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
UNIVERSE = ["SPY", "QQQ", "NVDA", "TSLA", "AAPL", "MSFT", "AMZN", "META", "AMD", "AVGO"]
START_CASH = 100.0
COST_RATE = 0.001
SELL_FEE = 0.01
END = "2026-11-20"
ROADS = {"LONG": "2010-01-04", "DECADE": "2016-11-21", "CONT": "2019-01-02", "VAL": "2023-01-03"}
CHAMPION = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPY_REF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
PUBLISHED = {"LONG": 83.90, "DECADE": 98.52, "CONT": 83.83, "VAL": 83.07}
CONF_WINDOWS = {"CONF_A": ("2012-01-03", "2015-12-31"), "CONF_B": ("2020-01-02", "2022-12-30")}

DATA_FILES = {s: os.path.join(BT, "v7", "long-hold", "data", f"pxfull_{s}.json")
              for s in ["SPY", "AAPL", "MSFT", "AMZN", "NVDA", "TSLA", "AVGO", "META"]}
DATA_FILES["AMD"] = os.path.join(BT, "v10-retest", "quality-momentum", "data", "pxfull_AMD.json")
DATA_FILES["QQQ"] = os.path.join(BT, "v3", "data_etf", "QQQ.json")


def load_payload(path):
    res = json.load(open(path))["chart"]["result"][0]
    ts, q = res["timestamp"], res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose", [None] * len(ts))
    rows, adjmap = [], {}
    for i, t in enumerate(ts):
        if None in (q["open"][i], q["high"][i], q["low"][i], q["close"][i]):
            continue
        d = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
        rows.append({"date": d, "open": float(q["open"][i]), "high": float(q["high"][i]),
                     "low": float(q["low"][i]), "close": float(q["close"][i]),
                     "volume": float(q["volume"][i] or 0)})
        if adj[i] is not None:
            adjmap[d] = float(adj[i])
    rows.sort(key=lambda r: r["date"])
    return rows, adjmap


def load_data():
    data, adj = {}, {}
    for s in UNIVERSE:
        data[s], adj[s] = load_payload(DATA_FILES[s])
    return data, adj


def run_engine(data, win_start, win_end, placebo_seed=None, entry_schedule=None):
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    idx = {s: {r["date"]: i for i, r in enumerate(rows)} for s, rows in data.items()}
    spy = data["SPY"]
    cal = [r["date"] for r in spy if win_start <= r["date"] <= win_end]
    start_date, end_date = cal[0], cal[-1]

    def bar(s, date):
        i = idx[s].get(date)
        return data[s][i] if i is not None else None

    cash = START_CASH
    positions = {}
    trades = 0
    round_trips = []
    equity_curve = []
    total_costs = 0.0
    prev_equity = START_CASH
    days_invested = 0
    days_cash = 0
    entries_made = {}
    exit_reasons = {}

    def equity_at_close(date):
        eq = cash
        for s, p in positions.items():
            b = bar(s, date)
            if b:
                eq += p["shares"] * b["close"]
        return eq

    def sell(sym, price, reason):
        nonlocal cash, total_costs, trades
        p = positions.pop(sym)
        gross = p["shares"] * price
        cost = gross * COST_RATE + SELL_FEE
        total_costs += cost
        cash += gross - cost
        round_trips.append((gross - cost) - p["cost_in"])
        exit_reasons[reason] = exit_reasons.get(reason, 0) + 1
        trades += 1

    for di, date in enumerate(cal):
        last_day = (date == end_date)
        # signal day = previous trading day on the SPY calendar
        if di == 0:
            prev_date = None
            for r in spy:
                if r["date"] < start_date:
                    prev_date = r["date"]
        else:
            prev_date = cal[di - 1]
        # ---- entries at open ----
        if prev_date and len(positions) < 2:
            if rng is None:
                quals = []
                for s in UNIVERSE:
                    if s in positions:
                        continue
                    i = idx[s].get(prev_date)
                    if i is None or i < 20:
                        continue
                    rows = data[s]
                    b = rows[i]
                    prior20_high = max(r["high"] for r in rows[i - 20:i])
                    if b["close"] >= prior20_high:
                        ret20 = b["close"] / rows[i - 20]["close"] - 1
                        gain5 = b["close"] / rows[i - 5]["close"] - 1
                        quals.append((s, ret20, gain5))
                quals.sort(key=lambda x: (-x[1], -x[2]))
                picks = [q[0] for q in quals]
            else:
                want = entry_schedule.get(date, 0) if entry_schedule else 0
                eligible = sorted(s for s in UNIVERSE if s not in positions)
                picks = rng.sample(eligible, min(want, len(eligible))) if want > 0 else []
            slots = 2 - len(positions)
            made = 0
            for s in picks[:slots]:
                b = bar(s, date)
                if b is None:
                    continue
                alloc = min(0.50 * prev_equity, cash)
                if alloc < 1.0:
                    break
                price = b["open"]
                shares = alloc / (price * (1 + COST_RATE))
                cost_in = shares * price * (1 + COST_RATE)
                total_costs += shares * price * COST_RATE
                cash -= cost_in
                positions[s] = {"shares": shares, "entry_price": price, "cost_in": cost_in}
                trades += 1
                made += 1
            if rng is None:
                entries_made[date] = made
        # ---- exits: hard stop intraday, channel exit at close ----
        for s in list(positions.keys()):
            b = bar(s, date)
            if b is None:
                continue
            p = positions[s]
            stop = p["entry_price"] * 0.92
            if b["low"] <= stop:
                fill = b["open"] if b["open"] < stop else stop
                sell(s, fill, "stop -8%")
                continue
            i = idx[s][date]
            if i >= 20:
                chan_low = min(r["low"] for r in data[s][i - 20:i])
                if b["close"] < chan_low:
                    sell(s, b["close"], "channel exit")
        # ---- end of day ----
        eq = equity_at_close(date)
        equity_curve.append([date, round(eq, 4)])
        if positions:
            days_invested += 1
        else:
            days_cash += 1
        prev_equity = eq
        if last_day:
            for s in list(positions.keys()):
                b = bar(s, date)
                if b:
                    sell(s, b["close"], "end of period liquidation")
            equity_curve[-1] = [date, round(cash, 4)]

    final = round(cash, 2)
    peak, max_dd = START_CASH, 0.0
    for _, e in equity_curve:
        peak = max(peak, e)
        max_dd = min(max_dd, e / peak - 1.0)
    wins = [p for p in round_trips if p > 0]
    losses = [p for p in round_trips if p <= 0]
    days = (datetime.strptime(end_date, "%Y-%m-%d") - datetime.strptime(start_date, "%Y-%m-%d")).days
    years = days / 365.25
    cagr = ((final / START_CASH) ** (1.0 / years) - 1.0) * 100 if final > 0 else -100.0
    return {"start": start_date, "end": end_date, "final": final,
            "return_pct": round((final / START_CASH - 1) * 100, 2),
            "cagr_pct": round(cagr, 2), "max_dd_pct": round(max_dd * 100, 2),
            "orders": trades, "round_trips": len(round_trips),
            "wins": len(wins), "losses": len(losses),
            "win_rate_pct": round(len(wins) / len(round_trips) * 100, 1) if round_trips else 0,
            "avg_win": round(statistics.mean(wins), 2) if wins else 0.0,
            "avg_loss": round(statistics.mean(losses), 2) if losses else 0.0,
            "expectancy_per_rt": round(statistics.mean(round_trips), 2) if round_trips else 0.0,
            "costs": round(total_costs, 2), "exit_reasons": exit_reasons,
            "days_invested": days_invested, "days_cash": days_cash,
            "curve": equity_curve, "entries_made": entries_made}


def monthly_distribution(curve):
    """Monthly periods from a daily equity curve."""
    months = {}
    for d, e in curve:
        months.setdefault(d[:7], []).append((d, e))
    keys = sorted(months)
    rets = []
    prev_close = START_CASH
    for k in keys:
        close = months[k][-1][1]
        rets.append((k, close / prev_close - 1.0))
        prev_close = close
    vals = [r for _, r in rets]
    med = statistics.median(vals) if vals else 0.0
    pos = sum(1 for v in vals if v > 0)
    # longest losing streak (months <= 0)
    streak = longest = 0
    for v in vals:
        streak = streak + 1 if v <= 0 else 0
        longest = max(longest, streak)
    # longest stretch between new highs (trading days)
    peak = START_CASH
    last_high_i = 0
    longest_gap = 0
    for i, (_, e) in enumerate(curve):
        if e >= peak:
            peak = e
            longest_gap = max(longest_gap, i - last_high_i)
            last_high_i = i
    longest_gap = max(longest_gap, len(curve) - 1 - last_high_i)
    return {"months": len(vals), "median_month_pct": round(med * 100, 2),
            "share_positive_pct": round(pos / len(vals) * 100, 1) if vals else 0,
            "best_month_pct": round(max(vals) * 100, 2) if vals else 0,
            "worst_month_pct": round(min(vals) * 100, 2) if vals else 0,
            "mean_month_pct": round(statistics.mean(vals) * 100, 2) if vals else 0,
            "longest_losing_streak_months": longest,
            "longest_stretch_between_new_highs_days": longest_gap}


def spy_benchmarks(data, adj, win_start, win_end):
    spy = data["SPY"]
    cal = [r["date"] for r in spy if win_start <= r["date"] <= win_end]
    idx = {r["date"]: i for i, r in enumerate(spy)}
    first, last = cal[0], cal[-1]
    o = spy[idx[first]]["open"]
    c = spy[idx[last]]["close"]
    shares = START_CASH / (o * (1 + COST_RATE))
    price_net = shares * c * (1 - COST_RATE) - SELL_FEE
    adj_first, adj_last = adj["SPY"].get(first), adj["SPY"].get(last)
    adj_gross = round(START_CASH * adj_last / adj_first, 2) if adj_first and adj_last else None
    return {"window": [first, last], "price_only_net": round(price_net, 2),
            "dividend_adjusted_gross": adj_gross}


def summarize(r):
    return {k: r[k] for k in ("start", "end", "final", "return_pct", "cagr_pct",
                               "max_dd_pct", "orders", "round_trips", "wins", "losses",
                               "win_rate_pct", "avg_win", "avg_loss", "expectancy_per_rt",
                               "costs", "exit_reasons", "days_invested", "days_cash")}


def main():
    data, adj = load_data()
    results = {"family": "v0-aggressive", "program": "v13-best-rules",
               "spec": "BEST-RULES-SPEC.md (frozen before the run)",
               "form": "20d-high breakout only, ranked by 20d return; max 2 names at 50% each; "
                       "-8% hard stop + 20d channel exit at close; no target, no floor, no regime gate; daily",
               "costs": "0.10% of trade value per side + $0.01 per sell order",
               "champion_vm": CHAMPION, "spy_reference": SPY_REF, "published_form_v12": PUBLISHED,
               "roads": {}, "confirmation": None}
    beaten = []
    for road, start in ROADS.items():
        real = run_engine(data, start, END)
        twin_finals = []
        for seed in range(20):
            twin = run_engine(data, start, END, placebo_seed=seed,
                              entry_schedule=real["entries_made"])
            twin_finals.append(twin["final"])
        n_beaten = sum(1 for f in twin_finals if real["final"] > f)
        results["roads"][road] = dict(
            summarize(real),
            placebo_beaten=n_beaten, placebo_twin_finals=twin_finals,
            placebo_median=round(statistics.median(twin_finals), 2),
            spy=spy_benchmarks(data, adj, start, END),
            monthly_distribution=monthly_distribution(real["curve"]),
            equity_curve=real["curve"])
        print(road, json.dumps({k: results["roads"][road][k] for k in
                                ("final", "cagr_pct", "max_dd_pct", "orders", "round_trips",
                                 "win_rate_pct", "costs", "placebo_beaten")}), flush=True)
        if real["final"] > CHAMPION[road]:
            beaten.append(road)

    # ---- Terry's confirmation, only if a champion was beaten ----
    if beaten:
        conf = {"triggered_by_roads": beaten, "windows": {}, "yearly_folds": {}}
        for name, (s, e) in CONF_WINDOWS.items():
            r = run_engine(data, s, e)
            spy = spy_benchmarks(data, adj, s, e)
            conf["windows"][name] = dict(summarize(r), spy_price_only_net=spy["price_only_net"],
                                         passes=bool(r["final"] > 100 and r["final"] > spy["price_only_net"]))
        for road in beaten:
            start_year = int(ROADS[road][:4])
            years = {}
            for y in range(start_year, 2027):
                s = f"{y}-01-01"
                e = f"{y}-12-31" if y < 2026 else END
                if s < ROADS[road]:
                    s = ROADS[road]
                r = run_engine(data, s, e)
                years[str(y)] = r["final"]
            finals = list(years.values())
            conf["yearly_folds"][road] = {"year_finals": years,
                                          "median_year": round(statistics.median(finals), 2),
                                          "passes": bool(statistics.median(finals) > 100)}
        conf["all_pass"] = bool(all(w["passes"] for w in conf["windows"].values())
                                and all(f["passes"] for f in conf["yearly_folds"].values()))
        results["confirmation"] = conf
        print("CONFIRMATION", json.dumps(conf, indent=1), flush=True)
    else:
        print("No road beat the champion; confirmation not triggered.", flush=True)

    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("wrote results.json")


if __name__ == "__main__":
    main()
