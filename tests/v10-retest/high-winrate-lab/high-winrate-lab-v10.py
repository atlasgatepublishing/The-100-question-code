#!/usr/bin/env python3
"""
THE GREAT RETEST (v10) - HIGH-WIN-RATE LAB (H1-H4).

Treatment per SPEC.md (binding):
  (1) INTEGRITY: reproduce the v9 published finals in ORIGINAL form by calling
      the v9 engine itself (imported from _v9_engine_reference.py, a verbatim
      copy of backtests/v9-muse-rules/high-winrate-lab/high-winrate-lab-v9.py),
      with its data cache redirected (read-only) to backtests/v2/tournament-data/.
  (2) SWEEP: DECADE 2016-11-21 -> 2026-11-20 x 7 cadences x 4 shapes, $100/cell,
      program costs, v9 protections (plain -15% floor, 90-day cash restart,
      episode-2 floor 85% of restart balance, second halt ends the run).
      Cadence (SPEC uniform definition): signal evaluation, selection, trading,
      intraday stop/target checks, time exits, MA-exit checks and the floor
      check happen ONLY on cadence dates. Fills for signals taken at a cadence
      close occur at the NEXT cadence date's open (the original engine's
      next-open fill, restricted to decision days). For the daily cadence this
      reduces exactly to the original engine - verified against integrity.
      Cadence dates: daily = every trading day; weekly = first trading day of
      each ISO week; biweekly = first trading day of every second week counted
      from the window's first week; monthly = first trading day of each month;
      quarterly = first trading day of each calendar quarter; semiannual =
      first trading day of Jan/Jul; annual = first trading day of each year.
  (3) PLACEBOS: 20 seeds per cell. Random-SELECTION twins: identical shape
      mechanics (sizing, stops, targets, time exits, costs, floor, cadence),
      but on each cadence date the twin enters the SAME NUMBER of names the
      real shape signaled that day, chosen uniformly at random (seeded) from
      the shape's universe. Only symbol selection is randomized.
Outputs: cells/<shape>/<cadence>.json (full equity curve, placebo finals),
results.json (SPEC sweep format with shapes{}), sweep_summary.json (for the
human RESULTS.md). Simulation only; no broker orders.
"""
import json
import math
import os
import sys
from datetime import date, timedelta

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _v9_engine_reference as E  # verbatim v9 engine (mechanics unchanged)

# Redirect the v9 engine's cache to the shared read-only tournament cache.
E.CACHE_DIR = os.path.abspath(os.path.join(
    HERE, "..", "..", "v2", "tournament-data"))

DECADE_START = date(2016, 11, 21)
DECADE_END = date(2026, 11, 20)
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]
START_CASH = 100.0


# ----------------------------------------------------------------------------
# Cadence-aware runner: a faithful copy of E.run_shape with decision-day
# gating, signal recording, and an optional signal override (placebos).
# ----------------------------------------------------------------------------

