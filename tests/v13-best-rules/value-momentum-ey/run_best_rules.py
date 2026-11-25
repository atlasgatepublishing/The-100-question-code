#!/usr/bin/env python3
"""
V13 BEST-RULES — VALUE+MOMENTUM-EY (earnings-yield variant).
Simulation only. Spec frozen in BEST-RULES-SPEC.md BEFORE this run.

MY RULES: published EY signal unchanged (PIT EDGAR trailing annual
NetIncomeLoss / market cap + 12-1 momentum, percentile ranks averaged,
next-open execution, equal weight, honest top-30 pond, program costs
0.10%/side + $0.01/sell) with exactly three changes:
  - cadence = monthly (published: quarterly)
  - holdings count = 3 (published: 5)
  - NO floor / stop / ladder (house -15% chassis removed per spec)

Chassis: v12 holdings-value-momentum-ey/run_sweep.py imported read-only.
INTEGRITY GATE: house count-5 quarterly must reproduce the published
finals (LONG $1,367.87 / DECADE $399.16 / CONT $302.28 / VAL $227.25)
before any v13 number is taken.

CONFIRMATION (pre-registered in the spec): if my rules beat a champion
(V+M LONG $1,415.62 / CONT $544.47 / VAL $288.05 / DECADE $667.35) on
any road -> fresh-$100 calendar-year folds 2017..2026 + DECADE
half-windows, my full rule set head-to-head vs the published house
form (count 5, quarterly, floor chassis). Confirmed requires
>=6/10 folds AND >=1/2 halves.
"""
import importlib.util
import json
import os
import random
import time
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
SWEEP_PATH = os.path.expanduser(
    "~/workspace/stock-app/backtests/v12-completions/"
    "holdings-value-momentum-ey/run_sweep.py")
END = "2026-11-20"
SEEDS = list(range(1, 21))
MY_COUNT = 3
MY_CADENCE = "monthly"
NO_FLOOR = -1.0  # run_one halts only if close value <= floor; never

CHAMPION = {"LONG": 1415.62, "CONT": 544.47, "VAL": 288.05, "DECADE": 667.35}
PUBLISHED = {"LONG": 1367.87, "DECADE": 399.16, "CONT": 302.28, "VAL": 227.25}
VARIANT3 = {"LONG": 2046.22, "DECADE": 510.35, "CONT": 410.21, "VAL": 232.57}
SPY_REF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


S = load_module("ey_sweep", SWEEP_PATH)


def max_dd(curve):
    peak, peak_d, mdd, mdd_d, worst, worst_d = -1.0, None, 0.0, None, 1e18, None
    for d, v in curve:
        if v > peak:
            peak, peak_d = v, d
        if peak > 0:
            dd = (peak - v) / peak * 100.0
            if dd > mdd:
                mdd, mdd_d = dd, d
        if v < worst:
            worst, worst_d = v, d
    return {"max_dd_pct": round(mdd, 2), "max_dd_date": mdd_d,
            "worst_close": round(worst, 2), "worst_close_date": worst_d}


