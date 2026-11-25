#!/usr/bin/env python3
"""
THE GREAT RETEST (v10) - donchian-basket (tournament2 family F2).

Turtle-style Donchian channel breakout basket: 55-day high breakout entry /
20-day low exit, 9 ETFs (SPY QQQ IWM IEFA EEM GLD TLT VNQ DBC), max 5
positions, equal slices of equity/5 at entry. Long only, fractional shares.
Costs (program conventions, identical to the original engine): 0.10% of
trade value per side + $0.01 per sell order.

Data: the original tournament2 cache, read-only -
backtests/v3/tournament2-data/*.csv (Yahoo split-adjusted OHLC, NOT
dividend-adjusted). All 9 universe symbols share the SPY trading calendar
(verified). Signals use closes up to and including day t; executions at an
open (no look-ahead), exactly as the original.

This script does three things:

  1. INTEGRITY - imports the ORIGINAL backtests/v3/tournament2.py engine
     untouched and reproduces F2's published finals under the ORIGINAL
     rules (Terry's ladder-era floor: $85, rising to $100 at a $125 close
     and $125 at a $150 close; a close at/below the floor liquidates at
     the next open and ENDS the run):
       FULL 2016-11-21->2026-11-20  $148.86 (max DD 12.8%, never halted)
       DESIGN 2016-11-21->2022-12-31 $120.23
       VALIDATION 2023-01-01->2026-11-20 $119.62

  2. CADENCE SWEEP (SPEC) - DECADE 2016-11-21 -> 2026-11-20, $100/cell,
     v9 protections (plain -15% floor from the episode's starting balance,
     NO ladder; first halt: liquidate at the next open, sit in cash 90
     calendar days, restart at the next trading day with an episode-2
     floor of -15% from the restart balance; second halt ends the run).

     CADENCE TREATMENT (uniform SPEC definition, stated): the Donchian
     channel signals are computed from closes EVERY trading day - the
     channel is daily by construction (native cadence: daily-signal).
     Cadence governs EVALUATION / ENTRY / EXIT DATES only: signals
     computed on day t become pending; pending exits then entries execute
     at the open of the next cadence date. At the daily cadence this is
     exactly the original next-open behaviour. Pending signals are not
     re-tested against later closes - a breakout that fired stays pending
     until its execution date (the same honesty the daily original
     applies one day later), and an exit that fired stays pending even
     if price recovers before the execution date.
     Cadence dates: daily = every trading day; weekly = first trading
     day of each ISO week; biweekly = first trading day of every second
     week (weeks counted from the window's first week); monthly = first
     trading day of each month; quarterly = first trading day of each
     calendar quarter; semiannual = first trading day of each half-year;
     annual = first trading day of each year.

  3. PLACEBOS - 20 seeds per cell, random-entry twins: on each day the
     twin receives the SAME NUMBER of entry signals as the real strategy
     received that day, but the symbols are drawn at random (seeded) from
     the symbols not held and not already pending entry. Exits are the
     real 20-day-low Donchian exit applied to whatever the twin holds.
     Execution cadence, sizing, costs and v9 protections identical.
     (tournament2 ran NO placebos for this family - these are built fresh
     here, per the task.)

Benchmarks printed both ways, labeled: SPY buy-and-hold on the decade,
price-only (tournament2 bars, program costs) and dividend-adjusted
(long-run-2010 bars_adj construction on the read-only pxfull_SPY payload,
program costs).

Outputs (this folder): cells/<cadence>.json (full equity curve, halts /
restarts with dates, all 20 placebo twin finals), results.json,
integrity.json. Simulation only - no broker orders.
"""

import bisect
import importlib.util
import json
import os
import random
import sys
from datetime import date, timedelta

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
T2_DIR = os.path.join(ROOT, "v3")
T2_DATA = os.path.join(T2_DIR, "tournament2-data")
LR_DIR = os.path.join(ROOT, "long-run-2010")

START_CASH = 100.0
COST_RATE = 0.001
SELL_FEE = 0.01
UNIVERSE = ["SPY", "QQQ", "IWM", "IEFA", "EEM", "GLD", "TLT", "VNQ", "DBC"]
DECADE = (date(2016, 11, 21), date(2026, 11, 20))
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]
PLACEBO_SEEDS = list(range(1, 21))


