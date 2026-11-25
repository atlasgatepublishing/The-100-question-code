#!/usr/bin/env python3
"""HOLDINGS-COUNT SWEEP — breakout-validation, George-Hwang native form.

DISPOSITION LOGIC (frozen before runs, PEAD precedent):
  * The family's PROGRAM chassis (v2/v3/v10: max 2 at 50%, entries in
    fixed UNIVERSE-list order) has NO ranking — slots fill first-come.
    That form is NOT-APPLICABLE for a count sweep (see RESULTS.md).
  * The family's NATIVE form (George & Hwang 2004, run in v11) IS a
    ranked portfolio: monthly formation, rank the 30-name pond by
    close / prior-252-session high, long the top tercile (count = 10)
    in six overlapping 6-month cohorts. Count is a genuine sweep
    variable HERE: count N -> top N names per monthly cohort.
  * breakout-regime's only ranked form is this identical GH engine
    (byte-identical script + results in its v11 folder); it is swept
    ONCE, here, under breakout-validation, and cross-referenced there.

FROZEN SWEEP: grid 1,2,3,5,8,10,15,20,30,ALL-ELIGIBLE; pond = 30
ranked names, so ALL-ELIGIBLE = 30 (its placebo is degenerate: a
random 30-of-30 is the pool itself — reported n/a). Native count = 10.
Roads (v11's): DECADE 2016-11-21->2026-11-20, CONT 2019-01-02->
2026-11-20, VAL 2023-01-03->2026-11-20. Confirmation windows:
CONF_A 2018-01-02->2021-12-31, CONF_B 2022-01-03->2025-12-31.
Forms: NATIVE = the paper's form, no floor (v11 engine, TOP_N
parameterized only). HOUSE = same book + v9 protections: plain -15%
floor from episode start, checked at every close; breach liquidates
all cohorts at the next open, 90 calendar days in cash, restart at the
next monthly formation under an episode-2 -15% floor; second halt ends
the run. Costs: 0.10%/side + $0.01/sell (program standard, as v11).
Placebos: v11 design — 20 seeds (7700+k), random N of the ranked pool
per cohort, same engine/costs/form.
Reproduction gate: native count 10 must equal the v11 finals
(DECADE $263.23 / CONT $201.32 / VAL $154.25) before sweep numbers
are trusted. Engine below is gh_native.py with TOP_N parameterized;
the long book only (the v11 long-short supplementary series is not a
holdings-count object and is not swept).
Simulation only. Shared v4/v11 inputs READ-ONLY.
"""
import json, os, random, sys
from datetime import date, timedelta
import pathlib

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = pathlib.Path.home() / "workspace/stock-app/backtests/v4/momentum-basket-honest-data"
START_CASH = 100.0
COST_RATE = 0.001
SELL_FEE = 0.01
LOOKBACK = 252
HOLD_MONTHS = 6
NATIVE_COUNT = 10
GRID = [1, 2, 3, 5, 8, 10, 15, 20, 30, "ALL"]

def load():
    series = {}
    for f in sorted(DATA.glob("*.json")):
        series[f.stem] = json.loads(f.read_text())
    return series

SERIES = load()
SYMS = [s for s in sorted(SERIES) if s != "SPY"]
DATES = [r["d"] for r in SERIES["SPY"]]
IDX = {d: i for i, d in enumerate(DATES)}
OPEN = {s: [r["o"] for r in SERIES[s]] for s in SERIES}
CLOSE = {s: [r["c"] for r in SERIES[s]] for s in SERIES}

def month_starts(start_i, end_i):
    out, seen = [], set()
    for i in range(start_i, end_i + 1):
        ym = DATES[i][:7]
        if ym not in seen:
            seen.add(ym); out.append(i)
    return out

