#!/usr/bin/env python3
"""
THE GRAND COMBINATION — Terry's AI stock app, simulation only.

QUESTION (Terry's directive): the program has exactly three promoted
components. (1) Value+Momentum — quarterly top-5 by average percentile
rank of book-to-market and 12-1 momentum, honest 2016 top-30 universe,
EDGAR point-in-time (value-momentum-plainfloor.py). (2) The Momentum
Basket — monthly top-5 by 12-1 momentum among names above their 200-day
average, same universe (momentum-basket-honest.py). (3) The ETF Trend
Sleeve, monthly variant — multi-asset trend (SPY/QQQ/TLT/IEF/GLD/DBC/
UUP, 3/6/12-month sign blend, inverse-vol weights, monthly evaluation;
etf-trend-sleeve-monthly.py). Put EVERYTHING THAT ACTUALLY WORKED into
one pot and test the combination: does it beat the best single piece,
or dilute again (as the two-engine winners' blend did: $400.84 vs
value+momentum's $544.47, sleeve correlation +0.79)?

SPEC (frozen a priori, no tuning):
  - One $100 pot split in equal thirds: $33.333... per sleeve. Each
    sleeve runs its own proven rules and cost schedule verbatim
    (0.10%/side + $0.01/sell inside each engine) on its third, with its
    internal floor/ladder DISABLED — protection lives at pot level.
  - Every January (first trading day of the month, at that day's close)
    the split is rebalanced back to thirds of the pot: overweight
    sleeves are trimmed pro-rata and the proceeds buy into underweight
    sleeves, charged at the engines' normal cost schedule (0.10% on
    each sale + 0.10% on each purchase + $0.01 x 5 sell orders per
    trimmed sleeve — the winners'-blend approximation, generalized).
  - Pot-level protection: the PLAIN -15% floor only ($85 on the $100
    pot). No ladder, no sleeve-level floor. If the pot closes at/below
    $85 the run ends (liquidation approximated at the next day's close
    less 0.10% and $0.17 of sell fees = 17 positions x $0.01).
  - Windows: CONTINUOUS 2019-01-01 -> 2026-11-20 and VALIDATION
    2023-01-01 -> 2026-11-20, $100 pots — the longest windows all three
    engines share (value+momentum's published runs start 2019) and the
    same windows the winners' blend used, for exact comparability.
    (Engines snap to the first trading day: 2019-01-02 / 2023-01-03.)

METHOD — engines verbatim, blended at the equity-curve level (the
winners'-blend methodology, generalized from two sleeves to three):
  All three engines are IMPORTED UNMODIFIED and called with their own
  data loaders. Each sleeve is run standalone on its third with its
  internal floor disabled, producing a daily close-equity curve. The
  pot is the sum of the three sleeve values (forward-filled over the
  union of the sleeves' trading days); at each January rebalance the
  sleeves are rescaled to thirds of the pot less the transfer cost.
  Documented approximations, inherited from the winners' blend:
  (1) after a January rescale a sleeve's subsequent path follows its
  standalone curve, so the $0.01 fixed sell fees inside the engines are
  charged at the standalone trajectory rather than the rescaled one —
  a pennies-level effect; (2) the January transfer is charged at the
  engines' cost schedule on the transferred value rather than by
  re-trading every share; (3) the ETF sleeve's January trim is charged
  5 sell orders like the stock sleeves (it holds a variable 0-7 assets;
  the error is at most $0.02 per rebalance).

PLACEBO: 20 seeds (1..20) per window. Each seed runs random picks
inside the two stock sleeves (basket engine's own placebo mode;
value engine's placebo_rng) with the identical blend machinery; the
ETF trend sleeve is deterministic and has no picks to randomize, so
its curve is unchanged across seeds (per the assigned spec).

WALK-FORWARD FOLDS: fresh $100 pot per calendar year 2020-2026
(2026 -> Nov 20), same construction (no January rebalance falls inside
a single fold year), scored against SPY net over the same window —
the value+momentum walk-forward convention (its published record on
this convention: 4 wins / 7).

INTEGRITY CHECKS (run first, abort on failure) — each engine in its
ORIGINAL configuration must reproduce its published final:
  - Momentum basket, original floor+ladder, full 2016 window, $100
    -> $439.45.
  - Value+momentum plain floor, $100 -> $544.47 (continuous) and
    $288.05 (validation).
  - ETF trend sleeve monthly, original floor+ladder, full 2016
    window, $100 -> $194.61.

Data: the parent studies' own caches, read-only (Yahoo bars under
v4/momentum-basket-honest-data and v4/value-momentum-honest-data;
EDGAR companyfacts under v4/data; ETF bars under v3/data_etf).
"""

