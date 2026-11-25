#!/usr/bin/env python3
"""
WALK-FORWARD of the HONEST MOMENTUM BASKET — Terry's AI stock app,
simulation only.

The basket (momentum-basket-honest.py) was promoted on a single
design/validation split. This test walks the SAME frozen engine across
the decade fold by fold, copying the chassis walk-forward's methodology
(~/workspace/stock-app/backtests/v4/chassis-walkforward.md):

  - Engine imported VERBATIM from momentum-basket-honest.py: honest
    30-name Nov-2016 universe, monthly selection, 200-day eligibility,
    12-1 momentum rank, top 5 at 20% each, costs 0.10%/side + $0.01/sell.
  - Rules are FROZEN — nothing is re-tuned per fold. So unlike a classic
    walk-forward this does NOT test parameter stability; it tests
    year-by-year consistency of one fixed rule set.
  - Folds: test years 2018..2026. One continuous run 2016-11-21 ->
    2026-11-20 (2016-11-21 -> 2017-12-31 is the warm-up segment); each
    fold is that calendar year's slice of the run, with positions, cash
    AND floor state carried across year boundaries — the folds are
    segments of a single pot, not fresh pots.
  - Pot: $100 only.
  - TWO protection variants:
      (a) LADDER — Terry's floor as published ($85; -> $100 at a $125
          close; -> $125 at a $150 close). This is the engine default and
          must reproduce the published full-window final of $439.45.
      (b) PLAIN FLOOR — floor fixed at $85, no ladder (implemented by
          patching the module's FLOORS entry for the run; the engine
          code itself is untouched).
  - Per fold: basket return vs SPY's same-calendar-year close-to-close
    return, win/loss, year-end equity, in-year max drawdown.
  - Stitched totals vs SPY buy-and-hold net ($314.10 published) and vs
    the single-split published numbers ($439.45 full / $208.27
    validation — the validation figure was a FRESH pot from 2023-01-01;
    the stitched curve's 2023->2026 segment is reported alongside for
    comparison, labelled as carried-state, not fresh-pot).
  - PLACEBO: 20 seeds (1..20), random 5 eligible monthly, stitched full
    window, under EACH protection variant — distribution + the ranked
    run's percentile within its own variant's distribution.

Data: the honest study's cached Yahoo Finance daily bars
(split-adjusted closes) under ./momentum-basket-honest-data/.
"""

import importlib.util
import json
import math
import os
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))

spec = importlib.util.spec_from_file_location(
    "mbh", os.path.join(HERE, "momentum-basket-honest.py"))
eng = importlib.util.module_from_spec(spec)
spec.loader.exec_module(eng)

START_D, END_D = eng.WINDOWS["full"]          # 2016-11-21 -> 2026-11-20
POT = 100
TEST_YEARS = [str(y) for y in range(2018, 2027)]
PLACEBO_SEEDS = list(range(1, 21))


def year_slices(res, pot0):
    """Calendar-year returns from an equity curve. Returns
    {year: {ret, end_eq, max_dd, halted}} where 'halted' marks years the
    pot sat in cash after a floor liquidation."""
    pts = res.equity_curve
    out = {}
    years = sorted({d[:4] for d, _ in pts})
    prev_eq = float(pot0)
    last_year = years[-1] if years else None
    for y in years:
        ys = [e for d, e in pts if d[:4] == y]
        end_eq = ys[-1]
        # in-year max drawdown, peak seeded with the start-of-year equity
        peak, dd = prev_eq, 0.0
        for e in [prev_eq] + ys:
            peak = max(peak, e)
            if peak > 0:
                dd = min(dd, e / peak - 1.0)
        out[y] = {
            "ret_pct": round((end_eq / prev_eq - 1.0) * 100, 2),
            "end_eq": round(end_eq, 2),
            "max_dd_pct": round(dd * 100, 2),
            "halted": bool(res.halt_date and y == last_year
                           and res.halt_date[:4] == y),
        }
        prev_eq = end_eq
    if res.halt_date:
        hy = res.halt_date[:4]
        for y in TEST_YEARS:
            if y > hy and y not in out:
                out[y] = {"ret_pct": 0.0, "end_eq": round(res.final, 2),
                          "max_dd_pct": 0.0, "halted": True}
    return out


def segment_return(res, from_d, to_d):
    """Return of the stitched curve between two dates (last close <= each)."""
    pts = res.equity_curve
    a = [e for d, e in pts if d <= from_d]
    b = [e for d, e in pts if d <= to_d]
    if not a or not b:
        return None
    return round((b[-1] / a[-1] - 1.0) * 100, 2)


def pct(sorted_vals, q):
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] * (1 - (pos - lo)) + sorted_vals[hi] * (pos - lo)


def run_variant(mkt, ladder_on):
    """Ranked stitched run under one protection variant."""
    saved = eng.FLOORS[POT]
    if not ladder_on:
        eng.FLOORS[POT] = (85.0, [])          # plain floor: $85, no rungs
    try:
        return eng.simulate(mkt, START_D, END_D, POT, "ranked")
    finally:
        eng.FLOORS[POT] = saved


