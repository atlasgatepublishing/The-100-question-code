#!/usr/bin/env python3
"""HOLDINGS-COUNT SWEEP — donchian-basket HOUSE form (v9/v10, tournament2 F2).
Frozen rendering (SWEEP-SPEC.md, written before runs): 55-day-high breakout
entry / 20-day-low exit, long-only, 9 ETFs, signals from closes daily,
execution at next open (the v10 daily cell). The ONLY varied parameter is
the max-concurrent-positions cap N. Slice size stays the published form —
equity/5 at entry — at every N. ALL-ELIGIBLE = cap 9 (whole universe).
v9 protections: plain -15% floor from episode start; halt -> liquidate at
next open, sit out 90 calendar days, restart with -15% floor from restart
balance; second halt ends the run. Costs 0.10%/side + $0.01 per sell order.
Reproduction target: N=5 DECADE = $148.86 (v10 daily cell, to the cent).
Roads: DECADE/CONT/VAL + CONF_A/CONF_B (all counts). Placebos: 20 seeds,
DECADE only (PEAD precedent), v10 random-entry twin design.
Data read-only: backtests/v3/tournament2-data/*.csv. Output: house_results.json.
"""
import bisect, json, os, random, statistics
from datetime import date, timedelta
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
T2_DATA = os.path.join(ROOT, "backtests", "v3", "tournament2-data")
START_CASH = 100.0
COST_RATE = 0.001
SELL_FEE = 0.01
UNIVERSE = ["SPY", "QQQ", "IWM", "IEFA", "EEM", "GLD", "TLT", "VNQ", "DBC"]
COUNTS = [1, 2, 3, 5, 8, 10, 15, 20, 30, None]  # None = ALL-ELIGIBLE
WINDOWS = {"DECADE": (date(2016, 11, 21), date(2026, 11, 20)),
           "CONT": (date(2019, 1, 2), date(2026, 11, 20)),
           "VAL": (date(2023, 1, 3), date(2026, 11, 20)),
           "CONF_A": (date(2017, 1, 1), date(2020, 12, 31)),
           "CONF_B": (date(2021, 1, 1), date(2024, 12, 31))}

def load_data():
    data = {}
    for sym in UNIVERSE:
        df = pd.read_csv(os.path.join(T2_DATA, f"{sym}.csv"))
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df = df.drop_duplicates("date").sort_values("date").reset_index(drop=True)
        df["high55_prev"] = df["high"].rolling(55).max().shift(1)
        df["low20_prev"] = df["low"].rolling(20).min().shift(1)
        data[sym] = {"dates": df["date"].tolist(),
                     "open": df["open"].tolist(), "close": df["close"].tolist(),
                     "high55": [None if pd.isna(x) else float(x) for x in df["high55_prev"]],
                     "low20": [None if pd.isna(x) else float(x) for x in df["low20_prev"]],
                     "pos": {d: i for i, d in enumerate(df["date"])}}
    return data

DATA = load_data()
CAL = DATA["SPY"]["dates"]

def bar(sym, d, field):
    i = DATA[sym]["pos"].get(d)
    if i is None: return None
    v = DATA[sym][field][i]
    return None if v is None else float(v)

def last_close(sym, d):
    dates = DATA[sym]["dates"]
    j = bisect.bisect_right(dates, d) - 1
    return None if j < 0 else float(DATA[sym]["close"][j])

class Pot:
    def __init__(self):
        self.cash = START_CASH; self.pos = {}; self.total_costs = 0.0; self.orders = 0
    def buy(self, sym, price, notional):
        if price is None or price <= 0 or notional <= 0: return
        cost = notional * COST_RATE
        if notional + cost > self.cash:
            notional = self.cash / (1.0 + COST_RATE); cost = notional * COST_RATE
        if notional < 0.01: return
        self.cash -= notional + cost
        self.pos[sym] = self.pos.get(sym, 0.0) + notional / price
        self.total_costs += cost; self.orders += 1
    def sell_all(self, sym, price):
        if price is None or price <= 0 or sym not in self.pos: return
        value = self.pos[sym] * price
        cost = value * COST_RATE + SELL_FEE
        self.cash += value - cost; self.total_costs += cost; self.orders += 1
        del self.pos[sym]
    def equity(self, d, field):
        eq = self.cash
        for sym, sh in self.pos.items():
            px = bar(sym, d, field)
            if px is None: px = last_close(sym, d)
            eq += sh * px
        return eq

