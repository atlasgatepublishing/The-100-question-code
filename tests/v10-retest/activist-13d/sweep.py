#!/usr/bin/env python3
"""
THE GREAT RETEST (v10) — activist-13d DECADE CADENCE SWEEP.

Strategy: initial Schedule 13D events on the champion's honest
point-in-time top-30 pond (Brav, Jiang, Partnoy & Thomas 2008 form, as
run in v6). ONE clean shot, no tuning.

ROAD: DECADE 2016-11-21 -> 2026-11-20, $100/cell, program costs
(0.10%/side + $0.01 per sell order), point-in-time, v9 protections
(plain -15% floor from the episode's starting balance, NO ladder;
first halt -> liquidate at next open, sit in cash 90 calendar days,
restart at the next regular decision point under an episode-2 floor of
-15% from the restart balance; second halt ends the run).

CADENCE TREATMENT FOR THIS EVENT STRATEGY (per SPEC, stated plainly):
  - The EVENT rules stay exactly as published: an initial SC 13D filed
    on a pond name is entered at the first trading-day OPEN strictly
    after the filing's EDGAR acceptance timestamp. Cadence does NOT
    gate entries — the filing is the event.
  - Cadence governs the position REVIEW / EXIT rhythm only: the
    published 12-month hold is exited at the OPEN of the first cadence
    date on/after the 12-month anniversary of entry, and the -15%
    floor is reviewed at the CLOSE of cadence dates only (a breach
    liquidates at the next trading-day open, the original engine's
    convention). Daily cadence therefore reproduces the original form
    exactly (exit on the anniversary open, floor checked daily).
  - Cadence dates (SPEC uniform definition): daily = every trading
    day; weekly = first trading day of each week; biweekly = first
    trading day of every second week (weeks counted from the first
    week of the window); monthly = first trading day of each month;
    quarterly = first trading day of each calendar quarter;
    semi-annual = first trading day of each half-year; annual = first
    trading day of each year.
  - Portfolio rules unchanged: each event invests 1/5 of the pot's
    market value at the entry open; max 5 concurrent lots; exits at an
    open execute before entries at that open; a position still open at
    the window's end is liquidated at the final close (SELL-END).

EVENTS: the census reproduced in this folder by engine.py (the
original v6 engine, byte-identical) into activist-13d-results.json —
1 qualifying event in the whole decade. The pond is NOT widened; the
cache is the original EDGAR atom/header/document cache.

PLACEBOS: not run, by the original test's own pre-stated rule (the
+6-month date-shift placebo runs only for a window holding >= 4
events) and by arithmetic: with n=1 event decade-wide there is no
distribution to randomize — any "twin" would be the same single trade.
placebo_beaten = null in every cell, with this note attached.

Outputs: cells/<cadence>.json (full equity curve, halts/restarts,
event stats, placebo note) and results.json (SPEC sweep format).
"""
import importlib.util
import json
import os
from datetime import date as _date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)

spec = importlib.util.spec_from_file_location(
    "orig_engine", os.path.join(HERE, "engine.py"))
OE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(OE)
E = OE.E

START, END = "2016-11-21", "2026-11-20"
START_CASH = 100.0
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]
PLACEBO_NOTE = ("infeasible: n=1 qualifying event in the whole decade "
                "(original test's own pre-stated rule runs its +6-month "
                "date-shift placebo only for windows with >=4 events; "
                "a 20-seed random placebo has nothing to randomize with "
                "one event, one target, one date)")


