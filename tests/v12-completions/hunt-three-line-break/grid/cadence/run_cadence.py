#!/usr/bin/env python3
"""Cadence grid slice — hunt-three-line-break (SPY, the family's primary record).

Second-Chance Protocol, DECADE road (2016-11-21 -> 2026-11-20), v10 timer
convention: cadence = signal-evaluation frequency. The frozen TLB signal
engine (run_tlb.py, read-only import) runs on daily closes exactly as
published; at cadences slower than daily the dictated state is only ACTED ON
at evaluation dates (first trading day of each cadence period), executed at
that day's close — the frozen form's own execution point. The state held
between evaluation dates is the state dictated at the last evaluation date.
No rule, window, or cost is changed. Program costs 0.10%/side + $0.01 sell
fee. Both rulebooks of the primary run are swept: NATIVE (bare published
rules) and HOUSE v9 (plain -15% floor chassis from run_tlb.simulate).
Placebos: 20-seed circular shifts of the cadence-sampled state series inside
the window (run_tlb.placebo_finals, seeds 4200+s — identical machinery to the
primary run, so the daily cell must reproduce the primary record exactly).
Writes ONLY into this grid/cadence folder.
"""
import json, os, sys, statistics
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
FAM = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, FAM)
import run_tlb as T  # read-only import of the frozen engine

START, END = T.ROADS["DECADE"]
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly", "semiannual", "annual"]


def period_key(dstr, cadence):
    y, m, dd = int(dstr[:4]), int(dstr[5:7]), int(dstr[8:10])
    if cadence == "daily":
        return dstr
    if cadence in ("weekly", "biweekly"):
        iso = date(y, m, dd).isocalendar()
        wk = iso[1]
        if cadence == "biweekly":
            wk = (wk - 1) // 2
        return (iso[0], wk)
    if cadence == "monthly":
        return (y, m)
    if cadence == "quarterly":
        return (y, (m - 1) // 3)
    if cadence == "semiannual":
        return (y, (m - 1) // 6)
    if cadence == "annual":
        return (y,)
    raise ValueError(cadence)


def eval_indices(dates, cadence):
    """First trading day of each cadence period, over the full series."""
    if cadence == "daily":
        return set(range(len(dates)))
    out = set()
    seen = set()
    for i, d in enumerate(dates):
        k = period_key(d, cadence)
        if k not in seen:
            seen.add(k)
            out.add(i)
    return out


def sampled_desired(dates, desired, cadence):
    ev = eval_indices(dates, cadence)
    out = [0] * len(dates)
    cur = 0
    for i in range(len(dates)):
        if i in ev:
            cur = desired[i]
        out[i] = cur
    return out


def cadence_period_stats(curve, cadence):
    """Per-period distribution at the cell's own tempo."""
    buckets = {}
    order = []
    for d, v in curve:
        k = str(period_key(d, cadence))
        if k not in buckets:
            order.append(k)
        buckets[k] = v
    vals = [buckets[k] for k in order]
    rets = []
    prev = T.START
    for v in vals:
        rets.append(v / prev - 1.0)
        prev = v
    if not rets:
        return None
    prof = sum(1 for r in rets if r > 0)
    longest_loss = 0
    run = 0
    for r in rets:
        run = run + 1 if r < 0 else 0
        longest_loss = max(longest_loss, run)
    peak = -1.0
    since = 0
    longest_gap = 0
    for v in vals:
        if v > peak:
            peak = v
            since = 0
        else:
            since += 1
            longest_gap = max(longest_gap, since)
    return {"periods": len(rets), "pct_profitable": round(100.0 * prof / len(rets), 1),
            "median_pct": round(100.0 * statistics.median(rets), 2),
            "best_pct": round(100.0 * max(rets), 2), "worst_pct": round(100.0 * min(rets), 2),
            "longest_losing_run": longest_loss,
            "longest_between_highs_periods": longest_gap,
            "average_pct_secondary": round(100.0 * statistics.mean(rets), 2)}


def main():
    dates, opens, closes = T.load_stock("SPY")
    desired, nlines, nb, ns = T.tlb_desired(closes)
    i0, i1 = T.idx_range(dates, START, END)
    cells = {}
    for cad in CADENCES:
        des = sampled_desired(dates, desired, cad)
        cell = {"cadence": cad, "evaluation": "first trading day of period; state acted on at that day's close (frozen execution point)"}
        for rules, house in (("native", False), ("v9", True)):
            r = T.simulate(dates, opens, closes, des, i0, i1, T.STK_COST, T.STK_FEE, house)
            pl = T.placebo_finals(dates, opens, closes, des, i0, i1, T.STK_COST, T.STK_FEE, house)
            cell[rules] = {**{k: r[k] for k in ("final", "max_dd_pct", "costs", "orders", "halts", "invested_pct")},
                           "placebo_finals": pl,
                           "placebo_median": round(statistics.median(pl), 2),
                           "placebos_beaten": sum(1 for x in pl if r["final"] > x),
                           "period_stats_at_cadence": cadence_period_stats(r["equity_curve"], cad),
                           "equity_curve": r["equity_curve"]}
        cells[cad] = cell
        print(cad, "native", cell["native"]["final"], "beaten", cell["native"]["placebos_beaten"],
              "| v9", cell["v9"]["final"], "beaten", cell["v9"]["placebos_beaten"], flush=True)
    # integrity gate: daily cell must reproduce the primary record to the cent
    prim = json.load(open(os.path.join(FAM, "results.json")))["stocks"]["SPY"]["roads"]["DECADE"]
    gate = {"native_primary": prim["native"]["final"], "native_daily_cell": cells["daily"]["native"]["final"],
            "v9_primary": prim["v9"]["final"], "v9_daily_cell": cells["daily"]["v9"]["final"],
            "native_placebos_primary": prim["native"]["placebos_beaten"], "native_placebos_cell": cells["daily"]["native"]["placebos_beaten"],
            "match": prim["native"]["final"] == cells["daily"]["native"]["final"] and prim["v9"]["final"] == cells["daily"]["v9"]["final"]}
    print("INTEGRITY GATE:", gate)
    out = {"family": "hunt-three-line-break", "slice": "cadence grid, DECADE road only (Second-Chance Protocol)",
           "instrument": "SPY (the primary record of the frozen form; pond/coin records are per-name daily-form runs, not re-swept here)",
           "window": [START, END], "start_pot": 100.0,
           "costs": "0.10%/side + $0.01 sell fee (program standard, as frozen)",
           "convention": "cadence = signal-evaluation frequency (v10 timer convention); frozen daily TLB engine unchanged; state acted on only at evaluation dates, executed at the evaluation day's close (the frozen form's execution point)",
           "champion_vm_decade": 667.35, "spy_buyhold_decade_program_ref": 367.80,
           "spy_buyhold_decade_own_plumbing": prim["buyhold_own_plumbing"],
           "integrity_gate": gate, "cells": cells}
    with open(os.path.join(HERE, "cadence_results.json"), "w") as f:
        json.dump(out, f)
    print("written cadence_results.json")


if __name__ == "__main__":
    main()
