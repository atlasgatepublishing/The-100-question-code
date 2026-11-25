#!/usr/bin/env python3
"""
THE THREE BIGGEST, COMBINED — value+momentum x Lazy Prices x N-F3
"Paying in Stock", one $100 pot, three equal sleeves — Terry's AI
stock app. Simulation only.

TERRY'S REQUEST (2026-11-21): do NOT mix two — mix the THREE biggest:
the champion (value+momentum), Lazy Prices (the second promoted
engine, the judging-years leader), and N-F3 "Paying in Stock" (the
invented candidate). Run it under Terry's rules, one clean shot.

SPEC (frozen, mirroring the program's prior combination tests — the
winners'-blend / two-way-combo construction):
  - One $100 pot, split in equal thirds ($33.33 each): one third runs
    value+momentum EXACTLY as promoted (value-momentum-plainfloor.py,
    imported verbatim), one third runs Lazy Prices EXACTLY as promoted
    (lazy-prices.py, imported verbatim), one third runs N-F3 EXACTLY
    as frozen (novel-f3-paying-in-stock.py, imported verbatim: TTM
    ShareBasedCompensation / TTM revenue, ACCEL vs the same quarter a
    year earlier, rank ascending, quarterly top-5).
  - Each sleeve is its own sub-pot on the shared quarterly schedule
    with champion mechanics (all three engines select on the first
    trading day of Jan/Apr/Jul/Oct — verified in-run: the script
    asserts the selection-date lists are identical), same costs inside
    each engine (0.10%/side + $0.01/sell).
  - At each quarterly selection date (close), the sleeve weights are
    reset to equal thirds of the pot: the overweight sleeves are
    trimmed pro-rata and the proceeds buy into the underweight
    sleeves, charged at the engines' normal cost schedule (0.10% on
    the sale + 0.10% on the purchase + $0.01 x 5 sell orders for each
    trimmed sleeve). The inception selection date is excluded (the pot
    starts in equal thirds).
  - Pot-level protection: Terry's rules — the PLAIN -15% floor only
    ($85 on the $100 pot), NO ladder, NO restart, NO sleeve-level
    floor. If the pot closes at/below $85 the run ends (liquidation
    approximated at the next day's close less 0.10% and $0.15 of sell
    fees — three sleeves x 5 positions x $0.01; documented
    approximation, as in the prior combos).
  - Windows: CONTINUOUS 2019-01-02 -> 2026-11-20 and VALIDATION
    2023-01-03 -> 2026-11-20, $100 pots. Plus fresh-pot calendar-year
    folds 2020-2026 vs SPY (each parent's own fold convention).
  - Placebos: 20 seeds (1..20). For each seed, ALL THREE sleeves draw
    random picks from their own eligible pools on the identical dates
    with identical mechanics, and the three placebo sleeves are
    combined with the identical quarterly-reset machinery and pot
    floor.

PRE-REGISTERED ADOPTION BAR (written before any result):
  The combination must beat ALL THREE parents on BOTH windows —
    continuous:  > $544.47 (V+M) AND > $504.34 (Lazy) AND > $505.43 (NF3)
    validation:  > $288.05 (V+M) AND > $324.12 (Lazy) AND > $289.53 (NF3)
  Anything less is dilution and is reported as such. Because one
  sleeve (N-F3) is an invented-in-2026 rule, even a full pass is
  CANDIDATE-grade only: only the forward paper trial can adopt it.

PROGRAM PRIOR (stated before the run): all five prior combinations
diluted their better parent on at least one window — winners' blend
$400.84, grand combination $306.56 (the previous THREE-way, and the
worst dilution of all), V+M + ETF trend $320.97, V+M x Lazy $540.72
(missed the champion by $3.75), V+M x N-F3 $532.39 (missed the
champion by $12.08), all continuous-window finals against the
champion's $544.47. The prior for this test is dilution again.

METHOD — engines verbatim, combined at the equity-curve level (the
winners'-blend / two-way-combo method):
  Each sleeve is run standalone on its $33.33 third with its internal
  floor disabled, producing a daily close-equity curve. The combined
  pot is the sum of the three sleeve values; at each quarterly
  selection-date close the sleeves are rescaled to equal thirds of
  the pot less the transfer cost. Documented approximations, identical
  in kind to the precedents: (1) after a rescale a sleeve's subsequent
  path follows its standalone $33.33 curve, so the $0.01 fixed sell
  fees inside the engines are charged at the standalone trajectory
  rather than the rescaled one — a pennies-level effect; (2) the
  quarterly transfer is charged at the engines' cost schedule on the
  transferred value rather than by re-trading every share; (3) the
  headline final is the end-of-window post-liquidation value (final
  close x (1 - 0.10%) - $0.15 of sell fees, three sleeves x five
  positions), the same basis as the parents' published finals; the
  mark-to-market final is reported alongside.
  Parents are RECOMPUTED inside this run over the identical windows
  under the identical protection rule (plain -15% floor) for exact
  comparability; the as-published figures are the integrity targets.

INTEGRITY CHECKS (run first, abort on failure):
  - Value+momentum plain floor, $100 -> $544.47 / $288.05.
  - Lazy Prices, $100 -> $504.34 / $324.12.
  - N-F3, $100 -> $505.43 / $289.53.
  - SPY buy-hold net -> $313.62 / $187.77.

Data: the parent studies' own caches, read-only (Yahoo bars and EDGAR
companyfacts under ~/workspace/stock-app/backtests/v4/; the Lazy
Prices 10-K corpus and similarities under
~/workspace/stock-app/backtests/v7/gap-a5-lazy-prices/data/).
"""