def cadence_dates(days, cadence):
    """SPEC uniform cadence dates drawn from the window's trading days."""
    if cadence == "daily":
        return set(days)
    out, seen = [], set()
    week_index = {}
    for d in days:
        dt = _date(int(d[:4]), int(d[5:7]), int(d[8:10]))
        iso = dt.isocalendar()
        wk = (iso[0], iso[1])
        if wk not in week_index:
            week_index[wk] = len(week_index)
        if cadence == "weekly":
            key = wk
        elif cadence == "biweekly":
            if week_index[wk] % 2 == 1:
                continue
            key = ("bi", week_index[wk] // 2)
        elif cadence == "monthly":
            key = (dt.year, dt.month)
        elif cadence == "quarterly":
            key = (dt.year, (dt.month - 1) // 3)
        elif cadence == "semiannual":
            key = (dt.year, (dt.month - 1) // 6)
        elif cadence == "annual":
            key = (dt.year,)
        else:
            raise ValueError(cadence)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return set(out)


def first_cadence_on_or_after(cdates_sorted, dstr):
    for d in cdates_sorted:
        if d >= dstr:
            return d
    return None


def run_cell(pb, events, cadence):
    days = [d for d in pb.dates if START <= d <= END]
    cdates = cadence_dates(days, cadence)
    cdates_sorted = sorted(cdates)
    cash = START_CASH
    total_costs = 0.0
    orders = []
    lots, closed, skipped = [], [], []
    halts = []               # {signal_date, liquidate_date, episode, value}
    restarts = []            # {date, balance, floor}
    episode = 1
    floor = 0.85 * START_CASH
    ended = False
    sit_until = None         # calendar date; no entries before this
    curve = []

    # schedule entries by entry day (event rule, cadence-independent)
    sched = {}
    for ev in events:
        if not (START <= ev["filed_date"] <= END):
            continue
        ed = OE.entry_day_for(pb, ev)
        if ed is None or ed > END:
            skipped.append({**ev, "reason": "no entry day inside window"})
            continue
        sched.setdefault(ed, []).append(ev)

    def open_value(d):
        v = cash
        for lot in lots:
            b = pb.bar(lot["ticker"], d)
            px = b["o"] if b else pb.close_on_or_before(lot["ticker"], d)
            if px:
                v += lot["shares"] * px
        return v

    def close_value(d):
        v = cash
        for lot in lots:
            c = pb.close_on_or_before(lot["ticker"], d)
            if c:
                v += lot["shares"] * c
        return v

    def sell_lot(lot, d, price, reason):
        nonlocal cash, total_costs
        val = lot["shares"] * price
        c = val * 0.001 + 0.01
        cash += val - c
        total_costs += c
        orders.append({"date": d, "ticker": lot["ticker"],
                       "side": "SELL-" + reason, "shares": lot["shares"],
                       "price": round(price, 4), "value": round(val, 2),
                       "cost": round(c, 4)})
        closed.append({**lot, "exit_date": d,
                       "exit_price": round(price, 4), "exit_reason": reason,
                       "proceeds_net": round(val - c, 2),
                       "return_pct": round((val - c) / lot["outlay"] * 100 - 100, 2)})

    exits = {}   # cadence exit day -> [lot ids]
    lot_seq = [0]
    di = 0
    while di < len(days):
        d = days[di]
        if ended:
            curve.append([d, round(cash, 4)])
            di += 1
            continue
        # restart bookkeeping: first cadence date at/after sit-out end
        if sit_until is not None and d in cdates and d >= sit_until:
            restarts.append({"date": d, "balance": round(cash, 2),
                             "floor": round(0.85 * cash, 2), "episode": episode})
            floor = 0.85 * cash
            sit_until = None
        # (1) scheduled 12-month exits at today's open (cadence dates only)
        for lid in exits.pop(d, []):
            lot = next((L for L in lots if L["id"] == lid), None)
            if lot is None:
                continue
            b = pb.bar(lot["ticker"], d)
            if b:
                lots.remove(lot)
                sell_lot(lot, d, b["o"], "12MO-CADENCE")
        # (2) entries at today's open (event rule; blocked while sitting out)
        for ev in sched.get(d, []):
            if sit_until is not None:
                skipped.append({**ev, "reason": "inside post-halt 90-day sit-out",
                                "entry_day": d})
                continue
            if len(lots) >= 5:
                skipped.append({**ev, "reason": "book full (5 lots open)",
                                "entry_day": d})
                continue
            b = pb.bar(ev["ticker"], d)
            if not b:
                skipped.append({**ev, "reason": "no bar on entry day",
                                "entry_day": d})
                continue
            pv = open_value(d)
            buy_val = min(pv / 5.0, cash / 1.001)
            if buy_val <= 0.005:
                skipped.append({**ev, "reason": "no cash for slice",
                                "entry_day": d})
                continue
            sh = buy_val / b["o"]
            c = buy_val * 0.001
            cash -= buy_val + c
            total_costs += c
            orders.append({"date": d, "ticker": ev["ticker"], "side": "BUY",
                           "shares": sh, "price": round(b["o"], 4),
                           "value": round(buy_val, 2), "cost": round(c, 4)})
            lot_seq[0] += 1
            anniv = OE.add_months(d, 12)
            xd = first_cadence_on_or_after(cdates_sorted, anniv)
            lot = {"id": lot_seq[0], "ticker": ev["ticker"],
                   "filer_name": ev["filer_name"],
                   "filed_date": ev["filed_date"],
                   "accession": ev["accession"],
                   "entry_date": d, "entry_price": round(b["o"], 4),
                   "shares": sh, "outlay": round(buy_val + c, 2),
                   "anniversary": anniv, "exit_due": xd}
            lots.append(lot)
            if xd is not None and xd <= END:
                exits.setdefault(xd, []).append(lot["id"])
        # (3) floor review at cadence-date closes only
        v = close_value(d)
        curve.append([d, round(v, 4)])
        if d in cdates and v <= floor and di < len(days) - 1:
            nd = days[di + 1]
            for lot in list(lots):
                b = pb.bar(lot["ticker"], nd)
                if b:
                    lots.remove(lot)
                    sell_lot(lot, nd, b["o"], "HALT")
            halts.append({"signal_date": d, "signal_close": round(v, 2),
                          "liquidate_date": nd, "episode": episode,
                          "floor_in_effect": round(floor, 2)})
            if episode >= 2:
                ended = True
            else:
                episode = 2
                sit_until = (_date(int(nd[:4]), int(nd[5:7]), int(nd[8:10]))
                             + timedelta(days=90)).isoformat()
            curve[-1] = [d, round(v, 4)]
            di += 1
            # record the liquidation day's close value too
            if di < len(days):
                curve.append([days[di], round(close_value(days[di]), 4)])
            di += 1
            continue
        di += 1
    if not ended:
        last = days[-1]
        for lot in list(lots):
            c_ = pb.close_on_or_before(lot["ticker"], last)
            if c_:
                lots.remove(lot)
                sell_lot(lot, last, c_, "END")
        if curve and curve[-1][0] == last:
            curve[-1] = [last, round(cash, 4)]
    # stats
    peak, max_dd = START_CASH, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            max_dd = min(max_dd, v / peak - 1.0)
    years = (_date(2026, 11, 20) - _date(2016, 11, 21)).days / 365.25
    final = cash
    cagr = (final / START_CASH) ** (1.0 / years) * 100 - 100
    return {"final": round(final, 2), "cagr_pct": round(cagr, 3),
            "max_dd_pct": round(max_dd * 100, 3),
            "costs": round(total_costs, 2), "orders": len(orders),
            "orders_detail": orders, "halts": halts, "restarts": restarts,
            "second_halt": any(h["episode"] >= 2 for h in halts),
            "lots": closed, "skipped": skipped, "curve": curve}


def standalone_cadence(pb, ev, cdates_sorted):
    """$20 slice, entry open -> exit open on first cadence date on/after
    the 12-month anniversary; SPY over the identical span, same costs."""
    ed = OE.entry_day_for(pb, ev)
    b = pb.bar(ev["ticker"], ed)
    anniv = OE.add_months(ed, 12)
    xd = first_cadence_on_or_after(cdates_sorted, anniv)
    truncated = False
    if xd is None:
        xd = pb.dates[-1]
        truncated = True
    out = {"entry_date": ed, "entry_price": round(b["o"], 4),
           "anniversary": anniv, "exit_date": xd, "truncated": truncated}
    for t, key in ((ev["ticker"], "ret_pct"), ("SPY", "spy_ret_pct")):
        bb = pb.bar(t, ed)
        xx = pb.bar(t, xd)
        xp = xx["o"] if (xx and not truncated) else pb.close_on_or_before(t, xd)
        out[key + "_exit_price"] = round(xp, 4)
        buy_val = 20.0 / 1.001
        sh = buy_val / bb["o"]
        val = sh * xp
        net = val - (val * 0.001 + 0.01)
        out[key] = round(net / 20.0 * 100 - 100, 2)
    out["excess_vs_spy_pct"] = round(out["ret_pct"] - out["spy_ret_pct"], 2)
    return out


def main():
    census = json.load(open(os.path.join(HERE, "activist-13d-results.json")))
    events = census["census"]
    bars = {}
    for t in OE.UNIVERSE + ["SPY"]:
        bars[t] = OE.get_prices_long(t)
    pb = E.PriceBook(bars)
    spy_final, _ = E.spy_net(pb, START, END, START_CASH)
    print(f"DECADE SPY (long book, program convention): ${spy_final:,.2f}",
          flush=True)
    days = [d for d in pb.dates if START <= d <= END]
    results = {"slug": "activist-13d",
               "decade_spy_final": round(spy_final, 2), "cells": {}}
    for cad in CADENCES:
        r = run_cell(pb, events, cad)
        cdates_sorted = sorted(cadence_dates(days, cad))
        ev_stats = [standalone_cadence(pb, ev, cdates_sorted) for ev in events]
        cell = {"final": r["final"], "cagr_pct": r["cagr_pct"],
                "max_dd_pct": r["max_dd_pct"],
                "halts": len(r["halts"]), "halts_detail": r["halts"],
                "restart": bool(r["restarts"]), "restarts": r["restarts"],
                "second_halt": r["second_halt"], "costs": r["costs"],
                "orders": r["orders"], "orders_detail": r["orders_detail"],
                "events_in_window": len(events),
                "events_traded": len(r["lots"]),
                "events_skipped": r["skipped"], "lots": r["lots"],
                "event_stats": ev_stats,
                "placebo_beaten": None, "placebo_note": PLACEBO_NOTE,
                "placebo_twin_finals": None,
                "equity_curve": r["curve"]}
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump(cell, f, indent=1)
        results["cells"][cad] = {
            "final": r["final"], "cagr_pct": r["cagr_pct"],
            "max_dd_pct": r["max_dd_pct"], "halts": len(r["halts"]),
            "restart": bool(r["restarts"]), "second_halt": r["second_halt"],
            "costs": r["costs"], "orders": r["orders"],
            "placebo_beaten": None, "placebo_note": PLACEBO_NOTE}
        e0 = ev_stats[0] if ev_stats else {}
        print(f"{cad:11s} final=${r['final']:,.2f} CAGR={r['cagr_pct']:+.3f}% "
              f"maxDD={r['max_dd_pct']:.3f}% orders={r['orders']} "
              f"costs=${r['costs']:.2f} halts={len(r['halts'])} | event: "
              f"{e0.get('ret_pct')}% vs SPY {e0.get('spy_ret_pct')}% "
              f"excess {e0.get('excess_vs_spy_pct')}% exit {e0.get('exit_date')}",
              flush=True)
    with open(os.path.join(HERE, "sweep-cells.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("DONE")


if __name__ == "__main__":
    main()
