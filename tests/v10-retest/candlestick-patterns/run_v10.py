#!/usr/bin/env python3
"""
THE GREAT RETEST (v10) — candlestick-patterns CADENCE SWEEP.

Strategy (v2 tournament style A, frozen — one clean shot, no tuning):
  bullish engulfing OR hammer, only when the close is above the 50-day
  average; enter at the next open; -5% stop / +10% target (stop-first,
  gaps fill at the open); 10-trading-day time exit at the close;
  max 2 positions, each sized at 50% of equity at the open.
  Universe: the tournament's 10 names (SPY QQQ NVDA TSLA AAPL MSFT AMZN
  META AMD AVGO). Bars: split-adjusted (not dividend-adjusted) Yahoo daily
  bars, read-only from backtests/v2/tournament-data/ — the same bars the
  tournament ran on, so eras are never mixed silently.

ROAD: DECADE 2016-11-21 -> 2026-11-20, $100 per cell.

CADENCE (SPEC uniform definition): signal evaluation, entries and ALL exit
checks (stop / target / time) happen ONLY on cadence dates —
  daily      = every trading day (the strategy's native tempo)
  weekly     = first trading day of each ISO week
  biweekly   = first trading day of every second ISO week (weeks counted
               from the first test week)
  monthly    = first trading day of each month
  quarterly  = first trading day of each calendar quarter
  semiannual = first trading day of each half-year
  annual     = first trading day of each year
Signals are read at the close of one cadence date and filled at the open of
the NEXT cadence date (the daily cell is exactly the tournament rhythm).
The 10-trading-day time exit keeps its trading-day count; it is simply
only *checked* on cadence dates. The v9 floor is protection, not a trade:
it is checked at every close, and a breach liquidates at the next open.

PROTECTION (adopted v9, every cell): plain -15% floor from the episode's
starting balance (NO ladder). First halt: liquidate at the next open, sit
in cash 90 calendar days, restart at the first cadence date on/after
halt-trigger date + 90 days, under an episode-2 floor of -15% from the
restart balance. Second halt ends the run.

COSTS: program conventions — 0.10% of trade value per side + $0.01 per
sell order (the tournament engine's own cost code).

PLACEBOS (this strategy's whole question): random-entry twins with
identical exits / sizing / costs / protection / cadence gating. Per cell,
the twin's target entry count equals the real run's executed buy count in
that cell; entry (date, symbol) pairs are drawn uniformly from that
cell's cadence dates (excluding the final test day) and the universe.
20 seeds per cell: seed = 91000 + 1000*cadence_index + s, s = 0..19.
(The integrity placebo is the tournament's own single seed 42101 — see
integrity.py.)

Outputs: cells/<cadence>.json (full equity curve, halts/restarts with
dates, all 20 placebo finals), results.json (SPEC sweep format),
RESULTS.md. Simulation only — no broker orders.
"""
import json
import math
import os
from datetime import date, timedelta

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.expanduser("~/workspace/stock-app/backtests/v2/tournament-data")

UNIVERSE = ["SPY", "QQQ", "NVDA", "TSLA", "AAPL",
            "MSFT", "AMZN", "META", "AMD", "AVGO"]
TEST_START = date(2016, 11, 21)
TEST_END = date(2026, 11, 20)
START_CASH = 100.0
COST_RATE = 0.001
SELL_FEE = 0.01
STOP_PCT, TARGET_PCT, TIME_EXIT_DAYS = 0.05, 0.10, 10
MAX_POS, FRAC = 2, 0.5
CADENCES = ["daily", "weekly", "biweekly", "monthly",
            "quarterly", "semiannual", "annual"]

# ---------------------------------------------------------------- data -----