import importlib.util
import json
import math
import os
import random
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.expanduser("~/workspace/stock-app/backtests/v4")
LZ_DIR = os.path.expanduser(
    "~/workspace/stock-app/backtests/v7/gap-a5-lazy-prices")
V8 = os.path.expanduser("~/workspace/stock-app/backtests/v8")


def _load(modname, path):
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vm = _load("value_momentum_plainfloor",
           os.path.join(V4, "value-momentum-plainfloor.py"))
lz = _load("lazy_prices", os.path.join(LZ_DIR, "lazy-prices.py"))
nf3 = _load("nf3_paying_in_stock",
            os.path.join(V8, "novel-f3-paying-in-stock",
                         "novel-f3-paying-in-stock.py"))

POT = 100.0
FLOOR = 85.0
THIRD = POT / 3.0
SLEEVES = ["vm", "lz", "nf3"]
WINDOWS = {
    "continuous": ("2019-01-02", "2026-11-20"),
    "validation": ("2023-01-03", "2026-11-20"),
}
PUBLISHED = {
    "vm": {"continuous": 544.47, "validation": 288.05},
    "lz": {"continuous": 504.34, "validation": 324.12},
    "nf3": {"continuous": 505.43, "validation": 289.53},
    "spy": {"continuous": 313.62, "validation": 187.77},
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
    for y in sorted({d[:4] for d, _ in curve}):
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


def curve_diag(curve, floor=FLOOR):
    worst_d, worst_v = min(curve, key=lambda kv: kv[1])
    covid = [(d, v) for d, v in curve if "2020-02-01" <= d <= "2020-04-30"]
    cw = min(covid, key=lambda kv: kv[1]) if covid else (None, None)
    return {"worst_close": round(worst_v, 2), "worst_close_date": worst_d,
            "worst_close_above_floor": round(worst_v - floor, 2),
            "max_drawdown_pct": round(max_dd(curve) * 100, 2),
            "covid_worst_close": round(cw[1], 2) if cw[1] else None,
            "covid_worst_date": cw[0]}


def _pct(sorted_vals, q):
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if lo == hi:
        return sorted_vals[lo]
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


# --------------------------------------------------------------------------
# The combination: three sleeve equity curves -> one pot, quarterly resets
# --------------------------------------------------------------------------
def blend_curves(curves, reset_dates, pot0=POT, floor=FLOOR):
    """curves: list of standalone $33.33 sleeve daily close-equity
    curves (one per sleeve, in SLEEVES order). reset_dates: the
    window's quarterly selection dates; the first (inception) is
    skipped — the pot starts in equal thirds. Returns (pot_curve,
    info). Pot-level plain floor checked on every close."""
    dicts = [dict(c) for c in curves]
    first = max(min(d) for d in dicts)
    last = min(max(d) for d in dicts)
    all_dates = set()
    for d in dicts:
        all_dates |= set(d)
    dates = sorted(d for d in all_dates if first <= d <= last)
    resets = set(reset_dates[1:]) if reset_dates else set()

    scales = [1.0, 1.0, 1.0]
    lasts = [None, None, None]
    pot_curve = []
    rebalances = []
    transfer_costs = 0.0
    halt = None
    final = None
    for idx, d in enumerate(dates):
        for i in range(3):
            if d in dicts[i]:
                lasts[i] = dicts[i][d]
        vals = [scales[i] * lasts[i] for i in range(3)]
        tot = sum(vals)
        if d in resets:
            target = tot / 3.0
            transfer = sum(max(v - target, 0.0) for v in vals)
            n_trim = sum(1 for v in vals if v > target + 1e-9)
            cost = transfer * 0.002 + 0.05 * n_trim  # 0.10% sell +
            # 0.10% buy on the moved value + $0.01 x 5 sell orders per
            # trimmed sleeve
            tot -= cost
            transfer_costs += cost
            scales = [(tot / 3.0) / lasts[i] for i in range(3)]
            rebalances.append({"date": d,
                               "vm_before": round(vals[0], 2),
                               "lz_before": round(vals[1], 2),
                               "nf3_before": round(vals[2], 2),
                               "transfer": round(transfer, 2),
                               "cost": round(cost, 2)})
            vals = [tot / 3.0] * 3
        pot_curve.append((d, tot))
        if tot <= floor and idx < len(dates) - 1:
            halt = d
            nd = dates[idx + 1]
            nxt = 0.0
            for i in range(3):
                nb = dicts[i].get(nd, lasts[i])
                nxt += scales[i] * nb
            final = nxt * (1 - 0.001) - 0.15
            break
    mtm = pot_curve[-1][1]
    if final is None:
        # end of window: liquidate at the final close, parents' basis
        final = mtm * (1 - 0.001) - 0.15
    info = {"halt": halt, "final": final, "final_mtm": mtm,
            "transfer_costs": transfer_costs, "rebalances": rebalances,
            "max_dd": max_dd(pot_curve)}
    return pot_curve, info


# --------------------------------------------------------------------------
# Parent data assembly — each parent study's own assembly, verbatim
# --------------------------------------------------------------------------
def build_books():
    """One pass over the champion cache: builds the V+M rows, the N-F3
    facts (same companyfacts payloads), and both PriceBooks."""
    ciks = vm.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}
    equity_rows, shares_rows, facts_by_ticker = {}, {}, {}
    for t in vm.UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts = vm.get_companyfacts(cik)
        facts_by_ticker[t] = facts
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
    pb_vm = vm.PriceBook(bars)

    signals, census = lz.build_signals()
    bars_lz = {}
    for t in lz.UNIVERSE + ["SPY"]:
        bars_lz[t] = lz.get_prices(t)
    pb_lz = lz.PriceBook(bars_lz)
    return pb_vm, equity_rows, shares_rows, facts_by_ticker, pb_lz, \
        signals, census


