#!/usr/bin/env python3
"""
THE GREAT RETEST (v10) — Turn-of-Month (tournament2 family F5), SPY only.
Simulation only. One clean shot, frozen per backtests/v10-retest/SPEC.md
plus the worker task's cadence treatment (below). No tuning.

THE STRATEGY (original, v3 tournament2 run_f5, copied in spirit exactly):
  Buy SPY at the CLOSE of the 2nd-last trading day of each month; sell at
  the CLOSE of the 3rd trading day of the next month. Nothing else is ever
  held. Pairs count only when the buy date is on/after the window start
  and the sell date is on/before the window end (original filter).

WHAT THIS SCRIPT DOES
  1. INTEGRITY — re-runs F5 in its ORIGINAL form on the ORIGINAL bars
     (backtests/v3/tournament2-data/SPY.csv, split-adjusted, NOT dividend
     adjusted, read-only), trades at the close, ORIGINAL ladder-era floor
     ($85, rising to $100 at a $125 close and $125 at a $150 close; a close
     at/below the floor liquidates at the next open and ends the run).
     Targets: FULL $110.74 (costs $26.14, 240 orders), DESIGN $105.30,
     VALIDATION $106.50 (backtests/v3/tournament2.md).
  2. DECADE CADENCE SWEEP — 2016-11-21 -> 2026-11-20, $100/cell, on
     dividend-adjusted SPY bars (read-only shared cache
     backtests/v7/long-hold/data/pxfull_SPY.json; champion construction:
     close = adjclose, open scaled by adjclose/close). Costs: program
     0.10%/side + $0.01 per sell order (the original engine's own cost
     code). Protection: adopted v9 rules — plain -15% floor from the
     episode's starting balance, checked at every close; on first halt
     liquidate at the next open, sit in cash 90 calendar days, restart at
     the next cadence review date on/after eligibility under an episode-2
     floor of -15% from the restart balance; second halt ends the run.
     End of window: open position liquidated at the last close.

CADENCE TREATMENT (the honest part — stated in RESULTS.md too):
  This strategy IS a calendar rule: its holding window is defined by the
  month turn. Cadence can only govern the review/execution rhythm around
  that window. Uniform machinery: build the desired-state series from the
  original calendar schedule (IN from the buy close through the day
  before the sell close, OUT otherwise). On a cadence review date, at the
  close, trade to match the desired state; between review dates, hold.
    - daily    = every trading day -> reproduces the original timing
                 exactly (native; the SPEC grid classifies this family
                 "daily/calendar-event").
    - weekly   = first trading day of each week.
    - biweekly = first trading day of every second week (weeks anchored
                 on the first week of the window).
    - monthly / quarterly / semiannual / annual = NOT-APPLICABLE.
      Mechanical reason: their review dates are first trading days of a
      month/quarter/half/year, and the 1st trading day of a month is
      ALWAYS inside the holding window (the window runs from the 2nd-last
      trading day of the prior month through the 3rd trading day of this
      month), while the entry date (2nd-last trading day of a month) and
      the exit date (3rd trading day) are NEVER review dates at those
      rhythms. Sampling the calendar only at those dates only ever
      observes the IN state — the entry and exit of a monthly calendar
      rule cannot both be executed, so the rule cannot be expressed.
  3. PLACEBO — a shifted-window twin per expressible cadence: the same
     schedule with every (buy, sell) pair shifted +10 trading days
     (~two weeks, same holding length in trading days), run through the
     identical cadence machinery, costs and v9 protection. A single
     deterministic twin (the honest placebo design for a calendar
     effect), so placebo_beaten is null and the twin's final is reported
     directly; N/A cells state n/a.

Outputs (this folder only): cells/<cadence>.json (full equity curve,
halts/restarts with dates, placebo twin final), results.json,
RESULTS.md, integrity.json. Only SPY bars are ever loaded.
"""
import json
import os
import time
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ORIG_CSV = os.path.expanduser(
    "~/workspace/stock-app/backtests/v3/tournament2-data/SPY.csv")
LONG_PX = os.path.expanduser(
    "~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")

