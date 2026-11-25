#!/usr/bin/env python3
"""
GEM DUAL MOMENTUM (Antonacci GEM, tournament2 family F1) — v10 GREAT RETEST.
Simulation only — no broker orders.

Strategy (frozen, from backtests/v3/tournament2.py run_f1):
  Universe of possible holdings: SPY, IEFA (risk assets), AGG (defensive),
  SHY (cash-proxy benchmark for the absolute-momentum test).
  At each evaluation: compute 252-trading-day total (price) return of SPY,
  IEFA and SHY from closes up to the signal day. Hold the better of SPY/IEFA
  if its 252d return beats SHY's; otherwise hold AGG. All-in, one asset,
  fractional shares. Published form: monthly (month-end close signal,
  next-open execution).

Costs (program, identical to the original engine): 0.10% of trade value on
every buy and every sell, plus $0.01 per sell order.

INTEGRITY mode (original rules): ladder-era floor ($85, rising to $100 at a
$125 close and $125 at a $150 close; a close at/below the floor liquidates at
the next open and ENDS the run), month-end decisions executing at the next
open, windows FULL 2016-11-21->2026-11-20, DESIGN 2016-11-21->2022-12-31,
VALIDATION 2023-01-01->2026-11-20. Published: FULL $96.66 (halted
2020-02-28), DESIGN $96.66, VALIDATION $150.22.

SWEEP mode (SPEC v10): DECADE 2016-11-21 -> 2026-11-20, $100/cell, v9
protections — plain -15% floor from the episode's starting balance (checked
at every close), liquidate at the next open on a halt; on the FIRST halt sit
in cash 90 calendar days and restart at the next cadence date under an
episode-2 floor of -15% from the restart balance; a second halt ends the run.
Cadence governs the momentum evaluation / rotation dates, uniformly:
cadence dates are the first trading day of each period (daily = every
trading day; weekly = first trading day of each ISO week; biweekly = first
trading day of every second week anchored on the week containing the window
start; monthly = first trading day of each month; quarterly = first trading
day of each calendar quarter; semi-annual = first trading day of each
half-year; annual = first trading day of each year). The window's first
trading day is a cadence date. The signal uses closes through the PRIOR
trading day and the rotation executes at the cadence date's open — for the
monthly cadence this is trade-for-trade the published form's execution set
(month-end close signal -> next open), plus the initial entry at the window
start, which the original (whose first decision was the first month-end)
did not make. That one-entry difference is documented, never hidden.

PLACEBOS: per cell, 20 seeds. A rotation placebo picks its target uniformly
at random from the same possible holdings {SPY, IEFA, AGG} at each cadence
date (seeded RNG), through the identical cadence machinery, costs and v9
protection. placebo_beaten = number of the 20 twin finals the real run beat
(strictly greater final).

Data: read-only shared cache backtests/v3/tournament2-data/{SPY,IEFA,AGG,SHY}.csv
(Yahoo split-adjusted daily bars 2015-01-02 -> 2026-11-20, NOT dividend
adjusted — the original tournament's own convention). Only these 4 symbols
are loaded. No downloads; no shared folder written.
SPY decade benchmark: price-only net $314.10 computed in this plumbing (the
original tournament's figure); dividend-adjusted $367.80 is the program
reference (SPEC) and is reported labeled as such — it cannot be computed
from this price-only cache.
"""

import bisect
import csv
import json
import math
import os
import random
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.expanduser("~/workspace/stock-app/backtests/v3/tournament2-data")
CELLS = os.path.join(HERE, "cells")
os.makedirs(CELLS, exist_ok=True)

SYMS = ["SPY", "IEFA", "AGG", "SHY"]
RISK = ["SPY", "IEFA"]
HOLDINGS = ["SPY", "IEFA", "AGG"]
COST_RATE = 0.001
SELL_FEE = 0.01
POT0 = 100.0
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]
DECADE = (date(2016, 11, 21), date(2026, 11, 20))


