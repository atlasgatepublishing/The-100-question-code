#!/usr/bin/env python3
"""
THE GREAT RETEST (v10) - breakout-regime (ONE strategy, ONE clean shot).

Strategy (v4 form, backtests/v4/breakout-regime.py, engine = v2 tournament):
  ENTRY: a name closes at a new 252-day high (close above the highest close
         of the prior 252 sessions) AND the regime gate is open: SPY's close
         on the signal day is above SPY's 200-day average that day.
         Entries fill at the next open.
  SIZE:  max 2 positions, 50% of equity each.
  EXIT:  next open after a close below the name's 20-day average, or a -8%
         intraday stop (stop-first; gaps fill at the open).
  COSTS: 0.10% of trade value per side + $0.01 per sell order.
  UNIVERSE: SPY QQQ NVDA TSLA AAPL MSFT AMZN META AMD AVGO (today's famous
         names - survivorship tilt flatters every number).
  DATA: Yahoo daily bars cached by the v2 tournament (split-adjusted,
         NOT dividend-adjusted), read-only.

This script does three things:
  (1) INTEGRITY: reproduces the ORIGINAL published finals through the
      original v4 module itself, under the ORIGINAL era rules: ladder floor
      ($100 start: floor $85, ladder to $100 at a $125 close, $125 at a
      $150 close; a close at/below the floor liquidates at the next open
      and ENDS the run - no restart), original windows (full / design /
      validation), $100 and $50 pots, original 1-seed placebo (777001).
  (2) SWEEP: DECADE 2016-11-21 -> 2026-11-20, $100/cell, 7 cadences, under
      v9 protections (plain -15% floor from the episode's starting balance,
      NO ladder; first halt: liquidate at next open, sit in cash 90 calendar
      days, restart at the next cadence evaluation date under an episode-2
      floor of -15% from the restart balance; second halt ends the run).
      UNIFORM CADENCE RULE APPLIED: signal evaluation (breakout entry
      signals, the regime-filter evaluation, and the 20-day-average exit
      signals) happens ONLY on cadence dates (at the close); entry and
      MA-exit fills happen at the next trading day's open, as in the
      original. The -8% intraday stop and the -15% floor are risk
      protections and are checked every trading day. Cadence dates:
      daily = every trading day; weekly = first trading day of each ISO
      week; biweekly = first trading day of every second ISO week (weeks
      counted from the first test week); monthly = first trading day of
      each month; quarterly = first trading day of each calendar quarter;
      semi-annual = first trading day of each half-year; annual = first
      trading day of each year.
      The fast sweep runner is validated against the original engine:
      run in original mode (daily cadence, ladder floor, no restart) it
      must reproduce the v4 full-window gated final to the cent.
  (3) PLACEBOS: 20 seeds per cell - random-entry twins with identical
      exits and the same regime filter (attempts only on gate-open cadence
      evaluation dates, filled entries matched per year to the real
      strategy in that cell, original v4 matching design adapted to the
      cadence grid; seeds 777001 + 7919*i, i = 0..19).

Outputs: cells/<cadence>.json, results.json, integrity.json in this folder.
"""

import importlib.util
import json
import os
import sys
from datetime import date, timedelta

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
V2_DIR = os.path.join(ROOT, "v2")
V4_DIR = os.path.join(ROOT, "v4")
sys.path.insert(0, V2_DIR)

import tournament as T  # the exact v2 tournament engine

# Load the original v4 module itself for the integrity reproduction.
spec = importlib.util.spec_from_file_location(
    "breakout_regime_v4", os.path.join(V4_DIR, "breakout-regime.py"))
V4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V4)

UNIVERSE = T.STOCK_UNIVERSE
FULL = (date(2016, 11, 21), date(2026, 11, 20))
DESIGN = (date(2016, 11, 21), date(2022, 12, 31))
VALIDATION = (date(2023, 1, 1), date(2026, 11, 20))
COST_RATE = T.COST_RATE
SELL_FEE = T.SELL_FEE

PUBLISHED_100 = {
    "full_gated_final": 359.44, "full_ungated_final": 383.36,
    "design_gated_final": 327.01, "validation_gated_final": 124.82,
    "validation_placebo_final": 177.92,
    "full_spy_net": 314.10, "validation_spy_net": 179.10,
    "validation_halt": "2026-08-14",
}
PUBLISHED_50 = {
    "full_gated_final": 178.57, "validation_gated_final": 62.25,
    "validation_halt": "2026-08-13",
}


