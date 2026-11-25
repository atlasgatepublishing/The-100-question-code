#!/usr/bin/env python3
"""
THE GREAT RETEST (v10) — breakout-validation
Single-name 52-week-high breakout (v2 tournament style C, the tournament
winner, deep-validated in v3 and DEMOTED; v9 protection re-run in
backtests/v9-muse-rules/breakout-validation/).

Simulation only — no broker orders.

WHAT THIS SCRIPT DOES
  1. INTEGRITY: reproduces the original published finals in their ORIGINAL
     form through the original engines (v3 breakout-validation.py for the
     his-rules runs; the v9 copy for the v9 validation run):
       FULL  2016-11-21 -> 2026-11-20  $383.36 (his rules)
       DESIGN 2016-11-21 -> 2022-12-31 $348.73 (his rules)
       VALIDATION 2023-01-01 -> 2026-11-20 $124.82 (his rules, LADDER halt
             2026-08-14) / $109.54 (v9 plain floor, no halt)
  2. CADENCE SWEEP: DECADE 2016-11-21 -> 2026-11-20 x 7 cadences
     (daily, weekly, biweekly, monthly, quarterly, semiannual, annual),
     $100 per cell, program costs (0.10%/side + $0.01/sell), v9 protections
     (plain -15% floor, no ladder; first halt -> liquidate at next open,
     90 calendar days in cash, restart at the next regular decision point
     under an episode-2 -15% floor from the restart balance; second halt
     ends the run).

CADENCE TREATMENT (SPEC uniform definition, stated for this strategy):
  This strategy is DAILY-SIGNAL native: in its original form the breakout
  signal (close above the highest close of the prior 252 sessions), the
  20-day-MA exit condition and the -8% intraday stop are all evaluated
  every trading day, with trades filling at the next open.
  Under the sweep, the 252-day-high and SMA20 series are still computed
  from daily bars, but signal EVALUATION happens only on cadence dates
  (daily = every trading day; weekly = first trading day of each ISO
  week; biweekly = first trading day of every second ISO week, anchored
  on the window's first week; monthly/quarterly/semi-annual/annual =
  first trading day of the period). Decisions taken at a cadence date's
  close fill at the NEXT trading day's open, exactly as the original
  next-open convention. The -8% stop is likewise only checked on
  cadence dates (that date's open/low vs the stop price) — the SPEC's
  uniform rule that definitional exits are evaluated on cadence dates.
  The v9 floor is a protection overlay, not a strategy signal: equity is
  marked and the floor is tested EVERY trading day in every cell, and a
  halt liquidates at the next open. After a halt's 90-day sit-out the
  strategy resumes at the first test day on/after the sit-out end and
  generates signals again from the next cadence date onward.

PLACEBOS: 20 seeds per cell (seeds 1001-1020). Random-entry twins in the
tournament/v3 design: random (cadence date, symbol) entry attempts are
scheduled so the number of FILLED entries matches the real run's filled
entries per calendar year (iterative top-up, as in v3's fixed placebo);
entries fill at the next open after the chosen cadence date; exits,
stop, sizing, costs and the v9 floor are the identical code path.

DATA: read-only from the v2 tournament cache (backtests/v2/tournament-data/,
Yahoo daily bars, split-adjusted, NOT dividend-adjusted; universe SPY QQQ
NVDA TSLA AAPL MSFT AMZN META AMD AVGO — today's famous names, so
survivorship tilt flatters every number, as in the original). The decade
SPY benchmark for the sweep is the SPEC's dividend-adjusted $367.80; the
engine's own price-only SPY net on this data is ~$314.10 (the original
tournament convention) and is reported alongside for honesty.

Outputs (this folder): integrity.json, cells/<cadence>.json, results.json.
"""

import contextlib
import importlib.util
import json
import os
import sys
from datetime import date, timedelta

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.join(HERE, "..", "..")
V2_DIR = os.path.join(BT, "v2")
sys.path.insert(0, V2_DIR)

import tournament as T  # the exact tournament engine (Portfolio/costs/floor)

UNIVERSE = T.STOCK_UNIVERSE
DECADE = (date(2016, 11, 21), date(2026, 11, 20))
FULL = DECADE
DESIGN = (date(2016, 11, 21), date(2022, 12, 31))
VALIDATION = (date(2023, 1, 1), date(2026, 11, 20))
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]
PLACEBO_SEEDS = list(range(1001, 1021))
DECADE_SPY_DIV_ADJ = 367.80


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ----------------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------------