def run(window_start, window_end, top_n, house=False, seed=None):
    rng = random.Random(seed) if seed is not None else None
    s_i, e_i = IDX[window_start], IDX[window_end]
    forms = set(month_starts(s_i, e_i))
    cash = START_CASH
    cohorts = []
    costs = 0.0; orders = 0; formations = 0
    curve = []
    episode, floor = 1, 0.85 * START_CASH
    halts = []
    state = "run"           # run | sit | done
    sit_until = None        # date string
    pending_liquidation = False
    for i in range(s_i, e_i + 1):
        d = DATES[i]
        if house and state == "sit" and d >= sit_until and i in forms:
            state, episode = "run", 2
            floor = 0.85 * cash
        if house and pending_liquidation:
            for c in cohorts:
                for sym, sh in c["shares"].items():
                    px = OPEN[sym][i]
                    notional = abs(sh * px)
                    fee = notional * COST_RATE + SELL_FEE
                    cash += sh * px - fee; costs += fee; orders += 1
            cohorts = []
            pending_liquidation = False
            if episode == 2:
                state = "done"
            else:
                state = "sit"
                sit_until = (date.fromisoformat(d) + timedelta(days=90)).isoformat()
            curve.append({"d": d, "eq": round(cash, 4)})
            continue
        if state == "done":
            curve.append({"d": d, "eq": round(cash, 4)})
            continue
        if state == "run" and i in forms and i > 0:
            sig = i - 1
            keep = []
            for c in cohorts:
                c["age"] += 1
                if c["age"] > HOLD_MONTHS:
                    for sym, sh in c["shares"].items():
                        px = OPEN[sym][i]
                        notional = abs(sh * px)
                        fee = notional * COST_RATE + SELL_FEE
                        cash += sh * px - fee; costs += fee; orders += 1
                else:
                    keep.append(c)
            cohorts = keep
            eq = cash + sum(sh * OPEN[s][i] for c in cohorts for s, sh in c["shares"].items())
            budget = eq / HOLD_MONTHS
            if sig >= LOOKBACK - 1:
                ratios = {}
                for s in SYMS:
                    hi = max(CLOSE[s][sig - LOOKBACK + 1: sig + 1])
                    if hi > 0:
                        ratios[s] = CLOSE[s][sig] / hi
                ranked = sorted(ratios, key=lambda s: -ratios[s])
                n = len(ranked) if top_n == "ALL" else min(top_n, len(ranked))
                if rng is not None:
                    picks = rng.sample(sorted(ratios), n)
                else:
                    picks = ranked[:n]
                shares = {}
                per = budget / n
                for s in picks:
                    sh = per / OPEN[s][i]
                    fee = per * COST_RATE
                    cash -= per + fee; costs += fee; orders += 1
                    shares[s] = shares.get(s, 0.0) + sh
                cohorts.append({"shares": shares, "age": 1})
                formations += 1
        eq_close = cash + sum(sh * CLOSE[s][i] for c in cohorts for s, sh in c["shares"].items())
        curve.append({"d": d, "eq": round(eq_close, 4)})
        if house and state == "run" and eq_close <= floor:
            halts.append({"episode": episode, "trigger_date": d, "floor": round(floor, 2),
                          "equity_at_trigger": round(eq_close, 2)})
            if i < e_i:
                pending_liquidation = True
            else:
                state = "done"
    final = curve[-1]["eq"] if curve else START_CASH
    peak, maxdd = START_CASH, 0.0
    for p in curve:
        peak = max(peak, p["eq"]); maxdd = max(maxdd, (peak - p["eq"]) / peak if peak else 0)
    return {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 2),
            "costs": round(costs, 2), "orders": orders, "formations": formations,
            "halts": halts, "curve": curve}

def spy_bh(a, b):
    s_i, e_i = IDX[a], IDX[b]
    sh = START_CASH / OPEN["SPY"][s_i]
    v = sh * CLOSE["SPY"][e_i]
    return round(v - v * COST_RATE - SELL_FEE, 2)