# ----------------------------------------------------------------------------
# Data (light: 4 symbols, plain lists/dicts)
# ----------------------------------------------------------------------------

class Sym:
    def __init__(self, name):
        self.dates = []
        self.open = {}
        self.close = {}
        with open(os.path.join(SRC, f"{name}.csv")) as fh:
            for row in csv.DictReader(fh):
                d = date.fromisoformat(row["date"])
                self.dates.append(d)
                self.open[d] = float(row["open"])
                self.close[d] = float(row["close"])
        self.closes = [self.close[d] for d in self.dates]

    def close_on(self, d):
        return self.close.get(d)

    def last_close(self, d):
        j = bisect.bisect_right(self.dates, d) - 1
        return None if j < 0 else self.closes[j]

    def open_on(self, d):
        o = self.open.get(d)
        return o if o is not None else self.last_close(d)

    def ret252(self, d):
        """252-trading-day return on this symbol's own series, signal day d
        (the original engine's ret252: close / close.shift(252) - 1)."""
        j = bisect.bisect_right(self.dates, d) - 1
        if j < 252:
            return None
        return self.closes[j] / self.closes[j - 252] - 1.0


DATA = {s: Sym(s) for s in SYMS}
CAL = DATA["SPY"].dates[:]           # master calendar = SPY trading days
CAL_IDX = {d: i for i, d in enumerate(CAL)}


def window_days(start, end):
    return [d for d in CAL if start <= d <= end]


def stats(final, days, curve):
    eqs = [POT0] + [e for _, e in curve]
    peak, maxdd = eqs[0], 0.0
    for e in eqs:
        peak = max(peak, e)
        if peak > 0:
            maxdd = max(maxdd, (peak - e) / peak)
    years = (days[-1] - days[0]).days / 365.25
    cagr = (final / POT0) ** (1.0 / years) - 1.0 if final > 0 else float("nan")
    return round(cagr * 100, 2), round(maxdd * 100, 2)


# ----------------------------------------------------------------------------
# INTEGRITY — original tournament2 F1, ladder-era floor, original windows
# (Portfolio math copied from the original engine)
# ----------------------------------------------------------------------------

class OrigPortfolio:
    def __init__(self):
        self.cash = POT0
        self.pos = {}            # sym -> [shares, basis, proceeds]
        self.total_costs = 0.0
        self.orders = 0
        self.trips = []
        self.floor = 85.0
        self.halt_trigger = None
        self.halt_date = None
        self.curve = []

    def buy(self, d, sym, price, notional):
        if price is None or price <= 0 or notional <= 0:
            return
        cost = notional * COST_RATE
        if notional + cost > self.cash:
            notional = self.cash / (1.0 + COST_RATE)
            cost = notional * COST_RATE
        if notional < 0.01:
            return
        shares = notional / price
        self.cash -= notional + cost
        p = self.pos.setdefault(sym, [0.0, 0.0, 0.0])
        p[0] += shares
        p[1] += notional + cost
        self.total_costs += cost
        self.orders += 1

    def sell_all(self, d, sym, price):
        if price is None or price <= 0 or sym not in self.pos:
            return
        p = self.pos[sym]
        shares = p[0]
        if shares <= 0:
            return
        value = shares * price
        cost = value * COST_RATE + SELL_FEE
        net = value - cost
        self.cash += net
        p[2] += net
        self.total_costs += cost
        self.orders += 1
        self.trips.append(p[2] - p[1])
        del self.pos[sym]

    def equity_close(self, d):
        eq = self.cash
        for sym, p in self.pos.items():
            c = DATA[sym].close_on(d)
            if c is None:
                c = DATA[sym].last_close(d)
            eq += p[0] * c
        return eq

    def record_close(self, d):
        eq = self.equity_close(d)
        self.curve.append((d, eq))
        if eq >= 150.0:
            self.floor = max(self.floor, 125.0)
        elif eq >= 125.0:
            self.floor = max(self.floor, 100.0)
        if eq <= self.floor and self.halt_trigger is None:
            self.halt_trigger = d
        return eq

    def liquidate(self, d, at_open):
        for sym in list(self.pos.keys()):
            px = DATA[sym].open_on(d) if at_open else DATA[sym].close_on(d)
            if px is None:
                px = DATA[sym].last_close(d)
            self.sell_all(d, sym, px)


