#!/usr/bin/env python3
"""
v12 COMPLETIONS - v0-aggressive: the FROZEN ORIGINAL spec on the standard roads.

The engine below is the original year engine
(backtests/2025-11-21-year/aggressive-year.py) transcribed rule-for-rule and
generalized only in its window and data source - no rule changes:

  - Universe (10): SPY QQQ NVDA TSLA AAPL MSFT AMZN META AMD AVGO.
  - Signal (prior trading day's bars only): close >= prior 10-day high
    (breakout) OR day gain > +2% on volume > 1.5x the 20-day average volume
    (average over the 20 bars before the signal bar). Rank by 5-day % gain
    desc, then volume ratio desc.
  - Buy at the next day's open: top qualifiers, up to 50% of prior-close pot
    equity each, max 2 positions, fractional shares.
  - Exits daily (stop before target if both touched; a gapped-through
    stop/target fills at the open): hard stop -3%, profit exit +6%, fade exit
    at the close if the name closes below the prior day's low.
  - No new entries on a day after a day the pot fell 4%+ close-to-close.
  - Costs: 0.10% of trade value on every buy and sell + $0.01 per sell order.
  - Profit-ladder floor: starts $85; close >= $125 -> floor $100; >= $150 ->
    floor $125. A close at/below the floor liquidates at the next open and
    ENDS the run (original form - no restart). Window end: liquidate at the
    final close.

ROADS (each an independent $100 run, ladder reset): LONG 2010-01-04,
DECADE 2016-11-21, CONT 2019-01-02, VAL 2023-01-03, all -> 2026-11-20.

DATA (read-only program caches, all Yahoo Finance chart API payloads,
split-adjusted, NOT dividend-adjusted - the v0 convention):
  SPY AAPL MSFT AMZN NVDA TSLA AVGO META : backtests/v7/long-hold/data/pxfull_*
  AMD : backtests/v10-retest/quality-momentum/data/pxfull_AMD.json
  QQQ : backtests/v3/data_etf/QQQ.json

PLACEBOS: 20 seeds per road; twins replay the real run's entry-count
schedule with random name choice, identical sizing/exits/block/ladder/costs
(the v10 program convention).

VERIFICATION MODE (--verify): runs this same engine on the original year
window (2025-11-21 -> 2026-11-20) using the ORIGINAL year folder's own
cached data (copied into orig/year/data) - it must reproduce $84.51.
"""
import json, os, random, sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
UNIVERSE = ["SPY", "QQQ", "NVDA", "TSLA", "AAPL", "MSFT", "AMZN", "META", "AMD", "AVGO"]
START_CASH = 100.0
COST_RATE = 0.001
SELL_FEE = 0.01
END = "2026-11-20"
ROADS = {"LONG": "2010-01-04", "DECADE": "2016-11-21", "CONT": "2019-01-02", "VAL": "2023-01-03"}

DATA_FILES = {s: os.path.join(BT, "v7", "long-hold", "data", f"pxfull_{s}.json")
              for s in ["SPY", "AAPL", "MSFT", "AMZN", "NVDA", "TSLA", "AVGO", "META"]}
DATA_FILES["AMD"] = os.path.join(BT, "v10-retest", "quality-momentum", "data", "pxfull_AMD.json")
DATA_FILES["QQQ"] = os.path.join(BT, "v3", "data_etf", "QQQ.json")


def load_payload(path):
    """Yahoo chart payload -> (bars, adjclose_by_date)."""
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


def load_roads_data():
    data, adj = {}, {}
    for s in UNIVERSE:
        data[s], adj[s] = load_payload(DATA_FILES[s])
    return data, adj


def load_verify_data():
    data, adj = {}, {}
    for s in UNIVERSE:
        data[s], adj[s] = load_payload(os.path.join(HERE, "orig", "year", "data", f"{s}.json"))
    return data, adj