def period_distribution(curve):
    """Monthly periods (my cadence): last curve value per calendar month."""
    months = {}
    for d, v in curve:
        months[d[:7]] = v  # curve is date-ordered; last write wins
    keys = sorted(months)
    rets = []  # (month, $ change, % change)
    prev = 100.0
    for k in keys:
        v = months[k]
        rets.append((k, round(v - prev, 2),
                     round((v / prev - 1.0) * 100.0, 2) if prev else 0.0))
        prev = v
    dollars = sorted(r[1] for r in rets)
    n = len(dollars)
    median = dollars[n // 2] if n % 2 == 1 else (dollars[n // 2 - 1] + dollars[n // 2]) / 2.0
    pos = sum(1 for r in rets if r[1] > 0)
    best = max(rets, key=lambda r: r[1])
    worst = min(rets, key=lambda r: r[1])
    streak = longest = 0
    for r in rets:
        streak = streak + 1 if r[1] < 0 else 0
        longest = max(longest, streak)
    # longest stretch (in periods) between new highs of period-end value
    run_max, since, longest_gap = -1.0, 0, 0
    vals = [months[k] for k in keys]
    for v in vals:
        if v > run_max:
            run_max, since = v, 0
        else:
            since += 1
            longest_gap = max(longest_gap, since)
    return {"periods": n, "median_period_dollars": round(median, 2),
            "share_positive_pct": round(100.0 * pos / n, 1) if n else None,
            "best_period": {"month": best[0], "dollars": best[1], "pct": best[2]},
            "worst_period": {"month": worst[0], "dollars": worst[1], "pct": worst[2]},
            "longest_losing_streak_periods": longest,
            "longest_between_new_highs_periods": longest_gap,
            "mean_period_dollars_secondary": round(sum(r[1] for r in rets) / n, 2) if n else None}


def run_mine(pb, scorer, start, end, placebo_seed=None):
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    return S.run_one(pb, scorer, start, end, S.START_CASH, NO_FLOOR,
                     MY_CADENCE, placebo_rng=rng, n_pick=MY_COUNT)


def main():
    t0 = time.time()
    results = {
        "program": "v13-best-rules",
        "family": "value-momentum-ey (earnings-yield variant)",
        "spec": "BEST-RULES-SPEC.md (frozen before run)",
        "my_rules": {"count": MY_COUNT, "cadence": MY_CADENCE, "floor": None,
                     "weighting": "equal",
                     "costs": "0.10%/side + $0.01 per sell order",
                     "start_cash": 100.0},
        "published_form": {"count": 5, "cadence": "quarterly",
                           "rules": "house (-15% floor chassis)",
                           "finals": PUBLISHED},
        "family_best_prior_variant_count3": VARIANT3,
        "champion_vm": CHAMPION,
        "spy_reference": SPY_REF,
        "integrity": {}, "roads": {}, "confirmation": None,
    }

    pb, scorer = S.build()

    road_specs = [("LONG", "2010-01-04", END), ("DECADE", "2016-11-21", END),
                  ("CONT", "2019-01-02", END), ("VAL", "2023-01-03", END)]

    # ---------------- integrity gate: house count-5 quarterly = published
    for name, s, e in road_specs:
        r = S.run_v9(pb, scorer, "quarterly", s, e, n_pick=5)
        ok = abs(round(r["final"], 2) - PUBLISHED[name]) < 0.02
        results["integrity"][name] = {"expected_house_count5": PUBLISHED[name],
                                      "reproduced": round(r["final"], 2),
                                      "match": ok}
        print(f"INTEGRITY {name} house-5 quarterly: ${r['final']:,.2f} "
              f"expected ${PUBLISHED[name]} match={ok}", flush=True)
        assert ok, f"integrity failed on {name}"

    # ---------------- my-rules run + placebos per road
    beat_champion_any = False
    for name, s, e in road_specs:
        spy_final, _ = S.spy_net(pb, s, e, S.START_CASH)
        r = run_mine(pb, scorer, s, e)
        diag = max_dd(r["curve"])
        pfinals = []
        for seed in SEEDS:
            pr = run_mine(pb, scorer, s, e, placebo_seed=seed)
            pfinals.append(round(pr["final"], 2))
        beaten = sum(1 for f in pfinals if f < r["final"])
        dist = period_distribution(r["curve"])
        # published-form reference diagnostics (house count-5 quarterly)
        pr5 = S.run_v9(pb, scorer, "quarterly", s, e, n_pick=5)
        pdiag = max_dd(pr5["curve"])
        pdist = period_distribution(pr5["curve"])
        beat_champ = round(r["final"], 2) > CHAMPION[name]
        beat_champion_any = beat_champion_any or beat_champ
        results["roads"][name] = {
            "window": [s, e], "spy_final": round(spy_final, 2),
            "my_rules": {"final": round(r["final"], 2),
                         "costs": round(r["costs"], 2),
                         "orders": len(r["trades"]),
                         "max_dd_pct": diag["max_dd_pct"],
                         "max_dd_date": diag["max_dd_date"],
                         "worst_close": diag["worst_close"],
                         "worst_close_date": diag["worst_close_date"],
                         "placebo_beaten": beaten,
                         "placebo_finals": pfinals,
                         "beats_champion": beat_champ,
                         "period_distribution": dist,
                         "curve": [[d, round(v, 4)] for d, v in r["curve"]]},
            "published_form_house5": {
                "final": round(pr5["final"], 2),
                "costs": round(pr5["costs"], 2), "orders": pr5["orders"],
                "halts": len(pr5["halts"]),
                "max_dd_pct": pdiag["max_dd_pct"],
                "max_dd_date": pdiag["max_dd_date"],
                "period_distribution": pdist,
                "curve": [[d, round(v, 4)] for d, v in pr5["curve"]]},
        }
        print(f"{name} MY-RULES monthly/count3/nofloor: ${r['final']:,.2f} "
              f"(published ${PUBLISHED[name]:,.2f}, variant3 ${VARIANT3[name]:,.2f}, "
              f"champion ${CHAMPION[name]:,.2f}, SPY ${spy_final:,.2f}) "
              f"placebos {beaten}/20 maxDD {diag['max_dd_pct']}% "
              f"orders={len(r['trades'])} costs=${r['costs']:,.2f}", flush=True)

    # ---------------- confirmation (Terry's rule, pre-registered)
    if beat_champion_any:
        folds = {}
        for yr in range(2017, 2027):
            s = f"{yr}-01-01"
            e = END if yr == 2026 else f"{yr}-12-31"
            rc = run_mine(pb, scorer, s, e)
            rp = S.run_v9(pb, scorer, "quarterly", s, e, n_pick=5)
            folds[str(yr)] = {"my_rules_final": round(rc["final"], 2),
                              "published_final": round(rp["final"], 2),
                              "my_rules_max_dd_pct": max_dd(rc["curve"])["max_dd_pct"],
                              "my_rules_win": rc["final"] > rp["final"]}
        halves = {}
        for hn, (s, e) in {"H1_2016-2021": ("2016-11-21", "2021-12-31"),
                           "H2_2022-2026": ("2022-01-01", END)}.items():
            rc = run_mine(pb, scorer, s, e)
            rp = S.run_v9(pb, scorer, "quarterly", s, e, n_pick=5)
            halves[hn] = {"my_rules_final": round(rc["final"], 2),
                          "published_final": round(rp["final"], 2),
                          "my_rules_max_dd_pct": max_dd(rc["curve"])["max_dd_pct"],
                          "my_rules_win": rc["final"] > rp["final"]}
        wins = sum(1 for v in folds.values() if v["my_rules_win"])
        hwins = sum(1 for v in halves.values() if v["my_rules_win"])
        results["confirmation"] = {
            "design": "fresh-$100 calendar-year folds 2017-2026 + DECADE "
                      "half-windows; my full rule set vs published house form",
            "year_folds": folds, "fold_wins": f"{wins}/10",
            "half_windows": halves, "half_wins": f"{hwins}/2",
            "confirmed": wins >= 6 and hwins >= 1}
        print(f"CONFIRMATION: folds {wins}/10 halves {hwins}/2 "
              f"confirmed={results['confirmation']['confirmed']}", flush=True)

    results["elapsed_sec"] = round(time.time() - t0, 1)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("DONE", results["elapsed_sec"], flush=True)


if __name__ == "__main__":
    main()
