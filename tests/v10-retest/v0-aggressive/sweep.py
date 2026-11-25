#!/usr/bin/env python3
"""
v10 GREAT RETEST - v0-aggressive CADENCE SWEEP (one clean shot, no tuning).

Strategy: the ORIGINAL v0 Aggressive sprint pot (Terry's fast style, earliest form).
Rules as published in backtests/2026-11-16-week/aggressive.py and extended in
backtests/2025-11-21-year/aggressive-year.py (the year engine's fill conventions
are used here: a gapped-through stop/target fills at the open):
  - Universe (10): SPY QQQ NVDA TSLA AAPL MSFT AMZN META AMD AVGO.
  - Signal (from the most recent completed bar before the decision date):
    qualifies if close >= prior 10-day high (breakout) OR day gain > +2% on
    volume > 1.5x the 20-day average volume (avg over the 20 bars before the
    signal bar). Rank by 5-day % gain desc, then volume ratio desc.
  - Buy at the decision date's open: top qualifiers, up to 50% of pot each,
    max 2 positions, fractional shares.
  - Exits (checked only on cadence dates, stop before target if both touched):
    hard stop -3% from entry; profit exit +6% from entry; fade exit at the
    close if the name closes below the prior trading day's low.
  - No new entries at a cadence date if the pot's previous cadence close fell
    4%+ from the cadence close before it (the v0 -4% down-day block, cadence form).
  - Costs: 0.10% of trade value on every buy and sell + $0.01 per sell order.

RULE SUBSTITUTION (SPEC, stated plainly): the v0 originals ran Terry's profit
LADDER floor ($85, rising to $100 at $125 and $125 at $150; breach = run over).
The sweep replaces the ladder with the adopted v9 protection: plain -15% floor
from the episode's starting balance; on a breach (checked at cadence-date
closes) liquidate everything at the next trading day's open, sit in cash 90
calendar days, restart at the next regular cadence date under an episode-2
floor of -15% from the restart balance; a second breach ends the run.

CADENCE TREATMENT (SPEC uniform definition): signal evaluation, entries and
exit checks happen ONLY on cadence dates (daily = every trading day; weekly =
first trading day of each week; biweekly = first trading day of every second
week, anchored on the first cadence date of the window; monthly / quarterly /
semi-annual / annual = first trading day of the month / quarter / half / year).
Between cadence dates positions are simply held - stops and targets are NOT
checked. Equity is still marked to market every trading day for the curve.
Halt liquidation keeps the engine convention (next trading day's open, not
the next cadence date). End of window: liquidate at the final close.

ROAD: DECADE 2016-11-21 -> 2026-11-20, $100 start.
DATA (read-only): backtests/v2/data/<SYM>.json - Yahoo Finance chart API
payloads (split-adjusted, NOT dividend-adjusted - the v0 convention),
2015-06-01..2026-11-20, giving full indicator lead-in before the window.

PLACEBOS: random-entry twins. Each twin replays the real run's entry-count
schedule (same number of entries filled on each cadence date, capped by the
twin's own free slots/cash), choosing names uniformly at random from the
universe names it does not already hold, with identical sizing, exits, -4%
block (on its own equity) and v9 protection. 20 seeds per cell.
"""
import json, os, random, sys
from datetime import datetime, timezone, timedelta, date as ddate

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.expanduser("~/workspace/stock-app/backtests/v2/data")
UNIVERSE = ["SPY", "QQQ", "NVDA", "TSLA", "AAPL", "MSFT", "AMZN", "META", "AMD", "AVGO"]
START_CASH = 100.0
COST_RATE = 0.001
SELL_FEE = 0.01
STOP_PCT, TARGET_PCT = 0.03, 0.06
WIN_START, WIN_END = "2016-11-21", "2026-11-20"
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly", "semiannual", "annual"]


def load_bars():
    data = {}
    for sym in UNIVERSE:
        payload = json.load(open(os.path.join(CACHE, f"{sym}.json")))
        res = payload["chart"]["result"][0]
        ts, q = res["timestamp"], res["indicators"]["quote"][0]
        rows = []
        for i, t in enumerate(ts):
            if None in (q["open"][i], q["high"][i], q["low"][i], q["close"][i]):
                continue
            d = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
            rows.append({"date": d, "open": float(q["open"][i]), "high": float(q["high"][i]),
                         "low": float(q["low"][i]), "close": float(q["close"][i]),
                         "volume": float(q["volume"][i] or 0)})
        rows.sort(key=lambda r: r["date"])
        data[sym] = rows
    return data