def run_cell(days, cap, placebo_seed=None):
    """Daily cadence (v10 daily cell) with max-concurrent cap; slice = equity/5."""
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    pf = Pot()
    pending_exits, pending_entries = [], []
    episode = 1; episode_start = START_CASH; floor = 0.85 * episode_start
    halts = []; restarts = []
    state = "active"; restart_on = None
    equity_curve = []
    for d in days:
        if state == "ended":
            equity_curve.append((d, pf.cash)); continue
        if state == "sitting":
            if d >= restart_on:
                state = "active"; episode = 2; episode_start = pf.cash
                floor = 0.85 * episode_start
                restarts.append({"date": d.isoformat(), "balance": round(pf.cash, 2)})
                pending_exits, pending_entries = [], []
            else:
                equity_curve.append((d, pf.cash)); continue
        if state == "liquidate_tomorrow":
            for sym in list(pf.pos.keys()):
                px = bar(sym, d, "open")
                if px is None: px = last_close(sym, d)
                pf.sell_all(sym, px)
            pending_exits, pending_entries = [], []
            halts[-1]["liquidation"] = d.isoformat()
            if episode == 1:
                restart_on = d + timedelta(days=90); state = "sitting"
            else:
                state = "ended"
            equity_curve.append((d, pf.cash)); continue
        # execute pending at today's open (daily cadence)
        for s in pending_exits:
            if s in pf.pos: pf.sell_all(s, bar(s, d, "open"))
        exited = set(pending_exits)
        if pending_entries:
            eq = pf.equity(d, "open"); slice_val = eq / 5.0
            for s in pending_entries:
                if len(pf.pos) >= cap or s in pf.pos or s in exited: continue
                o = bar(s, d, "open")
                if o: pf.buy(s, o, slice_val)
        pending_exits, pending_entries = [], []
        # today's signals from closes
        real_entries = []
        for s in UNIVERSE:
            c = bar(s, d, "close")
            if c is None: continue
            if s in pf.pos:
                lo = bar(s, d, "low20")
                if lo is not None and c < lo and s not in pending_exits:
                    pending_exits.append(s)
            else:
                hi = bar(s, d, "high55")
                if hi is not None and c > hi: real_entries.append(s)
        if rng is None:
            for s in real_entries:
                if s not in pending_entries: pending_entries.append(s)
        else:
            pool = [s for s in UNIVERSE if s not in pf.pos
                    and s not in pending_entries and s not in pending_exits]
            k = min(len(real_entries), len(pool))
            for s in (rng.sample(pool, k) if k else []):
                pending_entries.append(s)
        eq = pf.equity(d, "close")
        equity_curve.append((d, eq))
        if eq <= floor:
            halts.append({"trigger": d.isoformat(), "liquidation": None, "episode": episode})
            state = "liquidate_tomorrow"
    last = days[-1]
    if pf.pos:
        for sym in list(pf.pos.keys()):
            px = bar(sym, last, "close")
            if px is None: px = last_close(sym, last)
            pf.sell_all(sym, px)
        equity_curve[-1] = (last, pf.cash)
    final = pf.cash
    eqs = [START_CASH] + [e for _, e in equity_curve]
    peak, maxdd = eqs[0], 0.0
    for e in eqs:
        peak = max(peak, e)
        if peak > 0: maxdd = max(maxdd, (peak - e) / peak)
    return {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 1),
            "costs": round(pf.total_costs, 2), "orders": pf.orders,
            "halts": len(halts), "halt_detail": halts, "restart_detail": restarts,
            "curve": [[d.isoformat(), round(e, 2)] for d, e in equity_curve]}

def period_stats(curve):
    bym = {}
    for dstr, v in curve: bym[dstr[:7]] = v
    keys = sorted(bym); rets = []; prev = 100.0
    for k in keys:
        rets.append(bym[k] / prev - 1); prev = bym[k]
    if not rets: return None
    prof = sum(1 for r in rets if r > 0)
    worst_run = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; worst_run = max(worst_run, cur)
    peak, since, longest = 100.0, 0, 0
    for k in keys:
        if bym[k] >= peak: peak = bym[k]; longest = max(longest, since); since = 0
        else: since += 1
    longest = max(longest, since)
    return {"period": "calendar month", "n_periods": len(rets),
            "pct_profitable": round(100 * prof / len(rets), 1),
            "median_pct": round(statistics.median(rets) * 100, 2),
            "mean_pct_secondary_average": round(statistics.mean(rets) * 100, 2),
            "best_pct": round(max(rets) * 100, 2), "worst_pct": round(min(rets) * 100, 2),
            "longest_losing_run_periods": worst_run,
            "longest_stretch_between_new_highs_periods": longest}

def main():
    out = {"form": "house-v9-donchian", "native_count": 5,
           "counts_grid": ["ALL" if c is None else c for c in COUNTS], "cells": {}}
    days_by_w = {w: [d for d in CAL if a <= d <= b] for w, (a, b) in WINDOWS.items()}
    for n in COUNTS:
        cap = 9 if n is None else n
        key = "ALL" if n is None else str(n)
        cell = {}
        for w, days in days_by_w.items():
            r = run_cell(days, cap)
            cell[w] = {k: v for k, v in r.items() if k != "curve"}
            if w == "DECADE":
                cell[w]["curve"] = r["curve"]
                cell[w]["period_stats_monthly"] = period_stats(r["curve"])
        days = days_by_w["DECADE"]
        twins = [run_cell(days, cap, placebo_seed=s)["final"] for s in range(1, 21)]
        real = cell["DECADE"]["final"]
        cell["placebos_decade"] = {"finals": twins,
            "beaten": sum(1 for t in twins if real > t),
            "median": round(statistics.median(twins), 2)}
        out["cells"][key] = cell
        print(f"house cap {key}: DECADE {cell['DECADE']['final']} CONT {cell['CONT']['final']} "
              f"VAL {cell['VAL']['final']} plb {cell['placebos_decade']['beaten']}/20", flush=True)
    json.dump(out, open(os.path.join(HERE, "house_results.json"), "w"), indent=1)
    print("saved house_results.json")

if __name__ == "__main__":
    main()