# ----------------------------------------------------------------------------
# (1) INTEGRITY - original v4 module, original era rules (ladder floor)
# ----------------------------------------------------------------------------

def integrity(frames):
    out = {}
    for size, published in ((100, PUBLISHED_100), (50, PUBLISHED_50)):
        cfg = V4.POT_CONFIGS[size]
        rep = {}
        with V4.pot_config(**cfg):
            mkt_full = V4.make_market(frames, FULL)
            pf = V4.run_breakout_regime(mkt_full, "breakout_regime")
            r = T.score(pf, mkt_full.test_dates[0])
            g, n = T.spy_benchmark(mkt_full)
            rep["full_gated"] = r
            rep["full_spy_net"] = n
            rep["full_spy_gross"] = g
            if size == 100:
                _, r_ctl, _, _ = V4.run_window(
                    frames, FULL, "breakout_ungated_control", gate=False)
                rep["full_ungated"] = r_ctl
                _, r_des, _, _ = V4.run_window(
                    frames, DESIGN, "breakout_regime", gate=True)
                rep["design_gated"] = r_des
            _, r_val, _, n_val = V4.run_window(
                frames, VALIDATION, "breakout_regime", gate=True)
            rep["validation_gated"] = r_val
            rep["validation_spy_net"] = n_val
            if size == 100:
                mkt_val = V4.make_market(frames, VALIDATION)
                real_val = V4.run_breakout_regime(mkt_val, "breakout_regime")
                target = V4.entries_by_year(real_val)
                ppf, meta = V4.run_placebo_matched(mkt_val, target)
                rep["validation_placebo"] = T.score(ppf, mkt_val.test_dates[0])
                rep["validation_placebo_meta"] = meta
        out[f"start{size}"] = rep
        print(f"[integrity ${size}] full gated ${rep['full_gated']['final']:,.2f} "
              f"| validation gated ${rep['validation_gated']['final']:,.2f} "
              f"halt {rep['validation_gated']['halt_date']}")
    checks = {
        "full_gated_100": round(out["start100"]["full_gated"]["final"], 2),
        "full_ungated_100": round(out["start100"]["full_ungated"]["final"], 2),
        "design_gated_100": round(out["start100"]["design_gated"]["final"], 2),
        "validation_gated_100": round(out["start100"]["validation_gated"]["final"], 2),
        "validation_placebo_100": round(out["start100"]["validation_placebo"]["final"], 2),
        "full_spy_net_100": round(out["start100"]["full_spy_net"], 2),
        "validation_spy_net_100": round(out["start100"]["validation_spy_net"], 2),
        "validation_halt_100": out["start100"]["validation_gated"]["halt_date"],
        "full_gated_50": round(out["start50"]["full_gated"]["final"], 2),
        "validation_gated_50": round(out["start50"]["validation_gated"]["final"], 2),
        "validation_halt_50": out["start50"]["validation_gated"]["halt_date"],
    }
    expected = {
        "full_gated_100": 359.44, "full_ungated_100": 383.36,
        "design_gated_100": 327.01, "validation_gated_100": 124.82,
        "validation_placebo_100": 177.92, "full_spy_net_100": 314.10,
        "validation_spy_net_100": 179.10, "validation_halt_100": "2026-08-14",
        "full_gated_50": 178.57, "validation_gated_50": 62.25,
        "validation_halt_50": "2026-08-13",
    }
    ok = all(checks[k] == v for k, v in expected.items())
    print(f"[integrity] checks: {checks} -> {'ALL MATCH' if ok else 'MISMATCH'}")
    return out, checks, expected, ok


# ----------------------------------------------------------------------------
# (2) Fast sweep runner (numpy arrays extracted from the tournament frames)
# ----------------------------------------------------------------------------

class Data:
    def __init__(self, frames, mkt):
        self.dates = list(mkt.test_dates)
        self.pos_list = list(mkt.test_pos)
        self.n = len(self.dates)
        self.arr = {}
        for sym in UNIVERSE:
            df = frames[sym]
            self.arr[sym] = {
                k: df[k].to_numpy(dtype=float)
                for k in ("open", "high", "low", "close", "sma20", "sma200",
                          "prior252_high_close")
            }
        spy = self.arr["SPY"]
        self.regime = np.zeros(len(frames["SPY"]), dtype=bool)
        c, m = spy["close"], spy["sma200"]
        valid = ~np.isnan(m)
        self.regime[valid] = c[valid] > m[valid]
        self.regime[:200] = False

    def breakout(self, sym, p):
        if p < 253:
            return False
        ph = self.arr[sym]["prior252_high_close"][p]
        return not np.isnan(ph) and self.arr[sym]["close"][p] > ph