# ----------------------------------------------------------------------------
# Data (numpy lists aligned to the shared SPY calendar)
# ----------------------------------------------------------------------------

def load_data():
    data = {}
    for sym in UNIVERSE + ["SPY"]:
        df = pd.read_csv(os.path.join(T2_DATA, f"{sym}.csv"))
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df = df.drop_duplicates("date").sort_values("date").reset_index(drop=True)
        df["high55_prev"] = df["high"].rolling(55).max().shift(1)
        df["low20_prev"] = df["low"].rolling(20).min().shift(1)
        data[sym] = {
            "dates": df["date"].tolist(),
            "open": df["open"].tolist(),
            "close": df["close"].tolist(),
            "high55": [None if pd.isna(x) else float(x) for x in df["high55_prev"]],
            "low20": [None if pd.isna(x) else float(x) for x in df["low20_prev"]],
            "pos": {d: i for i, d in enumerate(df["date"])},
        }
    return data


DATA = load_data()
CAL = DATA["SPY"]["dates"]


def bar(sym, d, field):
    i = DATA[sym]["pos"].get(d)
    if i is None:
        return None
    v = DATA[sym][field][i]
    return None if v is None else float(v)


def last_close(sym, d):
    dates = DATA[sym]["dates"]
    j = bisect.bisect_right(dates, d) - 1
    if j < 0:
        return None
    return float(DATA[sym]["close"][j])


# ----------------------------------------------------------------------------
# Cadence calendar
# ----------------------------------------------------------------------------

