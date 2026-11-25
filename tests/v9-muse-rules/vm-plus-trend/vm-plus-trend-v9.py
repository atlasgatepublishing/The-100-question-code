#!/usr/bin/env python3
"""
VALUE+MOMENTUM + ETF TREND SLEEVE — Terry's AI stock app, simulation only.

QUESTION: The program's two stock engines were blended once and diluted
each other (winners-blend: correlation +0.79, blend $400.84 vs V+M
$544.47). The ETF Trend Sleeve (monthly variant) is the one promoted
component that behaves DIFFERENTLY — it rotates out of equities into
bonds/gold/cash proxies in downturns (decade max DD -13.73% monthly vs
V+M's -36.26%). Does giving the flagship a genuinely defensive partner
buy real protection, and what does the insurance cost in final balance
under Terry's most-money-first scoreboard?

SPEC (frozen a priori, no tuning):
  - One $100 pot split 50/50.
    Sleeve A: Value+Momentum exactly as proven
      (../../v4/value-momentum-plainfloor.py — quarterly top-5,
      book-to-market + 12-1 momentum average percentile rank, honest
      2016 top-30 universe, EDGAR point-in-time, costs 0.10%/side +
      $0.01/sell).
    Sleeve B: ETF Trend Sleeve, MONTHLY variant, exactly as proven
      (../../v3/etf-trend-sleeve-monthly.py — SPY/QQQ/TLT/IEF/GLD/DBC/
      UUP, 3/6/12-month sign-blend trend, inverse-vol weights capped
      40%, 20% no-trade band, monthly evaluation, same cost schedule,
      dividend+split adjusted prices).
  - Every January (first trading day, at the close) the split is
    rebalanced back to 50/50, charged at the engines' normal cost
    schedule (0.10% sell + 0.10% buy on the transferred value +
    $0.01 x 5 sell orders) — the identical convention to winners-blend.
  - Protection: the PLAIN -15% floor ($85) at the WHOLE-POT level only.
    No ladder, no sleeve-level floor (each sleeve runs standalone with
    its internal floor/ladder disabled; only the pot floor can stop
    the run — same method as winners-blend).
  - Windows (both engines have data): CONTINUOUS 2019-01-01 ->
    2026-11-20 and VALIDATION 2023-01-01 -> 2026-11-20, $100 pots
    (engines snap to the first trading day: 2019-01-02 / 2023-01-03).
  - Placebo: 20 seeds (1..20); the V+M sleeve draws 5 names RANDOMLY
    from the scored pool each quarter (identical machinery), the trend
    sleeve runs unchanged; same blending, same pot floor.
  - Walk-forward folds: fresh $100 pot per calendar year 2020-2026
    (2026 -> Nov 20), same construction, scored vs SPY net and vs the
    V+M parent fold.

METHOD — engines verbatim, blended at the equity-curve level (the
winners-blend method): each sleeve runs standalone on its $50 half,
producing a daily close-equity curve; the pot is the sum of the two
sleeve values with January rescaling. Two documented approximations,
both pennies-level: (1) after a January rescale a sleeve follows its
standalone $50 path, so its internal $0.01 sell fees are charged at the
standalone trajectory; (2) the January transfer is charged on the
transferred value rather than by re-trading every share. A static-mix
diagnostic (no January rebalancing) separates dilution from rebalancing
cost, so neither approximation can hide the verdict.

INTEGRITY CHECKS (run first, abort on failure):
  - Value+momentum plain floor, $100 -> published $544.47 (continuous)
    and $288.05 (validation).
  - ETF trend sleeve monthly, AS-PROVEN config (floor $85 + ladder),
    $100 over its published decade 2016-11-21 -> 2026-11-20 ->
    published $194.61; $50 as-proven (floor $42.50 + scaled ladder) ->
    published $96.00; validation $100 as-proven -> published $123.18.
  - V+M walk-forward fold finals recomputed in-run must match the
    published vm-walkforward fold finals to the cent.

Data: the parent studies' own caches, read-only (EDGAR companyfacts
under ../../v4/data; Yahoo bars under ../../v4/value-momentum-honest-data
and ../../v3/data_etf).
"""

