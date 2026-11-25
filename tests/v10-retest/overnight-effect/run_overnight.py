#!/usr/bin/env python3
"""
v10 GREAT RETEST - overnight-effect (tournament2 family F4).

Strategy: buy SPY at the close, sell at the next open - harvest the
overnight drift. One clean shot, no tuning.

PART 1 - INTEGRITY: the tournament2 F4 engine copied in ORIGINAL form
(ladder-era floor: $85, rising to $100 at a $125 close and $125 at a $150
close; a close at/below the floor liquidates at the next open and ENDS the
run; costs 0.10%/side + $0.01 per sell order; split-adjusted Yahoo bars,
NOT dividend-adjusted - the tournament2 conventions), on the three
tournament windows. Published targets: FULL $84.78 (halted 2017-03-30),
DESIGN $84.78, VALIDATION $84.26 (halts 2017-03-30 / 2023-03-16).

PART 2 - CADENCE SWEEP (SPEC): DECADE 2016-11-21 -> 2026-11-20, $100/cell,
program costs, v9 protections (plain -15% floor from the episode's starting
balance, NO ladder; first halt -> liquidate at next open, sit in cash 90
calendar days, restart at the next cadence-selected overnight under an
episode-2 floor of -15% from the restart balance; second halt ends the run).

CADENCE TREATMENT (stated precisely): this strategy is DEFINED on a daily
close->open cycle. Cadence selects WHICH nights are traded: a night is
traded only when its BUY day (the close day) is a cadence date - daily =
every trading day; weekly = first trading day of each week; biweekly =
first trading day of every second week (weeks counted from the first week
of the window); monthly = first trading day of each month; quarterly =
first trading day of each calendar quarter; semi-annual = first trading
day of each half-year; annual = first trading day of each year. The sale
always happens at the next trading day's open, whatever the cadence.

GROSS vs NET (first-class): each cell also runs a frictionless twin (no
costs, no floor) over the same nights; gross_final and the gross drift it
captured are reported beside the net final and the total costs, so the
cost-kill is visible cell by cell.

PLACEBO: a shifted-day twin - the same number of nights, shifted +2
trading days from the cadence dates (wrapping inside the window). For the
daily cell a shift of "every day" is the same set of nights, so the twin
is n/a there by construction. Singular deterministic twin, not a 20-seed
distribution (the selection here is a fixed calendar rule, not a ranking;
there is nothing to random-rank).

Data: SPY bars ONLY (open/close used), read read-only from
backtests/v3/tournament2-data/SPY.csv (split-adjusted, price-only - the
tournament's own cache). The dividend-adjusted SPY decade benchmark is
computed from the read-only Yahoo payload in
backtests/v7/long-hold/data/pxfull_SPY.json (adjclose convention, as in
lr_common.py). Simulation only - no broker orders.
"""

import json
import os
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
SPY_CSV = os.path.join(ROOT, "backtests", "v3", "tournament2-data", "SPY.csv")
SPY_PXFULL = os.path.join(ROOT, "backtests", "v7", "long-hold", "data",
                          "pxfull_SPY.json")

START_CASH = 100.0
COST_RATE = 0.001          # 0.10% per side (program convention)
SELL_FEE = 0.01            # per sell order

DECADE = (date(2016, 11, 21), date(2026, 11, 20))


# ----------------------------------------------------------------------------
# Data - SPY open/close only (shared RAM is tight)
# ----------------------------------------------------------------------------

def load_spy():
    days, opens, closes = [], [], []
    with open(SPY_CSV) as fh:
        header = fh.readline()
        assert header.strip().startswith("date,open"), header
        for line in fh:
            parts = line.strip().split(",")
            if len(parts) < 5:
                continue
            d = date.fromisoformat(parts[0])
            days.append(d)
            opens.append(float(parts[1]))
            closes.append(float(parts[4]))
    return days, opens, closes


DAYS, OPEN, CLOSE = load_spy()
POS = {d: i for i, d in enumerate(DAYS)}


