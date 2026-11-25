#!/usr/bin/env python3
"""
V12 HOLDINGS-COUNT SWEEP — N-F3 analysis pass. Simulation only.
Writes ONLY inside this folder.

1) CONFIRMATION (Terry's rule, applied to the nearest challenger):
   count 3 is the only non-native count that beat native 5 on more
   than one road (DECADE + LONG) and its house-form 4-road total is
   within ~1% of native's, so it gets the cross-year check anyway:
   fresh-$100 yearly folds, house form, counts 3 vs 5 — calendar years
   2017-2026 on the Nov-2016 pond and 2013-2016 on the 2012 pond.
   (No count beat native across roads, so no VARIANT-CANDIDATE is at
   stake; this is the documented check behind the verdict.)
2) PER-PERIOD DISTRIBUTION (Terry's reporting standard) for the
   winning/native count 5, from the saved equity curves in
   results.json: quarterly periods (the strategy's tempo) — period
   count, % profitable, MEDIAN period, best, worst, longest losing
   run, longest stretch between new highs (daily curve, trading
   days); average shown only as a labeled secondary.
"""
import json
import os
import statistics
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_sweep as R  # noqa: E402


def period_distribution(curve, sel_dates):
    """Quarterly periods: period i runs from selection date i to the
    next selection date (or the curve's last day). Values are curve
    closes on those dates."""
    vals = dict(curve)
    bounds = [d for d in sel_dates if d in vals]
    periods = []
    for i, b in enumerate(bounds):
        e = bounds[i + 1] if i + 1 < len(bounds) else curve[-1][0]
        periods.append((b, e, round(vals[e] - vals[b], 2)))
    profits = [p[2] for p in periods]
    n = len(profits)
    prof = sum(1 for p in profits if p > 0)
    longest_loss = 0
    run = 0
    for p in profits:
        run = run + 1 if p <= 0 else 0
        longest_loss = max(longest_loss, run)
    # longest stretch between new highs on the daily curve (trading days)
    peak = -1.0
    peak_i = 0
    longest_gap = 0
    gap_dates = (None, None)
    for i, (d, v) in enumerate(curve):
        if v > peak:
            if i - peak_i > longest_gap:
                longest_gap = i - peak_i
                gap_dates = (curve[peak_i][0], d)
            peak, peak_i = v, i
    tail = len(curve) - 1 - peak_i
    if tail > longest_gap:
        longest_gap = tail
        gap_dates = (curve[peak_i][0], curve[-1][0] + " (still open)")
    return {
        "periods": periods,
        "n_periods": n,
        "pct_profitable": round(100.0 * prof / n, 1) if n else None,
        "median_period_usd": round(statistics.median(profits), 2) if n else None,
        "best_period_usd": max(profits) if n else None,
        "worst_period_usd": min(profits) if n else None,
        "longest_losing_run_periods": longest_loss,
        "longest_stretch_between_new_highs_trading_days": longest_gap,
        "new_high_gap": gap_dates,
        "average_period_usd_secondary": round(sum(profits) / n, 2) if n else None,
    }


def folds_for(pond, years, label):
    caches = R.load_caches(pond)
    pb = R.build_book(pond)
    folds = []
    for y in years:
        s = f"{y}-01-01"
        e = "2026-11-20" if y == 2026 else f"{y}-12-31"
        days = [d for d in pb.dates if s <= d <= e]
        sel = R.cadence_dates(days, "quarterly")
        sel_set = set(sel)
        scores = {}
        for d in sel:
            sc = {}
            for t in pond:
                v, _st = caches[t].get(d)
                if v is not None:
                    sc[t] = v
            scores[d] = sc
        win = R.Window(pb, pond, s, e)
        rec = {"pond": label, "year": y, "window": [s, e], "counts": {}}
        for n_req in (3, 5):
            def run_one(s2, e2, cash, floor, _rng, n_req=n_req):
                idx = [i for i, d in enumerate(win.days) if s2 <= d <= e2]
                return R.run_pot_slice(win, idx, sel_set, scores, n_req,
                                       cash, floor, None)
            r = R.run_v9(run_one, pb.dates, s, e)
            spy, _ = R.C.champ.spy_net(pb, s, e, R.START_CASH)
            rec["counts"][str(n_req)] = {
                "final": round(r["final"], 2),
                "costs": round(r["costs"], 2), "orders": r["orders"],
                "halts": r["halts"], "spy_final": round(spy, 2),
                "equity_curve": [[d, round(v, 4)] for d, v in r["curve"]]}
            print(f"[FOLD {label} {y} n={n_req}] final="
                  f"${r['final']:,.2f} SPY=${spy:,.2f} "
                  f"halts={len(r['halts'])}", flush=True)
        folds.append(rec)
    return folds


def main():
    out = json.load(open(os.path.join(HERE, "results.json")))

    # ---- per-period distributions, count 5 (winner == native)
    dists = {}
    sel_cache = {}
    for form in ("house", "native"):
        for road in ("DECADE", "CONT", "VAL", "LONG"):
            cell = out["cells"][f"{road}-{form}-5"]
            s, e = cell["start"], cell["end"]
            if road not in sel_cache:
                # quarterly selection dates are a property of the road
                # window; recompute from the curve's calendar: first
                # trading day of each Jan/Apr/Jul/Oct in the window.
                days = [d for d, _v in cell["equity_curve"]]
                sel_cache[road] = R.cadence_dates(days, "quarterly")
            dists[f"{road}-{form}-5"] = period_distribution(
                cell["equity_curve"], sel_cache[road])
            d = dists[f"{road}-{form}-5"]
            print(f"[DIST {road}-{form}-5] periods={d['n_periods']} "
                  f"prof={d['pct_profitable']}% median="
                  f"${d['median_period_usd']} best=${d['best_period_usd']} "
                  f"worst=${d['worst_period_usd']} lossrun="
                  f"{d['longest_losing_run_periods']} gap="
                  f"{d['longest_stretch_between_new_highs_trading_days']}d",
                  flush=True)
    out["period_distributions_count5"] = dists

    # ---- confirmation folds: count 3 vs count 5, house form
    folds = []
    folds += folds_for(R.UNIVERSE, list(range(2017, 2027)), "pond2016")
    folds += folds_for(R.LONG_POND, list(range(2013, 2017)), "pond2012")
    with open(os.path.join(HERE, "confirmation_folds.json"), "w") as f:
        json.dump({"counts_compared": [3, 5], "form": "house",
                   "folds": folds}, f, indent=1, default=str)
    w3 = sum(1 for fd in folds
             if fd["counts"]["3"]["final"] > fd["counts"]["5"]["final"])
    tot3 = round(sum(fd["counts"]["3"]["final"] for fd in folds), 2)
    tot5 = round(sum(fd["counts"]["5"]["final"] for fd in folds), 2)
    out["confirmation_count3_vs_5"] = {
        "folds": len(folds), "count3_fold_wins": w3,
        "count5_fold_wins": len(folds) - w3,
        "fold_finals_total_count3": tot3,
        "fold_finals_total_count5": tot5}
    print(f"CONFIRMATION: count3 wins {w3}/{len(folds)} folds; "
          f"totals 3=${tot3} vs 5=${tot5}", flush=True)

    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