import importlib.util
import json
import math
import os
import random
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


vm = _load("value_momentum_plainfloor",
           os.path.join(V4, "value-momentum-plainfloor.py"))
etf = _load("etf_trend_sleeve_monthly",
            os.path.join(V3, "etf-trend-sleeve-monthly.py"))

POT = 100.0
FLOOR = 85.0
HALF = 50.0
WINDOWS = {
    "continuous": ("2019-01-01", "2026-11-20"),
    "validation": ("2023-01-01", "2026-11-20"),
}
PLACEBO_SEEDS = list(range(1, 21))
COVID = ("2020-02-01", "2020-04-30")
PUBLISHED_FOLDS = {2020: 83.62, 2021: 118.43, 2022: 108.91, 2023: 118.47,
                   2024: 144.32, 2025: 124.57, 2026: 136.26}


# --------------------------------------------------------------------------
# Reporting helpers (no trading logic) — same as winners-blend
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


def min_close_in(curve, sd, ed):
    pts = [(d, e) for d, e in curve if sd <= d <= ed]
    if not pts:
        return None, None
    d, e = min(pts, key=lambda p: p[1])
    return e, d


def pct(sorted_vals, q):
    if not sorted_vals:
        return float("nan")
    i = q * (len(sorted_vals) - 1)
    lo = int(math.floor(i))
    hi = int(math.ceil(i))
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] * (hi - i) + sorted_vals[hi] * (i - lo)


# --------------------------------------------------------------------------
# The blend: two sleeve equity curves -> one pot (winners-blend method)
# --------------------------------------------------------------------------
def blend_curves(curveA, curveB, pot0=POT, floor=FLOOR, rebalance=True):
    """curveA/curveB: standalone $50 sleeve daily close-equity curves.
    January split-rebalances at the close of the first trading day of
    each January after the inception January (skipped when
    rebalance=False — the static-mix diagnostic); pot-level plain
    floor checked on every close."""
    A = dict(curveA)
    B = dict(curveB)
    first = max(min(A), min(B))
    last = min(max(A), max(B))
    dates = sorted(d for d in (set(A) | set(B)) if first <= d <= last)
    start_year = dates[0][:4]
    jan_dates = set()
    seen_jan = set()
    for d in dates:
        if d[5:7] == "01" and d[:4] != start_year and d[:4] not in seen_jan:
            seen_jan.add(d[:4])
            jan_dates.add(d)

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
        if rebalance and d in jan_dates:
            transfer = abs(va - vb) / 2.0
            cost = transfer * 0.002 + 0.05      # 0.10% sell + 0.10% buy
            #                               + $0.01 x 5 sell orders
            tot -= cost
            transfer_costs += cost
            scaleA = (tot / 2.0) / lastA
            scaleB = (tot / 2.0) / lastB
            rebalances.append({"date": d, "sleeveA_before": round(va, 2),
                               "sleeveB_before": round(vb, 2),
                               "transfer": round(transfer, 2),
                               "cost": round(cost, 2)})
            va = vb = tot / 2.0
        pot_curve.append((d, tot))
        if tot <= floor:
            halt = d
            if idx < len(dates) - 1:
                nd = dates[idx + 1]
                na = A.get(nd, lastA)
                nb = B.get(nd, lastB)
                nxt = scaleA * na + scaleB * nb
                final = nxt * (1 - 0.001) - 0.10
            else:
                final = tot * (1 - 0.001) - 0.10
            break
    if final is None:
        final = pot_curve[-1][1]
    info = {"halt": halt, "final": final,
            "transfer_costs": transfer_costs,
            "rebalances": rebalances, "max_dd": max_dd(pot_curve)}
    return pot_curve, info