def period_stats(curve):
    months = {}
    for p in curve:
        months[p["d"][:7]] = p["eq"]
    keys = sorted(months)
    rets, prev = [], START_CASH
    for k in keys:
        rets.append(months[k] / prev - 1.0); prev = months[k]
    if not rets: return None
    srt = sorted(rets)
    med = srt[len(srt) // 2] if len(srt) % 2 else 0.5 * (srt[len(srt)//2 - 1] + srt[len(srt)//2])
    los, run_l = 0, 0
    for r in rets:
        run_l = run_l + 1 if r < 0 else 0; los = max(los, run_l)
    peak, since, longest = -1.0, 0, 0
    for v in [START_CASH] + [months[k] for k in keys]:
        if v >= peak: peak, since = v, 0
        else: since += 1; longest = max(longest, since)
    return {"periods": len(rets), "pct_profitable": round(100.0 * sum(1 for r in rets if r > 0) / len(rets), 1),
            "median_pct": round(med * 100, 2), "best_pct": round(max(rets) * 100, 2),
            "worst_pct": round(min(rets) * 100, 2), "longest_losing_run": los,
            "longest_between_highs_months": longest,
            "average_pct_secondary": round(sum(rets) / len(rets) * 100, 2)}

WINDOWS_MAIN = {"DECADE": ("2016-11-21", "2026-11-20"),
                "CONT": ("2019-01-02", "2026-11-20"),
                "VAL": ("2023-01-03", "2026-11-20")}
WINDOWS_CONF = {"CONF_A": ("2018-01-02", "2021-12-31"),
                "CONF_B": ("2022-01-03", "2025-12-31")}
EXPECTED = {"DECADE": 263.23, "CONT": 201.32, "VAL": 154.25}

def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "main"
    windows = WINDOWS_MAIN if which == "main" else WINDOWS_CONF
    counts = GRID if which == "main" else [1, 2, 3, 5, 8, 10, 15, 20, 30]
    out_path = os.path.join(HERE, "gh_results.json" if which == "main" else "gh_confirm.json")
    out = {"family": "breakout-validation (George-Hwang native form; also breakout-regime's and breakout-basket's shared GH native)",
           "native_count": NATIVE_COUNT, "cells": {}, "spy_buyhold_price_basis": {}}
    if which == "main":
        gate = {}
        ok = True
        for w, (a, b) in WINDOWS_MAIN.items():
            g = run(a, b, 10, house=False)
            gate[w] = g["final"]; ok = ok and abs(g["final"] - EXPECTED[w]) < 0.005
        out["reproduction_gate"] = {"native_count10": gate, "expected": EXPECTED, "match": ok}
        print(f"GATE native10 {gate} match={ok}", flush=True)
    for form, house in (("native", False), ("house", True)):
        for w, (a, b) in windows.items():
            out["spy_buyhold_price_basis"][w] = spy_bh(a, b)
            for n in counts:
                r = run(a, b, n, house=house)
                if n == "ALL" or n == 30:
                    twins, beaten = None, None
                else:
                    twins = [run(a, b, n, house=house, seed=7700 + k)["final"] for k in range(20)]
                    beaten = sum(1 for t in twins if r["final"] > t)
                cell = {"final": r["final"], "max_dd_pct": r["max_dd_pct"], "costs": r["costs"],
                        "orders": r["orders"], "formations": r["formations"], "halts": r["halts"],
                        "placebo_beaten": beaten, "placebo_twin_finals": twins}
                if w in WINDOWS_MAIN:
                    cell["curve"] = r["curve"]; cell["period_stats_monthly"] = period_stats(r["curve"])
                out["cells"][f"{form}|{w}|{n}"] = cell
                print(f"{form} {w} count={n}: ${r['final']} DD {r['max_dd_pct']}% orders {r['orders']} halts {len(r['halts'])} placebo {beaten}/20", flush=True)
    json.dump(out, open(out_path, "w"), indent=1)
    print("DONE", out_path, flush=True)

if __name__ == "__main__":
    main()
