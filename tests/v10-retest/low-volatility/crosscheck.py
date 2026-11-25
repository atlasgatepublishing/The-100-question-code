#!/usr/bin/env python3
"""
CROSSCHECK — the sweep's fast engine vs the original v6/v9 engine.

Runs the sweep engine (sweep.py: FastBook + precomputed scores +
cadence-parameterized selection) on the ORIGINAL windows at the
ORIGINAL quarterly cadence with the ORIGINAL cached prices
(E.get_prices, 2017-06-01 start) and the plain floor (his rules,
single episode), and compares finals to the published originals:
CONT $235.34, VAL $148.85. Also compares one placebo twin (seed 1)
per window against the published placebo rows ($409.76 / $250.97).
A match to the cent proves the sweep engine's mechanics are the
original engine's mechanics; only its speed differs.
"""
import importlib.util
import json
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "sweep", os.path.join(HERE, "sweep.py"))
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)
E = S.E

CONT = ("2019-01-02", "2026-11-20")
VAL = ("2023-01-03", "2026-11-20")
EXPECT = {"CONT": (235.34, 409.76), "VAL": (148.85, 250.97)}


def build_inputs_cached():
    ciks = E.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}
    equity_rows, shares_rows = {}, {}
    for t in S.UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts = E.get_companyfacts(cik)
        equity_rows[t] = (
            E.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
            E.pit_series(facts, "us-gaap",
                         "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                         prio=1))
        shares_rows[t] = (
            E.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
            E.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
            E.pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
        del facts
    bars = {}
    for t in S.UNIVERSE + ["SPY"]:
        bars[t] = E.get_prices(t)
    return S.FastBook(bars), equity_rows, shares_rows


def main():
    pb, equity_rows, shares_rows = build_inputs_cached()
    out = {}
    ok_all = True
    for tag, (ws, we) in (("CONT", CONT), ("VAL", VAL)):
        days = [d for d in pb.dates if ws <= d <= we]
        scores = {d: S.compute_scores(pb, equity_rows, shares_rows, d)
                  for d in days}
        sel = S.cadence_dates(pb, "quarterly", ws, we)
        r = S.run_episode(pb, scores, sel, ws, we, 100.0, 85.0)
        rng = random.Random(1)
        pr = S.run_episode(pb, scores, sel, ws, we, 100.0, 85.0,
                           placebo_rng=rng)
        exp_f, exp_p = EXPECT[tag]
        ok = abs(r["final"] - exp_f) < 0.005
        okp = abs(pr["final"] - exp_p) < 0.005
        ok_all = ok_all and ok and okp
        out[tag] = {"ranked_final": round(r["final"], 2),
                    "expected": exp_f, "match": ok,
                    "placebo_seed1_final": round(pr["final"], 2),
                    "placebo_seed1_expected": exp_p,
                    "placebo_match": okp}
        print(f"CROSSCHECK {tag}: ranked=${r['final']:,.2f} vs ${exp_f} "
              f"match={ok} | placebo seed1=${pr['final']:,.2f} vs "
              f"${exp_p} match={okp}", flush=True)
    out["all_match"] = ok_all
    with open(os.path.join(HERE, "crosscheck.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("CROSSCHECK", "PASSED" if ok_all else "FAILED", flush=True)


if __name__ == "__main__":
    main()