def cadence_eval_indices(data, cadence):
    """Set of test-day indices t that are cadence evaluation dates."""
    dates = data.dates
    if cadence == "daily":
        return set(range(data.n))
    out = set()
    if cadence in ("weekly", "biweekly"):
        weeks = []
        seen = {}
        for t, d in enumerate(dates):
            key = d.isocalendar()[:2]
            if key not in seen:
                seen[key] = len(weeks)
                weeks.append(t)
        if cadence == "weekly":
            out = set(weeks)
        else:
            out = {t for i, t in enumerate(weeks) if i % 2 == 0}
    elif cadence == "monthly":
        seen = set()
        for t, d in enumerate(dates):
            if (d.year, d.month) not in seen:
                seen.add((d.year, d.month)); out.add(t)
    elif cadence == "quarterly":
        seen = set()
        for t, d in enumerate(dates):
            q = (d.year, (d.month - 1) // 3)
            if q not in seen:
                seen.add(q); out.add(t)
    elif cadence == "semiannual":
        seen = set()
        for t, d in enumerate(dates):
            h = (d.year, 0 if d.month <= 6 else 1)
            if h not in seen:
                seen.add(h); out.add(t)
    elif cadence == "annual":
        seen = set()
        for t, d in enumerate(dates):
            if d.year not in seen:
                seen.add(d.year); out.add(t)
    else:
        raise ValueError(cadence)
    return out


def run_fast(data, eval_idx, floor_mode="v9", placebo_sched=None):
    """floor_mode 'original': ladder floor, halt ends the run (validation of
    this runner against the v4 engine). floor_mode 'v9': plain -15% floor,
    90-day cash sit, restart at next cadence date, second halt ends run.
    placebo_sched: {date: [symbols]} entry attempts decided on cadence
    evaluation dates (gate-open dates only), filling next open."""
    A = data.arr
    cash = 100.0
    lots = {}              # sym -> [shares, entry_price]
    curve = []
    orders = 0
    costs = 0.0
    entries_by_year = {}
    pending_entries, pending_exits = [], []
    halts = []
    episode = 1
    floor = 85.0
    halt_pending = False
    halt_trigger = None
    active = True
    restart_on_or_after = None
    restart_record = None
    second_halt = False
    n = data.n

    def equity(price_field, p):
        tot = cash
        for s, (sh, _) in lots.items():
            tot += sh * A[s][price_field][p]
        return tot

    def do_buy(d, p, sym):
        nonlocal cash, orders, costs
        price = A[sym]["open"][p]
        target = 0.5 * equity("open", p)
        value = min(target, cash / (1 + COST_RATE))
        if price <= 0 or value < 1.0:
            return False
        cost = COST_RATE * value
        lots[sym] = [value / price, price]
        cash -= value + cost
        costs += cost
        orders += 1
        entries_by_year[d.year] = entries_by_year.get(d.year, 0) + 1
        return True

    def do_sell(p, sym, price):
        nonlocal cash, orders, costs
        sh = lots.pop(sym)[0]
        value = sh * price
        cost = COST_RATE * value + SELL_FEE
        cash += value - cost
        costs += cost
        orders += 1

    for t in range(n):
        p = data.pos_list[t]
        d = data.dates[t]

        if halt_pending:
            # liquidate at today's open, as the engine does
            for sym in list(lots):
                do_sell(p, sym, A[sym]["open"][p])
            curve.append((d, cash))
            rec = halts[-1]
            rec["liquidation_date"] = d.isoformat()
            rec["liquidation_value"] = round(cash, 4)
            halt_pending = False
            if floor_mode == "original" or episode == 2:
                if episode == 2 and floor_mode == "v9":
                    second_halt = True
                break
            # v9 episode 1: sit in cash 90 calendar days
            active = False
            restart_on_or_after = d + timedelta(days=90)
            continue

        if not active:
            if t in eval_idx and d >= restart_on_or_after:
                episode = 2
                floor = 0.85 * cash
                restart_record = {
                    "restart_date": d.isoformat(),
                    "restart_balance": round(cash, 4),
                    "episode2_floor": round(floor, 4),
                }
                halts[-1]["restart_date"] = d.isoformat()
                active = True
                # fall through: flat day, evaluation happens at the close
            else:
                curve.append((d, cash))
                continue

        # 1) close-signal exits scheduled yesterday fill at today's open
        for sym in pending_exits:
            if sym in lots:
                do_sell(p, sym, A[sym]["open"][p])
        pending_exits = []
        # 2) entries at today's open
        cands, pending_entries = pending_entries, []
        for sym in cands:
            if sym in lots or len(lots) >= 2:
                continue
            do_buy(d, p, sym)
        # 3) intraday -8% stop, stop-first (protection: checked daily)
        for sym in list(lots):
            entry = lots[sym][1]
            o, low = A[sym]["open"][p], A[sym]["low"][p]
            stop_px = entry * (1 - 0.08)
            if o <= stop_px:
                do_sell(p, sym, o)
            elif low <= stop_px:
                do_sell(p, sym, stop_px)
        # 4) mark to close, floor test (protection: checked daily)
        eq = equity("close", p)
        curve.append((d, eq))
        if floor_mode == "original":
            if eq >= 150.0:
                floor = max(floor, 125.0)
            elif eq >= 125.0:
                floor = max(floor, 100.0)
        if eq <= floor:
            halts.append({
                "episode": episode,
                "trigger_date": d.isoformat(),
                "floor_level": round(floor, 4),
                "trigger_equity": round(eq, 4),
                "liquidation_date": None,
            })
            halt_trigger = d
            pending_entries, pending_exits = [], []
            if t == n - 1:
                if episode == 2 and floor_mode == "v9":
                    second_halt = True
                break
            halt_pending = True
            continue
        if t == n - 1:
            break
        # 5) cadence-date evaluation: MA exits + entry signals for tomorrow
        if t in eval_idx:
            for sym in list(lots):
                ma = A[sym]["sma20"][p]
                if not np.isnan(ma) and A[sym]["close"][p] < ma:
                    pending_exits.append(sym)
            if placebo_sched is not None:
                pending_entries = list(placebo_sched.get(d, []))
            elif data.regime[p]:
                for sym in UNIVERSE:
                    if sym not in lots and data.breakout(sym, p):
                        pending_entries.append(sym)

    final = curve[-1][1] if curve else cash
    start_d, end_d = data.dates[0], curve[-1][0]
    years = max((end_d - start_d).days, 1) / 365.25
    cagr = (final / 100.0) ** (1 / years) - 1 if final > 0 else -1.0
    peak, max_dd = 100.0, 0.0
    for _, e in [(start_d, 100.0)] + curve:
        peak = max(peak, e)
        max_dd = max(max_dd, (peak - e) / peak)
    return {
        "final": final, "cagr_pct": cagr * 100, "max_dd_pct": max_dd * 100,
        "costs": costs, "orders": orders,
        "entries": sum(entries_by_year.values()),
        "entries_by_year": {str(k): v for k, v in sorted(entries_by_year.items())},
        "halts": halts, "restart": restart_record is not None,
        "restart_record": restart_record, "second_halt": second_halt,
        "equity_curve": [[d.isoformat(), round(e, 4)] for d, e in curve],
    }


# ----------------------------------------------------------------------------
# (3) Placebos - original v4 matching design adapted to the cadence grid
# ----------------------------------------------------------------------------

def run_placebo_cell(data, eval_idx, target_by_year, seed):
    rng = np.random.default_rng(seed)
    eval_dates = [data.dates[t] for t in sorted(eval_idx)]
    elig = [d for t, d in zip(sorted(eval_idx), eval_dates)
            if data.regime[data.pos_list[t]]]
    elig_by_year = {}
    for d in elig:
        elig_by_year.setdefault(d.year, []).append(d)
    elig_pos = {d: i for i, d in enumerate(elig)}
    schedule = {}

    def add_attempts(year, n_add):
        days = elig_by_year.get(year, [])
        if not days:
            return
        for _ in range(n_add):
            d = days[int(rng.integers(0, len(days)))]
            j = elig_pos[d]
            while len(schedule.get(d, [])) >= 2 and j < len(elig) - 1:
                j += 1
                d = elig[j]
            sym = UNIVERSE[int(rng.integers(0, len(UNIVERSE)))]
            schedule.setdefault(d, []).append(sym)

    for year, target in sorted(target_by_year.items()):
        add_attempts(year, target)
    res, actual = None, {}
    for _ in range(25):
        res = run_fast(data, eval_idx, "v9", placebo_sched=schedule)
        actual = {int(k): v for k, v in res["entries_by_year"].items()}
        missing = {y: target_by_year.get(y, 0) - actual.get(y, 0)
                   for y in target_by_year}
        if all(v <= 0 for v in missing.values()):
            break
        for year, miss in missing.items():
            if miss > 0:
                add_attempts(year, miss)
    return res, {"seed": seed,
                 "attempts": sum(len(v) for v in schedule.values()),
                 "target_by_year": {str(k): v for k, v in target_by_year.items()},
                 "actual_by_year": {str(k): v for k, v in sorted(actual.items())}}


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]

