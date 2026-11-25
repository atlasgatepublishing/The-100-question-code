#!/usr/bin/env python3
"""Re-run ONLY the quarterly cell. The first sweep's quarterly cell was
contaminated: cadence_dates('quarterly') called E.quarter_selection_dates
AFTER the monthly cell had patched that attribute, so it silently used
monthly dates (identical finals were the tell). cadence_dates is now
fixed (quarterly logic inlined verbatim). This script replicates the
main sweep's quarterly block exactly — same data, same fast paths
(equivalence already proven in the main run), same v9 wrapper, same
20 placebo seeds — and overwrites cells/quarterly.json."""
import importlib.util
import json
import os
import random
import time

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "pv10", os.path.join(HERE, "piotroski_v10.py"))
V = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V)
M, E = V.M, V.E

ciks = E.get_ciks()
equity_rows, shares_rows, concepts = {}, {}, {}
for t in V.UNIVERSE:
    cik = {"XOM": 34088}.get(t, ciks[t][0])
    facts = E.get_companyfacts(cik)
    equity_rows[t] = (E.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
                      E.pit_series(facts, "us-gaap", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", prio=1))
    shares_rows[t] = (E.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
                      E.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
                      E.pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
    concepts[t] = M.build_concept_rows(facts)
    time.sleep(0.05)
data = {"equity": equity_rows, "shares": shares_rows, "concepts": concepts}

bars = json.load(open(os.path.join(HERE, "data", "decade_bars.json")))
pb = V.FastPB(bars)
spy_dec, _ = E.spy_net(pb, V.DEC_START, V.DEC_END, V.START_CASH)

E.pit_value, M._at_end = V.pit_value_fast, V.at_end_fast
dates = V.cadence_dates(pb, V.DEC_START, V.DEC_END, "quarterly")
print("quarterly selection dates:", len(dates), dates[:4], flush=True)
orig_qsd = E.quarter_selection_dates
E.quarter_selection_dates = lambda pb_, s, e: [d for d in dates if s <= d <= e]
try:
    ranked = V.run_cell(pb, data, V.DEC_START, V.DEC_END, dates)
    rst = V.cell_stats(ranked, V.DEC_START, V.DEC_END)
    twins = []
    for seed in range(1, 21):
        tw = V.run_cell(pb, data, V.DEC_START, V.DEC_END, dates,
                        placebo_rng=random.Random(seed))
        tst = V.cell_stats(tw, V.DEC_START, V.DEC_END)
        twins.append({"seed": seed, "final": tst["final"],
                      "cagr_pct": tst["cagr_pct"],
                      "max_dd_pct": tst["max_dd_pct"],
                      "costs": tst["costs"], "orders": tst["orders"],
                      "halts": tst["halts"], "restarts": tst["restarts"],
                      "second_halt": tst["second_halt"]})
        print(f"  [quarterly] twin s{seed}: ${tst['final']:,.2f}", flush=True)
finally:
    E.quarter_selection_dates = orig_qsd

tfin = sorted(tw["final"] for tw in twins)
n_beat = sum(1 for v in tfin if rst["final"] > v)
median = E._pct(tfin, 0.50)
cell = dict(rst)
cell.update({"cadence": "quarterly", "window": [V.DEC_START, V.DEC_END],
             "n_selection_dates": len(dates), "placebo_beaten": n_beat,
             "placebo_median_twin": round(median, 2),
             "placebo_twin_finals": tfin, "placebo_twins": twins,
             "spy_final": round(spy_dec, 2),
             "beats_spy": rst["final"] > spy_dec,
             "rerun_note": "Re-run after fixing cadence_dates patch-"
                           "contamination (first pass duplicated monthly)."})
with open(os.path.join(HERE, "cells", "quarterly.json"), "w") as f:
    json.dump(cell, f, indent=1, default=str)
print(f"== CELL quarterly (fixed): final=${rst['final']:,.2f} "
      f"CAGR={rst['cagr_pct']}% maxDD={rst['max_dd_pct']}% "
      f"costs=${rst['costs']:,.2f} orders={rst['orders']} "
      f"placebo {n_beat}/20 median twin=${median:,.2f}", flush=True)
print("DONE")
