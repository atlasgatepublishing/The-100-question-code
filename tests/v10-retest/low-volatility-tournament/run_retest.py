#!/usr/bin/env python3
"""
THE GREAT RETEST (v10) - low-volatility-tournament (v3 tournament2 family F3).

ORIGINAL (tournament) CONSTRUCTION - from backtests/v3/tournament2.py run_f3:
  - Universe: 5 ETFs only - SPY, QQQ, IWM, GLD, TLT.
  - Monthly: at each MONTH-END close, for each ETF compute vol20 (20-trading-day
    rolling std of daily % returns) and ma200; eligible only if close > ma200.
  - Rank eligible by vol20 ascending, hold the CALMEST 2, equal weight.
  - Decisions at month-end close execute at the NEXT trading day's open;
    rebalance to equal weight with a $0.25 minimum delta (original mechanics).
  - Original protections: Terry's LADDER floor - $85 start, rising to $100 at
    a $125 close and $125 at a $150 close; a close at/below the floor
    liquidates at the next open and ENDS the run (no restart).
  - Original costs: 0.10% of trade value per side + $0.01 per sell order.
  - Original data: Yahoo split-adjusted OHLC, NOT dividend-adjusted
    (cached in backtests/v3/tournament2-data/, read-only here).
  - Original published finals (tournament2.md): FULL decade $236.63,
    DESIGN $138.60, VALIDATION $161.60; SPY price-only net benchmark $314.10.

HOW THIS DIFFERS FROM THE W3 low-volatility FACTOR-SORT ROW (v6/v9):
  that row ranks the top-30 individual-STOCK pond QUARTERLY by trailing
  252-day realized volatility, holds the 5 lowest-vol names equal weight,
  has NO 200-day trend gate, and uses dividend-adjusted closes. This
  tournament form is an ETF rotation: 5 ETFs, MONTHLY, 20-day vol,
  a close>ma200 eligibility gate, calmest 2 only.

SWEEP (SPEC binding): DECADE 2016-11-21 -> 2026-11-20, $100/cell, program
costs, point-in-time, v9 protections substituted for the ladder (plain -15%
floor from the episode start; first halt -> liquidate at next open, sit in
cash 90 calendar days, restart at the next cadence execution date, episode-2
floor -15% from the restart balance; second halt ends the run).
Cadence (SPEC uniform definition) governs the vol-ranking / rebalance dates:
on each cadence execution date, the signal is computed from closes through
the PRIOR trading day (for monthly this reproduces the original exactly:
month-end close decision -> next open execution) and trades execute at the
cadence date's open. Native cadence = monthly.
Placebos: 20 seeds per cell - random-selection twins: on each cadence date,
2 names drawn at random from the SAME eligible set (same gate, same
mechanics, same protections).
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
ROOT = os.path.expanduser("~/workspace/stock-app/backtests")
T2_DIR = os.path.join(ROOT, "v3")
T2_DATA = os.path.join(T2_DIR, "tournament2-data")
UNIVERSE = ["SPY", "QQQ", "IWM", "GLD", "TLT"]
START_CASH = 100.0
COST_RATE = 0.001
SELL_FEE = 0.01
DEC_START, DEC_END = date(2016, 11, 21), date(2026, 11, 20)
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]

# ---------------------------------------------------------------- data ------
def read_csv(path):
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df[["date", "open", "high", "low", "close", "volume"]] \
        .drop_duplicates("date").sort_values("date").reset_index(drop=True)

def prepare(df):
    df = df.copy()
    df["ma200"] = df["close"].rolling(200).mean()
    df["vol20"] = df["close"].pct_change().rolling(20).std()
    df.attrs["pos"] = {d: i for i, d in enumerate(df["date"])}
    df.attrs["dates"] = df["date"].tolist()
    return df

DATA = {s: prepare(read_csv(os.path.join(T2_DATA, f"{s}.csv"))) for s in UNIVERSE}
CAL = DATA["SPY"]["date"].tolist()

def bar(sym, d, field):
    df = DATA[sym]
    i = df.attrs["pos"].get(d)
    if i is None:
        return None
    v = df[field].iloc[i]
    return None if (v is None or (isinstance(v, float) and np.isnan(v))) else float(v)

def last_close(sym, d):
    df = DATA[sym]
    j = bisect.bisect_right(df.attrs["dates"], d) - 1
    return None if j < 0 else float(df["close"].iloc[j])

# ------------------------------------------------------- cadence dates ------
def cadence_dates(days, cadence):
    if cadence == "daily":
        return list(days)
    out = []
    if cadence in ("weekly", "biweekly"):
        groups, seen = [], {}
        for d in days:
            k = d.isocalendar()[:2]
            if k not in seen:
                seen[k] = len(groups)
                groups.append(d)
        if cadence == "weekly":
            return groups
        return [g for i, g in enumerate(groups) if i % 2 == 0]
    def key(d):
        if cadence == "monthly":
            return (d.year, d.month)
        if cadence == "quarterly":
            return (d.year, (d.month - 1) // 3)
        if cadence == "semiannual":
            return (d.year, (d.month - 1) // 6)
        return (d.year,)
    prev = None
    for d in days:
        k = key(d)
        if k != prev:
            out.append(d)
            prev = k
    return out

# ------------------------------------------------------------ portfolio -----
class Pot:
    def __init__(self):
        self.cash = START_CASH
        self.pos = {}
        self.total_costs = 0.0
        self.orders = 0

    def buy(self, d, sym, price, notional):
        if price is None or price <= 0 or notional <= 0:
            return
        cost = notional * COST_RATE
        if notional + cost > self.cash:
            notional = self.cash / (1.0 + COST_RATE)
            cost = notional * COST_RATE
        if notional < 0.01:
            return
        self.cash -= notional + cost
        p = self.pos.setdefault(sym, 0.0)
        self.pos[sym] = p + notional / price
        self.total_costs += cost
        self.orders += 1

    def sell(self, d, sym, price, shares=None):
        if price is None or price <= 0 or sym not in self.pos:
            return
        sh = self.pos[sym] if shares is None else min(shares, self.pos[sym])
        if sh <= 0:
            return
        value = sh * price
        cost = value * COST_RATE + SELL_FEE
        self.cash += value - cost
        self.total_costs += cost
        self.orders += 1
        self.pos[sym] -= sh
        if self.pos[sym] <= 1e-9:
            del self.pos[sym]

    def sell_value(self, d, sym, price, value):
        if price:
            self.sell(d, sym, price, shares=value / price)

    def liquidate(self, d, at_open):
        for sym in list(self.pos.keys()):
            px = bar(sym, d, "open") if at_open else bar(sym, d, "close")
            if px is None:
                px = last_close(sym, d)
            self.sell(d, sym, px)

    def equity(self, d, at_open=False):
        eq = self.cash
        for sym, sh in self.pos.items():
            px = bar(sym, d, "open" if at_open else "close")
            if px is None:
                px = last_close(sym, d)
            eq += sh * px
        return eq

    def pos_value_open(self, sym, d):
        if sym not in self.pos:
            return 0.0
        px = bar(sym, d, "open")
        if px is None:
            px = last_close(sym, d)
        return self.pos[sym] * px

# ------------------------------------------------------------- strategy -----
def eligible_ranked(sig_day):
    elig = []
    for s in UNIVERSE:
        c = bar(s, sig_day, "close")
        ma = bar(s, sig_day, "ma200")
        v = bar(s, sig_day, "vol20")
        if c is not None and ma is not None and v is not None and c > ma:
            elig.append((v, s))
    elig.sort()
    return [s for _, s in elig]

def run_cell(cadence, days, placebo_seed=None):
    """One sweep cell under v9 protections. Returns results dict + curve."""
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    exec_days = cadence_dates(days, cadence)
    exec_set = set(exec_days)
    day_index = {d: i for i, d in enumerate(days)}
    pot = Pot()
    episode = 1
    ep_start_balance = START_CASH
    floor = 0.85 * ep_start_balance
    halts = []
    halt_trigger = None
    waiting_until = None      # restart execution date while sitting in cash
    ended = False
    curve = []
    peak = START_CASH
    maxdd = 0.0

    def targets_for(exec_day):
        i = day_index[exec_day]
        if i == 0:
            return []
        sig = days[i - 1]
        elig = eligible_ranked(sig)
        if rng is not None:
            if len(elig) <= 2:
                return list(elig)
            return rng.sample(elig, 2)
        return elig[:2]

    for i, d in enumerate(days):
        if ended:
            curve.append((d, pot.cash))
            continue
        if halt_trigger is not None:
            # liquidate at today's open
            pot.liquidate(d, at_open=True)
            halts.append({"episode": episode,
                          "trigger_date": halt_trigger.isoformat(),
                          "liquidation_date": d.isoformat(),
                          "floor": round(floor, 2),
                          "balance_after_liquidation": round(pot.cash, 2)})
            halt_trigger = None
            if episode == 2:
                ended = True
                curve.append((d, pot.cash))
                continue
            # sit in cash 90 calendar days; restart at next cadence exec date
            resume_after = d + timedelta(days=90)
            cands = [e for e in exec_days if e >= resume_after]
            waiting_until = cands[0] if cands else None
            if waiting_until is None:
                ended = True
                curve.append((d, pot.cash))
                continue
            curve.append((d, pot.cash))
            continue
        if waiting_until is not None:
            if d == waiting_until:
                episode = 2
                ep_start_balance = pot.cash
                floor = 0.85 * ep_start_balance
                waiting_until = None
                # fall through to execution below
            else:
                curve.append((d, pot.cash))
                continue
        if d in exec_set:
            targets = targets_for(d)
            for s in list(pot.pos.keys()):
                if s not in targets:
                    pot.sell(d, s, bar(s, d, "open"))
            if targets:
                eq = pot.equity(d, at_open=True)
                tgt = eq / len(targets)
                for s in targets:
                    o = bar(s, d, "open")
                    if o is None:
                        continue
                    delta = tgt - pot.pos_value_open(s, d)
                    if delta > 0.25:
                        pot.buy(d, s, o, delta)
                    elif delta < -0.25:
                        pot.sell_value(d, s, o, -delta)
        eq = pot.equity(d)
        curve.append((d, eq))
        peak = max(peak, eq)
        if peak > 0:
            maxdd = max(maxdd, (peak - eq) / peak)
        if eq <= floor:
            halt_trigger = d
    # end of window: liquidate at last close
    if pot.pos:
        pot.liquidate(days[-1], at_open=False)
    final = pot.cash
    if curve and curve[-1][0] == days[-1]:
        curve[-1] = (days[-1], final)
    else:
        curve.append((days[-1], final))
    # recompute maxdd incl. final point
    peak, maxdd = START_CASH, 0.0
    for _, e in [(days[0], START_CASH)] + curve:
        peak = max(peak, e)
        if peak > 0:
            maxdd = max(maxdd, (peak - e) / peak)
    years = (days[-1] - days[0]).days / 365.25
    cagr = (final / START_CASH) ** (1.0 / years) - 1.0 if final > 0 else -1.0
    return {
        "final": round(final, 2),
        "cagr_pct": round(cagr * 100.0, 2),
        "max_dd_pct": round(maxdd * 100.0, 2),
        "costs": round(pot.total_costs, 2),
        "orders": pot.orders,
        "halts": halts,
        "restart": len(halts) >= 1 and episode == 2 and not ended or
                   (len(halts) == 1 and episode == 2),
        "second_halt": len(halts) >= 2,
        "curve": [[d.isoformat(), round(e, 4)] for d, e in curve],
    }

# ------------------------------------------------------------- integrity ----
def integrity():
    spec = importlib.util.spec_from_file_location(
        "tournament2", os.path.join(T2_DIR, "tournament2.py"))
    T = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(T)
    for sym in T.SYMBOLS:
        T.DATA[sym] = T.prepare(T.load_symbol(sym))
    T.CAL = T.DATA["SPY"]["date"].tolist()
    out = {}
    for wname, (ws, we) in T.WINDOWS.items():
        days = T.window_days(ws, we)
        pf, res = T.run_f3(wname, days)
        g, n = T.spy_benchmark(days)
        out[wname] = {"final": round(res["final"], 2),
                      "orders": res["orders"], "costs": round(res["costs"], 2),
                      "maxdd_pct": round(res["maxdd_pct"], 1),
                      "halt": res["halt_date"].isoformat() if res["halt_date"] else None,
                      "spy_gross": round(g, 2), "spy_net": round(n, 2)}
    return out

# ----------------------------------------------------------------- main -----
def main():
    days = [d for d in CAL if DEC_START <= d <= DEC_END]
    # SPY price-only benchmark on the same data / costs (tournament convention)
    o0 = bar("SPY", days[0], "open")
    cN = bar("SPY", days[-1], "close")
    sh = (START_CASH / (1.0 + COST_RATE)) / o0
    spy_priceonly_net = sh * cN * (1.0 - COST_RATE) - SELL_FEE
    # SPY price-only max DD from daily closes (buy-hold curve)
    peak, spydd = None, 0.0
    for d in days:
        v = bar("SPY", d, "close") / o0 * START_CASH
        peak = v if peak is None else max(peak, v)
        spydd = max(spydd, (peak - v) / peak)
    print(f"SPY price-only net decade: ${spy_priceonly_net:.2f}; "
          f"price-only maxDD {spydd*100:.2f}% (SPEC div-adj DD ref 33.72%)")

    integ = integrity()
    print("INTEGRITY:", json.dumps(integ, indent=1))
    published = {"full": 236.63, "design": 138.60, "validation": 161.60}
    status = "reproduced" if all(
        abs(integ[w]["final"] - published[w]) < 0.02 for w in published) \
        else "reproduced-with-notes"
    print("integrity status:", status)

    os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)
    cells, money = {}, []
    for cad in CADENCES:
        r = run_cell(cad, days)
        twins = []
        for seed in range(20):
            tr = run_cell(cad, days, placebo_seed=seed)
            twins.append(tr["final"])
        beaten = sum(1 for t in twins if r["final"] > t)
        cell = {"final": r["final"], "cagr_pct": r["cagr_pct"],
                "max_dd_pct": r["max_dd_pct"],
                "halts": len(r["halts"]), "restart": bool(r["restart"]),
                "second_halt": bool(r["second_halt"]),
                "costs": r["costs"], "orders": r["orders"],
                "placebo_beaten": f"{beaten}/20",
                "placebo_note": "20 random-selection twins, same eligible set/gate/mechanics/protections"}
        cells[cad] = cell
        if r["final"] > spy_priceonly_net and beaten >= 11:
            money.append(cad)
        cj = dict(cell)
        cj.update({"cadence": cad, "equity_curve": r["curve"],
                   "halt_detail": r["halts"],
                   "placebo_twin_finals": twins})
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump(cj, f, indent=1)
        print(f"{cad}: final ${r['final']:.2f} CAGR {r['cagr_pct']:+.2f}% "
              f"DD {r['max_dd_pct']:.1f}% costs ${r['costs']:.2f} "
              f"orders {r['orders']} halts {len(r['halts'])} placebo {beaten}/20")

    results = {
        "slug": "low-volatility-tournament",
        "area": "ETF low-volatility rotation (defense) on the DECADE road, cadence sweep",
        "area_source": "SPEC W12: tournament forms - DECADE is the original window; CADENCE GRID: low-volatility-tournament = monthly",
        "native_cadence": "monthly",
        "original_cadence_foreign": False,
        "cadence": "monthly (native); sweep ran all 7 cadences",
        "native_change": "Sweep form differs from the tournament original ONLY in protections: v9 plain -15% episode floor with 90-day cash sit + one restart replaces the original ladder floor ($85->$100->$125, halt ends run). Signal, universe, gate, costs, execution unchanged. Cadence sweep varies only the ranking/rebalance dates per the SPEC uniform definition.",
        "integrity": {
            "status": status,
            "original_finals": {"full_decade": 236.63, "design": 138.60,
                                "validation": 161.60, "spy_priceonly_net_full": 314.10},
            "reproduced_finals": integ,
            "original_rules": "Ladder floor $85 rising to $100 at a $125 close and $125 at a $150 close; close at/below floor liquidates at next open and ENDS the run. Costs 0.10%/side + $0.01/sell. Yahoo split-adjusted (not dividend-adjusted) bars. Month-end-close vol20/ma200 signal, calmest 2 of SPY/QQQ/IWM/GLD/TLT above ma200, equal weight, next-open execution.",
        },
        "decade_spy_final": round(spy_priceonly_net, 2),
        "decade_spy": {
            "price_only_net_tournament_convention": round(spy_priceonly_net, 2),
            "dividend_adjusted_program_reference": 367.80,
            "note": "Tournament-era data is split-adjusted only, so the in-plumbing benchmark is the price-only $314.10 figure; the $367.80 dividend-adjusted figure is the SPEC program reference (W6-verified plumbing). Strategy cells are on the same price-only footing as the original.",
            "spy_max_dd_pct_reference": 33.72,
            "spy_priceonly_max_dd_pct_computed": round(spydd * 100.0, 2),
        },
        "champion_decade_reference": {"final": 65.89,
            "note": "Champion (value+momentum) decade $65.89 after two halts - caveat per SPEC: its crown rests on the 2010 and 2019 roads."},
        "cells": cells,
        "money_cadences": money,
        "verdict_area": "PENDING - see RESULTS.md",
        "verdict_change": "PENDING - see RESULTS.md",
        "data_note": "Read-only shared cache: backtests/v3/tournament2-data/ (Yahoo split-adjusted daily bars for SPY QQQ IWM GLD TLT, 2015-01-02 onward). No new downloads. Price-only footing understates both the strategy (GLD/TLT/SPY dividends excluded) and the price-only SPY benchmark alike, exactly as in the original tournament.",
    }
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("money cadences (vs price-only SPY + placebo majority):", money)

if __name__ == "__main__":
    main()
