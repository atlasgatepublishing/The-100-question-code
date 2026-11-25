#!/usr/bin/env python3
"""
HOLDINGS-COUNT SWEEP — combo-three-way (V+M + Lazy Prices + N-F3,
equal thirds). Simulation only.

Convention (frozen): at grid count N, EACH of the three sleeves holds
its own top-N; sleeve budgets reset to equal thirds at every
selection date; equal weight inside each sleeve. Native count = 5
per sleeve (15 effective). Cadence = quarterly (native) throughout —
the sweep variable is COUNT.

Forms: house = v9 protections at pot level (engine_3way.run_combo_v9);
native = the same engine under a single plain -15% floor, no restart
(run_combo) — the v9 engine's own plain-floor form; on CONT/VAL the
published record shows the floor never fired, so house and native
coincide there at N=5. Roads: DECADE 2016-11-21, CONT 2019-01-02,
VAL 2023-01-03 -> 2026-11-20, on the family's own book (v4 cached
bars, first bar 2017-06-01 — the documented effective-road artifact
of this plumbing, shared by every cell). Program costs. 20-seed
placebos per cell (each sleeve draws N random names from its own
pool, draw order VM, LZ, NF3, one Random(seed) per run).

Integrity gate: N=5 house CONT $536.53 / VAL $308.16 / DECADE $567.14.
"""
import bisect
import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import engine_3way as E  # noqa: E402
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
champ = E.champ
UNIVERSE = E.UNIVERSE


class FastBook:
    def __init__(self, bars):
        self.bars = bars
        self.dates = sorted({b["d"] for bl in bars.values() for b in bl})
        self._idx = {t: {b["d"]: b for b in bl} for t, bl in bars.items()}
        self._ds = {t: [b["d"] for b in bl] for t, bl in bars.items()}

    def bar(self, t, d):
        return self._idx.get(t, {}).get(d)

    def close_on_or_before(self, t, d):
        ds = self._ds.get(t, [])
        i = bisect.bisect_right(ds, d) - 1
        return self.bars[t][i]["c"] if i >= 0 else None


def main():
    t0 = time.time()
    ciks = champ.get_ciks()
    facts_by_ticker, equity_rows, shares_rows = {}, {}, {}
    for t in UNIVERSE:
        cik = {"XOM": 34088}.get(t, ciks[t][0])
        facts = champ.get_companyfacts(cik)
        facts_by_ticker[t] = facts
        equity_rows[t] = (
            champ.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2)
            + champ.pit_series(
                facts, "us-gaap",
                "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                prio=1))
        shares_rows[t] = (
            champ.pit_series(facts, "dei",
                             "EntityCommonStockSharesOutstanding", prio=3)
            + champ.pit_series(facts, "us-gaap",
                               "CommonStockSharesOutstanding", prio=2)
            + champ.pit_series(
                facts, "us-gaap",
                "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
    bars = {t: champ.get_prices(t) for t in UNIVERSE + ["SPY"]}
    pb = FastBook(bars)
    with open(os.path.expanduser(
            "~/workspace/stock-app/backtests/v7/gap-a5-lazy-prices/"
            "data/similarities.json")) as f:
        signals = json.load(f)["signals"]
    scorer = E.Scorer(pb, equity_rows, shares_rows, facts_by_ticker,
                      signals)

    checks = []
    for road, want in (("CONT", 536.53), ("VAL", 308.16),
                       ("DECADE", 567.14)):
        r = E.run_combo_v9(pb, scorer, ROADS[road], END, 100.0, hold_n=5)
        checks.append((f"{road} house N=5 == {want}",
                       round(r["final"], 2) == want,
                       round(r["final"], 2)))
    for name, ok, val in checks:
        print(f"INTEGRITY {'PASS' if ok else 'FAIL'}: {name} (got {val})",
              flush=True)
    if not all(ok for _, ok, _ in checks):
        print("INTEGRITY FAILED", flush=True)
        sys.exit(1)

    _opath = os.path.join(HERE, "cells_3way.json")
    out = (_safe_load(_opath) if os.path.exists(_opath) else None) or {"family": "combo-three-way", "native_count_per_sleeve": 5,
           "integrity": [{"check": n, "pass": ok, "value": v}
                         for n, ok, v in checks],
           "cells": {}, "curves": {}}
    for road, start in ROADS.items():
        for form in ("house", "native"):
            for n in COUNTS:
                key = f"{road}|{form}|{n}"
                if key in out["cells"]:
                    print(f"{key}: SKIP (saved)", flush=True)
                    continue
                if form == "house":
                    r = E.run_combo_v9(pb, scorer, start, END, 100.0, hold_n=n)
                    halts = (1 if r["halted"] else 0) \
                        + (1 if r["second_halt"] else 0)
                else:
                    r = E.run_combo(pb, scorer, start, END, 100.0, 85.0,
                                    hold_n=n)
                    halts = 1 if r["halted"] else 0
                twins = []
                for seed in range(1, 21):
                    rng = random.Random(seed)
                    if form == "house":
                        tr = E.run_combo_v9(pb, scorer, start, END, 100.0,
                                            placebo_rng=rng, hold_n=n)
                    else:
                        tr = E.run_combo(pb, scorer, start, END, 100.0,
                                         85.0, placebo_rng=rng, hold_n=n)
                    twins.append(round(tr["final"], 2))
                beats = sum(1 for x in twins if r["final"] > x)
                out["cells"][key] = {
                    "final": round(r["final"], 2),
                    "costs": round(r["costs"], 2),
                    "orders": len(r["trades"]), "halts": halts,
                    "max_dd_pct": SC.max_dd(r["curve"]),
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
    _safe_dump(out, os.path.join(HERE, "cells_3way.json"))
    print(f"DONE 3way in {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
