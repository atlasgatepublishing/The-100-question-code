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


def main():
    out = {"spec": "grand combination: equal thirds VM / MB / ETF-trend-"
                   "monthly, January rebalance to thirds, plain -15% "
                   "pot floor, $100 pots",
           "windows": WINDOWS}
    print("loading momentum-basket market (cache)...", flush=True)
    mkt = mb.Market(mb.UNIVERSE)

    # ---------------- integrity checks ----------------------------------
    r = mb.simulate(mkt, "2016-11-21", "2026-11-20", 100, "ranked")
    print(f"CHECK mb original full-2016 $100: ${r.final:.2f} "
          f"(published $439.45)", flush=True)
    assert abs(r.final - 439.45) < 0.05, "momentum engine check failed"

    print("loading value+momentum book (cache)...", flush=True)
    pb, eq_rows, sh_rows = build_vm_book()
    r = vm.run_pot(pb, eq_rows, sh_rows, "2019-01-02", "2026-11-20",
                   100.0, 85.0, [], quiet=True)
    print(f"CHECK vm plainfloor full $100: ${r['final']:.2f} "
          f"(published $544.47)", flush=True)
    assert abs(r["final"] - 544.47) < 0.05, "value engine check failed"
    r = vm.run_pot(pb, eq_rows, sh_rows, "2023-01-03", "2026-11-20",
                   100.0, 85.0, [], quiet=True)
    print(f"CHECK vm plainfloor validation $100: ${r['final']:.2f} "
          f"(published $288.05)", flush=True)
    assert abs(r["final"] - 288.05) < 0.05, "value engine check failed"

    r = etf.simulate("2016-11-21", "2026-11-20")
    print(f"CHECK etf monthly original full-2016 $100: ${r['final']:.2f} "
          f"(published $194.61)", flush=True)
    assert abs(r["final"] - 194.61) < 0.05, "etf engine check failed"
    out["integrity_checks"] = "passed (439.45 / 544.47 / 288.05 / 194.61)"

    # ------------- configure the basket engine: plain floor / none ------
    mb.FLOORS = {100: (FLOOR, []), THIRD: (0.0, [])}

    for wname, (sd, ed) in WINDOWS.items():
        print(f"\n===== {wname} {sd} -> {ed} =====", flush=True)
        # ---- parents alone at $100 --------------------------------------
        mbp = mb.simulate(mkt, sd, ed, 100, "ranked")
        vmp = vm.run_pot(pb, eq_rows, sh_rows, sd, ed, POT, FLOOR, [],
                         quiet=True)
        etfp = etf.simulate(sd, ed, start_cash=100.0, floor0=0.0,
                            ladder=())
        spy_vm, _ = vm.spy_net(pb, sd, ed, 100)
        spy_mb = mb.spy_net(mkt, sd, ed, 100)

        # ---- ranked sleeves at a third each, no sleeve floor ------------
        c_mb, cost_mb = sleeve_mb(mkt, sd, ed)
        c_vm, cost_vm = sleeve_vm(pb, eq_rows, sh_rows, sd, ed)
        c_etf, cost_etf = sleeve_etf(sd, ed)
        pot_curve, info = blend3([c_vm, c_mb, c_etf])

        # ---- sleeve correlations (monthly returns) -----------------------
        mrs = [monthly_returns(c) for c in (c_vm, c_mb, c_etf)]
        names = ["vm", "mb", "etf"]
        corrs = {}
        for a in range(3):
            for b in range(a + 1, 3):
                common = sorted(set(mrs[a]) & set(mrs[b]))
                corrs[f"{names[a]}-{names[b]}"] = round(
                    pearson([mrs[a][m] for m in common],
                            [mrs[b][m] for m in common]), 3)
                corrs[f"{names[a]}-{names[b]}_months"] = len(common)

        # ---- placebo: 20 seeds -------------------------------------------
        finals = []
        placebo_rows = []
        for seed in PLACEBO_SEEDS:
            p_mb, _ = sleeve_mb(mkt, sd, ed, mode="placebo", seed=seed)
            p_vm, _ = sleeve_vm(pb, eq_rows, sh_rows, sd, ed,
                                placebo_rng=random.Random(seed))
            _, pinfo = blend3([p_vm, p_mb, c_etf])
            finals.append(pinfo["final"])
            placebo_rows.append({"seed": seed,
                                 "final": round(pinfo["final"], 2),
                                 "halt": pinfo["halt"]})
            print(f"  placebo seed {seed:2d}: ${pinfo['final']:,.2f} "
                  f"halt={pinfo['halt']}", flush=True)
        srt = sorted(finals)
        ranked_final = info["final"]
        beaten = sum(1 for f in finals if f < ranked_final)
        dist = {"median": round(pct(srt, 0.50), 2),
                "q1": round(pct(srt, 0.25), 2),
                "q3": round(pct(srt, 0.75), 2),
                "best": round(srt[-1], 2), "worst": round(srt[0], 2),
                "ranked_final": round(ranked_final, 2),
                "seeds_beaten": beaten,
                "rows": placebo_rows}

        w = {
            "combo_final": round(info["final"], 2),
            "combo_ret_pct": round((info["final"] / POT - 1) * 100, 2),
            "combo_cagr_pct": round(cagr(info["final"], POT, sd, ed)
                                    * 100, 2),
            "combo_max_dd_pct": round(info["max_dd"] * 100, 2),
            "combo_halt": info["halt"],
            "combo_costs_sleeves": round(cost_vm + cost_mb + cost_etf, 2),
            "combo_costs_transfers": round(info["transfer_costs"], 2),
            "combo_rebalances": info["rebalances"],
            "sleeve_finals_standalone_third": {
                "vm": round(c_vm[-1][1], 2), "mb": round(c_mb[-1][1], 2),
                "etf": round(c_etf[-1][1], 2)},
            "sleeve_costs": {"vm": round(cost_vm, 2),
                             "mb": round(cost_mb, 2),
                             "etf": round(cost_etf, 2)},
            "correlations_monthly": corrs,
            "placebo": dist,
            "vm_parent_final_postliq": round(vmp["final"], 2),
            "vm_parent_final_mtm": round(vmp["curve"][-1][1], 2),
            "vm_parent_max_dd_pct": round(max_dd(vmp["curve"]) * 100, 2),
            "vm_parent_halt": vmp["halted"],
            "vm_parent_costs": round(vmp["costs"], 2),
            "mb_parent_final": round(mbp.final, 2),
            "mb_parent_max_dd_pct": round(mbp.max_dd * 100, 2),
            "mb_parent_halt": mbp.halt_date,
            "mb_parent_costs": round(mbp.costs, 2),
            "etf_parent_final_nofloor": round(etfp["final"], 2),
            "etf_parent_max_dd_pct": round(max_dd(etfp["curve"]) * 100, 2),
            "etf_parent_costs": round(etfp["costs"], 2),
            "spy_net_final_vm_basis": round(spy_vm, 2),
            "spy_net_final_mb_basis": round(spy_mb, 2),
            "per_year": {
                "combo": {y: round(v * 100, 2)
                          for y, v in per_year(pot_curve, POT).items()},
                "vm_parent": {y: round(v * 100, 2)
                              for y, v in per_year(vmp["curve"],
                                                   POT).items()},
                "mb_parent": {y: round(v * 100, 2)
                              for y, v in per_year(mbp.equity_curve,
                                                   POT).items()},
                "etf_parent": {y: round(v * 100, 2)
                               for y, v in per_year(etfp["curve"],
                                                    POT).items()},
            },
        }
        out[wname] = w
        print(f"COMBO      final=${w['combo_final']:.2f} "
              f"({w['combo_ret_pct']:+.2f}%) maxDD={w['combo_max_dd_pct']:.2f}% "
              f"halt={w['combo_halt']} placebo beaten={beaten}/20 "
              f"median=${dist['median']:.2f}", flush=True)
        print(f"VM parent  final=${w['vm_parent_final_mtm']:.2f} MtM / "
              f"${w['vm_parent_final_postliq']:.2f} post-liq "
              f"maxDD={w['vm_parent_max_dd_pct']:.2f}%", flush=True)
        print(f"MB parent  final=${w['mb_parent_final']:.2f} "
              f"maxDD={w['mb_parent_max_dd_pct']:.2f}%", flush=True)
        print(f"ETF parent final=${w['etf_parent_final_nofloor']:.2f} "
              f"(no-floor) maxDD={w['etf_parent_max_dd_pct']:.2f}%", flush=True)
        print(f"SPY net    vm-basis=${w['spy_net_final_vm_basis']:.2f} "
              f"mb-basis=${w['spy_net_final_mb_basis']:.2f}", flush=True)
        print(f"correlations: {corrs}", flush=True)

    # ---------------- walk-forward folds (fresh pot per year) -------------
    print("\n===== walk-forward folds =====", flush=True)
    folds = []
    for y in range(2020, 2027):
        fs = f"{y}-01-01"
        fe = "2026-11-20" if y == 2026 else f"{y}-12-31"
        f_vm, _ = sleeve_vm(pb, eq_rows, sh_rows, fs, fe)
        f_mb, _ = sleeve_mb(mkt, fs, fe)
        f_etf, _ = sleeve_etf(fs, fe)
        _, finfo = blend3([f_vm, f_mb, f_etf])
        fspy, _ = vm.spy_net(pb, fs, fe, 100)
        row = {"year": y, "start": fs, "end": fe,
               "final": round(finfo["final"], 2),
               "return_pct": round(finfo["final"] / POT * 100 - 100, 2),
               "spy_net_final": round(fspy, 2),
               "spy_return_pct": round(fspy / POT * 100 - 100, 2),
               "beat_spy": finfo["final"] > fspy,
               "max_dd_pct": round(finfo["max_dd"] * 100, 2),
               "halt": finfo["halt"]}
        folds.append(row)
        print(f"FOLD {y}: COMBO ${row['final']:,.2f} "
              f"({row['return_pct']:+.2f}%) vs SPY ${fspy:,.2f} "
              f"({row['spy_return_pct']:+.2f}%) beat={row['beat_spy']} "
              f"maxDD={row['max_dd_pct']:.2f}% halt={row['halt']}",
              flush=True)
    wins = sum(1 for f in folds if f["beat_spy"])
    out["folds"] = folds
    out["fold_record"] = f"{wins} wins, {len(folds) - wins} losses vs SPY"
    print(f"fold record: {out['fold_record']}", flush=True)

    with open(os.path.join(HERE, "grand-combination-results.json"),
              "w") as f:
        json.dump(out, f, indent=1)
    print("\nsaved grand-combination-results.json")


if __name__ == "__main__":
    main()