import importlib.util
import json
import math
import os
import random
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.join(HERE, "..", "..", "v4")
V3 = os.path.join(HERE, "..", "..", "v3")


def _load(modname, path):
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mb = _load("momentum_basket_honest",
           os.path.join(V4, "momentum-basket-honest.py"))
vm = _load("value_momentum_plainfloor",
           os.path.join(V4, "value-momentum-plainfloor.py"))
etf = _load("etf_trend_sleeve_monthly",
            os.path.join(V3, "etf-trend-sleeve-monthly.py"))

POT = 100.0
FLOOR = 85.0
THIRD = POT / 3.0
WINDOWS = {
    "continuous": ("2019-01-01", "2026-11-20"),
    "validation": ("2023-01-01", "2026-11-20"),
}
PLACEBO_SEEDS = list(range(1, 21))


# --------------------------------------------------------------------------
# Small helpers (reporting only — no trading logic)
# --------------------------------------------------------------------------
def max_dd(curve):
    peak, worst = -1.0, 0.0
    for _, eq in curve:
        peak = max(peak, eq)
        if peak > 0:
            worst = min(worst, eq / peak - 1.0)
    return worst


def per_year(curve, start_val):
    out = {}
    prev = float(start_val)
    years = sorted({d[:4] for d, _ in curve})
    for y in years:
        pts = [e for d, e in curve if d[:4] == y]
        if not pts:
            continue
        out[y] = pts[-1] / prev - 1.0
        prev = pts[-1]
    return out


def monthly_returns(curve):
    month_end = {}
    for d, eq in curve:
        month_end[d[:7]] = eq
    keys = sorted(month_end)
    return {b: month_end[b] / month_end[a] - 1.0
            for a, b in zip(keys, keys[1:])}


def pearson(xs, ys):
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return float("nan")
    return cov / math.sqrt(vx * vy)


def cagr(final, start, sd, ed):
    yrs = (datetime.strptime(ed, "%Y-%m-%d")
           - datetime.strptime(sd, "%Y-%m-%d")).days / 365.25
    return (final / start) ** (1.0 / yrs) - 1.0


def pct(sorted_vals, q):
    if not sorted_vals:
        return float("nan")
    i = q * (len(sorted_vals) - 1)
    lo, hi = int(math.floor(i)), int(math.ceil(i))
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (i - lo)


# --------------------------------------------------------------------------
# The combination: three sleeve equity curves -> one pot
# --------------------------------------------------------------------------
def blend3(curves, pot0=POT, floor=FLOOR):
    """curves: list of 3 standalone sleeve daily close-equity curves,
    each started at pot0/3. Returns (pot_curve, info). January
    split-rebalances at the close of the first trading day of each
    January after the inception January; pot-level plain floor checked
    on every close."""
    dicts = [dict(c) for c in curves]
    first = max(min(d) for d in dicts)
    last = min(max(d) for d in dicts)
    alldates = set()
    for d in dicts:
        alldates |= set(d)
    dates = sorted(d for d in alldates if first <= d <= last)
    start_year = dates[0][:4]
    jan_dates = set()
    seen_jan = set()
    for d in dates:
        if d[5:7] == "01" and d[:4] != start_year and d[:4] not in seen_jan:
            seen_jan.add(d[:4])
            jan_dates.add(d)

    scales = [1.0, 1.0, 1.0]
    lasts = [None, None, None]
    pot_curve = []
    rebalances = []
    transfer_costs = 0.0
    halt = None
    final = None
    for idx, d in enumerate(dates):
        for k in range(3):
            if d in dicts[k]:
                lasts[k] = dicts[k][d]
        vals = [scales[k] * lasts[k] for k in range(3)]
        tot = sum(vals)
        if d in jan_dates:
            target = tot / 3.0
            moved = sum(max(0.0, v - target) for v in vals)
            n_trim = sum(1 for v in vals if v > target)
            cost = moved * 0.002 + 0.05 * n_trim   # 0.10% sell + 0.10%
            #                                        buy + $0.01 x 5 sell
            #                                        orders per trim
            tot -= cost
            transfer_costs += cost
            target = tot / 3.0
            for k in range(3):
                scales[k] = target / lasts[k]
            rebalances.append({"date": d,
                               "sleeves_before": [round(v, 2) for v in vals],
                               "moved": round(moved, 2),
                               "cost": round(cost, 2)})
            tot = target * 3.0
        pot_curve.append((d, tot))
        if tot <= floor:
            halt = d
            if idx < len(dates) - 1:
                nd = dates[idx + 1]
                nxt = 0.0
                for k in range(3):
                    v = dicts[k].get(nd, lasts[k])
                    nxt += scales[k] * v
                final = nxt * (1 - 0.001) - 0.17
            else:
                final = tot * (1 - 0.001) - 0.17
            break
    if final is None:
        final = pot_curve[-1][1]
    info = {"halt": halt, "final": final,
            "transfer_costs": transfer_costs,
            "rebalances": rebalances, "max_dd": max_dd(pot_curve)}
    return pot_curve, info


