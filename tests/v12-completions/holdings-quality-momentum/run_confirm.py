#!/usr/bin/env python3
"""
CONFIRMATION (Terry's rule) for the holdings-count sweep, quality-momentum.

Non-native counts beat the native count (5) across roads:
  - weekly  n=1   (DECADE $2,870.72 / CONT $1,429.95 / VAL $424.55)
  - quarterly n=ALL (DECADE $1,268.96 / CONT $789.21 / VAL $315.36)
Both are re-run here on DIFFERENT YEARS: fresh-$100 calendar-year folds
2017-2026 (2026 partial to 2026-11-20, labelled), v9 protections per
fold, 20-seed placebos per fold, SPY per fold — the v10 confirmation's
own fold form. Candidate vs native count head-to-head in every fold.
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_sweep as rs

HERE = os.path.dirname(os.path.abspath(__file__))
YEARS = [(str(y), f"{y}-01-01", f"{y}-12-31") for y in range(2017, 2026)]
YEARS.append(("2026-partial", "2026-01-01", "2026-11-20"))

CASES = [("weekly", 1), ("weekly", 5), ("quarterly", "ALL"),
         ("quarterly", 5)]

def main():
    quality = rs.load_quality()
    bars = {t: rs.load_bars_full(t) for t in rs.UNIVERSE + ["SPY"]}
    pb = rs.PriceBook(bars)
    scorer = rs.Scorer(pb, quality)
    out = {"note": "Fresh $100 each fold; v9 protections; placebos are "
                   "20 random-rank twins at the same count/cadence.",
           "folds": {}}
    for label, ws, we in YEARS:
        spy, _ = rs.spy_net(pb, ws, we)
        fold = {"window": [ws, we], "spy_final": round(spy, 2), "runs": {}}
        for cadence, count in CASES:
            run = rs.run_v9(pb, scorer, ws, we, cadence, count,
                            want_curve=True)
            cagr, mdd = rs.stats(run["curve"], ws, we, run["final"])
            twins, beaten = [], 0
            for seed in rs.PLACEBO_SEEDS:
                tw = rs.run_v9(pb, scorer, ws, we, cadence, count,
                               placebo_seed=seed)
                twins.append(round(tw["final"], 2))
                if run["final"] > tw["final"]:
                    beaten += 1
            key = f"{cadence}-n{count}"
            fold["runs"][key] = {
                "final": round(run["final"], 2), "cagr_pct": cagr,
                "max_dd_pct": mdd, "costs": round(run["costs"], 2),
                "orders": run["orders"], "halts": run["halts"],
                "restart": run["restart"],
                "placebo_beaten": f"{beaten}/20",
                "placebo_twin_finals": twins}
            print(f"{label} {key}: ${run['final']:.2f} SPY ${spy:.2f} "
                  f"placebo {beaten}/20 halts={len(run['halts'])}",
                  flush=True)
        out["folds"][label] = fold
        with open(os.path.join(HERE, "confirmation.json"), "w") as f:
            json.dump(out, f, indent=1)
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