def build_frames():
    raw = {sym: T.load_symbol(sym) for sym in T.ALL_SYMBOLS}
    return T.align_frames(raw)


def make_market(frames, window):
    T.TEST_START, T.TEST_END = window
    return T.Market(frames)


def precompute(mkt):
    """Numpy views of the series the runner needs, indexed by frame pos."""
    arr = {}
    for sym in UNIVERSE:
        df = mkt.frames[sym]
        arr[sym] = {
            "close": df["close"].to_numpy(dtype=float),
            "open": df["open"].to_numpy(dtype=float),
            "low": df["low"].to_numpy(dtype=float),
            "sma20": df["sma20"].to_numpy(dtype=float),
            "prior252": df["prior252_high_close"].to_numpy(dtype=float),
        }
    return arr


def fast_map(arr, pos, field):
    """Price map over the universe from the numpy arrays — the identical
    values Market.open_map/close_map return for these symbols (the only
    symbols a portfolio here can hold), without the per-day pandas cost."""
    return {sym: float(arr[sym][field][pos]) for sym in UNIVERSE}


# ----------------------------------------------------------------------------
# Cadence calendar
# ----------------------------------------------------------------------------

def eval_dates(test_dates, cadence):
    """Set of dates on which signals are evaluated (at the close)."""
    if cadence == "daily":
        return set(test_dates)
    out = set()
    seen = set()
    first = test_dates[0]
    first_monday = first - timedelta(days=first.weekday())
    for d in test_dates:
        if cadence == "weekly":
            key = (d.isocalendar()[0], d.isocalendar()[1])
        elif cadence == "biweekly":
            monday = d - timedelta(days=d.weekday())
            wk = (monday - first_monday).days // 7
            key = ("bi", wk // 2) if wk % 2 == 0 else None
            if key is None:
                continue
        elif cadence == "monthly":
            key = (d.year, d.month)
        elif cadence == "quarterly":
            key = (d.year, (d.month - 1) // 3)
        elif cadence == "semiannual":
            key = (d.year, (d.month - 1) // 6)
        elif cadence == "annual":
            key = (d.year,)
        else:
            raise ValueError(cadence)
        if key not in seen:
            seen.add(key)
            out.add(d)
    return out


# ----------------------------------------------------------------------------
# v9 protection (plain floor) — the v9 folder's reading, verbatim in effect
# ----------------------------------------------------------------------------

def plain_floor_check(self, d, equity_close):
    if equity_close <= self.floor:
        self.halt_pending = True
        self.halt_trigger_date = d
        return True
    return False


# ----------------------------------------------------------------------------
# Cadence runner with v9 protection (structure follows the v9 runner)
# ----------------------------------------------------------------------------

def run_cadence(mkt, arr, cadence, style_name, placebo_schedule=None):
    evals = eval_dates(mkt.test_dates, cadence)
    pf = T.Portfolio(style_name)
    pending_entries = []
    pending_exits = []
    last_t = len(mkt.test_dates) - 1
    episode = 1
    restarts = []
    halt_events = []

    t = 0
    while t <= last_t:
        d = mkt.test_dates[t]
        pos = mkt.test_pos[t]
        if pf.halt_pending:
            pf.liquidate_all(d, pos, fast_map(arr, pos, "open"),
                             "floor-liquidation")
            pf.halted = True
            pf.halt_date = d
            pf.equity_curve.append((d, pf.equity(fast_map(arr, pos,
                                                          "close"))))
            halt_events.append({
                "episode": episode,
                "trigger_date": (pf.halt_trigger_date.isoformat()
                                 if pf.halt_trigger_date else None),
                "liquidation_date": d.isoformat(),
                "cash_after_liquidation": round(pf.cash, 2),
            })
            if episode == 2:
                break
            restart_balance = pf.cash
            resume_on_or_after = d + timedelta(days=90)
            j = t + 1
            while j <= last_t and mkt.test_dates[j] < resume_on_or_after:
                pf.equity_curve.append((mkt.test_dates[j], restart_balance))
                j += 1
            if j > last_t:
                restarts.append({
                    "halt_trigger_date": halt_events[-1]["trigger_date"],
                    "liquidation_date": d.isoformat(),
                    "restart_date": None,
                    "restart_balance": round(restart_balance, 2),
                    "note": "90-day sit-out runs past the window end; "
                            "run ends with the liquidation cash.",
                })
                break
            pf.floor = 0.85 * restart_balance
            pf.halt_pending = False
            pf.halted = False
            pf.halt_date = None
            pf.halt_trigger_date = None
            pending_entries = []
            pending_exits = []
            episode = 2
            restarts.append({
                "halt_trigger_date": halt_events[-1]["trigger_date"],
                "liquidation_date": d.isoformat(),
                "restart_date": mkt.test_dates[j].isoformat(),
                "restart_balance": round(restart_balance, 2),
                "episode2_floor": round(pf.floor, 2),
            })
            t = j
            continue

        is_eval = d in evals

        # 1) close-signal exits scheduled at the previous cadence date
        for sym, reason in pending_exits:
            if pf.shares_of(sym) > 0:
                pf.sell(d, pos, sym, float(arr[sym]["open"][pos]), reason)
        pending_exits = []

        # 2) entries at today's open (scheduled at the previous cadence
        #    date, or from the placebo schedule)
        if placebo_schedule is not None:
            candidates = list(placebo_schedule.get(d, []))
        else:
            candidates = list(pending_entries)
        pending_entries = []
        for sym in candidates:
            if pf.shares_of(sym) > 0 or len(pf.held_symbols()) >= 2:
                continue
            eq_open = pf.equity(fast_map(arr, pos, "open"))
            pf.buy(d, pos, sym, float(arr[sym]["open"][pos]),
                   0.5 * eq_open, "entry")

        # 3) intraday -8% stop — checked only on cadence dates
        if is_eval:
            for sym in list(pf.held_symbols()):
                entry = pf.weighted_entry_price(sym)
                if entry is None:
                    continue
                o = arr[sym]["open"][pos]
                low = arr[sym]["low"][pos]
                stop_px = entry * (1 - 0.08)
                fill, reason = None, None
                if o <= stop_px:
                    fill, reason = o, "stop-gap"
                elif low <= stop_px:
                    fill, reason = stop_px, "stop"
                if fill is not None:
                    pf.sell(d, pos, sym, fill, reason)

        # 4) mark to close; v9 plain floor tested every trading day
        eq_close = pf.equity(fast_map(arr, pos, "close"))
        pf.equity_curve.append((d, eq_close))
        touched = pf.floor_check(d, eq_close)
        if touched and t == last_t:
            pf.halted = True
            pf.halt_date = d
            halt_events.append({
                "episode": episode,
                "trigger_date": d.isoformat(),
                "liquidation_date": None,
                "cash_after_liquidation": round(pf.cash, 2),
                "note": "floor touched on the final day; run ends here "
                        "(no next open to liquidate at).",
            })
            break
        if t == last_t:
            break

        if is_eval:
            # 5) schedule MA exits for tomorrow's open
            for sym in list(pf.held_symbols()):
                ma = arr[sym]["sma20"][pos]
                if not np.isnan(ma) and arr[sym]["close"][pos] < ma:
                    pending_exits.append((sym, "ma-exit"))
            # 6) generate tomorrow's entries from today's close signals
            if placebo_schedule is None:
                for sym in UNIVERSE:
                    if pf.shares_of(sym) > 0:
                        continue
                    if pos < 253:
                        continue
                    ph = arr[sym]["prior252"][pos]
                    if not np.isnan(ph) and arr[sym]["close"][pos] > ph:
                        pending_entries.append(sym)
        t += 1

    pf.v9_restarts = restarts
    pf.v9_halt_events = halt_events
    return pf


# ----------------------------------------------------------------------------
# Placebos: matched filled-entry counts per year (v3 fixed-placebo design)
# ----------------------------------------------------------------------------

def entries_by_year(pf):
    out = {}
    for tr in pf.trades:
        if tr["side"] == "buy":
            y = int(tr["date"][:4])
            out[y] = out.get(y, 0) + 1
    return out


def run_placebo_matched(mkt, arr, cadence, target_by_year, seed):
    rng = np.random.default_rng(seed)
    test_dates = mkt.test_dates
    idx_of = {d: i for i, d in enumerate(test_dates)}
    evals_sorted = sorted(eval_dates(test_dates, cadence))
    eval_idx = {d: i for i, d in enumerate(evals_sorted)}
    evals_by_year = {}
    for d in evals_sorted[:-1]:  # an entry needs a next trading day
        if idx_of[d] < len(test_dates) - 1:
            evals_by_year.setdefault(d.year, []).append(d)
    schedule = {}

    def add_attempts(year, n):
        days = evals_by_year.get(year, [])
        if not days:
            return
        for _ in range(n):
            d = days[rng.integers(0, len(days))]
            i = eval_idx[d]
            # roll to the next cadence date while its fill day is full;
            # never roll onto the final test date (no next open exists)
            while i < len(evals_sorted) - 1:
                if idx_of[evals_sorted[i]] >= len(test_dates) - 1:
                    break
                fill = test_dates[idx_of[evals_sorted[i]] + 1]
                if len(schedule.get(fill, [])) < 2:
                    break
                i += 1
            if idx_of[evals_sorted[i]] >= len(test_dates) - 1:
                continue
            fill = test_dates[idx_of[evals_sorted[i]] + 1]
            sym = UNIVERSE[rng.integers(0, len(UNIVERSE))]
            schedule.setdefault(fill, []).append(sym)

    for year, target in sorted(target_by_year.items()):
        add_attempts(year, target)

    pf, actual = None, {}
    for _ in range(30):
        pf = run_cadence(mkt, arr, cadence, "breakout_placebo",
                         placebo_schedule=schedule)
        actual = entries_by_year(pf)
        missing = {y: target_by_year.get(y, 0) - actual.get(y, 0)
                   for y in target_by_year}
        if all(v <= 0 for v in missing.values()):
            break
        for year, miss in missing.items():
            if miss > 0:
                add_attempts(year, miss)
    attempts = sum(len(v) for v in schedule.values())
    return pf, {"seed": seed, "attempts": attempts,
                "target_by_year": {str(k): v for k, v in
                                   sorted(target_by_year.items())},
                "actual_by_year": {str(k): v for k, v in
                                   sorted(actual.items())}}


# ----------------------------------------------------------------------------
# Scoring helpers
# ----------------------------------------------------------------------------

def cell_stats(pf, mkt):
    r = T.score(pf, mkt.test_dates[0])
    curve = [[mkt.test_dates[0].isoformat(), 100.0]] + \
            [[d.isoformat(), round(e, 4)] for d, e in pf.equity_curve]
    return r, curve


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main():
    print("Loading data (v2 tournament cache, read-only)...", flush=True)
    frames = build_frames()

    # ---------------- INTEGRITY (original form, original engines) ----------
    v3 = load_module("bv_v3", os.path.join(BT, "v3", "breakout-validation.py"))
    integrity = {"status": None, "original_finals": {
                     "FULL_his_rules": 383.36, "DESIGN_his_rules": 348.73,
                     "VALIDATION_his_rules": 124.82,
                     "VALIDATION_v9": 109.54},
                 "reproduced_finals": {}, "detail": {}}
    for name, window in (("FULL", FULL), ("DESIGN", DESIGN),
                         ("VALIDATION", VALIDATION)):
        mkt = v3.make_market(frames, window)
        pf = v3.run_breakout(mkt, "c_breakout52")
        r = v3.brief(pf, mkt)
        key = f"{name}_his_rules"
        integrity["reproduced_finals"][key] = round(r["final"], 2)
        integrity["detail"][key] = {
            "final": round(r["final"], 2), "halt_date": r["halt_date"],
            "orders": r["orders"], "closed_trades": r["closed_trades"],
            "max_dd_pct": round(r["max_dd_pct"], 2),
            "total_costs": round(r["total_costs"], 2)}
        print(f"INTEGRITY his {name}: ${r['final']:,.2f} "
              f"halt {r['halt_date'] or '-'}", flush=True)

    v9 = load_module("bv_v9", os.path.join(
        BT, "v9-muse-rules", "breakout-validation",
        "breakout-validation-v9.py"))
    mkt = v9.make_market(frames, VALIDATION)
    orig_fc = T.Portfolio.floor_check
    T.Portfolio.floor_check = v9.plain_floor_check
    try:
        pf_v9 = v9.run_breakout_v9(mkt, "c_breakout52")
    finally:
        T.Portfolio.floor_check = orig_fc
    r_v9 = v9.brief(pf_v9, mkt)
    integrity["reproduced_finals"]["VALIDATION_v9"] = round(r_v9["final"], 2)
    integrity["detail"]["VALIDATION_v9"] = {
        "final": round(r_v9["final"], 2), "halt_date": r_v9["halt_date"],
        "orders": r_v9["orders"], "restarts": pf_v9.v9_restarts,
        "halt_events": pf_v9.v9_halt_events,
        "note": "plain $85 floor never fired (lowest close $97.21 in the "
                "v9 record); both his-rules validation halts were LADDER "
                "halts — under the plain floor the pot never fired."}
    print(f"INTEGRITY v9 VALIDATION: ${r_v9['final']:,.2f}", flush=True)

    ok = all(abs(integrity["reproduced_finals"][k] -
                 integrity["original_finals"][k]) < 0.005
             for k in integrity["original_finals"])
    integrity["status"] = "reproduced" if ok else "FAILED"
    integrity["record_note"] = (
        "Both his-rules validation halts (2026-08-14 $100 / 2026-08-13 $50) "
        "were LADDER halts: the pot had closed at/above $150, the floor had "
        "risen to $125, and a close at/below $125 ended the run. Under the "
        "plain floor the pot never fired (validation lowest close $97.21). "
        "Original verdict: DEMOTED — validation $124.82 trailed SPY net "
        "$179.10 (price-only convention); deflated Sharpe 0.61 vs the 0.95 "
        "gate at headline assumptions (N=17, dispersion 0.40).")
    with open(os.path.join(HERE, "integrity.json"), "w") as fh:
        json.dump(integrity, fh, indent=2, default=str)
    print(f"INTEGRITY STATUS: {integrity['status']}", flush=True)

    # ---------------- CADENCE SWEEP (v9 protections) -----------------------
    mkt = make_market(frames, DECADE)
    arr = precompute(mkt)
    spy_gross, spy_net = T.spy_benchmark(mkt)
    print(f"DECADE price-only SPY: gross ${spy_gross:,.2f} "
          f"net ${spy_net:,.2f} (SPEC dividend-adjusted: "
          f"${DECADE_SPY_DIV_ADJ:,.2f})", flush=True)

    orig_fc = T.Portfolio.floor_check
    T.Portfolio.floor_check = plain_floor_check
    cells = {}
    try:
        for cadence in CADENCES:
            pf = run_cadence(mkt, arr, cadence, f"breakout_{cadence}")
            r, curve = cell_stats(pf, mkt)
            target = entries_by_year(pf)
            twins = []
            for seed in PLACEBO_SEEDS:
                ppf, meta = run_placebo_matched(mkt, arr, cadence, target,
                                                seed)
                print(f"  placebo {cadence} seed {seed} done", flush=True)
                pr = T.score(ppf, mkt.test_dates[0])
                twins.append({"seed": seed, "final": round(pr["final"], 2),
                              "entries": pr["entries"],
                              "attempts": meta["attempts"],
                              "target_by_year": meta["target_by_year"],
                              "actual_by_year": meta["actual_by_year"],
                              "halt_date": pr["halt_date"]})
            beaten = sum(1 for tw in twins if r["final"] > tw["final"])
            cell = {
                "final": round(r["final"], 2),
                "cagr_pct": round(r["cagr_pct"], 2),
                "max_dd_pct": round(r["max_dd_pct"], 2),
                "halts": pf.v9_halt_events,
                "restart": bool(pf.v9_restarts and
                                pf.v9_restarts[0].get("restart_date")),
                "second_halt": len(pf.v9_halt_events) >= 2,
                "costs": round(r["total_costs"], 2),
                "orders": r["orders"],
                "entries": r["entries"],
                "closed_trades": r["closed_trades"],
                "placebo_beaten": beaten,
                "placebo_note": (
                    "20 random-entry twins (seeds 1001-1020), v3 "
                    "fixed-placebo design: random (cadence date, symbol) "
                    "attempts topped up until filled entries match the "
                    "real run per calendar year; identical exits, stop, "
                    "sizing, costs and v9 floor. placebo_beaten = seeds "
                    "whose final the real run exceeded, /20."),
            }
            cells[cadence] = cell
            cell_doc = {
                "slug": "breakout-validation", "cadence": cadence,
                "cadence_label": "daily-signal" if cadence == "daily"
                                 else cadence,
                "window": [DECADE[0].isoformat(), DECADE[1].isoformat()],
                "start_cash": 100.0,
                "n_eval_dates": len(eval_dates(mkt.test_dates, cadence)),
                **cell,
                "restarts_detail": pf.v9_restarts,
                "placebo_twins": twins,
                "placebo_finals": [tw["final"] for tw in twins],
                "equity_curve": curve,
            }
            with open(os.path.join(HERE, "cells", f"{cadence}.json"),
                      "w") as fh:
                json.dump(cell_doc, fh, indent=2, default=str)
            print(f"CELL {cadence}: ${r['final']:,.2f} CAGR "
                  f"{r['cagr_pct']:.2f}% DD {r['max_dd_pct']:.1f}% "
                  f"orders {r['orders']} costs ${r['total_costs']:,.2f} "
                  f"halts {len(pf.v9_halt_events)} placebo {beaten}/20",
                  flush=True)
    finally:
        T.Portfolio.floor_check = orig_fc

    money = [c for c in CADENCES
             if cells[c]["final"] > DECADE_SPY_DIV_ADJ
             and cells[c]["placebo_beaten"] is not None
             and cells[c]["placebo_beaten"] >= 11]
    results = {
        "slug": "breakout-validation",
        "area": "Single-name 52-week-high breakout — short-cycle daily "
                "stock style (W9); judged on the DECADE road at every "
                "cadence under the v10 sweep.",
        "area_source": "backtests/v10-retest/SPEC.md, worker batch W9 + "
                       "THE CADENCE SWEEP; task assignment (decade road, "
                       "7 cadences).",
        "native_cadence": "daily-signal",
        "cadence": "daily-signal",
        "original_cadence_foreign": {
            "foreign": False,
            "note": "Original tournament/v3/v9 tests ran the native "
                    "daily-signal form; no foreign cadence was forced. "
                    "The sweep's non-daily cells are the foreign tempos."},
        "cadence_treatment": (
            "Breakout (prior-252-close high) and SMA20 series computed "
            "from daily bars; signal evaluation, MA-exit checks and the "
            "-8% stop are evaluated ONLY on cadence dates (first trading "
            "day of the week / second week / month / quarter / half / "
            "year); decisions fill at the next trading day's open. The "
            "v9 floor is marked and tested every trading day (protection "
            "overlay, not a signal). Daily cell = the original form under "
            "v9 protection."),
        "integrity": integrity,
        "decade_spy_final": DECADE_SPY_DIV_ADJ,
        "decade_spy_note": "Dividend-adjusted per SPEC. The engine's own "
                           "price-only SPY net on the tournament cache "
                           f"is ${spy_net:,.2f} (gross ${spy_gross:,.2f}) "
                           "— the original tournament convention; the "
                           "strategy's bars are likewise not "
                           "dividend-adjusted.",
        "champion_decade": {"final": 65.89,
                            "note": "Value+Momentum champion DECADE final "
                                    "from the lazy-quarterly test, after "
                                    "two halts — its crown rests on the "
                                    "2010 and 2019 roads; printed with "
                                    "that caveat wherever the decade "
                                    "matrix is summarized (SPEC)."},
        "cells": cells,
        "money_cadences": money,
        "placebo_context_original": (
            "Cited, not re-derived: the task records the v9-era "
            "CONT/VAL placebo context for this strategy family as 19/20 "
            "and 8/20. The v3 deep validation's own fixed placebo "
            "(seed 90210, his rules) finished $123.32 full / $117.82 "
            "validation vs the real $383.36 / $124.82."),
        "verdict_area": None,  # filled in RESULTS.md narrative; set below
        "verdict_change": None,
    }
    # verdict fields computed from the sweep outcome
    daily = cells["daily"]
    if money:
        results["verdict_area"] = "OWNS ITS GROUND" if "daily" in money \
            else "REAL BUT SMALL"
    else:
        results["verdict_area"] = "NO GROUND"
    results["verdict_change"] = (
        f"Original verdict DEMOTED stands unless the sweep says otherwise: "
        f"daily-signal cell (native form, v9 protection) finished "
        f"${daily['final']:,.2f} vs dividend-adjusted SPY "
        f"${DECADE_SPY_DIV_ADJ:,.2f}; money cadences (beat SPY AND "
        f"placebos): {money or 'none'}. See RESULTS.md.")
    with open(os.path.join(HERE, "results.json"), "w") as fh:
        json.dump(results, fh, indent=2, default=str)
    print(f"MONEY CADENCES: {money}", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