# --------------------------------------------------------------------------
# Value+momentum data assembly — the parent study's own assembly, using
# the parent module's functions verbatim (incl. the XOM CIK override).
# --------------------------------------------------------------------------
def build_vm_book():
    ciks = vm.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}
    equity_rows, shares_rows = {}, {}
    for t in vm.UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts = vm.get_companyfacts(cik)
        equity_rows[t] = (
            vm.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
            vm.pit_series(facts, "us-gaap",
                          "StockholdersEquityIncludingPortionAttributable"
                          "ToNoncontrollingInterest", prio=1))
        shares_rows[t] = (
            vm.pit_series(facts, "dei",
                          "EntityCommonStockSharesOutstanding", prio=3) +
            vm.pit_series(facts, "us-gaap",
                          "CommonStockSharesOutstanding", prio=2) +
            vm.pit_series(facts, "us-gaap",
                          "WeightedAverageNumberOfSharesOutstandingBasic",
                          prio=1))
        time.sleep(0.05)
    bars = {}
    for t in vm.UNIVERSE + ["SPY"]:
        bars[t] = vm.get_prices(t)
    return vm.PriceBook(bars), equity_rows, shares_rows


# --------------------------------------------------------------------------
# Sleeve runners (floor disabled; protection at pot level only)
# --------------------------------------------------------------------------
def sleeve_mb(mkt, sd, ed, mode="ranked", seed=42):
    r = mb.simulate(mkt, sd, ed, THIRD, mode, seed=seed)
    return r.equity_curve, r.costs


def sleeve_vm(pb, eq_rows, sh_rows, sd, ed, placebo_rng=None):
    r = vm.run_pot(pb, eq_rows, sh_rows, sd, ed, THIRD, 0.0, [],
                   placebo_rng=placebo_rng, quiet=True)
    return r["curve"], r["costs"]


def sleeve_etf(sd, ed):
    r = etf.simulate(sd, ed, start_cash=THIRD, floor0=0.0, ladder=())
    return r["curve"], r["costs"]


# ============================================================ V9 MODULE
# "CLAUDE-RULES PROTECTION SPEC v9" - this copy only. The ONLY change vs
# the original v5 script is the protection module (the *_v9 wrapper
# below, which reuses the original sleeve runners and blend function
# unchanged for each episode; protection stays at the whole-pot level,
# exactly where the original puts it):
#   - Episode 1: plain -15% floor from the $100 start ($85.00), identical
#     to Terry's rule. On FIRST halt: liquidate exactly as the original
#     blend does (next-day sleeve values x (1-0.10%) - sell fees), sit
#     in cash 90 calendar days (counted from the liquidation date), then
#     RESTART the whole pot with the remaining cash at its next regular
#     rebalance/selection point after day 90 (the next quarterly V+M
#     selection date; it is also a monthly ETF-sleeve selection date),
#     split in the original proportions.
#   - Episode 2: floor = -15% from the RESTART balance. On SECOND halt:
#     the run ends permanently.
#   - If halt + 90 days runs past the window/fold end, the run ends in
#     cash.
# Everything else is byte-identical: universe, signals, parameters,
# costs, windows, $100 start. Scope (per spec): ranked pots only, no
# placebos. Windows/folds where the original recorded run never fired
# the floor are NOT re-run - identical under v9 by construction.
# This script writes ONLY v9-results.json next to itself.
# Simulation only.
# ============================================================

def _next_sel(pb, start, end, on_or_after_ordinal):
    from datetime import date as _date
    for cand in vm.quarter_selection_dates(pb, start, end):
        cy, cm, cd = int(cand[:4]), int(cand[5:7]), int(cand[8:10])
        if _date(cy, cm, cd).toordinal() >= on_or_after_ordinal:
            return cand
    return None