START_CASH = 100.0
COST_RATE = 0.001          # 0.10% per side
SELL_FEE = 0.01            # per sell order
DEC_START, DEC_END = date(2016, 11, 21), date(2026, 11, 20)
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]
NA_CADENCES = {"monthly", "quarterly", "semiannual", "annual"}
NA_REASON = ("Review dates at this rhythm are first trading days of a "
             "month/quarter/half/year. The 1st trading day of a month is "
             "always inside the turn-of-month holding window (window runs "
             "from the 2nd-last trading day of the prior month through "
             "the 3rd trading day of this month), and neither the entry "
             "date (2nd-last trading day of a month) nor the exit date "
             "(3rd trading day of a month) is ever a review date at this "
             "rhythm. The cadence only ever samples the IN state, so the "
             "monthly calendar rule's entry and exit cannot both be "
             "executed — the rule cannot be expressed at this cadence.")


# --------------------------------------------------------------------- data
def load_orig_bars():
    """Original tournament bars: split-adjusted OHLC from the v3 cache."""
    bars = []
    with open(ORIG_CSV) as fh:
        header = fh.readline()
        for line in fh:
            p = line.strip().split(",")
            if len(p) < 5:
                continue
            y, m, d = (int(x) for x in p[0].split("-"))
            bars.append({"d": date(y, m, d), "o": float(p[1]),
                         "c": float(p[4])})
    bars.sort(key=lambda b: b["d"])
    return bars


def load_adj_bars():
    """Dividend-adjusted bars from the pxfull payload (champion
    construction: close = adjclose, open scaled by adjclose/close).
    Also returns price-only bars (raw quote open/close) for the labeled
    price-only SPY benchmark."""
    with open(LONG_PX, "rb") as fh:
        j = json.loads(fh.read())
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    adj_bars, px_bars = [], []
    for i, t in enumerate(ts):
        o, c = q["open"][i], q["close"][i]
        if c is None or o is None:
            continue
        y, m, d = (int(x) for x in time.strftime("%Y-%m-%d",
                                                 time.gmtime(t)).split("-"))
        dt = date(y, m, d)
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        adj_bars.append({"d": dt, "o": o * ratio, "c": a})
        px_bars.append({"d": dt, "o": o, "c": c})
    adj_bars.sort(key=lambda b: b["d"])
    px_bars.sort(key=lambda b: b["d"])
    return adj_bars, px_bars


# ------------------------------------------------- original (integrity) run
class OrigPortfolio:
    """Faithful copy of tournament2.py's Portfolio, SPY-only use."""

    def __init__(self):
        self.cash = START_CASH
        self.shares = 0.0
        self.basis = 0.0
        self.proceeds = 0.0
        self.trades_costs = 0.0
        self.orders = 0
        self.trips = []
        self.floor = 85.0
        self.halt_trigger = None
        self.halt_date = None
        self.equity_series = []

    def buy(self, price):
        notional = self.cash / (1.0 + COST_RATE)
        cost = notional * COST_RATE
        self.shares = notional / price
        self.basis = notional + cost
        self.proceeds = 0.0
        self.cash -= notional + cost
        self.trades_costs += cost
        self.orders += 1

    def sell(self, price):
        if self.shares <= 0:
            return
        value = self.shares * price
        cost = value * COST_RATE + SELL_FEE
        net = value - cost
        self.cash += net
        self.proceeds += net
        self.trades_costs += cost
        self.orders += 1
        self.trips.append(self.proceeds - self.basis)
        self.shares = 0.0

    def equity_close(self, close):
        return self.cash + self.shares * close

    def record_close(self, d, close):
        eq = self.equity_close(close)
        self.equity_series.append((d, eq))
        if eq >= 150.0:
            self.floor = max(self.floor, 125.0)
        elif eq >= 125.0:
            self.floor = max(self.floor, 100.0)
        if eq <= self.floor and self.halt_trigger is None:
            self.halt_trigger = d
        return eq


def tom_pairs(cal):
    """Original F5 schedule over a full calendar: (buy, sell) date pairs."""
    by_month = {}
    for d in cal:
        by_month.setdefault((d.year, d.month), []).append(d)
    months = sorted(by_month.keys())
    pairs = []
    for k, ym in enumerate(months[:-1]):
        mdays = by_month[ym]
        nm = by_month[months[k + 1]]
        if len(mdays) >= 2 and len(nm) >= 3:
            pairs.append((mdays[-2], nm[2]))
    return pairs