def placebo_dist(mkt, ladder_on, ranked_final):
    saved = eng.FLOORS[POT]
    if not ladder_on:
        eng.FLOORS[POT] = (85.0, [])
    finals, rows = [], []
    try:
        for seed in PLACEBO_SEEDS:
            r = eng.simulate(mkt, START_D, END_D, POT, "placebo", seed=seed)
            finals.append(r.final)
            rows.append({"seed": seed, "final": round(r.final, 2),
                         "max_dd_pct": round(r.max_dd * 100, 2),
                         "halt": r.halt_date})
    finally:
        eng.FLOORS[POT] = saved
    s = sorted(finals)
    n_beat = sum(1 for v in finals if ranked_final > v)
    return {
        "n_seeds": len(finals),
        "median_final": round(pct(s, 0.50), 2),
        "p25_final": round(pct(s, 0.25), 2),
        "p75_final": round(pct(s, 0.75), 2),
        "best_final": round(s[-1], 2),
        "worst_final": round(s[0], 2),
        "n_halted": sum(1 for row in rows if row["halt"]),
        "ranked_final": round(ranked_final, 2),
        "ranked_minus_median": round(ranked_final - pct(s, 0.50), 2),
        "ranked_beats_n_of_20": n_beat,
        "ranked_percentile": round(100.0 * n_beat / len(finals), 1),
        "rows": rows,
    }


def main():
    mkt = eng.Market(eng.UNIVERSE)
    yrs = eng.years_between(START_D, END_D)
    bench = eng.spy_net(mkt, START_D, END_D, POT)
    spy_yrs = {y: (round(v * 100, 2) if v is not None else None)
               for y, v in eng.spy_year_returns(mkt, START_D, END_D).items()}

    out = {"pot": POT, "window": [START_D, END_D],
           "spy_net_final": round(bench, 2), "spy_year_returns": spy_yrs,
           "published": {"full_ranked_final": 439.45,
                         "validation_ranked_final": 208.27,
                         "full_placebo_median": 113.40}}

    for name, ladder_on in (("ladder", True), ("plain", False)):
        r = run_variant(mkt, ladder_on)
        folds = year_slices(r, POT)
        fold_rows = {}
        wins = 0
        for y in TEST_YEARS:
            f = folds.get(y)
            s = spy_yrs.get(y)
            if f is None:
                continue
            beat = (f["ret_pct"] > s) if s is not None else None
            if beat:
                wins += 1
            fold_rows[y] = {**f, "spy_ret_pct": s, "beat_spy": beat}
        seg = segment_return(r, "2022-12-30", END_D)
        out[name] = {
            "final": round(r.final, 2),
            "ret_pct": round((r.final / POT - 1) * 100, 2),
            "cagr_pct": round(eng.cagr(r.final, POT, yrs) * 100, 2),
            "orders": r.orders, "costs": round(r.costs, 2),
            "max_dd_pct": round(r.max_dd * 100, 2),
            "halt": r.halt_date,
            "folds": fold_rows,
            "fold_wins_vs_spy": wins,
            "fold_count": len(fold_rows),
            "segment_2023_2026_ret_pct": seg,
        }
        print(f"[{name}] stitched final={r.final:.2f} "
              f"ret={(r.final/POT-1)*100:+.2f}% CAGR="
              f"{eng.cagr(r.final, POT, yrs)*100:.2f}% orders={r.orders} "
              f"costs=${r.costs:.2f} maxDD={r.max_dd*100:.2f}% "
              f"halt={r.halt_date} folds won {wins}/{len(fold_rows)}",
              flush=True)
        for y in TEST_YEARS:
            fr = fold_rows.get(y)
            if fr:
                print(f"  {y}: basket {fr['ret_pct']:+.2f}% vs SPY "
                      f"{fr['spy_ret_pct']:+.2f}% "
                      f"{'WIN' if fr['beat_spy'] else 'loss'} "
                      f"(end ${fr['end_eq']:.2f}, yrDD "
                      f"{fr['max_dd_pct']:.2f}%"
                      f"{', HALTED' if fr['halted'] else ''})", flush=True)

    for name, ladder_on in (("ladder", True), ("plain", False)):
        dist = placebo_dist(mkt, ladder_on, out[name]["final"])
        out[f"{name}_placebo_dist"] = dist
        print(f"[{name}] placebo: median={dist['median_final']:.2f} "
              f"p25={dist['p25_final']:.2f} p75={dist['p75_final']:.2f} "
              f"best={dist['best_final']:.2f} worst={dist['worst_final']:.2f} "
              f"halted={dist['n_halted']}/20 ranked="
              f"{dist['ranked_final']:.2f} beats "
              f"{dist['ranked_beats_n_of_20']}/20", flush=True)

    with open(os.path.join(HERE, "basket-walkforward-results.json"),
              "w") as f:
        json.dump(out, f, indent=1)
    print("saved basket-walkforward-results.json")


if __name__ == "__main__":
    main()
