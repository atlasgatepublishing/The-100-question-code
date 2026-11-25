#!/usr/bin/env python3
"""
THE TWO PROMOTED ENGINES, COMBINED — Terry's AI stock app, simulation only.

QUESTION (Terry's request, 2026-11-21): the program now has TWO promoted
engines — honest value+momentum (the champion: quarterly top-5 by average
percentile rank of book-to-market and 12-1 momentum, EDGAR point-in-time)
and Lazy Prices (Cohen-Malloy-Nguyen 2020: quarterly top-5 by whole-document
10-K cosine similarity vs the prior year — the "non-changers"). Each made
the most money ALONE, on different windows (V+M leads the long run, Lazy
Prices leads the judging years). Does running them as two 50/50 sleeves of
ONE $100 pot make MORE than either alone, or do they dilute each other?

SPEC (frozen, mirroring the winners'-blend precedent):
  - One $100 pot, split 50/50: $50 to the value+momentum engine
    (value-momentum-plainfloor.py, imported verbatim), $50 to the Lazy
    Prices engine (lazy-prices.py, imported verbatim). Each sleeve runs
    its own rules on its half: same universes, signals, quarterly
    selection dates (both parents select on the first trading day of
    Jan/Apr/Jul/Oct, so the dates align), same costs
    (0.10%/side + $0.01/sell inside each engine).
  - At each quarterly selection date (close), the sleeve weights are
    reset to 50/50 of the pot: the overweight sleeve is trimmed pro-rata
    and the proceeds buy into the underweight sleeve, charged at the
    engines' normal cost schedule (0.10% on the sale + 0.10% on the
    purchase + $0.01 x 5 sell orders for the trimmed sleeve's positions).
    The inception selection date is excluded (the pot starts 50/50).
  - Pot-level protection: the PLAIN -15% floor only ($85 on the $100
    pot). No ladder, and NO sleeve-level floor — a sleeve can only be
    stopped by the pot floor. If the pot closes at/below $85 the run
    ends (liquidation approximated at the next day's close less 0.10%
    and $0.10 of sell fees; documented approximation, as in the
    winners' blend).
  - Windows: CONTINUOUS 2019-01-02 -> 2026-11-20 and VALIDATION
    2023-01-03 -> 2026-11-20, $100 pots. Plus fresh-pot calendar-year
    folds 2020-2026 vs SPY (each parent's own fold convention).
  - Placebos: 20 seeds (1..20). For each seed, BOTH sleeves draw random
    picks from their own eligible pools on the identical dates with
    identical mechanics, and the two placebo sleeves are combined with
    the identical quarterly-reset machinery and pot floor.

PRE-REGISTERED ADOPTION BAR (written before any result):
  The combination must beat BOTH parents on BOTH windows —
    continuous:  > $544.47 (V+M) AND > $504.34 (Lazy Prices)
    validation:  > $288.05 (V+M) AND > $324.12 (Lazy Prices)
  Anything less is dilution and is reported as such.

PROGRAM PRIOR (stated before the run): every combination tested so far
diluted the champion — winners' blend $400.84, grand combination
$306.56, V+M + ETF trend $320.97, all continuous-window finals against
the champion's $544.47. The prior for this test is dilution again.

METHOD — engines verbatim, combined at the equity-curve level (the
winners'-blend method):
  Each sleeve is run standalone on its $50 half with its internal floor
  disabled (protection lives at pot level only), producing a daily
  close-equity curve. The combined pot is the sum of the two sleeve
  values; at each quarterly selection-date close the sleeves are
  rescaled to 50/50 of the pot less the transfer cost. Documented
  approximations: (1) after a rescale a sleeve's subsequent path follows
  its standalone $50 curve, so the $0.01 fixed sell fees inside the
  engines are charged at the standalone trajectory rather than the
  rescaled one — a pennies-level effect; (2) the quarterly transfer is
  charged at the engines' cost schedule on the transferred value rather
  than by re-trading every share; (3) the headline final is the
  end-of-window post-liquidation value (final close x (1 - 0.10%) -
  $0.10 of sell fees), the same basis as both parents' published finals;
  the mark-to-market final is reported alongside.
  Parents are RECOMPUTED inside this run over the identical windows
  under the identical protection rule (plain -15% floor) for exact
  comparability; the as-published figures are the integrity targets.

INTEGRITY CHECKS (run first, abort on failure):
  - Value+momentum plain floor, $100 -> $544.47 (continuous) and
    $288.05 (validation).
  - Lazy Prices, $100 -> $504.34 (continuous) and $324.12 (validation).
  - SPY buy-hold net -> $313.62 (continuous) and $187.77 (validation).

Data: the parent studies' own caches, read-only (Yahoo bars and EDGAR
companyfacts under ~/workspace/stock-app/backtests/v4/; the Lazy Prices
10-K corpus and similarities under
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


def _load(modname, path):
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vm = _load("value_momentum_plainfloor",
           os.path.join(V4, "value-momentum-plainfloor.py"))
lz = _load("lazy_prices", os.path.join(LZ_DIR, "lazy-prices.py"))

POT = 100.0
FLOOR = 85.0
HALF = 50.0
WINDOWS = {
    "continuous": ("2019-01-02", "2026-11-20"),
    "validation": ("2023-01-03", "2026-11-20"),
}
PUBLISHED = {
    "vm": {"continuous": 544.47, "validation": 288.05},
    "lz": {"continuous": 504.34, "validation": 324.12},
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
# The combination: two sleeve equity curves -> one pot, quarterly resets
# --------------------------------------------------------------------------
def blend_curves(curveA, curveB, reset_dates, pot0=POT, floor=FLOOR):
    """curveA/curveB: standalone $50 sleeve daily close-equity curves.
    reset_dates: the window's quarterly selection dates; the first
    (inception) is skipped — the pot starts 50/50. Returns
    (pot_curve, info). Pot-level plain floor checked on every close."""
    A = dict(curveA)
    B = dict(curveB)
    first = max(min(A), min(B))
    last = min(max(A), max(B))
    dates = sorted(d for d in (set(A) | set(B)) if first <= d <= last)
    resets = set(reset_dates[1:]) if reset_dates else set()

    scaleA = scaleB = 1.0
    lastA = lastB = None
    pot_curve = []
    rebalances = []
    transfer_costs = 0.0
    halt = None
    final = None
    for idx, d in enumerate(dates):
        if d in A:
            lastA = A[d]
        if d in B:
            lastB = B[d]
        va = scaleA * lastA
        vb = scaleB * lastB
        tot = va + vb
        if d in resets:
            transfer = abs(va - vb) / 2.0
            cost = transfer * 0.002 + 0.05      # 0.10% sell + 0.10% buy
            #                               + $0.01 x 5 sell orders
            tot -= cost
            transfer_costs += cost
            scaleA = (tot / 2.0) / lastA
            scaleB = (tot / 2.0) / lastB
            rebalances.append({"date": d, "vm_before": round(va, 2),
                               "lz_before": round(vb, 2),
                               "transfer": round(transfer, 2),
                               "cost": round(cost, 2)})
            va = vb = tot / 2.0
        pot_curve.append((d, tot))
        if tot <= floor and idx < len(dates) - 1:
            halt = d
            nd = dates[idx + 1]
            na = A.get(nd, lastA)
            nb = B.get(nd, lastB)
            nxt = scaleA * na + scaleB * nb
            final = nxt * (1 - 0.001) - 0.10
            break
    mtm = pot_curve[-1][1]
    if final is None:
        # end of window: liquidate at the final close, parents' basis
        final = mtm * (1 - 0.001) - 0.10
    info = {"halt": halt, "final": final, "final_mtm": mtm,
            "transfer_costs": transfer_costs, "rebalances": rebalances,
            "max_dd": max_dd(pot_curve)}
    return pot_curve, info


# --------------------------------------------------------------------------
# Parent data assembly — each parent study's own assembly, verbatim
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


def build_lz_book():
    signals, census = lz.build_signals()
    bars = {}
    for t in lz.UNIVERSE + ["SPY"]:
        bars[t] = lz.get_prices(t)
    return lz.PriceBook(bars), signals, census


# --------------------------------------------------------------------------
def run_combo(pb_vm, eq_rows, sh_rows, pb_lz, signals, sd, ed,
              vm_rng=None, lz_rng=None, record=False):
    """One combined pot over [sd, ed]. Sleeves at $50, floors disabled;
    quarterly 50/50 resets; one plain -15% floor on the combined pot."""
    vms = vm.run_pot(pb_vm, eq_rows, sh_rows, sd, ed, HALF, 0.0, [],
                     placebo_rng=vm_rng, quiet=True, record_pools=record)
    lzs = lz.run_pot(pb_lz, signals, sd, ed, start_cash=HALF, floor0=0.0,
                     placebo_rng=lz_rng, record_pools=record)
    sel_vm = vm.quarter_selection_dates(pb_vm, sd, ed)
    sel_lz = lz.quarter_selection_dates(pb_lz, sd, ed)
    assert sel_vm == sel_lz, f"selection dates diverge: {sel_vm} vs {sel_lz}"
    curve, info = blend_curves(vms["curve"], lzs["curve"], sel_vm)
    info["sleeve_costs"] = vms["costs"] + lzs["costs"]
    info["vm_sleeve_final_mtm"] = vms["curve"][-1][1]
    info["lz_sleeve_final_mtm"] = lzs["curve"][-1][1]
    info["vm_sleeve"] = vms
    info["lz_sleeve"] = lzs
    info["curve"] = curve
    return info


def main():
    out = {"spec": "50/50 V+M + Lazy Prices, quarterly 50/50 sleeve reset "
                   "at selection dates, plain -15% pot floor, $100 pots",
           "windows": WINDOWS,
           "adoption_bar": {
               "continuous": "beat BOTH parents: V+M $544.47 and "
                             "Lazy Prices $504.34",
               "validation": "beat BOTH parents: V+M $288.05 and "
                             "Lazy Prices $324.12"},
           "program_prior": "every combination tested so far diluted "
                            "the champion (winners' blend $400.84, grand "
                            "combination $306.56, V+M+trend $320.97, all "
                            "continuous)"}

    print("loading value+momentum book (cache)...", flush=True)
    pb_vm, eq_rows, sh_rows = build_vm_book()
    print("loading lazy-prices signals + book (cache)...", flush=True)
    pb_lz, signals, census = build_lz_book()

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
        spy, _ = vm.spy_net(pb_vm, sd, ed, POT)

        # the combination, ranked
        combo = run_combo(pb_vm, eq_rows, sh_rows, pb_lz, signals, sd, ed,
                          record=True)
        curve = combo["curve"]

        # sleeve monthly-return correlation (ranked sleeves)
        mrA = monthly_returns(combo["vm_sleeve"]["curve"])
        mrB = monthly_returns(combo["lz_sleeve"]["curve"])
        common = sorted(set(mrA) & set(mrB))
        corr = pearson([mrA[m] for m in common], [mrB[m] for m in common])

        # pick overlap between the two ranked sleeves
        vm_picks = {d: set(p) for d, _pool, p in combo["vm_sleeve"]["pools"]}
        lz_picks = {p["date"]: set(p["picks"])
                    for p in combo["lz_sleeve"]["pools"]}
        overlap = {d: sorted(vm_picks[d] & lz_picks[d])
                   for d in sorted(set(vm_picks) & set(lz_picks))}
        overlap_counts = [len(v) for v in overlap.values()]

        # placebos: both sleeves random within their own pools
        twins = []
        for seed in PLACEBO_SEEDS:
            tc = run_combo(pb_vm, eq_rows, sh_rows, pb_lz, signals, sd, ed,
                           vm_rng=random.Random(seed),
                           lz_rng=random.Random(seed))
            twins.append({"seed": seed, "final": round(tc["final"], 2),
                          "final_mtm": round(tc["final_mtm"], 2),
                          "halt": tc["halt"],
                          "costs": round(tc["sleeve_costs"]
                                         + tc["transfer_costs"], 2)})
            print(f"  placebo seed {seed}: ${tc['final']:.2f} "
                  f"halt={tc['halt']}", flush=True)
        finals = sorted(tw["final"] for tw in twins)
        beats = sum(1 for x in finals if combo["final"] > x)

        bar_vm = PUBLISHED["vm"][wname]
        bar_lz = PUBLISHED["lz"][wname]
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
            "vm_sleeve_final_mtm_50": round(combo["vm_sleeve_final_mtm"], 2),
            "lz_sleeve_final_mtm_50": round(combo["lz_sleeve_final_mtm"], 2),
            "vm_parent_final": round(vmp["final"], 2),
            "vm_parent_halt": vmp["halted"],
            "vm_parent_costs": round(vmp["costs"], 2),
            "lz_parent_final": round(lzp["final"], 2),
            "lz_parent_halt": lzp["halted"],
            "lz_parent_costs": round(lzp["costs"], 2),
            "spy_net_final": round(spy, 2),
            "beats_vm_parent": combo["final"] > bar_vm,
            "beats_lz_parent": combo["final"] > bar_lz,
            "beats_both_parents": (combo["final"] > bar_vm
                                   and combo["final"] > bar_lz),
            "sleeve_corr_monthly": round(corr, 3),
            "sleeve_corr_months": len(common),
            "pick_overlap_by_date": overlap,
            "pick_overlap_mean": (round(sum(overlap_counts)
                                        / len(overlap_counts), 2)
                                  if overlap_counts else None),
            "placebo": {"finals_sorted": finals,
                        "median": round(_pct(finals, 0.5), 2),
                        "best": finals[-1], "worst": finals[0],
                        "ranked_beats": beats,
                        "twin_halts": sum(1 for tw in twins if tw["halt"]),
                        "twins": twins},
            "per_year": {
                "combo": {y: round(v * 100, 2)
                          for y, v in per_year(curve, POT).items()},
                "vm_parent": {y: round(v * 100, 2)
                              for y, v in per_year(vmp["curve"],
                                                   POT).items()},
                "lz_parent": {y: round(v * 100, 2)
                              for y, v in per_year(lzp["curve"],
                                                   POT).items()},
            },
        }
        out[wname] = w
        print(f"\n== {wname} {sd} -> {ed} ==", flush=True)
        print(f"COMBO      final=${w['combo_final']:.2f} "
              f"({w['combo_ret_pct']:+.2f}%) MtM=${w['combo_final_mtm']:.2f} "
              f"maxDD={w['combo_max_dd_pct']:.2f}% halt={w['combo_halt']} "
              f"corr={w['sleeve_corr_monthly']} "
              f"overlap={w['pick_overlap_mean']}/5", flush=True)
        print(f"VM parent  final=${w['vm_parent_final']:.2f} "
              f"halt={w['vm_parent_halt']}", flush=True)
        print(f"LZ parent  final=${w['lz_parent_final']:.2f} "
              f"halt={w['lz_parent_halt']}", flush=True)
        print(f"SPY net    final=${w['spy_net_final']:.2f}", flush=True)
        print(f"placebo: median=${w['placebo']['median']:.2f} "
              f"best=${w['placebo']['best']:.2f} "
              f"ranked beats {beats}/20, twin halts "
              f"{w['placebo']['twin_halts']}", flush=True)
        print(f"BAR: beats V+M={w['beats_vm_parent']} "
              f"beats LZ={w['beats_lz_parent']} "
              f"-> {'ADOPT' if w['beats_both_parents'] else 'DILUTION'}",
              flush=True)

    # ---------------- calendar-year folds --------------------------------
    folds = []
    for y in range(2020, 2027):
        sd, ed = f"{y}-01-02", f"{y}-12-31"
        if y == 2026:
            ed = "2026-11-20"
        spy, _ = vm.spy_net(pb_vm, sd, ed, POT)
        fc = run_combo(pb_vm, eq_rows, sh_rows, pb_lz, signals, sd, ed)
        fv = vm.run_pot(pb_vm, eq_rows, sh_rows, sd, ed, POT, FLOOR, [],
                        quiet=True)
        fl = lz.run_pot(pb_lz, signals, sd, ed)
        folds.append({
            "year": y, "combo_final": round(fc["final"], 2),
            "combo_ret_pct": round(fc["final"] - POT, 2),
            "combo_halt": fc["halt"],
            "vm_final": round(fv["final"], 2),
            "vm_halted": fv["halted"],
            "lz_final": round(fl["final"], 2),
            "lz_halted": fl["halted"],
            "spy_net": round(spy, 2),
            "combo_beat_spy": fc["final"] > spy,
            "combo_beat_both_parents": (fc["final"] > fv["final"]
                                        and fc["final"] > fl["final"])})
        print(f"fold {y}: combo=${fc['final']:.2f} halt={fc['halt']} | "
              f"VM=${fv['final']:.2f} LZ=${fl['final']:.2f} "
              f"SPY=${spy:.2f}", flush=True)
    def compound(rows, key):
        c = 100.0
        for r in rows:
            c *= r[key] / 100.0
        return round(c, 2)
    out["folds"] = {
        "folds": folds,
        "combo_record_vs_spy": (f"{sum(1 for f in folds if f['combo_beat_spy'])}"
                                f" wins, {sum(1 for f in folds if not f['combo_beat_spy'])}"
                                " losses"),
        "combo_fold_compounded": compound(folds, "combo_final"),
        "vm_fold_compounded": compound(folds, "vm_final"),
        "lz_fold_compounded": compound(folds, "lz_final"),
        "spy_fold_compounded": compound(folds, "spy_net"),
        "published_reference": {"vm": 313.01, "lz": 309.39, "spy": 227.34}}

    verdict = (out["continuous"]["beats_both_parents"]
               and out["validation"]["beats_both_parents"])
    out["verdict"] = ("ADOPT — beats both parents on both windows"
                      if verdict else
                      "NOT ADOPTED — dilution (fails the pre-registered "
                      "bar: must beat BOTH parents on BOTH windows)")
    print(f"\nVERDICT: {out['verdict']}", flush=True)

    with open(os.path.join(HERE, "combo-vm-lazyp-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("saved combo-vm-lazyp-results.json")


if __name__ == "__main__":
    main()