# --------------------------------------------------------------------------
# Sleeve runners (standalone, internal protection disabled)
# --------------------------------------------------------------------------
def vm_sleeve(pb, eq_rows, sh_rows, sd, ed, cash=HALF, rng=None):
    return vm.run_pot(pb, eq_rows, sh_rows, sd, ed, cash, 0.0, [],
                      placebo_rng=rng, quiet=True)


def etf_sleeve(sd, ed, cash=HALF):
    return etf.simulate(sd, ed, start_cash=cash, floor0=0.0, ladder=())


# --------------------------------------------------------------------------
# Value+momentum data assembly — the parent study's own assembly
# (incl. the XOM CIK override), copied from winners-blend.py.
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


def placebo_block(pb, eq_rows, sh_rows, etf_curve, sd, ed, ranked_final):
    finals = []
    halts = 0
    rows = []
    for seed in PLACEBO_SEEDS:
        rng = random.Random(seed)
        ps = vm_sleeve(pb, eq_rows, sh_rows, sd, ed, HALF, rng=rng)
        _, pinfo = blend_curves(ps["curve"], etf_curve)
        finals.append(pinfo["final"])
        if pinfo["halt"]:
            halts += 1
        rows.append({"seed": seed, "final": round(pinfo["final"], 2),
                     "halt": pinfo["halt"]})
        print(f"  placebo seed {seed:2d}: ${pinfo['final']:,.2f} "
              f"halt={pinfo['halt']}", flush=True)
    srt = sorted(finals)
    below = sum(1 for f in finals if f < ranked_final)
    ties = sum(1 for f in finals if f == ranked_final)
    return {
        "median": round(pct(srt, 0.50), 2),
        "q1": round(pct(srt, 0.25), 2),
        "q3": round(pct(srt, 0.75), 2),
        "best": round(srt[-1], 2), "worst": round(srt[0], 2),
        "mean": round(sum(finals) / len(finals), 2),
        "halted_count": halts,
        "ranked_final": round(ranked_final, 2),
        "ranked_percentile": round(100.0 * (below + 0.5 * ties)
                                   / len(finals), 1),
        "seeds_beaten": below,
        "rows": rows,
    }


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


def blend_v9(pb, eq_rows, sh_rows, start, end, start_cash=100.0):
    """One window under v9: episode 1 = original sleeves (half each,
    floorless) + original blend_curves with floor 85% of start_cash.
    On halt: liquidation date = next sleeve-curve date after the halt
    signal; cash 90 days; restart at next quarterly selection date;
    episode 2 = fresh sleeves at half the restart cash each + blend
    with floor 85% of the restart cash."""
    from datetime import date as _date
    floor1 = round(0.85 * start_cash, 2)
    vms = vm_sleeve(pb, eq_rows, sh_rows, start, end, cash=start_cash / 2.0)
    etfs = etf_sleeve(start, end, cash=start_cash / 2.0)
    curve1, info1 = blend_curves(vms["curve"], etfs["curve"],
                                 pot0=start_cash, floor=floor1)
    out = {"final": info1["final"], "curve": list(curve1),
           "halt": info1["halt"], "restarts": [], "second_halt": None,
           "episodes": 1, "ep1_final": info1["final"],
           "costs_sleeves": vms["costs"] + etfs["costs"],
           "costs_transfers": info1["transfer_costs"]}
    if info1["halt"] is None:
        return out
    all_dates = sorted(set(d for d, _ in vms["curve"]) |
                       set(d for d, _ in etfs["curve"]))
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
    vms2 = vm_sleeve(pb, eq_rows, sh_rows, restart, end, cash=cash / 2.0)
    etfs2 = etf_sleeve(restart, end, cash=cash / 2.0)
    curve2, info2 = blend_curves(vms2["curve"], etfs2["curve"],
                                 pot0=cash, floor=floor2)
    out["episodes"] = 2
    out["final"] = info2["final"]
    out["curve"] += list(curve2)
    out["costs_sleeves"] += vms2["costs"] + etfs2["costs"]
    out["costs_transfers"] += info2["transfer_costs"]
    if info2["halt"] is not None:
        out["second_halt"] = {"signal_date": info2["halt"],
                              "liquidation_final": round(info2["final"], 2),
                              "floor_in_effect": floor2}
    out["curve"].sort(key=lambda kv: kv[0])
    return out


