#!/usr/bin/env python3
"""
HOLDINGS-COUNT SWEEP — winners-blend (champion V+M + momentum
basket, 50/50). Simulation only.

Convention (frozen): at grid count N, EACH sleeve holds its own
top-N (basket sleeve top-N by 12-1 momentum above its 200-day;
VM sleeve top-N by champion rank), equal weight inside each sleeve.
Native count = 5 per sleeve (10 effective).

Forms:
- house = the v10 sweep construction under v9 protections at pot
  level: both sleeves re-pick QUARTERLY (the family's native cadence
  per the v10 CADENCE GRID), split rebalanced quarterly, plain -15%
  floor, 90-day sit-out, restart at next cadence date, second halt
  ends. Plumbing = the v10 sweep's own (basket on the v4 Yahoo
  cache; VM on the full-history pxfull book) for all three roads.
- native = the ORIGINAL published construction: basket sleeve
  monthly, VM sleeve quarterly, 50/50 split rebalanced each January,
  single plain -15% pot floor, finals mark-to-market (no terminal
  liquidation), run with the v10-validated sleeve copies
  (basket_sim / vm_sim) and the original blend_curves_orig; VM leg
  on the original v4 book for CONT/VAL, on the pxfull book for
  DECADE. Native windows keep the original test's starts
  (2019-01-01 / 2023-01-01).

Roads -> 2026-11-20. Program costs. 20-seed placebos per cell
(both sleeves draw N random names from their own eligible pools).

Integrity gates: house DECADE quarterly N=5 == $499.73 (the v10
sweep's published cell); native N=5 CONT == $400.84 / VAL == $245.18
(the original published finals).

Resumable: cells saved to cells_winners.json after every cell;
already-saved cells skipped on re-launch. Saves retry patiently on
the intermittent EPERM write failures seen on this box under load.
"""
import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import engine_winners as W  # noqa: E402
import sweep_common as SC  # noqa: E402


def _safe_dump(obj, path):
    last = None
    for _i in range(40):
        try:
            with open(path, "w") as _f:
                json.dump(obj, _f, indent=1)
            return
        except PermissionError as _e:
            last = _e
            time.sleep(10)
    raise last


def _safe_load(path):
    for _i in range(40):
        try:
            with open(path) as _f:
                return json.load(_f)
        except (PermissionError, ValueError):
            time.sleep(10)
    return None


COUNTS = [1, 2, 3, 5, 8, 10, 15, 20, 30, "ALL"]
END = "2026-11-20"
HOUSE_ROADS = {"DECADE": "2016-11-21", "CONT": "2019-01-02",
               "VAL": "2023-01-03"}
NATIVE_ROADS = {"DECADE": "2016-11-21", "CONT": "2019-01-01",
                "VAL": "2023-01-01"}


def run_native(ctx, fb, sd, ed, n, seed=None):
    W.HOLD_N = n
    mkt = ctx["mkt"]
    mset = set(W.cadence_dates(mkt.cal, "monthly", sd, ed))
    qset = set(W.cadence_dates(fb.dates, "quarterly", sd, ed))
    mode = "ranked" if seed is None else "placebo"
    b = W.basket_sim(mkt, sd, ed, 50.0, mset, mode,
                     seed=seed if seed is not None else 42)
    vrng = random.Random(seed) if seed is not None else None
    v = W.vm_sim(fb, ctx["eq_struct"], ctx["sh_struct"], sd, ed, 50.0,
                 qset, placebo_rng=vrng)
    curve, info = W.blend_curves_orig(b["curve"], v["curve"])
    costs = sum(f for _, f in b["order_log"]) + v["costs"] \
        + info["transfer_costs"]
    orders = len(b["order_log"]) + len(v["trades"])
    return {"final": round(info["final"], 2), "costs": round(costs, 2),
            "orders": orders, "halts": 1 if info["halt"] else 0,
            "curve": curve}