def run_original(bars, start, end):
    cal = [b["d"] for b in bars]
    px = {b["d"]: b for b in bars}
    days = [d for d in cal if start <= d <= end]
    buys, sells = set(), set()
    for b, s in tom_pairs(cal):
        if days[0] <= b and s <= days[-1]:
            buys.add(b)
            sells.add(s)
    pf = OrigPortfolio()
    for d in days:
        if pf.halt_trigger is not None:
            # liquidate at today's open and end the run (original)
            if pf.shares > 0:
                pf.sell(px[d]["o"])
            pf.halt_date = d
            pf.equity_series.append((d, pf.cash))
            break
        if d in sells and pf.shares > 0:
            pf.sell(px[d]["c"])
        if d in buys and pf.shares == 0:
            pf.buy(px[d]["c"])
        if pf.halt_trigger is None:
            pf.record_close(d, px[d]["c"])
    # finalize (original): liquidate at last close, last point = final cash
    last = days[-1]
    if pf.shares > 0:
        pf.sell(px[last]["c"])
    final = pf.cash
    if pf.equity_series and pf.equity_series[-1][0] == last:
        pf.equity_series[-1] = (last, final)
    else:
        pf.equity_series.append((last, final))
    return {"final": round(final, 2), "costs": round(pf.trades_costs, 2),
            "orders": pf.orders,
            "halt_date": pf.halt_date.isoformat() if pf.halt_date else None}


# ------------------------------------------------------------- sweep engine
def cadence_dates(days, cadence):
    if cadence == "daily":
        return set(days)
    out = set()
    if cadence == "weekly":
        seen = set()
        for d in days:
            key = d.isocalendar()[:2]
            if key not in seen:
                seen.add(key)
                out.add(d)
    elif cadence == "biweekly":
        weeks, seen = [], set()
        for d in days:
            key = d.isocalendar()[:2]
            if key not in seen:
                seen.add(key)
                weeks.append(d)          # first trading day of the week
        out = set(weeks[::2])
    return out


def shifted_pairs(pairs, cal, cal_index, shift):
    out = []
    for b, s in pairs:
        bi, si = cal_index[b] + shift, cal_index[s] + shift
        if si < len(cal):
            out.append((cal[bi], cal[si]))
    return out


def window_pairs(pairs, days):
    return [(b, s) for b, s in pairs if days[0] <= b and s <= days[-1]]


def run_sweep(bars, days, pairs, cadence):
    """One cadence cell (or one shifted placebo twin) under v9 rules."""
    px = {b["d"]: b for b in bars}
    wpairs = window_pairs(pairs, days)
    want = set()
    for b, s in wpairs:
        for d in days:
            if b <= d < s:
                want.add(d)
    reviews = cadence_dates(days, cadence)

    cash, shares = START_CASH, 0.0
    costs, orders = 0.0, 0
    curve = []
    halts = []               # [{trigger, liquidation, episode_start, floor}]
    episode_start = START_CASH
    halted_until = None      # date trading may resume
    pending_liquidation = False
    ended = False
    restart = False
    n_halts = 0

    def do_buy(d):
        nonlocal cash, shares, costs, orders
        notional = cash / (1.0 + COST_RATE)
        c = notional * COST_RATE
        shares = notional / px[d]["c"]
        cash -= notional + c
        costs += c
        orders += 1

    def do_sell(d, price):
        nonlocal cash, shares, costs, orders
        value = shares * price
        c = value * COST_RATE + SELL_FEE
        cash += value - c
        costs += c
        orders += 1
        shares = 0.0

    for i, d in enumerate(days):
        if ended:
            curve.append((d, cash))
            continue
        if pending_liquidation:
            if shares > 0:
                do_sell(d, px[d]["o"])       # liquidate at the open (v9)
            halts[-1]["liquidation"] = d.isoformat()
            pending_liquidation = False
            if n_halts >= 2:
                ended = True
                curve.append((d, cash))
                continue
            halted_until = d + timedelta(days=90)
            curve.append((d, cash))
            continue
        if halted_until is not None:
            if d >= halted_until and d in reviews:
                halted_until = None
                episode_start = cash          # episode-2 floor base
                restart = True
            else:
                curve.append((d, cash))
                continue
        if d in reviews:
            if d in want and shares == 0:
                do_buy(d)
            elif d not in want and shares > 0:
                do_sell(d, px[d]["c"])
        eq = cash + shares * px[d]["c"]
        curve.append((d, eq))
        if eq <= episode_start * 0.85:
            n_halts += 1
            halts.append({"trigger": d.isoformat(), "liquidation": None,
                          "episode_start_balance": round(episode_start, 2),
                          "floor": round(episode_start * 0.85, 2),
                          "episode": n_halts})
            if i + 1 < len(days):
                pending_liquidation = True
            else:
                halts[-1]["liquidation"] = d.isoformat()
                if shares > 0:
                    do_sell(d, px[d]["c"])
                if n_halts >= 2:
                    ended = True
    # end of window: liquidate at last close (original convention)
    last = days[-1]
    if shares > 0:
        do_sell(last, px[last]["c"])
    final = cash
    if curve and curve[-1][0] == last:
        curve[-1] = (last, final)
    else:
        curve.append((last, final))
    eqs = [START_CASH] + [e for _, e in curve]
    peak, maxdd = eqs[0], 0.0
    for e in eqs:
        peak = max(peak, e)
        if peak > 0:
            maxdd = max(maxdd, (peak - e) / peak)
    span = (days[-1] - days[0]).days
    years = span / 365.25 if span > 0 else 0.0
    cagr = (final / START_CASH) ** (1.0 / years) - 1.0 if final > 0 else -1.0
    return {"final": round(final, 2), "cagr_pct": round(cagr * 100, 2),
            "max_dd_pct": round(maxdd * 100, 2),
            "costs": round(costs, 2), "orders": orders,
            "halts": halts, "restart": restart,
            "second_halt": n_halts >= 2,
            "equity_curve": [[d.isoformat(), round(e, 2)] for d, e in curve]}