def main():
    print("Loading data (v2 tournament cache, read-only)...")
    frames = V4.build_frames()

    integ, checks, expected, ok = integrity(frames)
    with open(os.path.join(HERE, "integrity.json"), "w") as fh:
        json.dump({"status": "reproduced" if ok else "FAILED",
                   "era_rules": ("ORIGINAL v4 rules: entry = close at new "
                                 "252-day high AND SPY close > SPY 200-day "
                                 "average on the signal day, fill next open; "
                                 "max 2 positions at 50% of equity; exit next "
                                 "open after close below 20-day average or "
                                 "-8% intraday stop; costs 0.10%/side + "
                                 "$0.01/sell; LADDER floor ($85 start, $100 "
                                 "at $125 close, $125 at $150 close at $100; "
                                 "scaled at $50), halt liquidates next open "
                                 "and ENDS the run; windows full/design/"
                                 "validation as published; placebo seed "
                                 "777001, 1 seed, validation window only."),
                   "published": expected, "reproduced": checks,
                   "detail": integ}, fh, indent=2, default=str)

    # Fast-runner validation against the original engine (original mode)
    mkt_full = V4.make_market(frames, FULL)
    data = Data(frames, mkt_full)
    daily_idx = cadence_eval_indices(data, "daily")
    fast_orig = run_fast(data, daily_idx, floor_mode="original")
    engine_final = integ["start100"]["full_gated"]["final"]
    fast_ok = round(fast_orig["final"], 2) == round(engine_final, 2)
    print(f"[fast-runner check] original-mode daily final "
          f"${fast_orig['final']:,.2f} vs engine ${engine_final:,.2f} "
          f"-> {'MATCH' if fast_ok else 'MISMATCH'}")

    # Era price-only SPY benchmark on the decade (= full window), in-engine
    g_spy, n_spy = T.spy_benchmark(mkt_full)
    print(f"[decade SPY] price-only gross ${g_spy:,.2f} net ${n_spy:,.2f} "
          f"(dividend-adjusted reference per SPEC: $367.80)")

    # Regime activity on trading days (daily grid)
    test_pos = data.pos_list
    regime_days_on = int(sum(1 for p in test_pos if data.regime[p]))
    regime_day_frac = regime_days_on / data.n

    cells_dir = os.path.join(HERE, "cells")
    os.makedirs(cells_dir, exist_ok=True)
    cells = {}
    money = []
    for cad in CADENCES:
        eval_idx = cadence_eval_indices(data, cad)
        res = run_fast(data, eval_idx, "v9")
        eval_on = sum(1 for t in eval_idx if data.regime[data.pos_list[t]])
        regime_info = {
            "eval_dates": len(eval_idx),
            "regime_on_eval_dates": eval_on,
            "regime_off_eval_dates": len(eval_idx) - eval_on,
            "regime_on_fraction": round(eval_on / len(eval_idx), 4),
            "regime_on_trading_days": regime_days_on,
            "regime_on_trading_day_fraction": round(regime_day_frac, 4),
        }
        target = {int(k): v for k, v in res["entries_by_year"].items()}
        twin_finals, twin_meta = [], []
        for i in range(20):
            seed = 777001 + 7919 * i
            pres, pmeta = run_placebo_cell(data, eval_idx, target, seed)
            twin_finals.append(round(pres["final"], 4))
            twin_meta.append(pmeta)
        beaten = sum(1 for f in twin_finals if res["final"] > f)
        cell = {
            "cadence": cad, "final": round(res["final"], 2),
            "cagr_pct": round(res["cagr_pct"], 2),
            "max_dd_pct": round(res["max_dd_pct"], 2),
            "costs": round(res["costs"], 2), "orders": res["orders"],
            "entries": res["entries"],
            "halts": len(res["halts"]), "halt_records": res["halts"],
            "restart": res["restart"], "restart_record": res["restart_record"],
            "second_halt": res["second_halt"],
            "placebo_beaten": beaten, "placebo_twin_finals": twin_finals,
            "placebo_meta": twin_meta,
            "regime": regime_info,
            "equity_curve": res["equity_curve"],
        }
        with open(os.path.join(cells_dir, f"{cad}.json"), "w") as fh:
            json.dump(cell, fh, indent=2)
        cells[cad] = {k: cell[k] for k in (
            "final", "cagr_pct", "max_dd_pct", "costs", "orders", "entries",
            "halts", "restart", "second_halt", "placebo_beaten")}
        cells[cad]["regime_on_fraction"] = regime_info["regime_on_fraction"]
        if res["final"] > 367.80 and beaten == 20:
            money.append(cad)
        print(f"[{cad}] final ${res['final']:,.2f} CAGR {res['cagr_pct']:+.2f}% "
              f"DD {res['max_dd_pct']:.1f}% costs ${res['costs']:,.2f} "
              f"orders {res['orders']} halts {len(res['halts'])} "
              f"restart {res['restart']} 2nd {res['second_halt']} "
              f"placebo beaten {beaten}/20 regime-on "
              f"{regime_info['regime_on_fraction']:.1%}")

    results = {
        "slug": "breakout-regime",
        "area": ("Short-cycle daily-signal stock style with a market-regime "
                 "filter (v4 combination test of the demoted v2/v3 breakout) "
                 "- judged on the DECADE cadence sweep, its original road."),
        "area_source": "SPEC W12 + CADENCE GRID: breakout-regime - daily-signal.",
        "cadence": "daily-signal",
        "native_cadence": "daily",
        "original_cadence_foreign": False,
        "original_cadence_note": ("Original v4 test ran the native daily-signal "
                                  "form; no foreign cadence was forced."),
        "integrity": {
            "status": "reproduced" if ok else "FAILED",
            "fast_runner_crosscheck": ("original-mode daily run of the sweep "
                                       "runner vs the v4 engine full-window "
                                       f"gated final: {'MATCH' if fast_ok else 'MISMATCH'} "
                                       f"(${fast_orig['final']:,.2f})"),
            "original_finals": expected,
            "reproduced_finals": checks,
        },
        "decade_spy_final": 367.80,
        "decade_spy_note": ("Dividend-adjusted SPY buy-and-hold on the decade "
                            "per SPEC reference ($367.80). Era price-only "
                            f"benchmark from this strategy's own plumbing: "
                            f"gross ${g_spy:,.2f}, net ${n_spy:,.2f} (the "
                            "original v4 report's SPY net figure)."),
        "champion_decade_final": 65.89,
        "champion_decade_note": ("Champion (value+momentum) decade final "
                                 "$65.89 after two halts - its crown rests on "
                                 "the 2010 and 2019 roads; printed with the "
                                 "SPEC caveat."),
        "sweep_rules": ("DECADE 2016-11-21 -> 2026-11-20, $100/cell, program "
                        "costs (0.10%/side + $0.01/sell), point-in-time era "
                        "data, v9 protections (plain -15% floor per episode, "
                        "90-day cash sit, restart at next cadence date, "
                        "second halt ends). Uniform cadence rule: breakout "
                        "signals, regime-filter evaluation and 20-day exit "
                        "signals evaluated ONLY on cadence dates (close); "
                        "fills at next open; -8% stop and -15% floor checked "
                        "daily as protections. Substitution vs original era "
                        "rules stated plainly: ladder floor -> v9 plain "
                        "floor with restart; everything else unchanged."),
        "cells": cells,
        "money_cadences": money,
        "verdict_area": None,  # filled in RESULTS.md / coordinator review
        "verdict_change": None,
    }
    with open(os.path.join(HERE, "results.json"), "w") as fh:
        json.dump(results, fh, indent=2)
    print("Wrote cells/, results.json, integrity.json")


if __name__ == "__main__":
    main()