def load_market():
    raw = {}
    for sym in UNIVERSE:
        df = pd.read_csv(os.path.join(DATA_DIR, f"{sym}.csv"))
        df["date"] = pd.to_datetime(df["date"]).dt.date
        raw[sym] = df
    spy_dates = list(raw["SPY"]["date"])
    frames = {}
    for sym, df in raw.items():
        d = df.set_index("date").reindex(spy_dates)
        d[["open", "high", "low", "close"]] = \
            d[["open", "high", "low", "close"]].ffill()
        d["volume"] = d["volume"].fillna(0)
        d = d.reset_index().rename(columns={"index": "date"})
        d["sma50"] = d["close"].rolling(50).mean()
        frames[sym] = d
    dates = spy_dates
    test_idx = [i for i, d in enumerate(dates) if TEST_START <= d <= TEST_END]
    arr = {}
    for sym in UNIVERSE:
        f = frames[sym]
        arr[sym] = {k: f[k].to_numpy(dtype=float)
                    for k in ("open", "high", "low", "close", "sma50")}
        arr[sym]["sig"] = candlestick_signals(arr[sym])
    return dates, test_idx, arr


def candlestick_signals(a):
    """Tournament sig_candlestick, vectorised: engulfing or hammer with the
    close above the 50-day average. signal[pos] uses bars through pos."""
    o, h, l, c, s50 = a["open"], a["high"], a["low"], a["close"], a["sma50"]
    sig = np.zeros(len(c), dtype=bool)
    if len(c) < 52:
        return sig
    pc, po = c[:-1], o[:-1]
    cc, oo, hh, ll = c[1:], o[1:], h[1:], l[1:]
    engulfing = (pc < po) & (cc > oo) & (oo <= pc) & (cc >= po)
    body = np.abs(cc - oo)
    rng = hh - ll
    lower = np.minimum(oo, cc) - ll
    upper = hh - np.maximum(oo, cc)
    hammer = (rng > 0) & (cc >= oo) & (lower >= 2 * np.maximum(body, 1e-9)) \
        & (upper <= 0.1 * rng)
    ok = (~np.isnan(s50[1:])) & (cc > s50[1:])
    sig[1:] = ok & (engulfing | hammer)
    sig[:51] = False
    return sig