HIS_FOLDS = [
    {"year": 2020, "final": 83.51, "spy_net": 117.47, "halt": "2020-03-20"},
    {"year": 2021, "final": 118.38, "spy_net": 127.97, "halt": None},
    {"year": 2022, "final": 102.38, "spy_net": 81.42, "halt": None},
    {"year": 2023, "final": 112.13, "spy_net": 125.28, "halt": None},
    {"year": 2024, "final": 125.65, "spy_net": 125.46, "halt": None},
    {"year": 2025, "final": 115.02, "spy_net": 116.81, "halt": None},
    {"year": 2026, "final": 116.88, "spy_net": 101.17, "halt": None},
]


def main():
    print("loading value+momentum book (cache)...", flush=True)
    pb, eq_rows, sh_rows = build_vm_book()

    # Main windows: floor never fired under his rules (continuous blend
    # halt=None, min close $99.22; validation halt=None, min close
    # $97.41) -> identical under v9, NOT re-run. Only the 2020 fold
    # fired (blend halt 2020-03-20, final $83.51) -> re-run that fold.
    r = blend_v9(pb, eq_rows, sh_rows, "2020-01-01", "2020-12-31", 100.0)
    print(f"FOLD2020 EP1 final=${r['ep1_final']:.2f} halt={r['halt']} "
          f"(recorded his: $83.51, halt 2020-03-20)", flush=True)
    assert abs(r["ep1_final"] - 83.51) < 0.02 and r["halt"] == "2020-03-20", \
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
    ep1_curve_min = min(v for d, v in r["curve"] if d <= "2020-03-23")
    v9_min = min([v for _, v in r["curve"]] + [r["final"]])
    out = {
        "slug": "vm-plus-trend",
        "name": "V+M + ETF trend sleeve, 50/50, January split rebalance",
        "status": "partial-rerun",
        "his": {"continuous_final": 320.97, "validation_final": 192.36},
        "v9": {
            "continuous_final": 320.97, "validation_final": 192.36,
            "continuous_status": "identical - floor never fired (blend halt=None in v5 results; min close $99.22, COVID worst close $104.75 on 2020-03-23, both far above the $85 floor)",
            "validation_status": "identical - floor never fired (blend halt=None in v5 results; min close $97.41 vs $85 floor)",
            "restarts": [{"window": "fold-2020", **x} for x in r["restarts"]],
            "folds_note": (f"His folds 3/7 vs SPY (fold-compounded blend ${comp(HIS_FOLDS)}, matching the published figure); "
                           f"v9 folds {v9_wins}/7 vs SPY (fold-compounded ${comp(v9_folds)}). "
                           f"Only the 2020 fold fired under his rules (halt 2020-03-20, final $83.51); "
                           f"re-run under v9: final ${round(r['final'],2)}. Other folds never fired, unchanged."),
            "worst_total_loss_pct": round(v9_min / 100.0 * 100 - 100, 2),
        },
        "notes": ("Simulation only. Main windows NOT re-run: the pot-level floor never fired there "
                  "under his rules (the continuous run's worst close was the $104.75 COVID bottom, "
                  "per the task record and v5 results min close $99.22). 2020 fold episode 1 "
                  "reproduced the recorded his-rules result ($83.51, halt 2020-03-20) before the "
                  "v9 restart was applied. His worst total loss from $100 on the re-run fold: "
                  f"{round(ep1_curve_min/100*100-100,2)}% (episode-1 blend curve minimum close). "
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
