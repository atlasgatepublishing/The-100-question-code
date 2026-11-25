#!/usr/bin/env python3
"""
HOLDINGS-COUNT SWEEP — Lazy Prices. Simulation only.

Grid (pre-registered, PROGRAM.md): counts 1,2,3,5,8,10,15,20,30,ALL
on roads LONG / DECADE / CONT / VAL, under HOUSE (v9 wrapper:
-15% floor, 90-day sit-out, one restart) and NATIVE (the original
A-5 chassis: plain -15% floor, a halt ends the run, no restart).
20-seed placebos per cell (seeds 1..20, random sample of the same
count from the same scored pool, same form). Program costs.

Integrity gate first: N=5 must reproduce the published record to
the cent (CONT $504.34 / VAL $324.12 plain; LONG v9 $559.69;
DECADE v9 $514.77) before any sweep number is taken.

Chunked + resumable: results.json is rewritten after every cell;
cells already present are skipped on re-run. The LONG book is built
directly from the long-run payload cache for the 30 pond tickers
only (lr_engines._book via pool_data() loads the whole 200-name
pool's EDGAR facts — same bars, far more memory).
"""
import gc
import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.expanduser(
    "~/workspace/stock-app/backtests/lazy-quarterly"))
import lq_common as Q  # noqa: E402
import engine_n as EN  # noqa: E402

C = Q.C
END = Q.END
COUNTS = [1, 2, 3, 5, 8, 10, 15, 20, 30, "ALL"]
NATIVE_N = 5
OUT_PATH = os.path.join(HERE, "results.json")


def road_setup(road):
    """(book, signals, universe, start, end) for one road."""
    if road == "LONG":
        pond = Q.pond2010()
        bars = {t: C.bars_adj(C.yahoo_payload(t)) for t in pond}
        bars["SPY"] = C.bars_adj(C.yahoo_payload("SPY"))
        return C.FastPriceBook(bars), Q.era_signals(), pond, \
            "2010-01-04", END
    lazy, _pb, sims = Q.gap_book()
    book = C.FastPriceBook({t: lazy.get_prices(t)
                            for t in lazy.UNIVERSE + ["SPY"]})
    starts = {"DECADE": "2016-11-21", "CONT": "2019-01-02",
              "VAL": "2023-01-03"}
    return book, sims, list(lazy.UNIVERSE), starts[road], END


def run_cell(book, sims, uni, start, end, n, form, rng=None):
    def run_one(s, e, cash, floor):
        return EN.run_pot_n(book, sims, uni, s, e, n, cash, floor,
                            placebo_rng=rng, record_pools=True)
    if form == "house":
        v9 = C.run_v9(run_one, book.dates, start, end)
        return {"final": round(v9["final"], 2),
                "costs": round(v9["costs"], 2), "orders": v9["orders"],
                "halts": len(v9["halts"]), "curve": v9["curve"]}
    r = run_one(start, end, 100.0, 85.0)
    return {"final": round(r["final"], 2), "costs": round(r["costs"], 2),
            "orders": len(r["trades"]), "halts": 1 if r["halted"] else 0,
            "curve": r["curve"]}


def max_dd(curve):
    peak, mdd = -1.0, 0.0
    for _d, v in curve:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak)
    return round(mdd * 100, 2)


def load_out():
    if os.path.exists(OUT_PATH):
        with open(OUT_PATH) as f:
            return json.load(f)
    return {"family": "Lazy Prices (Cohen-Malloy-Nguyen 2020)",
            "native_count": NATIVE_N,
            "counts": [str(c) for c in COUNTS],
            "integrity": [], "cells": {}, "curves": {}}


def save_out(out):
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, indent=1)


def main():
    t0 = time.time()
    out = load_out()
    done = set(out["cells"])

    # ---------- integrity gate (once; recorded in results.json)
    if not out["integrity"]:
        checks = []
        for road, form, expect in (("VAL", "native", 324.12),
                                   ("CONT", "native", 504.34),
                                   ("DECADE", "house", 514.77),
                                   ("LONG", "house", 559.69)):
            book, sims, uni, s, e = road_setup(road)
            r = run_cell(book, sims, uni, s, e, 5, form)
            checks.append({"check": f"{road} {form} N=5 == {expect}",
                           "pass": r["final"] == expect,
                           "value": r["final"]})
            print(f"INTEGRITY {'PASS' if r['final'] == expect else 'FAIL'}"
                  f": {road} {form} N=5 -> {r['final']} "
                  f"({time.time()-t0:.0f}s)", flush=True)
            del book
            gc.collect()
        out["integrity"] = checks
        save_out(out)
        if not all(c["pass"] for c in checks):
            print("INTEGRITY FAILED — no sweep numbers produced",
                  flush=True)
            sys.exit(1)

    for road in ("LONG", "DECADE", "CONT", "VAL"):
        book, sims, uni, s, e = road_setup(road)
        for form in ("house", "native"):
            for n in COUNTS:
                key = f"{road}|{form}|{n}"
                if key in done:
                    continue
                r = run_cell(book, sims, uni, s, e, n, form)
                twins = []
                for seed in range(1, 21):
                    tr = run_cell(book, sims, uni, s, e, n, form,
                                  rng=random.Random(seed))
                    twins.append(round(tr["final"], 2))
                beats = sum(1 for x in twins if r["final"] > x)
                out["cells"][key] = {
                    "final": r["final"], "costs": r["costs"],
                    "orders": r["orders"], "halts": r["halts"],
                    "max_dd_pct": max_dd(r["curve"]),
                    "placebo_beats": beats,
                    "placebo_median": round(
                        EN.lazy._pct(sorted(twins), 0.5), 2),
                    "placebo_best": max(twins),
                    "placebo_worst": min(twins),
                    "placebo_finals": sorted(twins)}
                if form == "house" or n == NATIVE_N:
                    out["curves"][key] = [[d, round(v, 4)]
                                          for d, v in r["curve"]]
                save_out(out)
                print(f"{key}: ${r['final']:,.2f} "
                      f"dd {out['cells'][key]['max_dd_pct']}% "
                      f"halts {r['halts']} placebo {beats}/20 "
                      f"({time.time()-t0:.0f}s)", flush=True)
        del book
        gc.collect()
    print(f"DONE in {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