def run_engine(data, win_start, win_end, placebo_seed=None, entry_schedule=None):
    """One run of the frozen original spec. Transcribed from aggressive-year.py."""
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    idx = {s: {r["date"]: i for i, r in enumerate(rows)} for s, rows in data.items()}
    spy = data["SPY"]
    cal = [r["date"] for r in spy if win_start <= r["date"] <= win_end]
    start_date, end_date = cal[0], cal[-1]

    def bar(s, date):
        i = idx[s].get(date)
        return data[s][i] if i is not None else None

    def prev_bar(s, date):
        i = idx[s].get(date)
        return data[s][i - 1] if i is not None and i > 0 else None

    cash = START_CASH
    positions = {}
    trades = 0
    round_trips = []
    equity_curve = []
    floor = 85.0
    total_costs = 0.0
    halted = None
    prev_equity = START_CASH
    no_entry_today = False
    days_invested = 0
    days_cash = 0
    entries_made = {}

    def equity_at_close(date):
        eq = cash
        for s, p in positions.items():
            b = bar(s, date)
            if b:
                eq += p["shares"] * b["close"]
        return eq

    def sell(sym, date, price, reason):
        nonlocal cash, total_costs, trades
        p = positions.pop(sym)
        gross = p["shares"] * price
        cost = gross * COST_RATE + SELL_FEE
        total_costs += cost
        cash += gross - cost
        round_trips.append((gross - cost) - p["cost_in"])
        trades += 1

    for di, date in enumerate(cal):
        last_day = (date == end_date)
        # ---- entries at open (signals from the previous trading day) ----
        if di == 0:
            prev_date = None
            for r in spy:
                if r["date"] < start_date:
                    prev_date = r["date"]
        else:
            prev_date = cal[di - 1]
        if prev_date and not no_entry_today and len(positions) < 2:
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
                    prior10_high = max(r["high"] for r in rows[i - 10:i])
                    gain5 = b["close"] / rows[i - 5]["close"] - 1
                    day_gain = b["close"] / rows[i - 1]["close"] - 1
                    vol20 = sum(r["volume"] for r in rows[i - 20:i]) / 20
                    vol_ratio = (b["volume"] / vol20) if vol20 else 0
                    breakout = b["close"] >= prior10_high
                    momentum = day_gain > 0.02 and vol_ratio > 1.5
                    if breakout or momentum:
                        quals.append((s, gain5, vol_ratio))
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
        # ---- intraday + close exits ----
        for s in list(positions.keys()):
            b = bar(s, date)
            if b is None:
                continue
            p = positions[s]
            stop = p["entry_price"] * 0.97
            target = p["entry_price"] * 1.06
            if b["low"] <= stop:
                fill = b["open"] if b["open"] < stop else stop
                sell(s, date, fill, "stop -3%")
            elif b["high"] >= target:
                fill = b["open"] if b["open"] > target else target
                sell(s, date, fill, "target +6%")
            else:
                pb = prev_bar(s, date)
                if pb and b["close"] < pb["low"]:
                    sell(s, date, b["close"], "fade")
        # ---- end of day ----
        eq = equity_at_close(date)
        equity_curve.append([date, round(eq, 4)])
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
            halted = {"trigger_date": date, "liquidation_date": nxt,
                      "balance": round(cash, 2), "floor": floor}
            equity_curve.append([nxt, round(cash, 4)])
            break
        # daily -4% rule for tomorrow
        no_entry_today = bool(prev_equity > 0 and (eq / prev_equity - 1) <= -0.04)
        prev_equity = eq
        # final day liquidation at close
        if last_day:
            for s in list(positions.keys()):
                b = bar(s, date)
                if b:
                    sell(s, date, b["close"], "end of period liquidation")
            equity_curve[-1] = [date, round(cash, 4)]

    final = halted["balance"] if halted else round(cash, 2)
    peak, max_dd = START_CASH, 0.0
    for _, e in equity_curve:
        peak = max(peak, e)
        max_dd = min(max_dd, e / peak - 1.0)
    wins = [p for p in round_trips if p > 0]
    losses = [p for p in round_trips if p <= 0]
    days = (datetime.strptime(end_date, "%Y-%m-%d") - datetime.strptime(start_date, "%Y-%m-%d")).days
    years = days / 365.25
    cagr = ((final / START_CASH) ** (1.0 / years) - 1.0) * 100 if final > 0 else -100.0
    return {"start": start_date, "end": end_date, "final": round(final, 2),
            "return_pct": round((final / START_CASH - 1) * 100, 2),
            "cagr_pct": round(cagr, 2), "max_dd_pct": round(max_dd * 100, 2),
            "halted": halted, "orders": trades, "round_trips": len(round_trips),
            "wins": len(wins), "losses": len(losses),
            "win_rate_pct": round(len(wins) / len(round_trips) * 100, 1) if round_trips else 0,
            "costs": round(total_costs, 2), "final_floor": floor,
            "days_invested": days_invested, "days_cash": days_cash,
            "curve": equity_curve, "entries_made": entries_made}


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