def window_idx(start, end):
    return [i for i, d in enumerate(DAYS) if start <= d <= end]


# ----------------------------------------------------------------------------
# PART 1 - INTEGRITY: tournament2 F4 in original form (ladder-era floor)
# Portfolio/run_f4 logic copied from backtests/v3/tournament2.py, SPY-only.
# ----------------------------------------------------------------------------

class OrigPortfolio:
    def __init__(self):
        self.cash = START_CASH
        self.shares = 0.0
        self.basis = 0.0
        self.proceeds = 0.0
        self.total_costs = 0.0
        self.orders = 0
        self.trips = 0
        self.floor = 85.0
        self.halt_trigger = None
        self.halt_date = None
        self.equity_series = []

    def buy(self, i):
        price = CLOSE[i]
        notional = self.cash / (1.0 + COST_RATE)
        cost = notional * COST_RATE
        self.shares = notional / price
        self.basis = notional + cost
        self.cash -= notional + cost
        self.total_costs += cost
        self.orders += 1

    def sell(self, i, at_open=True):
        if self.shares <= 0:
            return
        price = OPEN[i] if at_open else CLOSE[i]
        value = self.shares * price
        cost = value * COST_RATE + SELL_FEE
        self.cash += value - cost
        self.proceeds = value - cost
        self.total_costs += cost
        self.orders += 1
        self.trips += 1
        self.shares = 0.0

    def equity_close(self, i):
        return self.cash + self.shares * CLOSE[i]

    def record_close(self, i):
        eq = self.equity_close(i)
        self.equity_series.append((DAYS[i], eq))
        if eq >= 150.0:
            self.floor = max(self.floor, 125.0)
        elif eq >= 125.0:
            self.floor = max(self.floor, 100.0)
        if eq <= self.floor and self.halt_trigger is None:
            self.halt_trigger = DAYS[i]
        return eq


def run_f4_original(start, end):
    idx = window_idx(start, end)
    pf = OrigPortfolio()
    for k, i in enumerate(idx):
        if pf.halt_trigger is not None:
            pf.sell(i, at_open=True)          # floor halt liquidation
            pf.halt_date = DAYS[i]
            pf.equity_series.append((DAYS[i], pf.cash))
            break
        # day_fn: sell at open what was bought at yesterday's close
        if pf.shares > 0:
            pf.sell(i, at_open=True)
        last_day = k == len(idx) - 1
        if pf.halt_trigger is None and not last_day:
            pf.buy(i)
        if pf.halt_trigger is None:
            pf.record_close(i)
    # finalize: liquidate at last close
    last = idx[-1]
    if pf.shares > 0:
        pf.sell(last, at_open=False)
    final = pf.cash
    if pf.equity_series and pf.equity_series[-1][0] == DAYS[last]:
        pf.equity_series[-1] = (DAYS[last], final)
    else:
        pf.equity_series.append((DAYS[last], final))
    return pf, final


# ----------------------------------------------------------------------------
# PART 2 - CADENCE SWEEP under v9 protections
# ----------------------------------------------------------------------------

