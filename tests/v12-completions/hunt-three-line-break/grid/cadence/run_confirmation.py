#!/usr/bin/env python3
"""Confirmation for the TLB cadence owner cell (quarterly) — Terry's rule:
a non-native cell that beats the native cell is re-run on DIFFERENT YEARS
before any ALIVE ONLY AS VARIANT language counts. Windows: LONG
2010-01-04->2026-11-20 and VAL 2023-01-03->2026-11-20, quarterly vs the
native daily cell, both rulebooks, 20-seed placebos per cell (same
machinery as run_cadence.py). The primary record already prints daily
LONG $217.20 / VAL $118.44 (native) — the daily cells here must match."""
import json, os, sys, statistics
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import run_tlb as T
from run_cadence import sampled_desired

dates, opens, closes = T.load_stock("SPY")
desired, *_ = T.tlb_desired(closes)
out = {}
for road in ("LONG", "VAL"):
    s, e = T.ROADS[road]
    i0, i1 = T.idx_range(dates, s, e)
    out[road] = {}
    for cad in ("daily", "quarterly"):
        des = sampled_desired(dates, desired, cad)
        cell = {}
        for rules, house in (("native", False), ("v9", True)):
            r = T.simulate(dates, opens, closes, des, i0, i1, T.STK_COST, T.STK_FEE, house)
            pl = T.placebo_finals(dates, opens, closes, des, i0, i1, T.STK_COST, T.STK_FEE, house)
            cell[rules] = {"final": r["final"], "max_dd_pct": r["max_dd_pct"], "orders": r["orders"],
                           "placebo_median": round(statistics.median(pl), 2),
                           "placebos_beaten": sum(1 for x in pl if r["final"] > x),
                           "placebo_finals": pl, "equity_curve": r["equity_curve"]}
        out[road][cad] = cell
        print(road, cad, "native", cell["native"]["final"], "beaten", cell["native"]["placebos_beaten"],
              "| v9", cell["v9"]["final"], "beaten", cell["v9"]["placebos_beaten"], flush=True)
with open(os.path.join(HERE, "confirmation_results.json"), "w") as f:
    json.dump({"family": "hunt-three-line-break", "purpose": "second-road confirmation of the quarterly cadence cell",
               "windows": {r: T.ROADS[r] for r in ("LONG", "VAL")}, "cells": out}, f)
print("written confirmation_results.json")