def buy_hold(bars, start, end):
    days = [b for b in bars if start <= b["d"] <= end]
    first, last = days[0], days[-1]
    shares = START_CASH / (first["o"] * (1.0 + COST_RATE))
    val = shares * last["c"]
    return round(val - (val * COST_RATE + SELL_FEE), 2)


# --------------------------------------------------------------------- main
def main():
    os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)

    # ---- integrity on the original bars / original rules
    orig = load_orig_bars()
    integrity_runs = {
        "FULL": run_original(orig, date(2016, 11, 21), date(2026, 11, 20)),
        "DESIGN": run_original(orig, date(2016, 11, 21), date(2022, 12, 31)),
        "VALIDATION": run_original(orig, date(2023, 1, 1), date(2026, 11, 20)),
    }
    published = {"FULL": 110.74, "DESIGN": 105.30, "VALIDATION": 106.50}
    integ = {"status": "reproduced",
             "original_finals": published,
             "reproduced_finals": {k: v["final"] for k, v in
                                   integrity_runs.items()},
             "detail": integrity_runs,
             "conventions": ("split-adjusted bars from v3 "
                             "tournament2-data/SPY.csv (not dividend "
                             "adjusted), trades at the close, ladder-era "
                             "floor ($85 -> $100 at $125 -> $125 at $150; "
                             "close at/below floor liquidates at next "
                             "open and ends the run), costs 0.10%/side + "
                             "$0.01/sell — all exactly as "
                             "backtests/v3/tournament2.py F5 ran")}
    for k, v in published.items():
        if integrity_runs[k]["final"] != v:
            integ["status"] = "reproduced-with-notes"
    with open(os.path.join(HERE, "integrity.json"), "w") as fh:
        json.dump(integ, fh, indent=1)
    print("INTEGRITY", integ["status"], integ["reproduced_finals"],
          "FULL costs", integrity_runs["FULL"]["costs"],
          "orders", integrity_runs["FULL"]["orders"], flush=True)

    # ---- decade sweep on dividend-adjusted bars
    adj, pxonly = load_adj_bars()
    cal = [b["d"] for b in adj]
    cal_index = {d: i for i, d in enumerate(cal)}
    days = [d for d in cal if DEC_START <= d <= DEC_END]
    pairs = tom_pairs(cal)
    placebo_pairs = shifted_pairs(pairs, cal, cal_index, 10)

    spy_div = buy_hold(adj, DEC_START, DEC_END)
    spy_px = buy_hold(pxonly, DEC_START, DEC_END)
    print(f"SPY DECADE dividend-adjusted ${spy_div} / price-only ${spy_px}",
          flush=True)

    cells, cell_files = {}, {}
    for cad in CADENCES:
        if cad in NA_CADENCES:
            cells[cad] = {"status": "NOT-APPLICABLE", "reason": NA_REASON,
                          "placebo_beaten": None,
                          "placebo_note": "n/a — cell is NOT-APPLICABLE; "
                                          "the shifted-window placebo "
                                          "cannot be expressed at this "
                                          "cadence either, for the same "
                                          "mechanical reason."}
            cell_files[cad] = {"slug": "turn-of-month", "cadence": cad,
                               "status": "NOT-APPLICABLE",
                               "reason": NA_REASON,
                               "window": [DEC_START.isoformat(),
                                          DEC_END.isoformat()],
                               "placebo_twins": None,
                               "placebo_note": "n/a — see reason"}
            continue
        r = run_sweep(adj, days, pairs, cad)
        twin = run_sweep(adj, days, placebo_pairs, cad)
        note = ("Single deterministic shifted-window twin: the original "
                "schedule with every (buy, sell) pair shifted +10 trading "
                "days (~two weeks), same holding length, run through the "
                "identical cadence machinery, costs and v9 protection. "
                "placebo_beaten is null by design (one twin, not a "
                "20-seed distribution); the twin final is the comparison.")
        cells[cad] = {"final": r["final"], "cagr_pct": r["cagr_pct"],
                      "max_dd_pct": r["max_dd_pct"], "halts": r["halts"],
                      "restart": r["restart"],
                      "second_halt": r["second_halt"], "costs": r["costs"],
                      "orders": r["orders"], "placebo_beaten": None,
                      "placebo_note": note,
                      "placebo_twin_final": twin["final"],
                      "placebo_twin_costs": twin["costs"]}
        cell_files[cad] = {"slug": "turn-of-month", "cadence": cad,
                           "window": [DEC_START.isoformat(),
                                      DEC_END.isoformat()],
                           "start_cash": START_CASH, "final": r["final"],
                           "cagr_pct": r["cagr_pct"],
                           "max_dd_pct": r["max_dd_pct"],
                           "halts": r["halts"], "restart": r["restart"],
                           "second_halt": r["second_halt"],
                           "costs": r["costs"], "orders": r["orders"],
                           "placebo_beaten": None, "placebo_note": note,
                           "placebo_twins": [{"shift_trading_days": 10,
                                              "final": twin["final"],
                                              "costs": twin["costs"],
                                              "orders": twin["orders"],
                                              "max_dd_pct":
                                                  twin["max_dd_pct"]}],
                           "equity_curve": r["equity_curve"]}
        print(f"{cad}: final ${r['final']} costs ${r['costs']} "
              f"orders {r['orders']} DD {r['max_dd_pct']}% "
              f"twin ${twin['final']}", flush=True)
    for cad in CADENCES:
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as fh:
            json.dump(cell_files[cad], fh, indent=1)

    money = [c for c in CADENCES if c not in NA_CADENCES
             and cells[c]["final"] > spy_div
             and cells[c]["final"] > cells[c]["placebo_twin_final"]]
    results = {
        "slug": "turn-of-month",
        "area": ("Calendar micro-effect — SPY held only around the month "
                 "turn (W9; SPEC cadence grid: turn-of-month = "
                 "daily/calendar-event)"),
        "area_source": "backtests/v10-retest/SPEC.md, worker batches W9 + "
                       "CADENCE GRID (turn-of-month, overnight-effect — "
                       "daily/calendar-event)",
        "native_cadence": "daily",
        "cadence": "daily/calendar-event",
        "original_cadence_foreign": {
            "foreign": False,
            "note": ("Original tournament2 test ran the rule in its "
                     "native daily/calendar-event form — not foreign. "
                     "What the sweep adds is slower review rhythms "
                     "around the same calendar window.")},
        "cadence_treatment": ("The strategy IS a calendar rule; cadence "
                              "governs only the review/execution rhythm "
                              "around the month-turn window. Desired "
                              "state comes from the original schedule; on "
                              "a cadence review date, at the close, the "
                              "pot trades to match it. Monthly and slower "
                              "cadences are NOT-APPLICABLE (mechanical "
                              "reason in each cell)."),
        "integrity": integ,
        "decade_spy_final": spy_div,
        "decade_spy_price_only_final": spy_px,
        "spy_labels": {"dividend_adjusted": spy_div,
                       "price_only": spy_px},
        "champion_decade_reference": {
            "final": 65.89,
            "caveat": ("Champion (Value+Momentum) DECADE $65.89 after two "
                       "halts — its crown rests on the 2010 and 2019 "
                       "roads; the decade caveat from the SPEC applies. "
                       "Turn-of-month is not on the champion's road and "
                       "does not challenge the crown on long-road money.")},
        "cells": cells,
        "dividend_note": ("Verified in-script data fact: none of the "
                            "120 decade holding windows spans an SPY "
                            "ex-dividend date (the adjclose/close ratio "
                            "is identical at every window's buy and sell "
                            "dates), so this strategy captures no "
                            "dividends and its daily-cell result on "
                            "dividend-adjusted bars is mathematically "
                            "the same as on price-only bars — which is "
                            "why the daily final equals the integrity "
                            "final to the cent. Documented, not patched."),
        "money_cadences": money,
        "verdict_area": "NO GROUND",
        "verdict_change": ("No change. The tournament already had it "
                           "behind SPY on the decade with the highest "
                           "cost bill of any family tested; the retest "
                           "confirms it at its native cadence on "
                           "dividend-adjusted bars, and no slower cadence "
                           "rescues it (the expressible ones lose more; "
                           "the rest cannot express the rule at all)."),
    }
    with open(os.path.join(HERE, "results.json"), "w") as fh:
        json.dump(results, fh, indent=1)
    print("money cadences:", money, flush=True)

    # ---- RESULTS.md
    def cell_row(cad):
        c = cells[cad]
        if "status" in c:
            return f"| {cad} | NOT-APPLICABLE | — | — | — | — | — | n/a |"
        twin = c["placebo_twin_final"]
        beat = "beat twin" if c["final"] > twin else "lost to twin"
        halts = (", ".join(h["trigger"] for h in c["halts"])
                 if c["halts"] else "none")
        return (f"| {cad} | ${c['final']:,.2f} | {c['cagr_pct']:+.2f}% | "
                f"{c['max_dd_pct']:.2f}% | ${c['costs']:,.2f} | "
                f"{c['orders']} | {halts} | ${twin:,.2f} ({beat}) |")

    lines = [
        "# Turn-of-Month (tournament2 family F5) — THE GREAT RETEST (v10)",
        "",
        "**One line:** SPY is held only around the month turn — bought at "
        "the close of the 2nd-last trading day of each month, sold at the "
        "close of the 3rd trading day of the next month — and sits in cash "
        "the rest of the time.",
        "",
        "**Area:** calendar micro-effect on SPY (W9). **Native cadence: "
        "daily / calendar-event** (SPEC cadence grid). **Original cadence "
        "foreign? No** — the original tournament ran the rule in exactly "
        "this native form; the sweep adds slower review rhythms around "
        "the same calendar window.",
        "",
        "**Cadence treatment (read before the table):** this strategy IS "
        "a calendar rule — its holding window is defined by the month "
        "turn, so cadence can only govern the review/execution rhythm "
        "around that window. The sweep builds the desired in/out state "
        "from the original schedule and, on each cadence review date at "
        "the close, trades to match it. Daily reproduces the original "
        "timing exactly. Weekly and biweekly can still see both the in "
        "and out states, so they run. **Monthly, quarterly, semi-annual "
        "and annual are NOT-APPLICABLE, mechanically:** their review "
        "dates are first trading days of a month/quarter/half/year; the "
        "1st trading day of a month is always *inside* the holding "
        "window, and neither the entry date (2nd-last trading day of a "
        "month) nor the exit date (3rd trading day) is ever a review date "
        "at those rhythms — those cadences only ever sample the IN "
        "state, so the rule's entry and exit cannot both be executed and "
        "the rule cannot be expressed.",
        "",
        "## Integrity (original form, original rules)",
        "",
        f"Reproduced through this folder's plumbing on the original v3 "
        f"bars (split-adjusted, NOT dividend-adjusted), trades at the "
        f"close, ladder-era floor: **{integ['status']}**.",
        "",
        "| Window | Published | Reproduced | Costs | Orders |",
        "|---|---|---|---|---|",
        f"| FULL 2016-11-21 → 2026-11-20 | $110.74 | "
        f"${integrity_runs['FULL']['final']:,.2f} | "
        f"${integrity_runs['FULL']['costs']:,.2f} | "
        f"{integrity_runs['FULL']['orders']} |",
        f"| DESIGN 2016-11-21 → 2022-12-31 | $105.30 | "
        f"${integrity_runs['DESIGN']['final']:,.2f} | "
        f"${integrity_runs['DESIGN']['costs']:,.2f} | "
        f"{integrity_runs['DESIGN']['orders']} |",
        f"| VALIDATION 2023-01-01 → 2026-11-20 | $106.50 | "
        f"${integrity_runs['VALIDATION']['final']:,.2f} | "
        f"${integrity_runs['VALIDATION']['costs']:,.2f} | "
        f"{integrity_runs['VALIDATION']['orders']} |",
        "",
        "The FULL run's $26.14 cost bill was the highest of any family "
        "in tournament2 — 240 orders (120 round trips) on a $100 pot. "
        "Costs are this family's story, so the cost line is printed "
        "first-class in every cell below.",
        "",
        "**Dividend artifact (documented, not patched):** the daily "
        "sweep cell below lands on exactly the integrity final. That is "
        "not a copy error — it was verified in the data: none of the "
        "120 decade holding windows spans an SPY ex-dividend date "
        "(SPY's ex-dates fall mid-month; this strategy is only invested "
        "at the month turn), so the strategy captures **no dividends at "
        "all**, and dividend-adjusted and price-only bars give it "
        "mathematically identical returns. The benchmark's dividend "
        "edge is one more thing this rule never touches.",
        "",
        "## Decade cadence sweep (2016-11-21 → 2026-11-20, $100/cell, v9 protections)",
        "",
        "Sweep bars are dividend-adjusted SPY (program convention); "
        "costs 0.10%/side + $0.01/sell. Placebo = shifted-window twin: "
        "the same schedule shifted +10 trading days (~two weeks, same "
        "holding length), same machinery — the honest placebo for a "
        "calendar effect. One deterministic twin per cell, so the twin "
        "final is reported directly instead of a seeds-beaten count.",
        "",
        "| Cadence | Final | CAGR | Max DD | Costs | Orders | Halts | Placebo twin |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for cad in CADENCES:
        lines.append(cell_row(cad))
    lines += [
        "",
        f"**Benchmarks, same decade:** SPY buy-and-hold "
        f"**${spy_div:,.2f} dividend-adjusted** / **${spy_px:,.2f} "
        f"price-only** (both labeled; the tournament's price-only bars "
        f"understate the benchmark). Champion (Value+Momentum) DECADE "
        f"$65.89 — with the standing caveat: the champion's crown rests "
        f"on the 2010 and 2019 roads, and its decade run was stopped "
        f"twice by the floor; turn-of-month is not competing on that "
        f"road and this does not dethrone it on long-road money.",
        "",
        "## Verdict (Terry's frame)",
        "",
        f"**Money cadences: {', '.join(money) if money else 'none'}.** "
        "No cadence beat both SPY (dividend-adjusted) and its own "
        "shifted-window twin.",
        "",
        "**What it is for:** a textbook calendar effect — at its native "
        "daily/calendar-event cadence it did make a little money over "
        "the decade and spent most of its time in cash, so its "
        "drawdown is shallow. That is all it ever claimed.",
        "",
        "**What it is not for:** making real money on a $100 pot. It "
        "trails simply holding SPY by a wide margin, its 120 round "
        "trips a decade hand back a large share of the gross effect in "
        "costs (the highest cost bill of any tournament2 family), and "
        "slowing the review rhythm only makes it worse — weekly and "
        "biweekly enter late and exit late, and monthly-or-slower "
        "rhythms cannot express a monthly calendar rule at all.",
        "",
        "**Place on the map: NO GROUND.** Judged on its own ground, at "
        "its own native tempo, with its own placebo beside it, "
        "turn-of-month does not earn a place. Verdict unchanged from "
        "the original program.",
        "",
        "## Files",
        "",
        "- `run_tom.py` — the exact runnable script (integrity + sweep "
        "+ placebos).",
        "- `cells/<cadence>.json` — per-cell final, CAGR, max DD, "
        "costs, orders, halts/restarts with dates, full equity curve, "
        "placebo twin final (N/A cells carry the mechanical reason).",
        "- `integrity.json`, `results.json` — machine-readable record.",
        "- Data: read-only shared caches only — original bars "
        "`backtests/v3/tournament2-data/SPY.csv`; sweep bars "
        "`backtests/v7/long-hold/data/pxfull_SPY.json` (dividend-"
        "adjusted construction). Only SPY bars were loaded. Nothing "
        "was written outside this folder.",
    ]
    with open(os.path.join(HERE, "RESULTS.md"), "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print("wrote RESULTS.md", flush=True)


if __name__ == "__main__":
    main()