# --------------------------------------------------------------------------
def run_combo(pb_vm, eq_rows, sh_rows, facts, pb_lz, signals, sd, ed,
              vm_rng=None, lz_rng=None, nf3_rng=None, record=False):
    """One combined pot over [sd, ed]. Sleeves at $33.33, floors
    disabled; quarterly equal-third resets; one plain -15% floor on
    the combined pot."""
    vms = vm.run_pot(pb_vm, eq_rows, sh_rows, sd, ed, THIRD, 0.0, [],
                     placebo_rng=vm_rng, quiet=True, record_pools=record)
    lzs = lz.run_pot(pb_lz, signals, sd, ed, start_cash=THIRD,
                     floor0=0.0, placebo_rng=lz_rng, record_pools=record)
    stats = {"direct": 0, "derived": 0}
    f3s = nf3.run_pot(pb_vm, facts, sd, ed, THIRD, 0.0,
                      placebo_rng=nf3_rng, quiet=True, stats=stats)
    sel_vm = vm.quarter_selection_dates(pb_vm, sd, ed)
    sel_lz = lz.quarter_selection_dates(pb_lz, sd, ed)
    assert sel_vm == sel_lz, f"selection dates diverge: {sel_vm} vs {sel_lz}"
    curve, info = blend_curves([vms["curve"], lzs["curve"], f3s["curve"]],
                               sel_vm)
    info["sleeve_costs"] = vms["costs"] + lzs["costs"] + f3s["costs"]
    info["vm_sleeve_final_mtm"] = vms["curve"][-1][1]
    info["lz_sleeve_final_mtm"] = lzs["curve"][-1][1]
    info["nf3_sleeve_final_mtm"] = f3s["curve"][-1][1]
    info["vm_sleeve"] = vms
    info["lz_sleeve"] = lzs
    info["nf3_sleeve"] = f3s
    info["curve"] = curve
    return info


def picks_by_date(sleeve_result, kind):
    if kind == "lz":
        return {p["date"]: set(p["picks"]) for p in sleeve_result["pools"]}
    return {d: set(p) for d, _pool, p in sleeve_result["pools"]}


