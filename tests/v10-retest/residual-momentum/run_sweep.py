#!/usr/bin/env python3
"""V10 RETEST — residual-momentum CADENCE SWEEP (SPEC: THE CADENCE SWEEP).
DECADE road 2016-11-21 -> 2026-11-20, $100/cell, program costs, v9
protections, at 7 cadences under the SPEC's uniform cadence definition
(first trading day of each period; cadence_dates copied verbatim from the
stood-down batch worker's w4lib.py, which implements the SPEC text).

Engine: engine_v9.py (verbatim copy of the v9 residual-momentum engine).
The ONLY change per cell is the selection calendar: the engine calls
E.quarter_selection_dates(pb, start, end); we patch that one function to
the cadence's date generator. Signal (12-1 residual return vs SPY-beta,
top-5 equal weight), pool gate, costs and v9 protection are untouched.

Data (read-only shared caches, per SPEC):
  - Prices: long-run-2010 lr_common.yahoo_payload (v7 long-hold pxfull
    cache, read-only; GOOGL from long-run-2010/data cache) -> bars_adj
    (champion bar construction: open scaled by adjclose/close, close =
    adjclose), assembled into the v9 engine's own FastBook class.
  - EDGAR chains: lr_common.load_facts(cik_for(t)) -> equity_chain /
    shares_chain (the champion's pit_series rows), same gate inputs the
    long-run construction uses.
  - Universe: the engine's UNIVERSE (honest PIT top-30 as of Nov 2016).
Placebos: 20 seeds per cell via the engine's own placebo_block machinery
(random 5-name twins from the identical scored pool, same mechanics).
Writes cells/<cadence>.json per cell (full equity curve, halts/restarts
with dates, all 20 placebo twin finals) and sweep_summary.json.
"""
import importlib.util
import json
import os
import sys
from datetime import date as _d

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
sys.path.insert(0, os.path.join(BT, "long-run-2010"))
import lr_common as C  # noqa: E402


def load_mod(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


M = load_mod("engine_v10", os.path.join(HERE, "engine_v10.py"))
# engine_v10 = engine_v9 + date-keyed score memoization ONLY (scores are a
# pure function of book/chains/date; equivalence to the uncached engine
# proven in validate_cache.py / cache_validation.json). One cache for the
# whole sweep: coarser cadences' selection dates are subsets of the daily
# set, so each date's scores are computed exactly once.
M.SCORES_CACHE = {}

# Speed-only substitution: fastpit.fast_pit_value replaces E.pit_value
# (identical semantics; proven on 49,560 chain/date comparisons against
# the original on these exact sweep chains — validate_fastpit.py).
from fastpit import fast_pit_value  # noqa: E402
M.E.pit_value = fast_pit_value
E = M.E
ORIG_QSD = E.quarter_selection_dates

START, END = "2016-11-21", "2026-11-20"
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]


def cadence_dates(pb, start, end, cad):
    """Uniform operational cadence (SPEC: THE CADENCE SWEEP) — verbatim
    from w4lib.py (stood-down batch worker's harness, adopted)."""
    days = [d for d in pb.dates if start <= d <= end]
    if cad == "daily":
        return days
    out, seen = [], set()
    for d in days:
        dt = _d.fromisoformat(d)
        if cad == "weekly":
            key = ("W", dt.isocalendar()[0], dt.isocalendar()[1])
        elif cad == "biweekly":
            monday = dt.toordinal() - dt.weekday()
            if (monday // 7) % 2 != 0:
                continue
            key = ("B", monday)
        elif cad == "monthly":
            key = ("M", d[:4], d[5:7])
        elif cad == "quarterly":
            if d[5:7] not in ("01", "04", "07", "10"):
                continue
            key = ("Q", d[:4], d[5:7])
        elif cad == "semiannual":
            if d[5:7] not in ("01", "07"):
                continue
            key = ("S", d[:4], d[5:7])
        elif cad == "annual":
            key = ("A", d[:4])
        else:
            raise ValueError(cad)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def build_book():
    bars = {}
    for t in M.UNIVERSE + ["SPY"]:
        bars[t] = C.bars_adj(C.yahoo_payload(t))
    pb = M.FastBook(bars)
    eq, so = {}, {}
    for t in M.UNIVERSE:
        facts = C.load_facts(C.cik_for(t))
        eq[t] = C.equity_chain(facts)
        so[t] = C.shares_chain(facts)
    return pb, eq, so


def curve_diag(curve):
    peak, maxdd = -1.0, 0.0
    worst, worst_d = None, None
    for d, v in curve:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak * 100.0
            if dd > maxdd:
                maxdd = dd
        if worst is None or v < worst:
            worst, worst_d = v, d
    return round(maxdd, 2), (round(worst, 2) if worst is not None else None), worst_d


def run_cell(pb, eq, so, cad):
    E.quarter_selection_dates = lambda b, s, e: cadence_dates(b, s, e, cad)
    try:
        r = M.run_pot_resmom(pb, eq, so, START, END, 100.0, 85.0, M.LADDER,
                             label=f"SWEEP {cad}", quiet=True)
        pl = M.placebo_block(pb, eq, so, START, END, r["final"],
                             f"SWEEP {cad}")
    finally:
        E.quarter_selection_dates = ORIG_QSD
    maxdd, worst, worst_d = curve_diag(r["curve"])
    cg, _ = C.cagr(r["final"], 100.0, START, END)
    halts = len(r.get("restarts") or []) + (1 if r.get("second_halt") else 0)
    cell = {"cadence": cad, "start": START, "end": END,
            "final": round(r["final"], 2), "cagr_pct": cg,
            "max_dd_pct": maxdd, "worst_close": worst,
            "worst_close_date": worst_d,
            "costs": round(r["costs"], 2), "orders": len(r["trades"]),
            "halts": halts, "restarts": r.get("restarts") or [],
            "restart": bool(r.get("restarts")),
            "second_halt": r.get("second_halt"),
            "placebo_beaten": pl["seeds_beaten"],
            "placebo_median": pl["median"], "placebo_best": pl["best"],
            "placebo_worst": pl["worst"],
            "placebo_twins": [{"seed": row["seed"], "final": row["final"],
                               "costs": row["costs"],
                               "orders": row["orders"],
                               "restarts": row["restarts"],
                               "second_halt": row["second_halt"]}
                              for row in pl["rows"]],
            "curve": [[d, round(v, 4)] for d, v in r["curve"]]}
    with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
        json.dump(cell, f, indent=1, default=str)
    print("CELL", cad, cell["final"], "beats", cell["placebo_beaten"],
          "costs", cell["costs"], "orders", cell["orders"],
          "halts", halts, flush=True)
    return cell


def main():
    pb, eq, so = build_book()
    M.SPY_RET = M.spy_daily_returns(pb)
    spy, _ = E.spy_net(pb, START, END, 100.0)
    print("SPY DECADE (this plumbing):", round(spy, 2), flush=True)
    cells = {}
    for cad in CADENCES:
        cells[cad] = run_cell(pb, eq, so, cad)
    summary = {"slug": "residual-momentum", "road": [START, END],
               "decade_spy_final": round(spy, 2),
               "cells": {c: {k: v for k, v in cell.items()
                             if k not in ("curve", "placebo_twins")}
                         for c, cell in cells.items()}}
    with open(os.path.join(HERE, "sweep_summary.json"), "w") as f:
        json.dump(summary, f, indent=1, default=str)
    print("SWEEP DONE", flush=True)


if __name__ == "__main__":
    main()
