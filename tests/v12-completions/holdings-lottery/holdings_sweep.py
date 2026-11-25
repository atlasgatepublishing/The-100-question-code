#!/usr/bin/env python3
"""
HOLDINGS-COUNT SWEEP (v12 wing, Terry 2026-11-22 ~07:37) -- lottery.

Family: penny-stock lottery pot, listed form (Terry's own design;
frozen v10 headline config E4+N3, as run in v12-completions/lottery).
NOTE on the assignment label: the parent task described this family
as "MAX-effect ranked selection". The canonical record contains no
MAX-effect system: the published lottery evidence (Eraker & Ready
2015) is a habitat study with no tradable system, and the only
tradable form in the record is Terry's listed penny pot, whose entry
ranking (N3) is "smallest prior-day % gain among screened names up on
the day" (quiet gainers). This sweep runs THAT form, exactly as
frozen. The discrepancy is flagged in RESULTS.md.

WHAT VARIES: only the maximum simultaneous positions cap
(MAX_POSITIONS in the v10 engine). Grid (pre-registered, fixed):
1, 2, 3, 5, 8, 10, 15, 20, 30, ALL-ELIGIBLE (cap = 9999; the frozen
15%-per-name sizing, cash, the 1-entry/day and 2-entries/week caps,
and the monthly screen size bind first -- reported, not hidden).

WHAT DOES NOT VARY (frozen v12/v10 chassis, imported unchanged):
monthly PIT screen (listed, close < $5, trailing-20d avg dollar
volume > $20M, candidate list = v3's 73 names as served by the v12
fresh cache), N3 quiet-gainer ranking, next-open fills, 15% of pot
equity per name, max 1 entry/day, max 2 entries/week, no averaging
down, E4 exits (-10% stop / +40% target, gap-throughs at the open),
costs 2.0%/side + $0.01/sell, v9 plain -15% floor (liquidate next
open, 90-day sit-out, one restart with fresh -15% floor from restart
balance; second halt ends the run), daily cadence.

FORMS: house = the form above (v9 protections -- this IS the v12
house/constructed form). Native: NO native tradable form exists
(v11 UNBUILDABLE-NATIVE; the OTC habitat has no free PIT data and
Alpaca cannot trade it) -- so there is no second form to sweep.
Native COUNT = 5 (max positions in both the lottery E4+N3 record
and the lottery-v2 record).

ROADS: LONG 2010-01-04, DECADE 2016-11-21, CONT 2019-01-02,
VAL 2023-01-03, all -> 2026-11-20 ($100 pots).

PLACEBOS: 20 seeded random-rank twins per cell (v10 definition:
identical everything, ranking replaced by seeded random order).

CONFIRMATION (Terry's rule): any non-native count beating count 5
on ALL four roads is re-run on calendar-year folds 2017..2026
before it can be labeled VARIANT-CANDIDATE.

DATA: read-only -- the v12 lottery folder's fresh Yahoo cache
(2009-11-01 -> 2026-11-22 pull). No fetching, no writes outside
this folder.

INTEGRITY: count 5 must reproduce the v12 published finals
(LONG $71.53, DECADE $67.05, CONT $66.87, VAL $69.88) before the
sweep counts.
"""
import importlib.util
import json
import os
import statistics
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_CACHE = os.path.expanduser(
    "~/workspace/stock-app/backtests/v12-completions/lottery/data_cache")
V10_PATH = os.path.expanduser(
    "~/workspace/stock-app/backtests/v10-retest/lottery/run_v10.py")
spec = importlib.util.spec_from_file_location("lottery_v10", V10_PATH)
v10 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v10)