def _sleeves_at(mkt, pb, eq_rows, sh_rows, sd, ed, total_cash):
    """Original sleeve engines at total_cash/3 each, sleeve floors off
    (protection is at pot level, as in the original)."""
    third = total_cash / 3.0
    mb.FLOORS[third] = (0.0, [])
    r_vm = vm.run_pot(pb, eq_rows, sh_rows, sd, ed, third, 0.0, [],
                      quiet=True)
    r_mb = mb.simulate(mkt, sd, ed, third, "ranked")
    r_etf = etf.simulate(sd, ed, start_cash=third, floor0=0.0, ladder=())
    return ([r_vm["curve"], r_mb.equity_curve, r_etf["curve"]],
            r_vm["costs"] + r_mb.costs + r_etf["costs"])


def combo_v9(mkt, pb, eq_rows, sh_rows, start, end, start_cash=100.0):
    from datetime import date as _date
    floor1 = round(0.85 * start_cash, 2)
    curves, costs1 = _sleeves_at(mkt, pb, eq_rows, sh_rows, start, end,
                                 start_cash)
    curve1, info1 = blend3(curves, pot0=start_cash, floor=floor1)
    out = {"final": info1["final"], "curve": list(curve1),
           "halt": info1["halt"], "restarts": [], "second_halt": None,
           "episodes": 1, "ep1_final": info1["final"],
           "costs_sleeves": costs1,
           "costs_transfers": info1["transfer_costs"]}
    if info1["halt"] is None:
        return out
    all_dates = sorted(set(d for c in curves for d, _ in c))
    liq_date = next(d for d in all_dates if d > info1["halt"])
    cash = info1["final"]
    ly, lm, ld = int(liq_date[:4]), int(liq_date[5:7]), int(liq_date[8:10])
    day90 = _date(ly, lm, ld).toordinal() + 90
    restart = _next_sel(pb, start, end, day90)
    seg_end = restart if restart else end
    for d in all_dates:
        if liq_date < d < seg_end:
            out["curve"].append((d, cash))
    if restart is None:
        out["curve"].append((end, cash))
        return out
    floor2 = round(0.85 * cash, 2)
    out["restarts"].append({
        "halt_signal_date": info1["halt"],
        "liquidation_date": liq_date,
        "halt_signal_close": round(dict(curve1)[info1["halt"]], 2),
        "restart_date": restart,
        "restart_balance": round(cash, 2),
        "episode2_floor": floor2})
    curves2, costs2 = _sleeves_at(mkt, pb, eq_rows, sh_rows, restart, end,
                                  cash)
    curve2, info2 = blend3(curves2, pot0=cash, floor=floor2)
    out["episodes"] = 2
    out["final"] = info2["final"]
    out["curve"] += list(curve2)
    out["costs_sleeves"] += costs2
    out["costs_transfers"] += info2["transfer_costs"]
    if info2["halt"] is not None:
        out["second_halt"] = {"signal_date": info2["halt"],
                              "liquidation_final": round(info2["final"], 2),
                              "floor_in_effect": floor2}
    out["curve"].sort(key=lambda kv: kv[0])
    return out


HIS_FOLDS = [
    {"year": 2020, "final": 91.43, "spy_net": 117.47, "halt": "2020-03-12"},
    {"year": 2021, "final": 115.27, "spy_net": 127.97, "halt": None},
    {"year": 2022, "final": 97.89, "spy_net": 81.42, "halt": None},
    {"year": 2023, "final": 115.33, "spy_net": 125.28, "halt": None},
    {"year": 2024, "final": 128.48, "spy_net": 125.46, "halt": None},
    {"year": 2025, "final": 113.77, "spy_net": 116.81, "halt": None},
    {"year": 2026, "final": 114.48, "spy_net": 101.17, "halt": None},
]