def main():
    out = {"spec": "equal-thirds V+M + Lazy Prices + N-F3, quarterly "
                   "equal-third sleeve reset at selection dates, plain "
                   "-15% pot floor (Terry's rules, no restart), $100 pots",
           "windows": WINDOWS,
           "adoption_bar": {
               "continuous": "beat ALL THREE parents: V+M $544.47, "
                             "Lazy Prices $504.34, N-F3 $505.43",
               "validation": "beat ALL THREE parents: V+M $288.05, "
                             "Lazy Prices $324.12, N-F3 $289.53"},
           "program_prior": "all five prior combinations diluted their "
                            "better parent on at least one window "
                            "(winners' blend $400.84, grand combination "
                            "$306.56 — the previous three-way and the "
                            "worst dilution of all, V+M+trend $320.97, "
                            "V+M x Lazy $540.72, V+M x N-F3 $532.39, "
                            "all continuous)"}

    print("loading books (champion cache + lazy signals)...", flush=True)
    (pb_vm, eq_rows, sh_rows, facts, pb_lz, signals, census) = \
        build_books()

    # ---------------- integrity checks ----------------------------------
    checks = {}
    for wname, (sd, ed) in WINDOWS.items():
        r = vm.run_pot(pb_vm, eq_rows, sh_rows, sd, ed, POT, FLOOR, [],
                       quiet=True)
        print(f"CHECK vm plainfloor {wname} $100: ${r['final']:.2f} "
              f"(published ${PUBLISHED['vm'][wname]})", flush=True)
        assert abs(r["final"] - PUBLISHED["vm"][wname]) < 0.05
        checks[f"vm_{wname}"] = round(r["final"], 2)
        r = lz.run_pot(pb_lz, signals, sd, ed)
        print(f"CHECK lazy {wname} $100: ${r['final']:.2f} "
              f"(published ${PUBLISHED['lz'][wname]})", flush=True)
        assert abs(r["final"] - PUBLISHED["lz"][wname]) < 0.05
        checks[f"lz_{wname}"] = round(r["final"], 2)
        stats = {"direct": 0, "derived": 0}
        r = nf3.run_pot(pb_vm, facts, sd, ed, POT, FLOOR, quiet=True,
                        stats=stats)
        print(f"CHECK nf3 {wname} $100: ${r['final']:.2f} "
              f"(published ${PUBLISHED['nf3'][wname]})", flush=True)
        assert abs(r["final"] - PUBLISHED["nf3"][wname]) < 0.05
        checks[f"nf3_{wname}"] = round(r["final"], 2)
        s, _ = vm.spy_net(pb_vm, sd, ed, POT)
        print(f"CHECK spy {wname} $100: ${s:.2f} "
              f"(published ${PUBLISHED['spy'][wname]})", flush=True)
        assert abs(s - PUBLISHED["spy"][wname]) < 0.05
        checks[f"spy_{wname}"] = round(s, 2)
    out["integrity_checks"] = checks
    print("integrity checks passed", flush=True)

    # ---------------- main windows ---------------------------------------
    for wname, (sd, ed) in WINDOWS.items():
        # parents alone at $100, plain floor (recomputed, identical basis)
        vmp = vm.run_pot(pb_vm, eq_rows, sh_rows, sd, ed, POT, FLOOR, [],
                         quiet=True)
        lzp = lz.run_pot(pb_lz, signals, sd, ed)
        stats = {"direct": 0, "derived": 0}
        f3p = nf3.run_pot(pb_vm, facts, sd, ed, POT, FLOOR, quiet=True,
                          stats=stats)
        spy, _ = vm.spy_net(pb_vm, sd, ed, POT)

        # the combination, ranked
        combo = run_combo(pb_vm, eq_rows, sh_rows, facts, pb_lz, signals,
                          sd, ed, record=True)
        curve = combo["curve"]

        # pairwise sleeve monthly-return correlations (ranked sleeves)
        mrs = {"vm": monthly_returns(combo["vm_sleeve"]["curve"]),
               "lz": monthly_returns(combo["lz_sleeve"]["curve"]),
               "nf3": monthly_returns(combo["nf3_sleeve"]["curve"])}
        corrs = {}
        for a, b in (("vm", "lz"), ("vm", "nf3"), ("lz", "nf3")):
            common = sorted(set(mrs[a]) & set(mrs[b]))
            corrs[f"{a}_{b}"] = {
                "r": round(pearson([mrs[a][m] for m in common],
                                   [mrs[b][m] for m in common]), 3),
                "months": len(common)}

        # pairwise pick overlaps between the ranked sleeves
        pk = {"vm": picks_by_date(combo["vm_sleeve"], "vm"),
              "lz": picks_by_date(combo["lz_sleeve"], "lz"),
              "nf3": picks_by_date(combo["nf3_sleeve"], "nf3")}
        overlaps = {}
        for a, b in (("vm", "lz"), ("vm", "nf3"), ("lz", "nf3")):
            ov = {d: sorted(pk[a][d] & pk[b][d])
                  for d in sorted(set(pk[a]) & set(pk[b]))}
            counts = [len(v) for v in ov.values()]
            overlaps[f"{a}_{b}"] = {
                "by_date": ov,
                "mean": (round(sum(counts) / len(counts), 2)
                         if counts else None)}
        all3 = {d: sorted(pk["vm"][d] & pk["lz"][d] & pk["nf3"][d])
                for d in sorted(set(pk["vm"]) & set(pk["lz"])
                                 & set(pk["nf3"]))}
        all3_counts = [len(v) for v in all3.values()]
        overlaps["all_three"] = {
            "by_date": all3,
            "mean": (round(sum(all3_counts) / len(all3_counts), 2)
                     if all3_counts else None)}

        # placebos: all three sleeves random within their own pools
        twins = []
        for seed in PLACEBO_SEEDS:
            tc = run_combo(pb_vm, eq_rows, sh_rows, facts, pb_lz, signals,
                           sd, ed,
                           vm_rng=random.Random(seed),
                           lz_rng=random.Random(seed),
                           nf3_rng=random.Random(seed))
            twins.append({"seed": seed, "final": round(tc["final"], 2),
                          "final_mtm": round(tc["final_mtm"], 2),
                          "halt": tc["halt"],
                          "costs": round(tc["sleeve_costs"]
                                         + tc["transfer_costs"], 2)})
            print(f"  placebo seed {seed}: ${tc['final']:.2f} "
                  f"halt={tc['halt']}", flush=True)
        finals = sorted(tw["final"] for tw in twins)
        beats = sum(1 for x in finals if combo["final"] > x)

        parents = {"vm": vmp, "lz": lzp, "nf3": f3p}
        w = {
            "combo_final": round(combo["final"], 2),
            "combo_final_mtm": round(combo["final_mtm"], 2),
            "combo_ret_pct": round((combo["final"] / POT - 1) * 100, 2),
            "combo_cagr_pct": round(cagr(combo["final"], POT, sd, ed)
                                    * 100, 2),
            "combo_max_dd_pct": round(combo["max_dd"] * 100, 2),
            "combo_halt": combo["halt"],
            "combo_diag": curve_diag(curve),
            "combo_costs_sleeves": round(combo["sleeve_costs"], 2),
            "combo_costs_transfers": round(combo["transfer_costs"], 2),
            "combo_rebalances": combo["rebalances"],
            "vm_sleeve_final_mtm_33": round(combo["vm_sleeve_final_mtm"], 2),
            "lz_sleeve_final_mtm_33": round(combo["lz_sleeve_final_mtm"], 2),
            "nf3_sleeve_final_mtm_33": round(combo["nf3_sleeve_final_mtm"],
                                             2),
            "spy_net_final": round(spy, 2),
            "sleeve_corr_monthly": corrs,
            "pick_overlaps": overlaps,
            "placebo": {"finals_sorted": finals,
                        "median": round(_pct(finals, 0.5), 2),
                        "best": finals[-1], "worst": finals[0],
                        "ranked_beats": beats,
                        "twin_halts": sum(1 for tw in twins if tw["halt"]),
                        "twins": twins},
            "per_year": {
                "combo": {y: round(v * 100, 2)
                          for y, v in per_year(curve, POT).items()},
            },
        }
        for name in SLEEVES:
            p = parents[name]
            w[f"{name}_parent_final"] = round(p["final"], 2)
            w[f"{name}_parent_halt"] = p["halted"]
            w[f"{name}_parent_costs"] = round(p["costs"], 2)
            w[f"beats_{name}_parent"] = \
                combo["final"] > PUBLISHED[name][wname]
            w["per_year"][f"{name}_parent"] = {
                y: round(v * 100, 2)
                for y, v in per_year(p["curve"], POT).items()}
        w["beats_all_three_parents"] = all(
            w[f"beats_{n}_parent"] for n in SLEEVES)
        out[wname] = w
        print(f"\n== {wname} {sd} -> {ed} ==", flush=True)
        print(f"COMBO      final=${w['combo_final']:.2f} "
              f"({w['combo_ret_pct']:+.2f}%) MtM=${w['combo_final_mtm']:.2f} "
              f"maxDD={w['combo_max_dd_pct']:.2f}% halt={w['combo_halt']}",
              flush=True)
        for name in SLEEVES:
            print(f"{name.upper():4s} parent final="
                  f"${w[f'{name}_parent_final']:.2f} "
                  f"halt={w[f'{name}_parent_halt']} "
                  f"beats={w[f'beats_{name}_parent']}", flush=True)
        print(f"SPY net    final=${w['spy_net_final']:.2f}", flush=True)
        print(f"placebo: median=${w['placebo']['median']:.2f} "
              f"best=${w['placebo']['best']:.2f} "
              f"ranked beats {beats}/20, twin halts "
              f"{w['placebo']['twin_halts']}", flush=True)
        print(f"BAR: beats ALL THREE="
              f"{w['beats_all_three_parents']} -> "
              f"{'PASS' if w['beats_all_three_parents'] else 'DILUTION'}",
              flush=True)

    # ---------------- calendar-year folds --------------------------------
    folds = []
    for y in range(2020, 2027):
        sd, ed = f"{y}-01-02", f"{y}-12-31"
        if y == 2026:
            ed = "2026-11-20"
        spy, _ = vm.spy_net(pb_vm, sd, ed, POT)
        fc = run_combo(pb_vm, eq_rows, sh_rows, facts, pb_lz, signals,
                       sd, ed)
        fv = vm.run_pot(pb_vm, eq_rows, sh_rows, sd, ed, POT, FLOOR, [],
                        quiet=True)
        fl = lz.run_pot(pb_lz, signals, sd, ed)
        stats = {"direct": 0, "derived": 0}
        ff = nf3.run_pot(pb_vm, facts, sd, ed, POT, FLOOR, quiet=True,
                         stats=stats)
        folds.append({
            "year": y, "combo_final": round(fc["final"], 2),
            "combo_ret_pct": round(fc["final"] - POT, 2),
            "combo_halt": fc["halt"],
            "vm_final": round(fv["final"], 2),
            "vm_halted": fv["halted"],
            "lz_final": round(fl["final"], 2),
            "lz_halted": fl["halted"],
            "nf3_final": round(ff["final"], 2),
            "nf3_halted": ff["halted"],
            "spy_net": round(spy, 2),
            "combo_beat_spy": fc["final"] > spy,
            "combo_beat_all_parents": (fc["final"] > fv["final"]
                                       and fc["final"] > fl["final"]
                                       and fc["final"] > ff["final"])})
        print(f"fold {y}: combo=${fc['final']:.2f} halt={fc['halt']} | "
              f"VM=${fv['final']:.2f} LZ=${fl['final']:.2f} "
              f"NF3=${ff['final']:.2f} SPY=${spy:.2f}", flush=True)

    def compound(rows, key):
        c = 100.0
        for r in rows:
            c *= r[key] / 100.0
        return round(c, 2)
    out["folds"] = {
        "folds": folds,
        "combo_record_vs_spy":
            (f"{sum(1 for f in folds if f['combo_beat_spy'])} wins, "
             f"{sum(1 for f in folds if not f['combo_beat_spy'])} losses"),
        "combo_fold_compounded": compound(folds, "combo_final"),
        "vm_fold_compounded": compound(folds, "vm_final"),
        "lz_fold_compounded": compound(folds, "lz_final"),
        "nf3_fold_compounded": compound(folds, "nf3_final"),
        "spy_fold_compounded": compound(folds, "spy_net"),
        "published_reference": {"vm": 313.01, "lz": 309.39, "spy": 227.34}}

    verdict = (out["continuous"]["beats_all_three_parents"]
               and out["validation"]["beats_all_three_parents"])
    out["verdict"] = ("CANDIDATE-GRADE PASS — beats all three parents "
                      "on both windows (adoption still requires the "
                      "forward paper trial: one sleeve is invented)"
                      if verdict else
                      "NOT ADOPTED — dilution (fails the pre-registered "
                      "bar: must beat ALL THREE parents on BOTH windows)")
    print(f"\nVERDICT: {out['verdict']}", flush=True)

    with open(os.path.join(HERE, "combo-three-way-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("saved combo-three-way-results.json")


if __name__ == "__main__":
    main()