ET = ZoneInfo("America/New_York")
ROADS = {
    "LONG":   ("2010-01-04", "2026-11-20"),
    "DECADE": ("2016-11-21", "2026-11-20"),
    "CONT":   ("2019-01-02", "2026-11-20"),
    "VAL":    ("2023-01-03", "2026-11-20"),
}
SPY_REF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
CHAMPION = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
V12_COUNT5 = {"LONG": 71.53, "DECADE": 67.05, "CONT": 66.87, "VAL": 69.88}
COUNTS = [1, 2, 3, 5, 8, 10, 15, 20, 30, "ALL"]
PLACEBO_SEEDS = list(range(1, 21))


def parse_bars(symbol):
    path = os.path.join(SRC_CACHE, f"{symbol}.json")
    if not os.path.exists(path):
        return {}, {}
    with open(path) as f:
        data = json.load(f)
    result = data.get("chart", {}).get("result")
    if not result:
        return {}, {}
    r = result[0]
    meta = r.get("meta", {})
    ts = r.get("timestamp", []) or []
    q = r.get("indicators", {}).get("quote", [{}])[0]
    bars = {}
    for i, t in enumerate(ts):
        d = datetime.fromtimestamp(t, tz=ET).strftime("%Y-%m-%d")
        try:
            bar = {"open": q["open"][i], "high": q["high"][i],
                   "low": q["low"][i], "close": q["close"][i],
                   "volume": q["volume"][i]}
        except (KeyError, IndexError, TypeError):
            continue
        if None in bar.values():
            continue
        bars[d] = bar
    return meta, bars


def period_distribution(curve, period="monthly"):
    """Per-period record from the daily equity curve. Period =
    calendar month (monthly) or trading day (daily). First period
    measured from the $100 start."""
    def key(d):
        return d[:7] if period == "monthly" else d
    ends, order = {}, []
    for d, v in curve:
        k = key(d)
        if k not in ends:
            order.append(k)
        ends[k] = v
    vals = [ends[k] for k in order]
    rets, prev = [], 100.0
    for v in vals:
        rets.append(v / prev - 1.0)
        prev = v
    if not rets:
        return None
    prof = sum(1 for r in rets if r > 0)
    longest_loss, cur = 0, 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0
        longest_loss = max(longest_loss, cur)
    peak, since_high, longest_gap = -1.0, 0, 0
    for v in vals:
        if v >= peak:
            peak, since_high = v, 0
        else:
            since_high += 1
            longest_gap = max(longest_gap, since_high)
    return {"periods": len(rets),
            "pct_profitable": round(100.0 * prof / len(rets), 1),
            "median_period_pct": round(statistics.median(rets) * 100, 2),
            "best_period_pct": round(max(rets) * 100, 2),
            "worst_period_pct": round(min(rets) * 100, 2),
            "longest_losing_run_periods": longest_loss,
            "longest_stretch_between_new_highs_periods": longest_gap,
            "average_period_pct_secondary": round(statistics.mean(rets) * 100, 2)}