def cadence_dates(cal, cadence):
    """cal: all SPY trading days in the window. Returns the decision-date set."""
    if cadence == "daily":
        return list(cal)
    out, seen = [], set()
    for d in cal:
        y, m, dd = int(d[:4]), int(d[5:7]), int(d[8:10])
        dt = ddate(y, m, dd)
        if cadence == "weekly":
            key = dt.isocalendar()[:2]
        elif cadence == "monthly":
            key = (y, m)
        elif cadence == "quarterly":
            key = (y, (m - 1) // 3)
        elif cadence == "semiannual":
            key = (y, (m - 1) // 6)
        elif cadence == "annual":
            key = (y,)
        else:
            key = None
        if cadence == "biweekly":
            continue
        if key not in seen:
            seen.add(key)
            out.append(d)
    if cadence == "biweekly":
        out = cal[::10]  # first trading day of every second week (10 trading days), anchored at window start
    return out


def run_engine(data, idx, cal, cad_set, placebo_seed=None, entry_schedule=None):
    """One run. If placebo_seed is not None, entries follow entry_schedule
    {date: n_entries} with random name choice."""
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    cal_pos = {d: i for i, d in enumerate(cal)}
    full_cal = [r["date"] for r in data["SPY"]]  # incl. lead-in
    full_pos = {d: i for i, d in enumerate(full_cal)}

    def bar(sym, d):
        i = idx[sym].get(d)
        return data[sym][i] if i is not None else None

    import bisect
    dates_by = {s: [r["date"] for r in rows] for s, rows in data.items()}

    def mark(d, cash, positions):
        eq = cash
        for s, p in positions.items():
            i = idx[s].get(d)
            if i is None:  # fall back to last close on/before d
                k = bisect.bisect_right(dates_by[s], d) - 1
                if k >= 0:
                    eq += p["shares"] * data[s][k]["close"]
            else:
                eq += p["shares"] * data[s][i]["close"]
        return eq

    cash = START_CASH
    positions = {}
    orders = 0
    total_costs = 0.0
    curve = []
    halts = []           # {trigger, liquidated, restart or None, episode}
    episode = 1
    ep_start_balance = START_CASH
    state = "active"     # active | halt_pending | sitting | ended
    halt_trigger = None
    restart_after = None  # first date allowed to restart (liq date + 90 cal days)
    cad_close_hist = []   # equity at each cadence close (for the -4% block)
    entries_made = {}     # date -> count (recorded for the real run)
    prev_close_eq = START_CASH  # equity at close of trading day before current day

    def sell(sym, d, price, reason):
        nonlocal cash, total_costs, orders
        p = positions.pop(sym)
        gross = p["shares"] * price
        cost = gross * COST_RATE + SELL_FEE
        total_costs += cost
        cash += gross - cost
        orders += 1

    for d in cal:
        is_cad = d in cad_set
        is_last = (d == cal[-1])
        # ---- pending halt liquidation at today's open (engine convention) ----
        if state == "halt_pending":
            for s in list(positions):
                b = bar(s, d)
                if b:
                    sell(s, d, b["open"], "floor liquidation")
            if episode == 1:
                halts.append({"episode": 1, "trigger_date": halt_trigger,
                              "liquidation_date": d, "restart_date": None})
                restart_after = (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=90)).strftime("%Y-%m-%d")
                state = "sitting"
            else:
                halts.append({"episode": 2, "trigger_date": halt_trigger,
                              "liquidation_date": d, "restart_date": None})
                state = "ended"
            curve.append([d, round(cash, 4)])
            prev_close_eq = cash
            continue
        if state == "ended":
            curve.append([d, round(cash, 4)])
            prev_close_eq = cash
            continue
        if state == "sitting":
            if is_cad and d >= restart_after:
                state = "active"
                episode = 2
                ep_start_balance = cash
                halts[-1]["restart_date"] = d
                cad_close_hist = []
            else:
                curve.append([d, round(cash, 4)])
                prev_close_eq = cash
                continue
        # ---- active: cadence-date decisions ----
        if is_cad and state == "active":
            # signals from the prior trading day (full calendar)
            j = full_pos[d]
            sig_date = full_cal[j - 1] if j > 0 else None
            down_block = (len(cad_close_hist) >= 2 and
                          cad_close_hist[-1] <= 0.96 * cad_close_hist[-2])
            if sig_date and not down_block and len(positions) < 2:
                if rng is None:
                    quals = []
                    for s in UNIVERSE:
                        if s in positions:
                            continue
                        i = idx[s].get(sig_date)
                        if i is None or i < 21:
                            continue
                        rows = data[s]
                        b = rows[i]
                        prior10 = max(r["high"] for r in rows[i - 10:i])
                        gain5 = b["close"] / rows[i - 5]["close"] - 1.0
                        day_gain = b["close"] / rows[i - 1]["close"] - 1.0
                        vol20 = sum(r["volume"] for r in rows[i - 20:i]) / 20.0
                        vr = b["volume"] / vol20 if vol20 else 0.0
                        if b["close"] >= prior10 or (day_gain > 0.02 and vr > 1.5):
                            quals.append((s, gain5, vr))
                    quals.sort(key=lambda x: (-x[1], -x[2]))
                    picks = [q[0] for q in quals]
                else:
                    want = entry_schedule.get(d, 0) if entry_schedule else 0
                    eligible = sorted(s for s in UNIVERSE if s not in positions)
                    picks = rng.sample(eligible, min(want, len(eligible))) if want > 0 else []
                slots = 2 - len(positions)
                made = 0
                for s in picks:
                    if slots <= 0:
                        break
                    b = bar(s, d)
                    if b is None:
                        continue
                    alloc = min(0.50 * prev_close_eq, cash)
                    if alloc < 1.0:
                        break
                    price = b["open"]
                    shares = alloc / (price * (1 + COST_RATE))
                    cost_in = shares * price * (1 + COST_RATE)
                    total_costs += shares * price * COST_RATE
                    cash -= cost_in
                    positions[s] = {"shares": shares, "entry_price": price}
                    orders += 1
                    slots -= 1
                    made += 1
                if rng is None:
                    entries_made[d] = made
            # ---- exits on the cadence date ----
            for s in list(positions):
                b = bar(s, d)
                if b is None:
                    continue
                p = positions[s]
                stop, target = p["entry_price"] * (1 - STOP_PCT), p["entry_price"] * (1 + TARGET_PCT)
                if b["low"] <= stop:
                    sell(s, d, b["open"] if b["open"] < stop else stop, "stop")
                elif b["high"] >= target:
                    sell(s, d, b["open"] if b["open"] > target else target, "target")
                else:
                    jj = full_pos[d]
                    prev_low = data[s][idx[s][d] - 1]["low"] if idx[s].get(d, 0) > 0 else None
                    if prev_low is not None and b["close"] < prev_low:
                        sell(s, d, b["close"], "fade")
        # ---- close of day ----
        eq = mark(d, cash, positions)
        if is_last and positions:
            for s in list(positions):
                b = bar(s, d)
                if b:
                    sell(s, d, b["close"], "end of window")
            eq = cash
        curve.append([d, round(eq, 4)])
        prev_close_eq = eq
        if is_cad and state == "active":
            cad_close_hist.append(eq)
            floor = 0.85 * ep_start_balance
            if eq <= floor and not is_last:
                state = "halt_pending"
                halt_trigger = d
    final = curve[-1][1]
    peak, max_dd = START_CASH, 0.0
    for _, e in curve:
        peak = max(peak, e)
        max_dd = min(max_dd, e / peak - 1.0)
    years = (datetime.strptime(WIN_END, "%Y-%m-%d") - datetime.strptime(WIN_START, "%Y-%m-%d")).days / 365.25
    cagr = ((final / START_CASH) ** (1.0 / years) - 1.0) * 100 if final > 0 else -100.0
    return {"final": round(final, 2), "cagr_pct": round(cagr, 2),
            "max_dd_pct": round(max_dd * 100, 2), "costs": round(total_costs, 2),
            "orders": orders, "halts": halts,
            "restart": any(h["restart_date"] for h in halts),
            "second_halt": any(h["episode"] == 2 for h in halts),
            "curve": curve, "entries_made": entries_made}


def main():
    import gc
    only = sys.argv[1:] or None
    data = load_bars()
    idx = {s: {r["date"]: i for i, r in enumerate(rows)} for s, rows in data.items()}
    cal = [r["date"] for r in data["SPY"] if WIN_START <= r["date"] <= WIN_END]
    os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)
    results = {}
    for cad in CADENCES:
        if only and cad not in only:
            continue
        cell_path = os.path.join(HERE, "cells", f"{cad}.json")
        if os.path.exists(cell_path) and not only:
            print(cad, "already on disk - skipped", flush=True)
            continue
        cdates = cadence_dates(cal, cad)
        cad_set = set(cdates)
        real = run_engine(data, idx, cal, cad_set)
        twin_finals = []
        for seed in range(20):
            twin = run_engine(data, idx, cal, cad_set, placebo_seed=seed,
                              entry_schedule=real["entries_made"])
            twin_finals.append(twin["final"])
        beaten = sum(1 for f in twin_finals if real["final"] > f)
        cell = {"final": real["final"], "cagr_pct": real["cagr_pct"],
                "max_dd_pct": real["max_dd_pct"], "halts": len(real["halts"]),
                "restart": real["restart"], "second_halt": real["second_halt"],
                "costs": real["costs"], "orders": real["orders"],
                "placebo_beaten": beaten, "placebo_note": "20 random-entry twins, same entry-count schedule/exits/sizing/protection",
                "halts_detail": real["halts"],
                "equity_curve": real["curve"],
                "placebo_twin_finals": twin_finals}
        with open(cell_path, "w") as f:
            json.dump(cell, f, indent=1)
        results[cad] = {k: cell[k] for k in ("final", "cagr_pct", "max_dd_pct", "halts",
                                             "restart", "second_halt", "costs", "orders", "placebo_beaten")}
        print(cad, json.dumps(results[cad]), "twins:", twin_finals, flush=True)
        del cell, real
        gc.collect()
    if not only:
        with open(os.path.join(HERE, "sweep_summary.json"), "w") as f:
            json.dump(results, f, indent=1)


if __name__ == "__main__":
    main()