def main():
    if "--verify" in sys.argv:
        data, adj = load_verify_data()
        r = run_engine(data, "2025-11-21", "2026-11-20")
        out = {k: r[k] for k in ("start", "end", "final", "return_pct", "max_dd_pct",
                                 "halted", "orders", "round_trips", "wins", "losses",
                                 "win_rate_pct", "costs", "final_floor",
                                 "days_invested", "days_cash")}
        out["recorded"] = {"final": 84.51, "orders": 202, "round_trips": 101, "wins": 32,
                           "losses": 69, "costs": 10.91, "max_dd_pct": 23.93,
                           "halt_trigger": "2026-10-26", "halt_liquidation": "2026-10-27"}
        out["match"] = (out["final"] == 84.51 and out["orders"] == 202
                        and out["halted"] and out["halted"]["trigger_date"] == "2026-10-26"
                        and out["halted"]["liquidation_date"] == "2026-10-27")
        print(json.dumps(out, indent=1))
        with open(os.path.join(HERE, "verify_engine.json"), "w") as f:
            json.dump(out, f, indent=1)
        return

    data, adj = load_roads_data()
    results = {"family": "v0-aggressive", "program": "v12-completions",
               "form": "frozen original spec (year-engine form, profit-ladder floor), daily cadence",
               "costs": "0.10% of trade value per side + $0.01 per sell order (original program costs)",
               "roads": {}}
    for road, start in ROADS.items():
        real = run_engine(data, start, END)
        twin_finals = []
        for seed in range(20):
            twin = run_engine(data, start, END, placebo_seed=seed,
                              entry_schedule=real["entries_made"])
            twin_finals.append(twin["final"])
        beaten = sum(1 for f in twin_finals if real["final"] > f)
        results["roads"][road] = {
            "start": real["start"], "end": real["end"], "final": real["final"],
            "return_pct": real["return_pct"], "cagr_pct": real["cagr_pct"],
            "max_dd_pct": real["max_dd_pct"], "halted": real["halted"],
            "orders": real["orders"], "round_trips": real["round_trips"],
            "wins": real["wins"], "losses": real["losses"],
            "win_rate_pct": real["win_rate_pct"], "costs": real["costs"],
            "final_floor": real["final_floor"],
            "days_invested": real["days_invested"], "days_cash": real["days_cash"],
            "placebo_beaten": beaten, "placebo_twin_finals": twin_finals,
            "spy": spy_benchmarks(data, adj, start, END),
            "equity_curve": real["curve"]}
        print(road, json.dumps({k: results["roads"][road][k] for k in
                                ("final", "cagr_pct", "max_dd_pct", "orders", "costs",
                                 "placebo_beaten")}), "halted:", real["halted"], flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("wrote results.json")


if __name__ == "__main__":
    main()