def main():
    t0 = time.time()
    all_bars, all_meta, failed = {}, {}, []
    for sym in v10.CANDIDATES + ["SPY"]:
        meta, bars = parse_bars(sym)
        all_meta[sym], all_bars[sym] = meta, bars
        if not bars:
            failed.append(sym)
    print(f"data: failed={sorted(set(failed))}", flush=True)
    store = v10.Store(all_bars)
    all_days = sorted(all_bars["SPY"].keys())
    months = v10.run_months("2009-12", "2026-11")
    universes = {}
    for mk in months:
        _, passed = v10.screen_for_month(mk, all_days, store, all_meta)
        universes[mk] = passed
    elig = [len(v) for v in universes.values()]
    elig_stats = {"months": len(elig), "min": min(elig),
                  "median": statistics.median(elig), "max": max(elig)}
    print(f"screen sizes: {elig_stats}", flush=True)

    run_days_by_road, cad_by_road, span_by_road = {}, {}, {}
    for road, (start, end) in ROADS.items():
        rd = [d for d in all_days if start <= d <= end]
        run_days_by_road[road] = rd
        cad_by_road[road] = v10.cadence_dates("daily", rd)
        span_by_road[road] = (datetime.strptime(end, "%Y-%m-%d")
                              - datetime.strptime(start, "%Y-%m-%d")).days

    def run_cell(count, road, mode="N3", seed=None):
        v10.MAX_POSITIONS = 9999 if count == "ALL" else count
        res = v10.simulate_cadence(store, all_days, run_days_by_road[road],
                                   universes, cad_by_road[road], mode,
                                   seed=seed)
        return res

    cells = {}       # cells[count][road]
    curves = {}      # kept for count 5 + winner (decided after sweep)
    raw_curves = {}
    ckpt = os.path.join(HERE, "sweep_checkpoint.json")
    if os.path.exists(ckpt):
        with open(ckpt) as f:
            saved = json.load(f)
        cells = saved.get("cells", {})
        raw_curves = {k: v for k, v in saved.get("curves", {}).items()}
        print(f"resumed: counts done = {list(cells)}", flush=True)

    for count in COUNTS:
        ck = str(count)
        if ck in cells:
            continue
        cells[ck] = {}
        for road in ROADS:
            ts = time.time()
            res = run_cell(count, road)
            st = v10.stats_of(res, span_by_road[road])
            placebo_finals = []
            for seed in PLACEBO_SEEDS:
                pres = run_cell(count, road, mode="RANDOM", seed=seed)
                placebo_finals.append(round(pres["final_balance"], 2))
            beaten = sum(1 for f in placebo_finals if st["final"] > f)
            cells[ck][road] = {
                "final": st["final"], "cagr_pct": st["cagr_pct"],
                "max_dd_pct": st["max_dd_pct"], "costs": st["costs"],
                "spread_costs": st["spread_costs"],
                "fee_costs": st["fee_costs"], "orders": st["orders"],
                "round_trips": st["round_trips"],
                "win_rate_pct": st["win_rate_pct"],
                "gap_through_stops": st["gap_through_stops"],
                "halts": res["halt_events"], "restarts": res["restarts"],
                "placebo_beaten": beaten, "placebo_finals": placebo_finals,
                "placebo_median": round(statistics.median(placebo_finals), 2),
                "placebo_min": min(placebo_finals),
                "placebo_max": max(placebo_finals)}
            raw_curves[f"{ck}|{road}"] = [[d, v] for d, v in res["daily"]]
            print(f"CELL n={ck} {road}: ${st['final']:.2f} DD "
                  f"{st['max_dd_pct']:.2f}% costs ${st['costs']:.2f} "
                  f"RT {st['round_trips']} halts {len(res['halt_events'])} "
                  f"beats {beaten}/20 ({time.time()-ts:.1f}s)", flush=True)
        with open(ckpt, "w") as f:
            json.dump({"cells": cells, "curves": raw_curves}, f, indent=1)

    # Integrity: count 5 vs v12 published
    integrity = {r: {"sweep": cells["5"][r]["final"],
                     "v12_published": V12_COUNT5[r],
                     "match": abs(cells["5"][r]["final"] - V12_COUNT5[r]) < 0.005}
                 for r in ROADS}
    print(f"INTEGRITY count5: {integrity}", flush=True)

    # Winner per road-sum
    totals = {ck: round(sum(cells[ck][r]["final"] for r in ROADS), 2)
              for ck in cells}
    win_count = max(totals, key=totals.get)
    print(f"WINNER by road-sum: n={win_count} totals={totals}", flush=True)

    # Distributions for native (5) and winner (if different), all roads
    dists = {}
    keep = {"5", win_count}
    for ck in keep:
        for road in ROADS:
            curve = [(d, v) for d, v in raw_curves[f"{ck}|{road}"]]
            dists[f"{ck}|{road}|monthly"] = period_distribution(curve, "monthly")
            dists[f"{ck}|{road}|daily"] = period_distribution(curve, "daily")
            curves[f"{ck}|{road}"] = raw_curves[f"{ck}|{road}"]

    # CONFIRMATION: non-native count beating count 5 on ALL roads ->
    # calendar-year folds 2017..2026, fresh $100 pot each year.
    folds_days = {}
    for yr in range(2017, 2027):
        s = f"{yr}-01-01"
        e = f"{yr}-12-31" if yr < 2026 else "2026-11-20"
        rd = [d for d in all_days if s <= d <= e]
        folds_days[yr] = (rd, v10.cadence_dates("daily", rd),
                          (datetime.strptime(e, "%Y-%m-%d")
                           - datetime.strptime(s, "%Y-%m-%d")).days)
    confirm = {}
    for ck in cells:
        if ck == "5":
            continue
        if all(cells[ck][r]["final"] > cells["5"][r]["final"] for r in ROADS):
            rec = {}
            for cnt in [ck, "5"]:
                yrs, tot = {}, 1.0
                for yr in range(2017, 2027):
                    rd, cad, span = folds_days[yr]
                    v10.MAX_POSITIONS = 9999 if cnt == "ALL" else int(cnt)
                    res = v10.simulate_cadence(store, all_days, rd, universes,
                                               cad, "N3")
                    fin = round(res["final_balance"], 2)
                    yrs[str(yr)] = fin
                    tot *= fin / 100.0
                rec[cnt] = {"folds": yrs, "fold_compounded": round(tot * 100, 2)}
            wins = sum(1 for y in rec[ck]["folds"]
                       if rec[ck]["folds"][y] > rec["5"]["folds"][y])
            rec["fold_years_won_vs_native"] = wins
            rec["confirmed"] = (rec[ck]["fold_compounded"]
                                > rec["5"]["fold_compounded"] and wins >= 6)
            confirm[ck] = rec
            print(f"CONFIRM n={ck}: folds won {wins}/10 compounded "
                  f"${rec[ck]['fold_compounded']} vs native "
                  f"${rec['5']['fold_compounded']} -> "
                  f"{'CONFIRMED' if rec['confirmed'] else 'NOT CONFIRMED'}",
                  flush=True)
    v10.MAX_POSITIONS = 5

    out = {
        "family": "lottery (penny-stock lottery pot, listed form; "
                  "Terry's design, frozen v10 headline E4+N3)",
        "assignment_label_note": "Parent task called this family "
            "'MAX-effect ranked selection'; the canonical record "
            "(v11 NATIVE-SPEC, v12 CONSTRUCTION-SPEC) contains no "
            "MAX-effect system -- the tradable form is the listed "
            "penny pot with N3 quiet-gainer ranking. That form was swept.",
        "native_count": 5,
        "native_count_source": "Max 5 positions in the frozen E4+N3 "
            "record (v12 lottery CONSTRUCTION-SPEC) and in lottery-v2's "
            "frozen house spec alike.",
        "forms": {"house_v9": "Only form swept: v9 protections (plain "
                  "-15% floor, one restart) on the frozen chassis -- "
                  "identical to the v12 constructed/house run. No "
                  "native tradable form exists (UNBUILDABLE-NATIVE, "
                  "OTC habitat), so no native-form sweep is possible."},
        "grid": [str(c) for c in COUNTS],
        "what_varies": "MAX_POSITIONS cap only. Per-name sizing stays "
            "the frozen 15% of pot equity; 1 entry/day and 2/week caps, "
            "E4 exits, 2%/side + $0.01 costs, floor machinery unchanged. "
            "ALL = cap 9999 (cash/sizing/entry caps bind first).",
        "roads": ROADS, "spy_ref": SPY_REF, "champion_vm": CHAMPION,
        "screen_size_stats": elig_stats,
        "failed_symbols": sorted(set(failed)),
        "integrity_count5_vs_v12": integrity,
        "cells": cells,
        "road_sum_totals_by_count": totals,
        "winner_by_road_sum": win_count,
        "period_distributions": dists,
        "confirmation_folds": confirm,
        "curves_native_and_winner": curves,
        "runtime_s": round(time.time() - t0, 1),
    }
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print(f"DONE in {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