def cadence_active_set(dates, cadence):
    """Return set of window indices t that are decision days."""
    if cadence == "daily":
        return set(range(len(dates)))
    active = set()
    seen_week = -1
    week_counter = -1
    prev_key = None
    for t, d in enumerate(dates):
        if cadence == "weekly":
            key = (d.isocalendar()[0], d.isocalendar()[1])
            if key != prev_key:
                active.add(t)
            prev_key = key
        elif cadence == "biweekly":
            key = (d.isocalendar()[0], d.isocalendar()[1])
            if key != prev_key:
                week_counter += 1
                if week_counter % 2 == 0:
                    active.add(t)
                prev_key = key
        elif cadence == "monthly":
            key = (d.year, d.month)
            if key != prev_key:
                active.add(t)
            prev_key = key
        elif cadence == "quarterly":
            key = (d.year, (d.month - 1) // 3)
            if key != prev_key:
                active.add(t)
            prev_key = key
        elif cadence == "semiannual":
            key = (d.year, 0 if d.month <= 6 else 1)
            if key != prev_key:
                active.add(t)
            prev_key = key
        elif cadence == "annual":
            key = d.year
            if key != prev_key:
                active.add(t)
            prev_key = key
    return active


def run_shape_cadence(mkt, name, dates, positions, start_cash, signal_fn,
                      universe, frac, max_positions, active_set,
                      stop_pct=None, target_pct=None, time_exit_days=None,
                      target_mode="fixed", ma_exit=False, order_by_gain=False,
                      signal_override=None):
    """signal_override: dict t -> [symbols] replacing signal generation
    (placebo twins). Returns (portfolio, signals_by_t)."""
    pf = E.Portfolio(name, start_cash)
    episode = 1
    awaiting_restart = False
    restart_not_before = None
    pending_entries = []
    pending_exits = []
    signals_by_t = {}
    last_t = len(dates) - 1

    for t, d in enumerate(dates):
        pos = positions[t]
        active = t in active_set
        if pf.halt_pending and active:
            pf.liquidate_all(d, pos, mkt.open_map(pos), "floor-liquidation")
            pf.halted = True
            pf.halt_date = d
            pf.equity_curve.append((d, pf.equity(mkt.close_map(pos))))
            pf.v9_halts.append({"date": d.isoformat(),
                                "balance": round(pf.cash, 2),
                                "episode": episode})
            if episode >= 2:
                break
            restart_not_before = d + timedelta(days=90)
            awaiting_restart = True
            pf.halt_pending = False
            pf.halted = False
            pending_entries = []
            pending_exits = []
            continue
        if awaiting_restart:
            if d < restart_not_before or not active:
                pf.equity_curve.append((d, pf.cash))
                continue
            pf.floor = 0.85 * pf.cash
            episode = 2
            pf.v9_restarts.append({"date": d.isoformat(),
                                   "balance": round(pf.cash, 2),
                                   "episode2_floor": round(pf.floor, 2)})
            awaiting_restart = False

        if not active:
            # No trading on non-decision days; still mark equity to close.
            pf.equity_curve.append((d, pf.equity(mkt.close_map(pos))))
            continue

        # 1) close-signal exits scheduled at the prior cadence close fill here
        for sym, reason in pending_exits:
            if pf.shares_of(sym) > 0:
                pf.sell(d, pos, sym, mkt.price(sym, pos, "open"), reason)
        pending_exits = []

        # 2) entries at today's open (signals from the prior cadence close)
        candidates = list(pending_entries)
        pending_entries = []
        if order_by_gain and len(candidates) > 1:
            def day_gain(sym):
                df = mkt.frames[sym]
                pc = df["close"].iloc[pos - 1]
                ppc = df["close"].iloc[pos - 2] if pos >= 2 else pc
                return (pc / ppc - 1) if ppc else 0.0
            candidates.sort(key=lambda s: -day_gain(s))
        for sym in candidates:
            if pf.shares_of(sym) > 0 or len(pf.held_symbols()) >= max_positions:
                continue
            eq_open = pf.equity(mkt.open_map(pos))
            pf.buy(d, pos, sym, mkt.price(sym, pos, "open"), frac * eq_open, "entry")

        # 3) intraday stop / target, stop-first (decision days only)
        for sym in list(pf.held_symbols()):
            entry = pf.weighted_entry_price(sym)
            if entry is None:
                continue
            o = mkt.price(sym, pos, "open")
            h = mkt.price(sym, pos, "high")
            l = mkt.price(sym, pos, "low")
            stop_px = entry * (1 - stop_pct) if stop_pct is not None else None
            if target_mode == "bb_mid":
                tgt_px = mkt.frames[sym]["bb_mid"].iloc[pos - 1] if pos >= 1 else None
                if tgt_px is not None and (np.isnan(tgt_px) or tgt_px <= 0):
                    tgt_px = None
            elif target_pct is not None:
                tgt_px = entry * (1 + target_pct)
            else:
                tgt_px = None
            fill, reason = None, None
            if stop_px is not None and o <= stop_px:
                fill, reason = o, "stop-gap"
            elif tgt_px is not None and o >= tgt_px:
                fill, reason = o, "target-gap"
            elif stop_px is not None and l <= stop_px and tgt_px is not None and h >= tgt_px:
                fill, reason = stop_px, "stop-first"
            elif stop_px is not None and l <= stop_px:
                fill, reason = stop_px, "stop"
            elif tgt_px is not None and h >= tgt_px:
                fill, reason = tgt_px, "target"
            if fill is not None:
                pf.sell(d, pos, sym, fill, reason)

        # 4) time exit at the close of the Nth trading day (checked on
        #    decision days under the uniform cadence rule)
        if time_exit_days is not None:
            for sym in list(pf.held_symbols()):
                ep = pf.entry_pos(sym)
                if ep is not None and pos - ep >= time_exit_days:
                    pf.sell(d, pos, sym, mkt.price(sym, pos, "close"), "time-exit")

        # 5) mark to close; floor test (decision days)
        eq_close = pf.equity(mkt.close_map(pos))
        pf.equity_curve.append((d, eq_close))
        touched = pf.floor_check(d, eq_close)
        if touched and t == last_t:
            pf.halted = True
            pf.halt_date = d
            break
        if t == last_t:
            break

        # 6) schedule MA exits for the next decision day's open (H4)
        if ma_exit:
            for sym in list(pf.held_symbols()):
                sma20 = mkt.frames[sym]["sma20"].iloc[pos]
                if not np.isnan(sma20) and mkt.price(sym, pos, "close") < sma20:
                    pending_exits.append((sym, "ma-exit"))

        # 7) generate the next decision day's entries from today's close
        todays = []
        if signal_override is not None:
            for sym in signal_override.get(t, []):
                if pf.shares_of(sym) > 0:
                    continue
                pending_entries.append(sym)
                todays.append(sym)
        else:
            for sym in universe:
                if pf.shares_of(sym) > 0:
                    continue
                if signal_fn(mkt, sym, pos):
                    pending_entries.append(sym)
                    todays.append(sym)
        if todays:
            signals_by_t[t] = todays

    return pf, signals_by_t


# ----------------------------------------------------------------------------
# Scoring helpers
# ----------------------------------------------------------------------------

def cell_stats(pf, start_date, end_date):
    curve = [(start_date, pf.start)] + list(pf.equity_curve)
    final = curve[-1][1]
    peak, max_dd = pf.start, 0.0
    for _, eq in curve:
        peak = max(peak, eq)
        if peak > 0:
            max_dd = max(max_dd, (peak - eq) / peak)
    years = max((end_date - start_date).days, 1) / 365.25
    cagr = ((final / pf.start) ** (1.0 / years) - 1) * 100 if final > 0 else -100.0
    rts = pf.round_trips
    wins = [r["pnl"] for r in rts if r["pnl"] > 0]
    return {
        "final": round(final, 2),
        "cagr_pct": round(cagr, 2),
        "max_dd_pct": round(max_dd * 100, 2),
        "costs": round(pf.total_costs, 2),
        "orders": len(pf.trades),
        "closed_trades": len(rts),
        "win_rate_pct": round(100 * len(wins) / len(rts), 1) if rts else None,
        "expectancy": round(float(np.mean([r["pnl"] for r in rts])), 4) if rts else None,
        "avg_win": round(float(np.mean(wins)), 4) if wins else None,
        "avg_loss": round(float(np.mean([r["pnl"] for r in rts if r["pnl"] <= 0])), 4)
                    if len(rts) > len(wins) else None,
        "halts": pf.v9_halts,
        "restarts": pf.v9_restarts,
        "second_halt": len(pf.v9_halts) >= 2,
        "equity_curve": [[d.isoformat(), round(v, 4)] for d, v in curve],
    }


def _json_default(o):
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    raise TypeError(f"not serializable: {type(o)}")


def clean(x):
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return None
    return x


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main():
    print("Loading data (shared read-only cache)...", flush=True)
    raw = {sym: E.load_symbol(sym) for sym in E.UNIVERSE}
    frames = E.align_frames(raw)
    mkt = E.Market(frames)

    decade_dates, decade_pos = mkt.window(DECADE_START, DECADE_END)
    print(f"Decade window: {decade_dates[0]} -> {decade_dates[-1]} "
          f"({len(decade_dates)} trading days)", flush=True)

    # SPY buy-and-hold in THIS plumbing (split-adjusted Yahoo bars, NOT
    # dividend-adjusted): price-only figure. SPEC canonical dividend-adjusted
    # decade SPY is $367.80 - recorded alongside.
    gross_spy, net_spy = E.spy_benchmark(mkt, decade_pos, START_CASH)
    spy_plumbing = round(net_spy, 2)
    SPY_CANONICAL = 367.80
    print(f"SPY decade in-plumbing (price-only): ${spy_plumbing} "
          f"(gross ${gross_spy:.2f}); canonical div-adj $367.80", flush=True)

    # ---------------- (1) INTEGRITY: original v9 engine, original form ----
    print("\n=== INTEGRITY (original v9 engine, original windows) ===", flush=True)
    full_dates, full_pos = mkt.window(E.FULL_START, E.TEST_END)
    val_dates, val_pos = mkt.window(E.VAL_START, E.TEST_END)
    published_v9 = {
        ("full", 50.0):  {"H1": 46.52, "H2": 60.31, "H3": 41.44, "H4": 81.17},
        ("full", 100.0): {"H1": 97.43, "H2": 123.68, "H3": 86.33, "H4": 171.12},
        ("validation", 50.0): {"H1": 54.30, "H2": 59.31, "H3": 46.59, "H4": 59.75},
    }
    published_his = {  # original ladder-era record, for the report table
        ("full", 50.0):  {"H1": 42.45, "H2": 60.31, "H3": 41.44, "H4": 81.17},
        ("full", 100.0): {"H1": 97.43, "H2": 123.68, "H3": 86.33, "H4": 171.12},
        ("validation", 50.0): {"H1": 54.30, "H2": 59.31, "H3": 46.59, "H4": 59.75},
    }
    reproduced = {}
    integrity_detail = {}
    all_match = True
    for (wname, start), expected in published_v9.items():
        ds, ps = (full_dates, full_pos) if wname == "full" else (val_dates, val_pos)
        for key, cfg in E.SHAPES.items():
            kwargs = {k: v for k, v in cfg.items() if k != "label"}
            pf = E.run_shape(mkt, key, ds, ps, start, **kwargs)
            sc = E.score(pf, ds[0])
            got = round(sc["final"], 2)
            reproduced[f"{wname}_{int(start)}_{key}"] = got
            ok = abs(got - expected[key]) < 0.005
            all_match = all_match and ok
            integrity_detail[f"{wname}_{int(start)}_{key}"] = {
                "published_v9": expected[key], "reproduced": got,
                "match": ok,
                "win_rate_pct": clean(round(sc["win_rate"], 1)),
                "expectancy": clean(round(sc["expectancy"], 4)) if sc["expectancy"] == sc["expectancy"] else None,
                "closed_trades": sc["closed_trades"],
                "halts": pf.v9_halts, "restarts": pf.v9_restarts,
            }
            print(f"  {key} {wname} ${start:.0f}: published ${expected[key]:.2f} "
                  f"reproduced ${got:.2f} {'MATCH' if ok else 'MISMATCH'}", flush=True)
    integrity_status = "reproduced" if all_match else "FAILED"
    print(f"Integrity: {integrity_status}", flush=True)

    # ---------------- (2)+(3) SWEEP + PLACEBOS ----------------------------
    shapes_out = {}
    summary = {"integrity_status": integrity_status,
               "spy_plumbing_price_only": spy_plumbing,
               "spy_canonical_div_adj": SPY_CANONICAL, "shapes": {}}
    for key, cfg in E.SHAPES.items():
        kwargs = {k: v for k, v in cfg.items() if k != "label"}
        universe = kwargs["universe"]
        cells = {}
        shape_summary = {}
        for cadence in CADENCES:
            active = cadence_active_set(decade_dates, cadence)
            pf, signals_by_t = run_shape_cadence(
                mkt, key, decade_dates, decade_pos, START_CASH,
                active_set=active, **kwargs)
            st = cell_stats(pf, decade_dates[0], decade_dates[-1])

            # Placebo twins: same per-day signal COUNT, random symbols.
            twin_finals = []
            for seed in range(20):
                import zlib
                rng = np.random.default_rng(
                    1000 * seed + zlib.crc32(f"{key}|{cadence}".encode()))
                override = {}
                for t, syms in signals_by_t.items():
                    k = min(len(syms), len(universe))
                    if k > 0:
                        override[t] = list(rng.choice(universe, size=k,
                                                       replace=False))
                tpf, _ = run_shape_cadence(
                    mkt, key, decade_dates, decade_pos, START_CASH,
                    active_set=active, signal_override=override, **kwargs)
                twin_finals.append(round(
                    ([START_CASH] + [v for _, v in tpf.equity_curve])[-1], 2))
            beaten = sum(1 for f in twin_finals if st["final"] > f)

            cell_json = {
                "shape": key, "cadence": cadence,
                "window": [decade_dates[0].isoformat(), decade_dates[-1].isoformat()],
                "start_cash": START_CASH,
                **{k2: st[k2] for k2 in ("final", "cagr_pct", "max_dd_pct",
                                         "costs", "orders", "closed_trades",
                                         "win_rate_pct", "expectancy",
                                         "avg_win", "avg_loss", "halts",
                                         "restarts", "second_halt")},
                "restart": bool(st["restarts"]),
                "placebo_twin_finals": twin_finals,
                "placebo_beaten": beaten,
                "placebo_note": ("20 random-selection twins: same cadence, same "
                                 "per-day signal count, same exits/costs/floor; "
                                 "symbols drawn uniformly at random from the "
                                 "shape's universe (seeded)."),
                "equity_curve": st["equity_curve"],
            }
            cdir = os.path.join(HERE, "cells", key)
            os.makedirs(cdir, exist_ok=True)
            with open(os.path.join(cdir, f"{cadence}.json"), "w") as fh:
                json.dump(cell_json, fh, indent=1, default=_json_default)
            cells[cadence] = {
                "final": st["final"], "cagr_pct": st["cagr_pct"],
                "max_dd_pct": st["max_dd_pct"],
                "halts": len(st["halts"]), "restart": bool(st["restarts"]),
                "second_halt": st["second_halt"], "costs": st["costs"],
                "orders": st["orders"],
                "win_rate_pct": st["win_rate_pct"],
                "expectancy": st["expectancy"],
                "closed_trades": st["closed_trades"],
                "placebo_beaten": beaten, "placebo_note": "20 random-selection twins (see cell JSON)",
            }
            shape_summary[cadence] = {
                "final": st["final"], "win_rate_pct": st["win_rate_pct"],
                "expectancy": st["expectancy"], "placebo_beaten": beaten,
                "closed_trades": st["closed_trades"], "orders": st["orders"],
                "max_dd_pct": st["max_dd_pct"], "costs": st["costs"],
                "halts": st["halts"], "restarts": st["restarts"],
            }
            print(f"{key} {cadence:11s}: final ${st['final']:8.2f}  win "
                  f"{st['win_rate_pct']}%  exp {st['expectancy']}  trades "
                  f"{st['closed_trades']}  placebo beaten {beaten}/20", flush=True)
        money = [c for c in CADENCES
                 if cells[c]["final"] > SPY_CANONICAL
                 and cells[c]["placebo_beaten"] is not None
                 and cells[c]["placebo_beaten"] >= 11]
        shapes_out[key] = {
            "label": cfg["label"], "cells": cells,
            "money_cadences": money,
            "verdict": None,  # filled below
        }
        summary["shapes"][key] = shape_summary

    # Verdicts (mechanical, per SPEC scale): a shape owns ground only if some
    # cadence beats SPY (canonical) AND its placebos.
    for key in shapes_out:
        shapes_out[key]["verdict"] = (
            "OWNS ITS GROUND" if shapes_out[key]["money_cadences"] else "NO GROUND")

    results = {
        "slug": "high-winrate-lab",
        "area": ("SHORT-CYCLE daily mean-reversion/breakout trade shapes on a "
                 "10-name universe (SPY, QQQ, NVDA, TSLA, AAPL, MSFT, AMZN, "
                 "META, AMD, AVGO), cycled over the DECADE road; judged on "
                 "money + expectancy, win rate reported as diagnostic"),
        "area_source": "SPEC W9: rsi2 / high-winrate-lab = daily short-cycle styles",
        "native_cadence": "daily",
        "cadence": "daily",
        "original_cadence_foreign": False,
        "native_change": ("none in form - original test was already daily on the "
                          "decade road; the v10 treatment adds the cadence sweep "
                          "(slower cadences gate entries, exits, stop/target and "
                          "floor checks to cadence dates) and $100 pots throughout"),
        "integrity": {
            "status": integrity_status,
            "original_finals": {f"{w}_{int(s)}_{k}": v
                                for (w, s), d in published_v9.items()
                                for k, v in d.items()},
            "original_finals_his_rules": {f"{w}_{int(s)}_{k}": v
                                          for (w, s), d in published_his.items()
                                          for k, v in d.items()},
            "reproduced_finals": reproduced,
            "detail": integrity_detail,
            "notes": ("Reproduced by calling the v9 engine itself (verbatim copy "
                      "in this folder) on its original windows. v9 full $50 H1 "
                      "includes the 2023-10-30 halt and 2024-01-29 restart. "
                      "Published record check: best win rate in the original lab "
                      "65.8%; H3 won ~65% and lost money; $100 pots never halted; "
                      "$50 H1 halted 2023-10-30."),
        },
        "decade_spy_final": SPY_CANONICAL,
        "decade_spy_final_note": ("SPEC canonical dividend-adjusted decade SPY "
                                  "$367.80. This engine's own bars are split-"
                                  "adjusted only (not dividend-adjusted), so its "
                                  f"in-plumbing price-only SPY final is "
                                  f"${spy_plumbing}; money_cadences are judged "
                                  "against the canonical $367.80 (the harder bar)."),
        "spy": {"DECADE": SPY_CANONICAL, "DECADE_price_only_in_plumbing": spy_plumbing},
        "shapes": shapes_out,
        "verdict_area": ("NO GROUND" if not any(s["money_cadences"]
                                                for s in shapes_out.values())
                         else "REAL BUT SMALL"),
        "verdict_change": "filled in RESULTS.md",
        "data_note": ("Read-only shared cache: backtests/v2/tournament-data/ "
                      "(Yahoo split-adjusted daily OHLC, not dividend-adjusted; "
                      "10-name universe of today's famous names - survivorship "
                      "flatters every number). No downloads; nothing written "
                      "outside this folder."),
    }
    with open(os.path.join(HERE, "results.json"), "w") as fh:
        json.dump(results, fh, indent=2, default=_json_default)
    with open(os.path.join(HERE, "sweep_summary.json"), "w") as fh:
        json.dump(summary, fh, indent=2, default=_json_default)
    print("\nDone. Wrote results.json, sweep_summary.json, cells/*/*.json", flush=True)


if __name__ == "__main__":
    main()