def main():
    t0 = time.time()
    mkt = W.mb.Market(W.mb.UNIVERSE)
    pb, eq_rows, sh_rows = W.build_vm_book_orig()
    eq_struct = {t: W.make_pit_struct(eq_rows[t]) for t in W.UNIVERSE}
    sh_struct = {t: W.make_pit_struct(sh_rows[t]) for t in W.UNIVERSE}
    fb_orig = W.FastBook({t: W.vm.get_prices(t)
                          for t in W.UNIVERSE + ["SPY"]})
    fb_decade = W.build_decade_book()
    ctx = {"mkt": mkt, "fb_decade": fb_decade, "eq_struct": eq_struct,
           "sh_struct": sh_struct}

    checks = []
    W.HOLD_N = 5
    r = W.run_cell_win(ctx, "quarterly", HOUSE_ROADS["DECADE"], END)
    checks.append(("DECADE house quarterly N=5 == 499.73",
                   r["final"] == 499.73, r["final"]))
    for road, want in (("CONT", 400.84), ("VAL", 245.18)):
        rn = run_native(ctx, fb_orig, NATIVE_ROADS[road], END, 5)
        checks.append((f"{road} native N=5 == {want}",
                       rn["final"] == want, rn["final"]))
    for name, ok, val in checks:
        print(f"INTEGRITY {'PASS' if ok else 'FAIL'}: {name} (got {val})",
              flush=True)
    if not all(ok for _, ok, _ in checks):
        print("INTEGRITY FAILED", flush=True)
        sys.exit(1)

    _opath = os.path.join(HERE, "cells_winners.json")
    out = (_safe_load(_opath) if os.path.exists(_opath) else None) or {
        "family": "winners-blend", "native_count_per_sleeve": 5,
        "integrity": [{"check": n, "pass": ok, "value": v}
                      for n, ok, v in checks],
        "cells": {}, "curves": {}}
    for road, start in HOUSE_ROADS.items():
        for n in COUNTS:
            key = f"{road}|house|{n}"
            if key in out["cells"]:
                print(f"{key}: SKIP (saved)", flush=True)
                continue
            W.HOLD_N = n
            r = W.run_cell_win(ctx, "quarterly", start, END)
            twins = []
            for seed in range(1, 21):
                W.HOLD_N = n
                tr = W.run_cell_win(ctx, "quarterly", start, END,
                                    seed=seed)
                twins.append(round(tr["final"], 2))
            beats = sum(1 for x in twins if r["final"] > x)
            out["cells"][key] = {
                "final": r["final"], "costs": r["costs"],
                "orders": r["orders"], "halts": r["halts"],
                "max_dd_pct": r["max_dd_pct"], "placebo_beats": beats,
                "placebo_median": round(
                    (sorted(twins)[9] + sorted(twins)[10]) / 2, 2),
                "placebo_finals": sorted(twins)}
            out["curves"][key] = r["equity_curve"]
            print(f"{key}: ${r['final']:,.2f} placebo {beats}/20 "
                  f"({time.time()-t0:.0f}s)", flush=True)
            _safe_dump(out, _opath)
    for road, start in NATIVE_ROADS.items():
        fb = fb_decade if road == "DECADE" else fb_orig
        for n in COUNTS:
            key = f"{road}|native|{n}"
            if key in out["cells"]:
                print(f"{key}: SKIP (saved)", flush=True)
                continue
            r = run_native(ctx, fb, start, END, n)
            twins = []
            for seed in range(1, 21):
                tr = run_native(ctx, fb, start, END, n, seed=seed)
                twins.append(round(tr["final"], 2))
            beats = sum(1 for x in twins if r["final"] > x)
            out["cells"][key] = {
                "final": r["final"], "costs": r["costs"],
                "orders": r["orders"], "halts": r["halts"],
                "max_dd_pct": SC.max_dd(r["curve"]),
                "placebo_beats": beats,
                "placebo_median": round(
                    (sorted(twins)[9] + sorted(twins)[10]) / 2, 2),
                "placebo_finals": sorted(twins)}
            print(f"{key}: ${r['final']:,.2f} placebo {beats}/20 "
                  f"({time.time()-t0:.0f}s)", flush=True)
            _safe_dump(out, _opath)
    _safe_dump(out, _opath)
    print(f"DONE winners in {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