def month_end_days(days):
    out = []
    for i, d in enumerate(days):
        if i == len(days) - 1 or (days[i + 1].year, days[i + 1].month) != (d.year, d.month):
            out.append(d)
    return out


def run_original(start, end):
    days = window_days(start, end)
    pf = OrigPortfolio()
    decisions = {}
    med = set(month_end_days(days))
    for i, d in enumerate(days):
        if d in med and i + 1 < len(days):
            rets, ok = {}, True
            for s in RISK + ["SHY"]:
                r = DATA[s].ret252(d)
                if r is None:
                    ok = False
                    break
                rets[s] = r
            if not ok:
                continue
            best = max(RISK, key=lambda s: rets[s])
            decisions[days[i + 1]] = best if rets[best] > rets["SHY"] else "AGG"
    for i, d in enumerate(days):
        if pf.halt_trigger is not None:
            pf.liquidate(d, at_open=True)
            pf.halt_date = d
            pf.curve.append((d, pf.cash))
            break
        if d in decisions:
            target = decisions[d]
            held = list(pf.pos.keys())
            if held != [target]:
                for s in held:
                    pf.sell_all(d, s, DATA[s].open_on(d))
                o = DATA[target].open_on(d)
                if o:
                    pf.buy(d, target, o, pf.cash / (1.0 + COST_RATE))
        if pf.halt_trigger is None:
            pf.record_close(d)
    # finalize: liquidate at last close
    last = days[-1]
    if pf.pos:
        pf.liquidate(last, at_open=False)
    final = pf.cash
    if pf.curve and pf.curve[-1][0] == last:
        pf.curve[-1] = (last, final)
    else:
        pf.curve.append((last, final))
    cagr, maxdd = stats(final, days, pf.curve)
    wins = sum(1 for t in pf.trips if t > 0)
    return {
        "final": round(final, 2), "cagr_pct": cagr, "max_dd_pct": maxdd,
        "orders": pf.orders, "trips": len(pf.trips),
        "win_rate_pct": round(100.0 * wins / len(pf.trips), 1) if pf.trips else None,
        "costs": round(pf.total_costs, 2),
        "halt_date": pf.halt_date.isoformat() if pf.halt_date else None,
        "halt_trigger": pf.halt_trigger.isoformat() if pf.halt_trigger else None,
    }


def spy_price_only(days):
    o = DATA["SPY"].open_on(days[0])
    c = DATA["SPY"].close_on(days[-1])
    gross = POT0 / o * c
    sh = (POT0 / (1.0 + COST_RATE)) / o
    net = sh * c * (1.0 - COST_RATE) - SELL_FEE
    return round(gross, 2), round(net, 2)


# ----------------------------------------------------------------------------
# SWEEP — v9 protections, cadence-governed evaluation/rotation
# ----------------------------------------------------------------------------