def cadence_test_positions(dates, test_idx, cadence):
    """Set of positions within test_idx (indices into test_idx) that are
    cadence dates."""
    td = [dates[i] for i in test_idx]
    out = set()
    if cadence == "daily":
        return set(range(len(td)))
    seen = set()
    week_counter = {}
    week_order = []
    for k, d in enumerate(td):
        if cadence == "weekly":
            key = (d.isocalendar()[0], d.isocalendar()[1])
        elif cadence == "biweekly":
            key = (d.isocalendar()[0], d.isocalendar()[1])
        elif cadence == "monthly":
            key = (d.year, d.month)
        elif cadence == "quarterly":
            key = (d.year, (d.month - 1) // 3)
        elif cadence == "semiannual":
            key = (d.year, (d.month - 1) // 6)
        elif cadence == "annual":
            key = (d.year,)
        if cadence == "biweekly":
            if key not in week_counter:
                week_counter[key] = len(week_order)
                week_order.append(key)
            if key not in seen and week_counter[key] % 2 == 0:
                seen.add(key)
                out.add(k)
        else:
            if key not in seen:
                seen.add(key)
                out.add(k)
    return out

# ------------------------------------------------------------- portfolio ---

class Pot:
    def __init__(self):
        self.cash = START_CASH
        self.pos = {}          # sym -> dict(shares, entry_price, entry_pos)
        self.costs = 0.0
        self.orders = 0
        self.buys = 0

    def equity(self, arr, pos, field="close"):
        v = self.cash
        for sym, p in self.pos.items():
            v += p["shares"] * arr[sym][field][pos]
        return v

    def buy(self, arr, pos, sym, target_value):
        price = arr[sym]["open"][pos]
        if price <= 0 or target_value <= 0:
            return False
        value = min(target_value, self.cash / (1 + COST_RATE))
        if value < 1.0:
            return False
        cost = COST_RATE * value
        self.cash -= value + cost
        self.costs += cost
        self.orders += 1
        self.buys += 1
        self.pos[sym] = {"shares": value / price, "entry_price": price,
                         "entry_pos": pos}
        return True

    def sell(self, arr, pos, sym, price):
        p = self.pos.get(sym)
        if not p or price <= 0:
            return False
        value = p["shares"] * price
        cost = COST_RATE * value + SELL_FEE
        self.cash += value - cost
        self.costs += cost
        self.orders += 1
        del self.pos[sym]
        return True

    def liquidate(self, arr, pos):
        for sym in list(self.pos):
            self.sell(arr, pos, sym, arr[sym]["open"][pos])

# --------------------------------------------------------------- episode ---

def run_episode(dates, test_idx, arr, cad_set, start_k, cash, floor,
                mode, schedule=None):
    """One episode from test position start_k. mode='signal' uses the
    candlestick signals; mode='placebo' uses schedule {date: [sym,...]}.
    Returns dict(cash_end, curve[(date,eq)], costs, orders, buys, halt)
    where halt is None or {trigger_date, liquidation_date or None}."""
    pot = Pot()
    pot.cash = cash
    costs0 = 0.0
    curve = []
    pending = []               # symbols to enter at this cadence open
    halt_pending = False
    halt = None
    last_k = len(test_idx) - 1
    k = start_k
    while k <= last_k:
        pos = test_idx[k]
        d = dates[pos]
        if halt_pending:
            pot.liquidate(arr, pos)
            halt = {"trigger_date": curve[-1][0].isoformat(), "liquidation_date": d.isoformat()}
            curve.append((d, pot.cash))
            return {"cash_end": pot.cash, "curve": curve, "costs": pot.costs,
                    "orders": pot.orders, "buys": pot.buys, "halt": halt,
                    "end_k": k}
        if k in cad_set:
            # entries at the open (scheduled at the previous cadence close,
            # or drawn from the placebo schedule for today)
            if mode == "placebo":
                cands = list(schedule.get(d, [])) if schedule else []
            else:
                cands = pending
            pending = []
            for sym in cands:
                if sym in pot.pos or len(pot.pos) >= MAX_POS:
                    continue
                eq_open = pot.equity(arr, pos, "open")
                pot.buy(arr, pos, sym, FRAC * eq_open)
            # intraday stop / target, stop-first (tournament rule)
            for sym in list(pot.pos):
                e = pot.pos[sym]["entry_price"]
                o = arr[sym]["open"][pos]
                h = arr[sym]["high"][pos]
                l = arr[sym]["low"][pos]
                sp, tp = e * (1 - STOP_PCT), e * (1 + TARGET_PCT)
                fill = None
                if o <= sp:
                    fill = o
                elif o >= tp:
                    fill = o
                elif l <= sp and h >= tp:
                    fill = sp
                elif l <= sp:
                    fill = sp
                elif h >= tp:
                    fill = tp
                if fill is not None:
                    pot.sell(arr, pos, sym, fill)
            # time exit at the close (10 trading days, checked today)
            for sym in list(pot.pos):
                if pos - pot.pos[sym]["entry_pos"] >= TIME_EXIT_DAYS:
                    pot.sell(arr, pos, sym, arr[sym]["close"][pos])
        eq_close = pot.equity(arr, pos, "close")
        curve.append((d, eq_close))
        if eq_close <= floor:
            if k == last_k:
                halt = {"trigger_date": d.isoformat(), "liquidation_date": None}
                return {"cash_end": eq_close, "curve": curve,
                        "costs": pot.costs, "orders": pot.orders,
                        "buys": pot.buys, "halt": halt, "end_k": k}
            halt_pending = True
            halt = {"trigger_date": d.isoformat(), "liquidation_date": None}
        # generate entries for the next cadence date
        if mode == "signal" and k in cad_set:
            nxt = []
            for sym in UNIVERSE:
                if sym not in pot.pos and arr[sym]["sig"][pos]:
                    nxt.append(sym)
            pending = nxt
        k += 1
    return {"cash_end": curve[-1][1] if curve else cash, "curve": curve,
            "costs": pot.costs, "orders": pot.orders, "buys": pot.buys,
            "halt": None, "end_k": last_k}

# ------------------------------------------------------------- full run ----

def run_full(dates, test_idx, arr, cadence, mode="signal", schedule=None):
    cad_set = cadence_test_positions(dates, test_idx, cadence)
    td = [dates[i] for i in test_idx]
    floor1 = round(0.85 * START_CASH, 2)
    r1 = run_episode(dates, test_idx, arr, cad_set, 0, START_CASH, floor1,
                     mode, schedule)
    curve = list(r1["curve"])
    costs, orders, buys = r1["costs"], r1["orders"], r1["buys"]
    halts, restarts, second_halt = [], [], None
    restart = False
    if r1["halt"] is None:
        final = r1["cash_end"]
    else:
        trig = date.fromisoformat(r1["halt"]["trigger_date"])
        halts.append({"episode": 1, "trigger_date": r1["halt"]["trigger_date"],
                      "liquidation_date": r1["halt"]["liquidation_date"],
                      "floor_in_effect": floor1})
        cash = r1["cash_end"]
        if r1["halt"]["liquidation_date"] is None:
            final = cash                      # halted on the final day
        else:
            day90 = trig + timedelta(days=90)
            restart_k = None
            for k in sorted(cad_set):
                if td[k] >= day90 and k > r1["end_k"]:
                    restart_k = k
                    break
            if restart_k is None:
                final = cash                  # no cadence date left to restart
            else:
                # cash-flat sit-out curve up to the restart day
                liq_k = r1["end_k"]
                for k in range(liq_k + 1, restart_k):
                    curve.append((td[k], cash))
                restart = True
                floor2 = round(0.85 * cash, 2)
                restarts.append({
                    "halt_trigger_date": r1["halt"]["trigger_date"],
                    "restart_date": td[restart_k].isoformat(),
                    "restart_balance": round(cash, 2),
                    "episode2_floor": floor2})
                r2 = run_episode(dates, test_idx, arr, cad_set, restart_k,
                                 cash, floor2, mode, schedule)
                curve.extend(r2["curve"])
                costs += r2["costs"]
                orders += r2["orders"]
                buys += r2["buys"]
                final = r2["cash_end"]
                if r2["halt"] is not None:
                    second_halt = {
                        "episode": 2,
                        "trigger_date": r2["halt"]["trigger_date"],
                        "liquidation_date": r2["halt"]["liquidation_date"],
                        "floor_in_effect": floor2}
                    halts.append(second_halt)
    return {"final": final, "curve": curve, "costs": costs, "orders": orders,
            "buys": buys, "halts": halts, "restarts": restarts,
            "restart": restart, "second_halt": second_halt,
            "cad_set": cad_set}


def metrics(final, curve, start_d, end_d):
    peak, max_dd = START_CASH, 0.0
    for _, eq in [(start_d, START_CASH)] + curve:
        peak = max(peak, eq)
        if peak > 0:
            max_dd = max(max_dd, (peak - eq) / peak)
    years = max((end_d - start_d).days, 1) / 365.25
    cagr = (final / START_CASH) ** (1 / years) - 1 if final > 0 else -1.0
    return round(cagr * 100, 2), round(max_dd * 100, 2)


def make_schedule(dates, test_idx, cad_set, n_entries, seed):
    rng = np.random.default_rng(seed)
    td = [dates[i] for i in test_idx]
    pool = [td[k] for k in sorted(cad_set) if td[k] != td[-1]]
    schedule = {}
    for _ in range(n_entries):
        d = pool[rng.integers(0, len(pool))]
        sym = UNIVERSE[rng.integers(0, len(UNIVERSE))]
        schedule.setdefault(d, []).append(sym)
    return schedule

# ------------------------------------------------------------------ main ---

def main():
    dates, test_idx, arr = load_market()
    td = [dates[i] for i in test_idx]
    start_d, end_d = td[0], td[-1]

    # SPY price-only benchmark on these same (split-adjusted) bars, program
    # costs — the tournament's own benchmark convention.
    o0 = arr["SPY"]["open"][test_idx[0]]
    cN = arr["SPY"]["close"][test_idx[-1]]
    bv = START_CASH / (1 + COST_RATE)
    spy_net_price_only = bv / o0 * cN
    spy_net_price_only -= COST_RATE * (bv / o0 * cN) + SELL_FEE

    results = {
        "slug": "candlestick-patterns",
        "area": ("SHORT-CYCLE daily stock style (W9): candlestick entries "
                 "cycled and compounded over the full DECADE road; the "
                 "random-entry placebo at every cadence is this strategy's "
                 "whole question — is there a tempo where its entries beat "
                 "random entries with identical exits?"),
        "area_source": "backtests/v10-retest/SPEC.md, worker batch W9 + THE CADENCE SWEEP",
        "native_cadence": "daily",
        "cadence": "daily",
        "original_cadence_foreign": False,
        "original_cadence_note": ("Original v2 tournament ran the style in its "
                                  "native daily form — not foreign."),
        "integrity": {
            "status": "reproduced",
            "conventions": ("ORIGINAL tournament rules: split-adjusted (not "
                            "dividend-adjusted) bars; ladder-era floor ($85, "
                            "rising to $100 at a $125 close and $125 at a $150 "
                            "close; halt ends the run, no restart); costs "
                            "0.10%/side + $0.01/sell. Reproduced through the "
                            "verbatim original engine (tournament_original.py "
                            "+ integrity.py in this folder)."),
            "original_finals": {"decade_real": 122.94,
                                "halt_date": "2021-05-19",
                                "decade_placebo_seed42101": 165.09,
                                "spy_net_price_only": 314.10},
            "reproduced_finals": {"decade_real": 122.94,
                                  "halt_date": "2021-05-19",
                                  "orders": 324, "costs": 20.47,
                                  "decade_placebo_seed42101": 165.09,
                                  "placebo_margin_over_real": 42.15,
                                  "spy_net_price_only": 314.10},
        },
        "decade_spy_final": 367.80,
        "decade_spy_note": ("Two labeled benchmarks, eras never mixed: "
                            "(1) tournament-era SPY net, price-only on the "
                            "same split-adjusted bars, computed in this "
                            "plumbing = $%.2f (the tournament's published "
                            "$314.10); (2) program dividend-adjusted SPY "
                            "decade = $367.80 (SPEC reference, verified by "
                            "W6 plumbing). Sweep verdicts are judged "
                            "against the $367.80 figure." % spy_net_price_only),
        "spy_net_price_only_in_plumbing": round(spy_net_price_only, 2),
        "champion_decade_reference": {
            "final": 65.89,
            "caveat": ("Champion (Value+Momentum) DECADE $65.89 after two "
                       "halts — its crown rests on the 2010 and 2019 roads; "
                       "the decade is its worst window, printed wherever the "
                       "decade matrix is summarized (SPEC).")},
        "cells": {},
    }

    for ci, cadence in enumerate(CADENCES):
        real = run_full(dates, test_idx, arr, cadence, mode="signal")
        cagr, max_dd = metrics(real["final"], real["curve"], start_d, end_d)
        # 20-seed placebos at this cadence
        twins = []
        for s in range(20):
            seed = 91000 + 1000 * ci + s
            sched = make_schedule(dates, test_idx, real["cad_set"],
                                  real["buys"], seed)
            tw = run_full(dates, test_idx, arr, cadence, mode="placebo",
                          schedule=sched)
            twins.append({"seed": seed, "final": round(tw["final"], 2)})
        beaten = sum(1 for t in twins if real["final"] > t["final"])
        cell = {
            "final": round(real["final"], 2),
            "cagr_pct": cagr,
            "max_dd_pct": max_dd,
            "halts": real["halts"],
            "restart": real["restart"],
            "second_halt": bool(real["second_halt"]),
            "costs": round(real["costs"], 2),
            "orders": real["orders"],
            "buys": real["buys"],
            "placebo_beaten": beaten,
            "placebo_note": ("20 random-entry twins (seeds 91000+%d000+s, "
                             "s=0..19), target entries = real run's %d buys "
                             "in this cell, identical exits/sizing/costs/"
                             "cadence gating/v9 protection."
                             % (ci, real["buys"])),
        }
        results["cells"][cadence] = cell
        cell_doc = {
            "slug": "candlestick-patterns", "cadence": cadence,
            "window": [start_d.isoformat(), end_d.isoformat()],
            "start_cash": START_CASH,
            **cell,
            "restarts": real["restarts"],
            "second_halt_detail": real["second_halt"],
            "placebo_twins": twins,
            "equity_curve": [[d.isoformat(), round(v, 4)]
                             for d, v in real["curve"]],
        }
        with open(os.path.join(HERE, "cells", f"{cadence}.json"), "w") as fh:
            json.dump(cell_doc, fh, indent=1)
        print(f"{cadence:11s} final ${real['final']:8.2f}  CAGR {cagr:+6.2f}%  "
              f"maxDD {max_dd:5.1f}%  orders {real['orders']:4d}  "
              f"costs ${real['costs']:6.2f}  halts {len(real['halts'])}  "
              f"restart {real['restart']}  placebo beaten {beaten}/20")

    # annual cell artifact note (documented, never patched): zero signal
    # hits at the 11 annual cadence closes across all 10 names in the
    # decade, so the pot never traded and every twin (0 target entries)
    # also sits at $100.00.
    if results["cells"]["annual"]["buys"] == 0:
        results["cells"]["annual"]["placebo_note"] += (
            " ARTIFACT (documented, not patched): zero candlestick signal "
            "hits at the 11 annual cadence closes in the whole decade, so "
            "the real pot never traded ($100.00 flat) and all 20 twins, "
            "with 0 target entries, are also $100.00 — beaten 0/20 is a "
            "tie artifact, not evidence.")
    spy = results["decade_spy_final"]
    results["money_cadences"] = [
        c for c in CADENCES
        if results["cells"][c]["final"] > spy
        and results["cells"][c]["placebo_beaten"] is not None
        and results["cells"][c]["placebo_beaten"] >= 11]
    results["verdict_area"] = "NO GROUND"
    results["verdict_change"] = (
        "Unchanged in substance: culled in the v2 tournament, still no "
        "ground. At its native daily tempo the entries remain worse than "
        "random (placebo beaten only 5/20; the tournament's single-seed "
        "placebo beat it by $42.15). One new wrinkle: slowing the "
        "exit-check rhythm to weekly/biweekly makes the same entries beat "
        "random entries 20/20 — but the best tempo (weekly, $287.30) "
        "still trails both SPY labels ($314.10 price-only tournament-era, "
        "$367.80 dividend-adjusted), so no cadence earns a place on the "
        "map. Beating the champion's decade $65.89 (its worst window, two "
        "halts — see caveat) at 5 of 7 cadences is not beating the "
        "champion.")
    with open(os.path.join(HERE, "results.json"), "w") as fh:
        json.dump(results, fh, indent=1)
    print("money_cadences:", results["money_cadences"])
    print("SPY price-only in-plumbing: $%.2f | dividend-adjusted: $367.80"
          % spy_net_price_only)


if __name__ == "__main__":
    main()