def cadence_dates(days, cadence):
    if cadence == "daily":
        return set(days)
    out = set()
    prev_key = None
    week_idx = -1
    for d in days:
        if cadence == "weekly":
            key = (d.isocalendar()[0], d.isocalendar()[1])
            if key != prev_key:
                out.add(d)
            prev_key = key
        elif cadence == "biweekly":
            key = (d.isocalendar()[0], d.isocalendar()[1])
            if key != prev_key:
                week_idx += 1
                if week_idx % 2 == 0:
                    out.add(d)
            prev_key = key
        elif cadence == "monthly":
            key = (d.year, d.month)
            if key != prev_key:
                out.add(d)
            prev_key = key
        elif cadence == "quarterly":
            key = (d.year, (d.month - 1) // 3)
            if key != prev_key:
                out.add(d)
            prev_key = key
        elif cadence == "semiannual":
            key = (d.year, (d.month - 1) // 6)
            if key != prev_key:
                out.add(d)
            prev_key = key
        elif cadence == "annual":
            key = d.year
            if key != prev_key:
                out.add(d)
            prev_key = key
    return out


# ----------------------------------------------------------------------------
# Sweep engine (F2 mechanics + cadence gating + v9 protections)
# ----------------------------------------------------------------------------

class Pot:
    def __init__(self):
        self.cash = START_CASH
        self.pos = {}          # sym -> shares
        self.total_costs = 0.0
        self.orders = 0

    def buy(self, sym, price, notional):
        if price is None or price <= 0 or notional <= 0:
            return
        cost = notional * COST_RATE
        if notional + cost > self.cash:
            notional = self.cash / (1.0 + COST_RATE)
            cost = notional * COST_RATE
        if notional < 0.01:
            return
        self.cash -= notional + cost
        self.pos[sym] = self.pos.get(sym, 0.0) + notional / price
        self.total_costs += cost
        self.orders += 1

    def sell_all(self, sym, price):
        if price is None or price <= 0 or sym not in self.pos:
            return
        value = self.pos[sym] * price
        cost = value * COST_RATE + SELL_FEE
        self.cash += value - cost
        self.total_costs += cost
        self.orders += 1
        del self.pos[sym]

    def equity(self, d, field):
        eq = self.cash
        for sym, sh in self.pos.items():
            px = bar(sym, d, field)
            if px is None:
                px = last_close(sym, d)
            eq += sh * px
        return eq


def run_cell(days, cadence, placebo_seed=None):
    """One DECADE run. Returns dict with final/cagr/maxdd/costs/orders,
    halts+restarts (dates), and the full daily equity curve."""
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    exec_days = cadence_dates(days, cadence)
    pf = Pot()
    pending_exits, pending_entries = [], []
    episode = 1
    episode_start = START_CASH
    floor = 0.85 * episode_start
    halts = []               # [{trigger, liquidation, episode}]
    restarts = []            # [{date, balance}]
    state = "active"         # active | liquidate_tomorrow | sitting | ended
    restart_on = None
    equity_curve = []

    for d in days:
        if state == "ended":
            equity_curve.append((d, pf.cash))
            continue
        if state == "sitting":
            if d >= restart_on:
                state = "active"
                episode = 2
                episode_start = pf.cash
                floor = 0.85 * episode_start
                restarts.append({"date": d.isoformat(),
                                  "balance": round(pf.cash, 2)})
                pending_exits, pending_entries = [], []
            else:
                equity_curve.append((d, pf.cash))
                continue
        if state == "liquidate_tomorrow":
            for sym in list(pf.pos.keys()):
                px = bar(sym, d, "open")
                if px is None:
                    px = last_close(sym, d)
                pf.sell_all(sym, px)
            pending_exits, pending_entries = [], []
            if episode == 1:
                halts[-1]["liquidation"] = d.isoformat()
                restart_on = d + timedelta(days=90)
                # first trading day on/after the 90-day sit-out end
                state = "sitting"
                equity_curve.append((d, pf.cash))
                continue
            halts[-1]["liquidation"] = d.isoformat()
            state = "ended"
            equity_curve.append((d, pf.cash))
            continue

        # --- active day: execute pending signals at the open on cadence dates
        if d in exec_days:
            for s in pending_exits:
                if s in pf.pos:
                    pf.sell_all(s, bar(s, d, "open"))
            exited = set(pending_exits)
            if pending_entries:
                eq = pf.equity(d, "open")
                slice_val = eq / 5.0
                for s in pending_entries:
                    if len(pf.pos) >= 5 or s in pf.pos or s in exited:
                        continue
                    o = bar(s, d, "open")
                    if o:
                        pf.buy(s, o, slice_val)
            pending_exits, pending_entries = [], []

        # --- compute today's signals from closes (daily by construction)
        real_entries = []
        for s in UNIVERSE:
            c = bar(s, d, "close")
            if c is None:
                continue
            if s in pf.pos:
                lo = bar(s, d, "low20")
                if lo is not None and c < lo and s not in pending_exits:
                    pending_exits.append(s)
            else:
                hi = bar(s, d, "high55")
                if hi is not None and c > hi:
                    real_entries.append(s)
        if rng is None:
            for s in real_entries:
                if s not in pending_entries:
                    pending_entries.append(s)
        else:
            # placebo twin: same NUMBER of entry signals today, random symbols
            pool = [s for s in UNIVERSE
                    if s not in pf.pos and s not in pending_entries
                    and s not in pending_exits]
            k = min(len(real_entries), len(pool))
            for s in rng.sample(pool, k) if k else []:
                pending_entries.append(s)

        # --- close: mark + v9 floor check
        eq = pf.equity(d, "close")
        equity_curve.append((d, eq))
        if eq <= floor:
            halts.append({"trigger": d.isoformat(), "liquidation": None,
                          "episode": episode})
            state = "liquidate_tomorrow"

    # end of window: liquidate at last close (original convention)
    last = days[-1]
    if pf.pos:
        for sym in list(pf.pos.keys()):
            px = bar(sym, last, "close")
            if px is None:
                px = last_close(sym, last)
            pf.sell_all(sym, px)
        equity_curve[-1] = (last, pf.cash)
    final = pf.cash

    eqs = [START_CASH] + [e for _, e in equity_curve]
    peak, maxdd = eqs[0], 0.0
    for e in eqs:
        peak = max(peak, e)
        if peak > 0:
            maxdd = max(maxdd, (peak - e) / peak)
    years = (days[-1] - days[0]).days / 365.25
    cagr = (final / START_CASH) ** (1.0 / years) - 1.0 if final > 0 else float("nan")
    return {
        "final": round(final, 2),
        "cagr_pct": round(cagr * 100.0, 2),
        "max_dd_pct": round(maxdd * 100.0, 1),
        "costs": round(pf.total_costs, 2),
        "orders": pf.orders,
        "halts": len(halts),
        "halt_detail": halts,
        "restart": bool(restarts),
        "restart_detail": restarts,
        "second_halt": any(h["episode"] == 2 for h in halts),
        "equity_curve": [[d.isoformat(), round(e, 2)] for d, e in equity_curve],
    }


# ----------------------------------------------------------------------------
# Benchmarks
# ----------------------------------------------------------------------------

def spy_price_only(days):
    o = bar("SPY", days[0], "open")
    c = bar("SPY", days[-1], "close")
    sh = (START_CASH / (1.0 + COST_RATE)) / o
    return round(sh * c * (1.0 - COST_RATE) - SELL_FEE, 2)


def spy_dividend_adjusted(days):
    sys.path.insert(0, LR_DIR)
    import lr_common as L
    bars = L.bars_adj(L.yahoo_payload("SPY"))
    sel = [b for b in bars if days[0].isoformat() <= b["d"] <= days[-1].isoformat()]
    o, c = sel[0]["o"], sel[-1]["c"]
    sh = (START_CASH / (1.0 + COST_RATE)) / o
    return round(sh * c * (1.0 - COST_RATE) - SELL_FEE, 2)


# ----------------------------------------------------------------------------
# Integrity: original engine, original (ladder-era) rules
# ----------------------------------------------------------------------------

def run_integrity():
    spec = importlib.util.spec_from_file_location(
        "tournament2_orig", os.path.join(T2_DIR, "tournament2.py"))
    T = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(T)
    for sym in T.SYMBOLS:
        T.DATA[sym] = T.prepare(T.load_symbol(sym))
    T.CAL = T.DATA["SPY"]["date"].tolist()
    out = {}
    for wname, (ws, we) in T.WINDOWS.items():
        days = T.window_days(ws, we)
        _pf, res = T.run_f2(wname, days)
        out[wname] = {
            "final": round(res["final"], 2),
            "cagr_pct": round(res["cagr_pct"], 2),
            "max_dd_pct": round(res["maxdd_pct"], 1),
            "orders": res["orders"],
            "costs": round(res["costs"], 2),
            "halt_date": res["halt_date"].isoformat() if res["halt_date"] else None,
        }
        print(f"integrity {wname}: final ${out[wname]['final']:.2f} "
              f"DD {out[wname]['max_dd_pct']}% orders {out[wname]['orders']} "
              f"halt {out[wname]['halt_date']}")
    return out


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main():
    days = [d for d in CAL if DECADE[0] <= d <= DECADE[1]]
    print(f"decade: {days[0]} -> {days[-1]} ({len(days)} trading days)")

    integrity = run_integrity()
    published = {"full": 148.86, "design": 120.23, "validation": 119.62}
    status = "reproduced"
    for w, pub in published.items():
        if abs(integrity[w]["final"] - pub) > 0.02:
            status = "FAILED"
    print(f"integrity status: {status}")
    with open(os.path.join(HERE, "integrity.json"), "w") as fh:
        json.dump({"status": status, "published": published,
                   "reproduced": integrity,
                   "conventions": "Original tournament2 engine imported "
                   "untouched; split-adjusted Yahoo bars from its own cache; "
                   "ladder-era floor ($85 rising to $100 at a $125 close, "
                   "$125 at a $150 close; close at/below floor liquidates at "
                   "next open and ends the run); costs 0.10%/side + $0.01 "
                   "per sell order."}, fh, indent=2)

    spy_price = spy_price_only(days)
    spy_adj = spy_dividend_adjusted(days)
    print(f"SPY decade: price-only ${spy_price} | dividend-adjusted ${spy_adj}")

    cells = {}
    for cad in CADENCES:
        res = run_cell(days, cad)
        twins = []
        for seed in PLACEBO_SEEDS:
            t = run_cell(days, cad, placebo_seed=seed)
            twins.append(t["final"])
        beaten = sum(1 for f in twins if res["final"] > f)
        print(f"{cad}: final ${res['final']:.2f} CAGR {res['cagr_pct']:+.2f}% "
              f"DD {res['max_dd_pct']}% costs ${res['costs']:.2f} "
              f"orders {res['orders']} halts {res['halts']} "
              f"placebo beaten {beaten}/20")
        cell = {
            "cadence": cad, "window": [days[0].isoformat(), days[-1].isoformat()],
            "start_cash": START_CASH,
            "final": res["final"], "cagr_pct": res["cagr_pct"],
            "max_dd_pct": res["max_dd_pct"], "costs": res["costs"],
            "orders": res["orders"],
            "halts": res["halt_detail"], "restarts": res["restart_detail"],
            "second_halt": res["second_halt"],
            "placebo_beaten": f"{beaten}/20",
            "placebo_twin_finals": twins,
            "equity_curve": res["equity_curve"],
        }
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as fh:
            json.dump(cell, fh, indent=1)
        cells[cad] = {
            "final": res["final"], "cagr_pct": res["cagr_pct"],
            "max_dd_pct": res["max_dd_pct"], "halts": res["halts"],
            "restart": res["restart"], "second_halt": res["second_halt"],
            "costs": res["costs"], "orders": res["orders"],
            "placebo_beaten": f"{beaten}/20",
            "placebo_note": "Random-entry twins built fresh for v10 "
            "(tournament2 ran none for this family): same number of entry "
            "signals per day as the real strategy, symbols drawn at random "
            "from non-held names; real 20-day-low exits; identical cadence "
            "gating, sizing, costs and v9 protections. 20 seeds (1-20).",
        }

    money = [c for c in CADENCES
             if cells[c]["final"] > spy_adj
             and int(cells[c]["placebo_beaten"].split("/")[0]) >= 11]
    results = {
        "slug": "donchian-basket",
        "area": "Monthly-era trend/rotation holding judged on the long road; "
                "in the cadence sweep: DECADE 2016-11-21 -> 2026-11-20 at "
                "every cadence (W9 assignment, SPEC cadence sweep).",
        "native_cadence": "daily-signal",
        "cadence": "daily-signal",
        "original_cadence_foreign": False,
        "original_cadence_note": "Not foreign: tournament2 ran F2 in its "
        "native form - Donchian channel signals computed daily from closes, "
        "executed at the next open. The sweep's daily cell is that form "
        "under v9 protections; slower cells gate execution to cadence "
        "dates while the channel signals are still computed daily.",
        "integrity": {
            "status": status,
            "original_finals": {"full": 148.86, "design": 120.23,
                                "validation": 119.62,
                                "full_max_dd_pct": 12.8,
                                "full_halted": False},
            "reproduced_finals": {w: integrity[w]["final"] for w in published},
            "conventions": "Reproduced through the ORIGINAL tournament2.py "
            "engine under ORIGINAL rules: split-adjusted bars, ladder-era "
            "floor ($85 -> $100 at $125 close -> $125 at $150 close; halt "
            "ends the run), costs 0.10%/side + $0.01/sell.",
        },
        "decade_spy_final": spy_adj,
        "decade_spy_price_only_final": spy_price,
        "decade_spy_note": "SPY buy-and-hold, DECADE, program costs both "
        "ways: $314.10 price-only (tournament2 split-adjusted bars) and "
        "$367.80 dividend-adjusted (long-run-2010 adjclose construction). "
        "The strategy's own bars are price-only, so its finals are "
        "understated by the ETFs' dividends just as the price-only SPY "
        "figure is; the dividend-adjusted figure is the honest "
        "real-index-fund bar.",
        "champion_decade_final": 65.89,
        "champion_note": "Champion (value+momentum) DECADE $65.89 after two "
        "halts - quoted with the SPEC caveat: its crown rests on the 2010 "
        "and 2019 roads, not the decade.",
        "cells": cells,
        "money_cadences": money,
        "verdict_area": None,  # filled in RESULTS.md narrative; set below
        "verdict_change": None,
    }
    # verdict fields are finalized after the numbers are seen (see RESULTS.md)
    with open(os.path.join(HERE, "results.json"), "w") as fh:
        json.dump(results, fh, indent=2)
    print("wrote results.json, integrity.json, cells/*.json")


if __name__ == "__main__":
    main()