def cadence_dates(days, cadence):
    if cadence == "daily":
        return set(days)
    def key(d):
        if cadence == "monthly":
            return (d.year, d.month)
        if cadence == "quarterly":
            return (d.year, (d.month - 1) // 3)
        if cadence == "semiannual":
            return (d.year, (d.month - 1) // 6)
        if cadence == "annual":
            return (d.year,)
        iso = d.isocalendar()
        return (iso[0], iso[1])
    out = {days[0]}
    prev = key(days[0])
    week_count = 0
    for d in days[1:]:
        k = key(d)
        if k != prev:
            prev = k
            if cadence == "biweekly":
                week_count += 1
                if week_count % 2 == 0:
                    out.add(d)
            else:
                out.add(d)
    return out


def gem_target(signal_day):
    rets = {}
    for s in RISK + ["SHY"]:
        r = DATA[s].ret252(signal_day)
        if r is None:
            return None
        rets[s] = r
    best = max(RISK, key=lambda s: rets[s])
    return best if rets[best] > rets["SHY"] else "AGG"


def simulate(days, cadence, mode="real", seed=None):
    """One DECADE run. mode='placebo' picks a uniformly random holding at
    each cadence date. Returns dict with final/curve/halts/etc."""
    rng = random.Random(seed) if mode == "placebo" else None
    cad = cadence_dates(days, cadence)
    cash = POT0
    held = None            # symbol held
    shares = 0.0
    costs = 0.0
    orders = 0
    curve = []
    halts = []
    episode = 1
    floor = 0.85 * POT0
    halt_pending = None    # trigger date awaiting next-open liquidation
    restart_idx = None     # window index of the restart cadence date
    ended = False
    second_halt = False

    def do_buy(d, sym):
        nonlocal cash, shares, held, costs, orders
        price = DATA[sym].open_on(d)
        if price is None or price <= 0 or cash <= 0:
            return
        notional = cash / (1.0 + COST_RATE)
        cost = notional * COST_RATE
        if notional + cost > cash:
            notional = cash / (1.0 + COST_RATE)
            cost = notional * COST_RATE
        if notional < 0.01:
            return
        shares = notional / price
        cash -= notional + cost
        held = sym
        costs += cost
        orders += 1

    def do_sell(d, at_open=True):
        nonlocal cash, shares, held, costs, orders
        if held is None or shares <= 0:
            return 0.0
        price = DATA[held].open_on(d) if at_open else DATA[held].close_on(d)
        if price is None:
            price = DATA[held].last_close(d)
        value = shares * price
        cost = value * COST_RATE + SELL_FEE
        cash += value - cost
        costs += cost
        orders += 1
        shares = 0.0
        held = None
        return cash

    def equity_close(d):
        if held is None:
            return cash
        c = DATA[held].close_on(d)
        if c is None:
            c = DATA[held].last_close(d)
        return cash + shares * c

    for i, d in enumerate(days):
        if ended:
            curve.append((d, cash))
            continue
        if halt_pending is not None:
            trig = halt_pending
            halt_pending = None
            do_sell(d, at_open=True)
            rec = {"episode": episode, "trigger_date": trig.isoformat(),
                   "liquidation_date": d.isoformat(),
                   "proceeds": round(cash, 2), "floor_in_effect": round(floor, 2)}
            halts.append(rec)
            curve.append((d, cash))
            if episode == 2:
                second_halt = True
                ended = True
                continue
            # episode 1: sit in cash 90 calendar days, restart at next
            # cadence date on/after liquidation + 90 days
            earliest = d + timedelta(days=90)
            ridx = None
            for j in range(i + 1, len(days)):
                if days[j] in cad and days[j] >= earliest:
                    ridx = j
                    break
            if ridx is None:
                ended = True
                continue
            restart_idx = ridx
            episode = 2
            floor = 0.85 * cash
            rec["restart_date"] = days[ridx].isoformat()
            rec["restart_balance"] = round(cash, 2)
            rec["episode2_floor"] = round(floor, 2)
            continue
        if restart_idx is not None and i < restart_idx:
            curve.append((d, cash))     # sitting in cash
            continue
        if restart_idx is not None and i == restart_idx:
            restart_idx = None          # fall through: rotation at this open
        if d in cad:
            gi = CAL_IDX[d]
            signal_day = CAL[gi - 1] if gi > 0 else None
            if signal_day is not None:
                if mode == "placebo":
                    target = rng.choice(HOLDINGS)
                else:
                    target = gem_target(signal_day)
                if target is not None and target != held:
                    if held is not None:
                        do_sell(d, at_open=True)
                    do_buy(d, target)
        eq = equity_close(d)
        curve.append((d, eq))
        if eq <= floor:
            if i == len(days) - 1:
                # halt on the final close: liquidate at that close, run ends
                do_sell(d, at_open=False)
                halts.append({"episode": episode, "trigger_date": d.isoformat(),
                              "liquidation_date": d.isoformat(),
                              "proceeds": round(cash, 2),
                              "floor_in_effect": round(floor, 2)})
                if episode == 2:
                    second_halt = True
                ended = True
                curve[-1] = (d, cash)
            else:
                halt_pending = d
    # end of window: liquidate any open position at the last close
    if held is not None:
        last = days[-1]
        do_sell(last, at_open=False)
        curve[-1] = (last, cash)
    final = cash
    cagr, maxdd = stats(final, days, curve)
    return {
        "final": round(final, 2), "cagr_pct": cagr, "max_dd_pct": maxdd,
        "costs": round(costs, 2), "orders": orders,
        "halts": halts, "restart": any("restart_date" in h for h in halts),
        "second_halt": second_halt,
        "curve": [[d.isoformat(), round(e, 2)] for d, e in curve],
    }


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main():
    days = window_days(*DECADE)
    print(f"DECADE road: {days[0]} -> {days[-1]} ({len(days)} trading days)")

    # ---- integrity (original rules) ----
    print("\n== INTEGRITY (original tournament2 F1, ladder floor) ==")
    pub = {"full": 96.66, "design": 96.66, "validation": 150.22}
    wins_spec = {"full": (date(2016, 11, 21), date(2026, 11, 20)),
                 "design": (date(2016, 11, 21), date(2022, 12, 31)),
                 "validation": (date(2023, 1, 1), date(2026, 11, 20))}
    integrity = {}
    for w, (ws, we) in wins_spec.items():
        r = run_original(ws, we)
        integrity[w] = r
        match = abs(r["final"] - pub[w]) < 0.005
        print(f"  {w}: published ${pub[w]:.2f} reproduced ${r['final']:.2f} "
              f"match={match} orders={r['orders']} costs=${r['costs']:.2f} "
              f"halt={r['halt_date']}")
    all_match = all(abs(integrity[w]["final"] - pub[w]) < 0.005 for w in pub)
    print(f"  integrity status: {'reproduced' if all_match else 'FAILED'}")

    gross, net = spy_price_only(days)
    print(f"\nSPY decade price-only: gross ${gross:.2f} net ${net:.2f} "
          f"(dividend-adjusted program reference: $367.80)")

    # ---- sweep + placebos ----
    print("\n== SWEEP (v9 protections) ==")
    cells = {}
    for cadence in CADENCES:
        r = simulate(days, cadence, mode="real")
        twins = []
        for seed in range(1, 21):
            t = simulate(days, cadence, mode="placebo", seed=seed)
            twins.append({"seed": seed, "final": t["final"]})
        beaten = sum(1 for t in twins if r["final"] > t["final"])
        cell = {
            "slug": "gem-dual-momentum", "cadence": cadence,
            "window": [str(DECADE[0]), str(DECADE[1])], "start_cash": POT0,
            "final": r["final"], "cagr_pct": r["cagr_pct"],
            "max_dd_pct": r["max_dd_pct"], "costs": r["costs"],
            "orders": r["orders"], "halts": r["halts"],
            "restart": r["restart"], "second_halt": r["second_halt"],
            "placebo_beaten": beaten,
            "placebo_note": ("20-seed rotation placebo: at each cadence date "
                             "the target holding is drawn uniformly at random "
                             "from the same possible holdings {SPY, IEFA, AGG} "
                             "(seeds 1-20), through the identical cadence "
                             "machinery, program costs and v9 protection."),
            "placebo_twins": twins,
            "equity_curve": r["curve"],
        }
        with open(os.path.join(CELLS, f"{cadence}.json"), "w") as fh:
            json.dump(cell, fh, indent=1)
        cells[cadence] = {k: cell[k] for k in
                          ("final", "cagr_pct", "max_dd_pct", "halts",
                           "restart", "second_halt", "costs", "orders",
                           "placebo_beaten", "placebo_note")}
        print(f"  {cadence:11s} final ${r['final']:7.2f} CAGR {r['cagr_pct']:+6.2f}% "
              f"DD {r['max_dd_pct']:5.2f}% costs ${r['costs']:5.2f} "
              f"orders {r['orders']:3d} placebo {beaten}/20 "
              f"halts={len(r['halts'])} restart={r['restart']} 2nd={r['second_halt']}")

    # money cadence per SPEC: beats SPY AND its placebo distribution
    money = [c for c in CADENCES
             if cells[c]["final"] > 367.80 and cells[c]["placebo_beaten"] > 10]

    results = {
        "slug": "gem-dual-momentum",
        "area": "Monthly trend/rotation (Antonacci GEM dual momentum) — W9 tournament styles",
        "area_source": "backtests/v10-retest/SPEC.md, worker batch W9 + CADENCE GRID (gem-dual-momentum, sector-rotation — monthly)",
        "native_cadence": "monthly",
        "cadence": "monthly",
        "original_cadence_foreign": {
            "foreign": False,
            "note": ("Original tournament2 test ran GEM in its published monthly form "
                     "(month-end close signal, next-open execution) — native cadence, "
                     "not foreign. The sweep's monthly cell uses the SPEC's uniform "
                     "cadence dates (first trading day of the month, prior-close "
                     "signal, open execution), which is the same execution set as the "
                     "published form plus the initial entry at the window start."),
        },
        "integrity": {
            "status": "reproduced" if all_match else "FAILED",
            "conventions": ("Split-adjusted (not dividend-adjusted) Yahoo bars from the "
                            "original tournament2-data cache; ladder-era floor ($85, "
                            "rising to $100 at a $125 close, $125 at a $150 close; a "
                            "close at/below the floor liquidates at the next open and "
                            "ends the run); month-end decisions execute at the next "
                            "open; costs 0.10%/side + $0.01 per sell order."),
            "original_finals": {"FULL": 96.66, "DESIGN": 96.66, "VALIDATION": 150.22},
            "reproduced_finals": {w.upper(): integrity[w]["final"] for w in pub},
            "detail": integrity,
            "source": "backtests/v3/tournament2.py family F1 + backtests/v3/tournament2.md",
        },
        "decade_spy_final": 367.80,
        "decade_spy_price_only_final": net,
        "decade_spy_note": ("$367.80 is the dividend-adjusted program reference (SPEC). "
                            f"This plumbing's price-only cache gives ${net:.2f} net "
                            f"(${gross:.2f} gross) — the original tournament's $314.10 "
                            "figure, labeled price-only wherever used."),
        "cells": cells,
        "money_cadences": money,
        "verdict_area": "NO GROUND" if not money else "OWNS ITS GROUND",
        "verdict_change": ("No change. Tournament2 culled GEM for trailing SPY "
                           "buy-and-hold; the cadence sweep confirms that verdict at "
                           "all seven tempos. Monthly — the published cadence — is in "
                           "fact its best cell ($158.58 under v9, vs the original "
                           "ladder-era $96.66, the difference earned by the v9 restart, "
                           "not the strategy), so its tempo was never the problem."),
        "champion_reference": {
            "DECADE_final": 65.89,
            "note": ("Champion (Value+Momentum) DECADE $65.89 after two halts — its crown "
                     "rests on the 2010 and 2019 roads, not the decade; printed with "
                     "that caveat wherever the decade is summarized (SPEC)."),
            "LONG": 1415.62, "CONT": 544.47, "VAL": 288.05,
        },
        "data_note": ("Read-only shared cache backtests/v3/tournament2-data/ "
                      "{SPY,IEFA,AGG,SHY}.csv (Yahoo split-adjusted daily bars, "
                      "2015-01-02 -> 2026-11-20). No downloads; no shared folder written."),
    }
    with open(os.path.join(HERE, "results.json"), "w") as fh:
        json.dump(results, fh, indent=1)
    print(f"\nmoney cadences: {money}")
    print("wrote results.json + cells/*.json")


if __name__ == "__main__":
    main()