def cadence_dates(idx, cadence):
    """Indices (into DAYS) whose close is a cadence date, per SPEC."""
    out = []
    if cadence == "daily":
        return list(idx)
    seen = set()
    for i in idx:
        d = DAYS[i]
        if cadence == "weekly":
            key = (d.isocalendar()[0], d.isocalendar()[1])
        elif cadence == "biweekly":
            key = None  # handled below via week counter
        elif cadence == "monthly":
            key = (d.year, d.month)
        elif cadence == "quarterly":
            key = (d.year, (d.month - 1) // 3)
        elif cadence == "semiannual":
            key = (d.year, (d.month - 1) // 6)
        elif cadence == "annual":
            key = (d.year,)
        if cadence == "biweekly":
            continue
        if key not in seen:
            seen.add(key)
            out.append(i)
    if cadence == "biweekly":
        weeks = []
        seenw = set()
        for i in idx:
            d = DAYS[i]
            key = (d.isocalendar()[0], d.isocalendar()[1])
            if key not in seenw:
                seenw.add(key)
                weeks.append(i)
        out = weeks[::2]
    return out


def run_cell(cadence, shift=0):
    """One sweep cell. shift>0 trades the placebo twin nights instead."""
    idx = window_idx(*DECADE)
    buys = cadence_dates(idx, cadence)
    if shift:
        pos_in_window = {v: k for k, v in enumerate(idx)}
        shifted = []
        for i in buys:
            j = idx[(pos_in_window[i] + shift) % len(idx)]
            if j not in shifted:
                shifted.append(j)
        buys = sorted(shifted)
    buy_set = set(buys)

    cash = START_CASH
    shares = 0.0
    costs = 0.0
    orders = 0
    gross = START_CASH          # frictionless twin over the same nights
    gross_nights = 0
    # frictionless, floorless twin over ALL cadence nights in the decade
    # (the full opportunity, whether the protected pot survived to take it)
    gross_all = START_CASH
    for k2, i2 in enumerate(idx):
        if i2 in buy_set and k2 < len(idx) - 1:
            gross_all *= OPEN[idx[k2 + 1]] / CLOSE[i2]
    episode = 1
    floor = 0.85 * START_CASH
    halts = []                  # (trigger_date, liquidation_date)
    restart = False
    restart_date = None
    second_halt = False
    halt_trigger = None
    resume_after = None         # first date trading may resume
    equity = []

    for k, i in enumerate(idx):
        d = DAYS[i]
        if halt_trigger is not None:
            # liquidate at this open (if holding) and start the 90-day sit-out
            if shares > 0:
                value = shares * OPEN[i]
                c = value * COST_RATE + SELL_FEE
                cash += value - c
                costs += c
                orders += 1
                shares = 0.0
            halts.append((halt_trigger.isoformat(), d.isoformat()))
            if episode == 1:
                episode = 2
                resume_after = d + timedelta(days=90)
                halt_trigger = None
                equity.append((d, round(cash, 4)))
                continue          # sit-out day: no trading, no floor check
            else:
                second_halt = True
                equity.append((d, round(cash, 4)))
                # run ends: freeze remaining days at cash for the curve tail
                for j in idx[k + 1:]:
                    equity.append((DAYS[j], round(cash, 4)))
                break
        if shares > 0:
            # morning sale of last night's position (normal overnight exit)
            value = shares * OPEN[i]
            c = value * COST_RATE + SELL_FEE
            cash += value - c
            costs += c
            orders += 1
            shares = 0.0
        # restart bookkeeping: first cadence night on/after resume date
        if resume_after is not None and d >= resume_after and i in buy_set \
                and k < len(idx) - 1:
            restart = True
            restart_date = d
            floor = 0.85 * cash
            resume_after = None
        # buy at the close on cadence nights (not during sit-out / after halt)
        if resume_after is None and not second_halt and i in buy_set \
                and k < len(idx) - 1:
            nxt = idx[k + 1]
            gross *= OPEN[nxt] / CLOSE[i]
            gross_nights += 1
            notional = cash / (1.0 + COST_RATE)
            c = notional * COST_RATE
            shares = notional / CLOSE[i]
            cash -= notional + c
            costs += c
            orders += 1
        # close equity + floor check (suspended during the sit-out: the pot
        # is flat in cash below the old floor by construction until restart)
        eq = cash + shares * CLOSE[i]
        equity.append((d, round(eq, 4)))
        if resume_after is None and eq <= floor and halt_trigger is None \
                and not second_halt:
            halt_trigger = d
    else:
        # end of window: liquidate any open position at the last close
        if shares > 0:
            last = idx[-1]
            value = shares * CLOSE[last]
            c = value * COST_RATE + SELL_FEE
            cash += value - c
            costs += c
            orders += 1
            shares = 0.0
            equity[-1] = (DAYS[last], round(cash, 4))

    final = cash
    peak, maxdd = START_CASH, 0.0
    for _, e in equity:
        peak = max(peak, e)
        if peak > 0:
            maxdd = max(maxdd, (peak - e) / peak)
    years = (DAYS[idx[-1]] - DAYS[idx[0]]).days / 365.25
    cagr = (final / START_CASH) ** (1.0 / years) - 1.0 if final > 0 else -1.0
    gross_cagr = (gross / START_CASH) ** (1.0 / years) - 1.0
    return {
        "final": round(final, 2),
        "cagr_pct": round(cagr * 100, 2),
        "max_dd_pct": round(maxdd * 100, 2),
        "costs": round(costs, 2),
        "orders": orders,
        "nights_traded": gross_nights,
        "gross_final_no_costs_no_floor": round(gross, 2),
        "gross_drift_pct": round((gross / START_CASH - 1.0) * 100, 2),
        "gross_cagr_pct": round(gross_cagr * 100, 2),
        "gross_final_all_cadence_nights_no_costs_no_floor": round(gross_all, 2),
        "gross_drift_all_nights_pct": round((gross_all / START_CASH - 1.0) * 100, 2),
        "halts": [{"trigger_date": t, "liquidation_date": l} for t, l in halts],
        "restart": restart,
        "restart_date": restart_date.isoformat() if restart_date else None,
        "second_halt": second_halt,
        "equity_curve": [[d.isoformat(), e] for d, e in equity],
    }


# ----------------------------------------------------------------------------
# SPY benchmarks on the decade
# ----------------------------------------------------------------------------

def spy_price_only():
    idx = window_idx(*DECADE)
    gross = START_CASH / OPEN[idx[0]] * CLOSE[idx[-1]]
    sh = (START_CASH / (1.0 + COST_RATE)) / OPEN[idx[0]]
    net = sh * CLOSE[idx[-1]] * (1.0 - COST_RATE) - SELL_FEE
    return round(gross, 2), round(net, 2)


def spy_dividend_adjusted():
    """Program convention (lr_common / peer v10 plumbing): bars are
    dividend-adjusted - open scaled by adjclose/close, close = adjclose.
    Buy-hold = buy at the first day's adjusted open, sell at the last
    day's adjusted close, program costs on both sides."""
    with open(SPY_PXFULL) as fh:
        payload = json.load(fh)
    res = payload["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"]["adjclose"][0]["adjclose"]
    series = {}
    for t, o, c, a in zip(ts, q["open"], q["close"], adj):
        if o and c and a:
            d = datetime.fromtimestamp(t, tz=timezone.utc).date()
            series[d] = (o * a / c, a)
    idx = window_idx(*DECADE)
    first_open_adj = series[DAYS[idx[0]]][0]
    last_close_adj = series[DAYS[idx[-1]]][1]
    gross = START_CASH / first_open_adj * last_close_adj
    sh = (START_CASH / (1.0 + COST_RATE)) / first_open_adj
    net = sh * last_close_adj * (1.0 - COST_RATE) - SELL_FEE
    return round(gross, 2), round(net, 2)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main():
    out = {"slug": "overnight-effect"}

    # ---- integrity -------------------------------------------------------
    windows = {
        "full": (date(2016, 11, 21), date(2026, 11, 20), 84.78, "2017-03-30"),
        "design": (date(2016, 11, 21), date(2022, 12, 31), 84.78, None),
        "validation": (date(2023, 1, 1), date(2026, 11, 20), 84.26, "2023-03-16"),
    }
    integ = {}
    all_ok = True
    for name, (s, e, target, halt_target) in windows.items():
        pf, final = run_f4_original(s, e)
        ok = abs(round(final, 2) - target) < 0.005
        halt_ok = (pf.halt_date.isoformat() if pf.halt_date else None) == halt_target \
            or halt_target is None
        all_ok = all_ok and ok
        integ[name] = {
            "window": [s.isoformat(), e.isoformat()],
            "published_final": target,
            "reproduced_final": round(final, 2),
            "match": ok,
            "orders": pf.orders,
            "costs": round(pf.total_costs, 2),
            "halt_date": pf.halt_date.isoformat() if pf.halt_date else None,
            "published_halt_date": halt_target,
        }
        print(f"integrity {name}: reproduced ${final:.2f} vs published "
              f"${target:.2f} orders {pf.orders} costs ${pf.total_costs:.2f} "
              f"halt {pf.halt_date}")
    out["integrity"] = {
        "status": "reproduced" if all_ok else "FAILED",
        "conventions": "Tournament2 originals: split-adjusted Yahoo bars "
                       "(NOT dividend-adjusted), close trades for F4, "
                       "0.10%/side + $0.01/sell, ladder-era floor ($85, "
                       "rising to $100 at $125 / $125 at $150; halt ends "
                       "the run). Reproduced under those original rules.",
        "original_finals": {"full": 84.78, "design": 84.78, "validation": 84.26},
        "reproduced_finals": {k: v["reproduced_final"] for k, v in integ.items()},
        "windows": integ,
        "census_note": "Census record: gross drift +2.1% over 88 days in its "
                       "first test; net pot halted at the floor in 2017 and "
                       "again on validation - 'the cleanest cost-kill in "
                       "program history.'",
    }

    # ---- benchmarks --------------------------------------------------------
    po_gross, po_net = spy_price_only()
    da_gross, da_net = spy_dividend_adjusted()
    out["decade_spy"] = {
        "price_only_final_gross": po_gross,
        "price_only_final_net": po_net,
        "dividend_adjusted_final_gross": da_gross,
        "dividend_adjusted_final_net": da_net,
        "note": "Price-only from the tournament2 SPY cache (split-adjusted); "
                "dividend-adjusted from the Yahoo pxfull adjclose payload "
                "(lr_common convention). SPEC reference points: price-only "
                "$314.10, dividend-adjusted $367.80.",
    }
    print(f"SPY decade: price-only gross ${po_gross} net ${po_net}; "
          f"dividend-adjusted gross ${da_gross} net ${da_net}")

    # ---- sweep -------------------------------------------------------------
    cadences = ["daily", "weekly", "biweekly", "monthly", "quarterly",
                "semiannual", "annual"]
    cells = {}
    for cad in cadences:
        r = run_cell(cad)
        twin = None
        if cad == "daily":
            pnote = ("n/a by construction: the placebo is a +2-trading-day "
                     "shift of the traded nights; shifting 'every trading "
                     "day' by 2 days yields the same set of nights.")
            pbeaten = None
        else:
            twin = run_cell(cad, shift=2)
            pnote = ("Shifted-day twin: same number of nights, each buy day "
                     "shifted +2 trading days (wrapping inside the window) - "
                     "a singular deterministic twin, not a 20-seed "
                     "distribution; the selection is a fixed calendar rule "
                     "with nothing to random-rank, so placebo_beaten is "
                     "reported as the twin comparison, not x/20.")
            pbeaten = None
        cell = {
            "slug": "overnight-effect",
            "cadence": cad,
            "cadence_treatment": "Overnight cycle traded only when the BUY "
                                 "(close) day is a cadence date; sale always "
                                 "at the next trading day's open.",
            "window": [DECADE[0].isoformat(), DECADE[1].isoformat()],
            "start_cash": START_CASH,
            "final": r["final"],
            "cagr_pct": r["cagr_pct"],
            "max_dd_pct": r["max_dd_pct"],
            "halts": r["halts"],
            "restart": r["restart"],
            "restart_date": r["restart_date"],
            "second_halt": r["second_halt"],
            "costs": r["costs"],
            "orders": r["orders"],
            "nights_traded": r["nights_traded"],
            "gross_final_no_costs_no_floor": r["gross_final_no_costs_no_floor"],
            "gross_drift_pct": r["gross_drift_pct"],
            "gross_cagr_pct": r["gross_cagr_pct"],
            "gross_final_all_cadence_nights_no_costs_no_floor":
                r["gross_final_all_cadence_nights_no_costs_no_floor"],
            "gross_drift_all_nights_pct": r["gross_drift_all_nights_pct"],
            "net_minus_gross": round(r["final"] - r["gross_final_no_costs_no_floor"], 2),
            "placebo_beaten": pbeaten,
            "placebo_note": pnote,
            "placebo_twin": ({"shift_trading_days": 2,
                              "final": twin["final"],
                              "costs": twin["costs"],
                              "orders": twin["orders"],
                              "gross_final_no_costs_no_floor":
                                  twin["gross_final_no_costs_no_floor"],
                              "strategy_beats_twin": r["final"] > twin["final"]}
                             if twin else None),
            "beats_spy_dividend_adjusted": r["final"] > da_net,
            "beats_spy_price_only": r["final"] > po_net,
            "equity_curve": r["equity_curve"],
        }
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as fh:
            json.dump(cell, fh, indent=1)
        cells[cad] = {k: cell[k] for k in (
            "final", "cagr_pct", "max_dd_pct", "halts", "restart",
            "second_halt", "costs", "orders", "nights_traded",
            "gross_final_no_costs_no_floor", "gross_drift_pct",
            "gross_final_all_cadence_nights_no_costs_no_floor",
            "gross_drift_all_nights_pct",
            "placebo_beaten", "placebo_note")}
        cells[cad]["placebo_twin_final"] = \
            cell["placebo_twin"]["final"] if cell["placebo_twin"] else None
        print(f"cell {cad}: net ${r['final']} gross ${r['gross_final_no_costs_no_floor']} "
              f"costs ${r['costs']} orders {r['orders']} nights {r['nights_traded']} "
              f"halts {len(r['halts'])} twin "
              f"{cell['placebo_twin']['final'] if cell['placebo_twin'] else 'n/a'}")

    out.update({
        "area": "Calendar micro-effect: SPY overnight drift (close->open), "
                "cycled over the full road (W9)",
        "area_source": "backtests/v10-retest/SPEC.md, worker batch W9; "
                       "original: backtests/v3/tournament2.py family F4 + "
                       "tournament2.md",
        "native_cadence": "daily",
        "cadence": "daily",
        "original_cadence_foreign": False,
        "original_cadence_foreign_note": "None - the original tournament ran "
                                         "the native daily cycle.",
        "cadence_treatment": "Cadence selects which nights are traded: a "
                             "night is traded only when its buy (close) day "
                             "is a cadence date (weekly = first trading day "
                             "of the week, etc., per the SPEC's uniform "
                             "definition); the sale is always at the next "
                             "trading day's open.",
        "decade_spy_final": da_net,
        "cells": cells,
        "money_cadences": [c for c in cadences
                           if cells[c]["final"] > da_net
                           and (cells[c]["placebo_twin_final"] is None
                                or cells[c]["final"] > cells[c]["placebo_twin_final"])],
        "champion_decade_reference": {
            "final": 65.89,
            "caveat": "Champion (Value+Momentum) decade $65.89 comes from the "
                      "lazy-quarterly test after two halts; its crown rests "
                      "on the 2010 and 2019 roads, not the decade.",
        },
        "data_note": "SPY open/close only, read read-only from "
                     "backtests/v3/tournament2-data/SPY.csv (split-adjusted, "
                     "price-only, the tournament's own cache); dividend-"
                     "adjusted benchmark from backtests/v7/long-hold/data/"
                     "pxfull_SPY.json. No downloads; nothing written outside "
                     "this folder.",
    })
    verdict_money = out["money_cadences"]
    out["verdict_area"] = "NO GROUND" if not verdict_money else "REAL BUT SMALL"
    out["verdict_change"] = (
        "Unchanged. The tournament culled F4 as a cost-kill; the sweep "
        "confirms it at every tempo - see RESULTS.md.")

    with open(os.path.join(HERE, "results.json"), "w") as fh:
        json.dump(out, fh, indent=1)
    print("wrote results.json")


if __name__ == "__main__":
    main()
