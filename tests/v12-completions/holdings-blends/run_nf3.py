#!/usr/bin/env python3
"""
HOLDINGS-COUNT SWEEP — combo-vm-nf3 (V+M x N-F3 50/50). Simulation only.

Convention (frozen): at grid count N, EACH sleeve holds its own top-N
(VM sleeve top-N by champion rank; NF3 sleeve top-N by SBC-intensity
deceleration rank), sleeve budgets reset 50/50 at every selection
date, equal weight inside each sleeve. Native count = 5 per sleeve
(10 effective). Cadence = quarterly (native) for every cell — the
sweep variable is COUNT, not tempo.

Forms: house = v9 protections at pot level (engine_nf3.run_combo_v9);
native = the original published form (single plain -15% floor, a halt
ends the run; engine_nf3.run_combo). Roads: DECADE 2016-11-21 (spliced
book, as in the v10 record), CONT 2019-01-02, VAL 2023-01-03 (original
cached book), all -> 2026-11-20. Program costs. 20-seed placebos per
cell (each sleeve draws N random names from its own scored pool).

Integrity gate: N=5 native CONT $532.39 / VAL $290.45; N=5 house
DECADE quarterly $715.60 — must reproduce before any sweep number.
"""
import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import engine_nf3 as E  # noqa: E402
import sweep_common as SC  # noqa: E402

def _safe_dump(obj, path):
    """json.dump with retries — writes on this box intermittently
    fail with EPERM under parallel load; retry before giving up."""
    import time as _t
    last = None
    for _i in range(40):
        try:
            with open(path, "w") as _f:
                json.dump(obj, _f, indent=1)
            return
        except PermissionError as _e:
            last = _e
            _t.sleep(10)
    raise last


def _safe_load(path):
    import time as _t
    for _i in range(40):
        try:
            with open(path) as _f:
                return json.load(_f)
        except (PermissionError, ValueError):
            _t.sleep(10)
    return None


COUNTS = [1, 2, 3, 5, 8, 10, 15, 20, 30, "ALL"]
NATIVE_N = 5
END = "2026-11-20"
ROADS = {"DECADE": "2016-11-21", "CONT": "2019-01-02", "VAL": "2023-01-03"}


def main():
    t0 = time.time()
    facts, eq, sh = E.load_facts()
    bars_cached = {t: E.champ.get_prices(t) for t in E.UNIVERSE + ["SPY"]}
    pb_c = E.FastPriceBook(bars_cached)
    sc_c = E.Scorer(pb_c, eq, sh, facts)
    bars_spliced, factors = E.spliced_bars()
    pb_s = E.FastPriceBook(bars_spliced)
    sc_s = E.Scorer(pb_s, eq, sh, facts)
    books = {"DECADE": (pb_s, sc_s), "CONT": (pb_c, sc_c),
             "VAL": (pb_c, sc_c)}

    # ---------------- integrity gate
    checks = []
    for road, want in (("CONT", 532.39), ("VAL", 290.45)):
        pb, sc = books[road]
        q = E.champ.quarter_selection_dates(pb, ROADS[road], END)
        r = E.run_combo(pb, sc, ROADS[road], END, q, 100.0, 85.0, n=5)
        checks.append((f"{road} native N=5 == {want}",
                       round(r["final"], 2) == want, round(r["final"], 2)))
    pb, sc = books["DECADE"]
    q = E.champ.quarter_selection_dates(pb, ROADS["DECADE"], END)
    r = E.run_combo_v9(pb, sc, ROADS["DECADE"], END, q, 100.0, n=5)
    checks.append(("DECADE house N=5 == 715.60",
                   round(r["final"], 2) == 715.60, round(r["final"], 2)))
    for name, ok, val in checks:
        print(f"INTEGRITY {'PASS' if ok else 'FAIL'}: {name} (got {val})",
              flush=True)
    if not all(ok for _, ok, _ in checks):
        print("INTEGRITY FAILED", flush=True)
        sys.exit(1)

    _opath = os.path.join(HERE, "cells_nf3.json")
    out = (_safe_load(_opath) if os.path.exists(_opath) else None) or {"family": "combo-vm-nf3", "native_count_per_sleeve": NATIVE_N,
           "integrity": [{"check": n, "pass": ok, "value": v}
                         for n, ok, v in checks],
           "cells": {}, "curves": {}}
    for road, start in ROADS.items():
        pb, sc = books[road]
        q = E.champ.quarter_selection_dates(pb, start, END)
        for form in ("house", "native"):
            for n in COUNTS:
                key = f"{road}|{form}|{n}"
                if key in out["cells"]:
                    print(f"{key}: SKIP (saved)", flush=True)
                    continue
                if form == "house":
                    r = E.run_combo_v9(pb, sc, start, END, q, 100.0, n=n)
                    halts = (1 if r["halted"] else 0) \
                        + (1 if r["second_halt"] else 0)
                    orders = r["orders"]
                else:
                    r = E.run_combo(pb, sc, start, END, q, 100.0, 85.0,
                                    n=n)
                    halts = 1 if r["halted"] else 0
                    orders = len(r["trades"])
                twins = []
                for seed in range(1, 21):
                    rng = random.Random(seed)
                    if form == "house":
                        tr = E.run_combo_v9(pb, sc, start, END, q, 100.0,
                                            placebo_rng=rng, n=n)
                    else:
                        tr = E.run_combo(pb, sc, start, END, q, 100.0,
                                         85.0, placebo_rng=rng, n=n)
                    twins.append(round(tr["final"], 2))
                beats = sum(1 for x in twins if r["final"] > x)
                out["cells"][key] = {
                    "final": round(r["final"], 2),
                    "costs": round(r["costs"], 2), "orders": orders,
                    "halts": halts, "max_dd_pct": SC.max_dd(r["curve"]),
                    "placebo_beats": beats,
                    "placebo_median": round(
                        (sorted(twins)[9] + sorted(twins)[10]) / 2, 2),
                    "placebo_finals": sorted(twins)}
                if form == "house":
                    out["curves"][key] = [[d, round(v, 4)]
                                          for d, v in r["curve"]]
                print(f"{key}: ${r['final']:,.2f} placebo {beats}/20 "
                      f"({time.time()-t0:.0f}s)", flush=True)
                _safe_dump(out, _opath)
    _safe_dump(out, os.path.join(HERE, "cells_nf3.json"))
    print(f"DONE nf3 in {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