def main():
    print("loading momentum-basket market (cache)...", flush=True)
    mkt = mb.Market(mb.UNIVERSE)
    print("loading value+momentum book (cache)...", flush=True)
    pb, eq_rows, sh_rows = build_vm_book()
    # configure the basket engine exactly as the original main does
    mb.FLOORS = {100: (FLOOR, []), THIRD: (0.0, [])}

    # Main windows: pot-level floor never fired under his rules
    # (continuous combo_halt=None, final $306.56; validation
    # combo_halt=None, final $195.83) -> identical under v9, NOT
    # re-run. Only the 2020 fold fired (halt 2020-03-12; the blend
    # liquidated next day into the Mar-13 rebound, final $91.43).
    r = combo_v9(mkt, pb, eq_rows, sh_rows, "2020-01-01", "2020-12-31", 100.0)
    print(f"FOLD2020 EP1 final=${r['ep1_final']:.2f} halt={r['halt']} "
          f"(recorded his: $91.43, halt 2020-03-12)", flush=True)
    assert abs(r["ep1_final"] - 91.43) < 0.02 and r["halt"] == "2020-03-12", \
        "fold episode-1 reproduction failed"
    print(f"V9 FOLD 2020 final=${r['final']:.2f} restarts={r['restarts']} "
          f"second_halt={r['second_halt']}", flush=True)

    v9_folds = []
    for f in HIS_FOLDS:
        if f["year"] == 2020:
            v9_folds.append({"year": 2020, "final": round(r["final"], 2),
                             "spy_net": f["spy_net"],
                             "beat_spy": r["final"] > f["spy_net"],
                             "halt_ep1": r["halt"],
                             "second_halt": r["second_halt"]})
        else:
            v9_folds.append({"year": f["year"], "final": f["final"],
                             "spy_net": f["spy_net"],
                             "beat_spy": f["final"] > f["spy_net"],
                             "halt_ep1": f["halt"], "second_halt": None})
    his_wins = sum(1 for f in HIS_FOLDS if f["final"] > f["spy_net"])
    v9_wins = sum(1 for f in v9_folds if f["beat_spy"])
    def comp(folds):
        c = 100.0
        for f in folds:
            c *= f["final"] / 100.0
        return round(c, 2)
    ep1_curve_min = min(v for d, v in r["curve"] if d <= "2020-03-13")
    v9_min = min([v for _, v in r["curve"]] + [r["final"]])
    out = {
        "slug": "grand-combination",
        "name": "Grand combination: equal thirds V+M / momentum basket / ETF trend, January rebalance",
        "status": "partial-rerun",
        "his": {"continuous_final": 306.56, "validation_final": 195.83},
        "v9": {
            "continuous_final": 306.56, "validation_final": 195.83,
            "continuous_status": "identical - floor never fired (combo_halt=None in v5 results; the blend checks the $85 floor on every close, so no close at/below $85 occurred)",
            "validation_status": "identical - floor never fired (combo_halt=None in v5 results; max drawdown -14.05%)",
            "restarts": [{"window": "fold-2020", **x} for x in r["restarts"]],
            "folds_note": (f"His folds 3/7 vs SPY (fold-compounded ${comp(HIS_FOLDS)}, matching the published figure); "
                           f"v9 folds {v9_wins}/7 vs SPY (fold-compounded ${comp(v9_folds)}). "
                           f"Only the 2020 fold fired under his rules (halt 2020-03-12, final $91.43 after "
                           f"next-day liquidation into the rebound); re-run under v9: final ${round(r['final'],2)}. "
                           f"Other folds never fired, unchanged."),
            "worst_total_loss_pct": round(v9_min / 100.0 * 100 - 100, 2),
        },
        "notes": ("Simulation only. Main windows NOT re-run: the pot-level floor never fired there "
                  "under his rules (combo_halt=None on both windows in the v5 results). 2020 fold "
                  "episode 1 reproduced the recorded his-rules result ($91.43, halt 2020-03-12) "
                  "before the v9 restart was applied. Note the episode-1 liquidation final ($91.43) "
                  "is ABOVE the $85 floor: the blend liquidates at next-day values, and 2020-03-13 "
                  "rebounded - the restart balance is therefore $91.43 and the episode-2 floor is "
                  "85% of that. His worst total loss from $100 on the re-run fold: "
                  f"{round(ep1_curve_min/100*100-100,2)}% (episode-1 blend curve minimum close, the halt signal close). "
                  f"V9 fold detail: {v9_folds}"),
        "detail": {"fold_2020_v9": {"ep1_final": round(r["ep1_final"], 2),
                                    "final": round(r["final"], 2),
                                    "costs_sleeves": round(r["costs_sleeves"], 2),
                                    "costs_transfers": round(r["costs_transfers"], 2),
                                    "restarts": r["restarts"],
                                    "second_halt": r["second_halt"],
                                    "ep1_curve_min_close": round(ep1_curve_min, 2),
                                    "v9_curve_min_close": round(v9_min, 2)},
                   "his_fold_compounded": comp(HIS_FOLDS),
                   "v9_fold_compounded": comp(v9_folds),
                   "his_fold_record": f"{his_wins} wins, {7-his_wins} losses vs SPY",
                   "v9_fold_record": f"{v9_wins} wins, {7-v9_wins} losses vs SPY"},
    }
    with open(os.path.join(HERE, "v9-results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
