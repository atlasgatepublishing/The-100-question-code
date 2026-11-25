#!/usr/bin/env python3
"""
Supplement to the integrity run: the verbatim-engine integrity process
was killed by a service restart after completing every ranked window and
the LADDER placebo distribution (all matching the published record), but
before the PLAIN-floor placebo distribution. This script runs ONLY that
missing piece, importing the integrity copy of the original v4 engine
unchanged and calling its own data loaders and run_pot.
"""
import importlib.util
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "vmey", os.path.join(HERE, "value-momentum-ey.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def main():
    ciks = m.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}
    value_rows, shares_rows = {}, {}
    for t in m.UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts = m.get_companyfacts(cik)
        value_rows[t] = m.pit_series_income(facts)
        shares_rows[t] = (
            m.pit_series(facts, "dei",
                       "EntityCommonStockSharesOutstanding", prio=3) +
            m.pit_series(facts, "us-gaap",
                         "CommonStockSharesOutstanding", prio=2) +
            m.pit_series(facts, "us-gaap",
                         "WeightedAverageNumberOfSharesOutstandingBasic",
                         prio=1))
    bars = {}
    for t in m.UNIVERSE + ["SPY"]:
        bars[t] = m.get_prices(t)
    pb = m.PriceBook(bars)

    ws, we = "2023-01-03", "2026-11-20"
    finals, rows = [], []
    for seed in m.PLACEBO_SEEDS:
        rng = random.Random(seed)
        rp = m.run_pot(pb, value_rows, shares_rows, ws, we, 100.0, 85.0,
                       [], placebo_rng=rng,
                       label=f"VALIDATION PLAIN PLACEBO s{seed}",
                       quiet=True)
        finals.append(rp["final"])
        rows.append({"seed": seed, "final": round(rp["final"], 2),
                     "ret_pct": round((rp["final"] / 100.0 - 1) * 100, 2),
                     "costs": round(rp["costs"], 2),
                     "orders": len(rp["trades"]),
                     "halted": rp["halted"]})
        print(f"seed {seed}: ${rp['final']:,.2f}", flush=True)
    sfin = sorted(finals)
    rk = 227.25
    n_beat = sum(1 for v in finals if rk > v)
    dist = {
        "n_seeds": len(finals),
        "median_final": round(m._pct(sfin, 0.50), 2),
        "p25_final": round(m._pct(sfin, 0.25), 2),
        "p75_final": round(m._pct(sfin, 0.75), 2),
        "best_final": round(sfin[-1], 2),
        "worst_final": round(sfin[0], 2),
        "n_halted": sum(1 for row in rows if row["halted"]),
        "ranked_final": rk,
        "ranked_minus_median": round(rk - m._pct(sfin, 0.50), 2),
        "ranked_beats_n_of_20": n_beat,
        "ranked_percentile": round(100.0 * n_beat / len(finals), 1),
        "rows": rows,
    }
    with open(os.path.join(HERE, "placebo-plain-dist.json"), "w") as f:
        json.dump(dist, f, indent=1)
    print(f"== VALIDATION PLAIN PLACEBO_DIST median=${dist['median_final']:,.2f} "
          f"p25=${dist['p25_final']:,.2f} p75=${dist['p75_final']:,.2f} "
          f"best=${dist['best_final']:,.2f} worst=${dist['worst_final']:,.2f} "
          f"ranked=${rk:,.2f} beats {n_beat}/20 halted={dist['n_halted']}",
          flush=True)
    print("DONE")


if __name__ == "__main__":
    main()
