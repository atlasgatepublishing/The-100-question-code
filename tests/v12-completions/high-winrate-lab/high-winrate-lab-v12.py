#!/usr/bin/env python3
"""
V12 COMPLETIONS - HIGH-WINRATE LAB (H1-H4).

NO-NATIVE-FORM program construction (v11 SCOREBOARD S6). There is nothing
to construct: the frozen v9 program spec IS this family's only form. This
script (frozen by CONSTRUCTION-SPEC.md before any run):

  (1) INTEGRITY: re-runs the original v9 engine (verbatim copy in this
      folder, _v9_engine_reference.py) on its original windows and checks
      all 12 published finals to the cent.
  (2) ROADS: the four frozen shapes, $100 pots, DAILY cadence (the lab's
      native tempo), program costs (0.10%/side + $0.01/sell), v9
      protections (plain -15% floor, 90-day cash restart, episode-2 floor
      85% of restart balance, second halt ends the run), on the standard
      roads available in this plumbing: DECADE 2016-11-21 -> 2026-11-20,
      CONT 2019-01-01 -> 2026-11-20, VAL 2023-01-01 -> 2026-11-20.
      (LONG 2010 is impossible here: the frozen shared cache begins
      2015-01-02 - named in CONSTRUCTION-SPEC.md.)
  (3) PLACEBOS: 20 random-selection twins per shape x road - same per-day
      signal count, same exits/costs/floor; only symbols randomized,
      seeded exactly as v10 seeded them (1000*k + crc32("shape|daily")),
      so DECADE placebo counts compare directly to v10's published counts.

The daily runner below is v10's cadence runner with the active set = all
days (v10 verified it reduces exactly to the original engine at daily).
Outputs: cells/<shape>/<road>.json (full equity curve + placebo finals),
results.json (curves + all stats). Simulation only; no broker orders.
Data: read-only shared cache backtests/v2/tournament-data/ (Yahoo
split-adjusted daily bars, NOT dividend-adjusted).
"""
import json
import math
import os
import sys
import zlib
from datetime import date, timedelta

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _v9_engine_reference as E  # verbatim v9 engine (mechanics unchanged)

E.CACHE_DIR = os.path.abspath(os.path.join(
    HERE, "..", "..", "v2", "tournament-data"))

ROADS = {
    "DECADE": (date(2016, 11, 21), date(2026, 11, 20)),
    "CONT":   (date(2019, 1, 1),   date(2026, 11, 20)),
    "VAL":    (date(2023, 1, 1),   date(2026, 11, 20)),
}
START_CASH = 100.0
# Program canonical (dividend-adjusted) references, from v12 PROGRAM.md.
SPY_CANONICAL = {"DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
CHAMPION_VM = {"DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}


# ----------------------------------------------------------------------------
# Daily runner: faithful copy of E.run_shape with signal recording and an
# optional signal override (placebo twins). Identical to v10's runner with
# every day active.
# ----------------------------------------------------------------------------

def run_shape_daily(mkt, name, dates, positions, start_cash, signal_fn,
                    universe, frac, max_positions, stop_pct=None,
                    target_pct=None, time_exit_days=None, target_mode="fixed",
                    ma_exit=False, order_by_gain=False, signal_override=None):
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
        if pf.halt_pending:
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
            if d < restart_not_before:
                pf.equity_curve.append((d, pf.cash))
                continue
            pf.floor = 0.85 * pf.cash
            episode = 2
            pf.v9_restarts.append({"date": d.isoformat(),
                                   "balance": round(pf.cash, 2),
                                   "episode2_floor": round(pf.floor, 2)})
            awaiting_restart = False

        # 1) close-signal exits scheduled yesterday fill at today's open
        for sym, reason in pending_exits:
            if pf.shares_of(sym) > 0:
                pf.sell(d, pos, sym, mkt.price(sym, pos, "open"), reason)
        pending_exits = []

        # 2) entries at today's open (signals from yesterday's close)
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

        # 3) intraday stop / target, stop-first
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

        # 4) time exit at the close of the Nth trading day
        if time_exit_days is not None:
            for sym in list(pf.held_symbols()):
                ep = pf.entry_pos(sym)
                if ep is not None and pos - ep >= time_exit_days:
                    pf.sell(d, pos, sym, mkt.price(sym, pos, "close"), "time-exit")

        # 5) mark to close; floor test
        eq_close = pf.equity(mkt.close_map(pos))
        pf.equity_curve.append((d, eq_close))
        touched = pf.floor_check(d, eq_close)
        if touched and t == last_t:
            pf.halted = True
            pf.halt_date = d
            break
        if t == last_t:
            break

        # 6) schedule MA exits for tomorrow's open (H4)
        if ma_exit:
            for sym in list(pf.held_symbols()):
                sma20 = mkt.frames[sym]["sma20"].iloc[pos]
                if not np.isnan(sma20) and mkt.price(sym, pos, "close") < sma20:
                    pending_exits.append((sym, "ma-exit"))

        # 7) generate tomorrow's entries from today's close
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
    losses = [r["pnl"] for r in rts if r["pnl"] <= 0]
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
        "avg_loss": round(float(np.mean(losses)), 4) if losses else None,
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


def main():
    print("Loading data (shared read-only cache)...", flush=True)
    raw = {sym: E.load_symbol(sym) for sym in E.UNIVERSE}
    frames = E.align_frames(raw)
    mkt = E.Market(frames)

    # ---------------- (1) INTEGRITY: original v9 engine, original form ----
    print("\n=== INTEGRITY (original v9 engine, original windows) ===", flush=True)
    full_dates, full_pos = mkt.window(E.FULL_START, E.TEST_END)
    val_dates, val_pos = mkt.window(E.VAL_START, E.TEST_END)
    published_v9 = {
        ("full", 50.0):  {"H1": 46.52, "H2": 60.31, "H3": 41.44, "H4": 81.17},
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
                "published_v9": expected[key], "reproduced": got, "match": ok,
                "win_rate_pct": clean(round(sc["win_rate"], 1)),
                "expectancy": clean(round(sc["expectancy"], 4)),
                "avg_win": clean(round(sc["avg_win"], 4)),
                "avg_loss": clean(round(sc["avg_loss"], 4)),
                "closed_trades": sc["closed_trades"],
                "max_dd_pct": clean(round(sc["max_dd_pct"], 2)),
                "halts": pf.v9_halts, "restarts": pf.v9_restarts,
            }
            print(f"  {key} {wname} ${start:.0f}: published ${expected[key]:.2f} "
                  f"reproduced ${got:.2f} {'MATCH' if ok else 'MISMATCH'}", flush=True)
    integrity_status = "reproduced" if all_match else "FAILED"
    print(f"Integrity: {integrity_status}", flush=True)

    # ---------------- (2)+(3) ROADS + PLACEBOS (daily) --------------------
    shapes_out = {}
    for key, cfg in E.SHAPES.items():
        kwargs = {k: v for k, v in cfg.items() if k != "label"}
        universe = kwargs["universe"]
        roads_out = {}
        for road, (rstart, rend) in ROADS.items():
            existing = os.path.join(HERE, "cells", key, f"{road}.json")
            if os.path.exists(existing):
                with open(existing) as fh:
                    cell_json = json.load(fh)
                roads_out[road] = {k2: cell_json[k2] for k2 in (
                    "final", "cagr_pct", "max_dd_pct", "costs", "orders",
                    "closed_trades", "win_rate_pct", "expectancy", "avg_win",
                    "avg_loss", "halts", "restarts", "second_halt",
                    "spy_in_plumbing_price_only", "spy_canonical_div_adj",
                    "champion_vm", "placebo_beaten", "placebo_twin_finals",
                    "equity_curve")}
                print(f"{key} {road:7s}: loaded saved cell "
                      f"(final ${cell_json['final']})", flush=True)
                continue
            dates, positions = mkt.window(rstart, rend)
            _, net_spy = E.spy_benchmark(mkt, positions, START_CASH)
            pf, signals_by_t = run_shape_daily(
                mkt, key, dates, positions, START_CASH, **kwargs)
            st = cell_stats(pf, dates[0], dates[-1])

            twin_finals = []
            twin_stats = []
            for seed in range(20):
                rng = np.random.default_rng(
                    1000 * seed + zlib.crc32(f"{key}|daily".encode()))
                override = {}
                for t, syms in signals_by_t.items():
                    k = min(len(syms), len(universe))
                    if k > 0:
                        override[t] = list(rng.choice(universe, size=k,
                                                       replace=False))
                tpf, _ = run_shape_daily(
                    mkt, key, dates, positions, START_CASH,
                    signal_override=override, **kwargs)
                tst = cell_stats(tpf, dates[0], dates[-1])
                twin_finals.append(tst["final"])
                twin_stats.append({"final": tst["final"],
                                   "win_rate_pct": tst["win_rate_pct"]})
            beaten = sum(1 for f in twin_finals if st["final"] > f)

            cell_json = {
                "shape": key, "label": cfg["label"], "road": road,
                "cadence": "daily",
                "window": [dates[0].isoformat(), dates[-1].isoformat()],
                "start_cash": START_CASH,
                **{k2: st[k2] for k2 in ("final", "cagr_pct", "max_dd_pct",
                                         "costs", "orders", "closed_trades",
                                         "win_rate_pct", "expectancy",
                                         "avg_win", "avg_loss", "halts",
                                         "restarts", "second_halt")},
                "spy_in_plumbing_price_only": round(net_spy, 2),
                "spy_canonical_div_adj": SPY_CANONICAL[road],
                "champion_vm": CHAMPION_VM[road],
                "placebo_twin_finals": twin_finals,
                "placebo_twin_win_rates": [t["win_rate_pct"] for t in twin_stats],
                "placebo_beaten": beaten,
                "placebo_note": ("20 random-selection twins: same per-day "
                                 "signal count, same exits/costs/floor; "
                                 "symbols drawn uniformly at random from the "
                                 "shape's universe (seeded as v10)."),
                "equity_curve": st["equity_curve"],
            }
            cdir = os.path.join(HERE, "cells", key)
            os.makedirs(cdir, exist_ok=True)
            with open(os.path.join(cdir, f"{road}.json"), "w") as fh:
                json.dump(cell_json, fh, indent=1, default=_json_default)
            roads_out[road] = {k2: cell_json[k2] for k2 in (
                "final", "cagr_pct", "max_dd_pct", "costs", "orders",
                "closed_trades", "win_rate_pct", "expectancy", "avg_win",
                "avg_loss", "halts", "restarts", "second_halt",
                "spy_in_plumbing_price_only", "spy_canonical_div_adj",
                "champion_vm", "placebo_beaten", "placebo_twin_finals",
                "equity_curve")}
            print(f"{key} {road:7s}: final ${st['final']:8.2f}  win "
                  f"{st['win_rate_pct']}%  exp {st['expectancy']}  trades "
                  f"{st['closed_trades']}  placebo beaten {beaten}/20",
                  flush=True)
        shapes_out[key] = {"label": cfg["label"], "roads": roads_out}

    results = {
        "slug": "high-winrate-lab",
        "family_status": ("NO-NATIVE-FORM (v11 S6 program construction) - "
                          "frozen v9 program spec is the only form; zero "
                          "constructed pieces; see CONSTRUCTION-SPEC.md"),
        "area": ("Four lab-built short-cycle trade shapes engineered for "
                 "Terry's 80-90% win-rate goal, on a 10-name survivors' "
                 "universe; judged on money AND win rate together, always."),
        "cadence": "daily (native tempo; only tempo run in v12)",
        "integrity": {
            "status": integrity_status,
            "published_v9": {f"{w}_{int(s)}_{k}": v
                             for (w, s), d in published_v9.items()
                             for k, v in d.items()},
            "reproduced_finals": reproduced,
            "detail": integrity_detail,
        },
        "roads_not_run": {
            "LONG": ("Frozen shared cache begins 2015-01-02; shapes need up "
                     "to 252 sessions warm-up. Substituting another data "
                     "source would break verification against the record. "
                     "Named limitation in CONSTRUCTION-SPEC.md."),
        },
        "spy_canonical_div_adj": SPY_CANONICAL,
        "champion_vm": CHAMPION_VM,
        "shapes": shapes_out,
        "data_note": ("Read-only shared cache: backtests/v2/tournament-data/ "
                      "(Yahoo split-adjusted daily OHLC, not dividend-"
                      "adjusted; 10-name universe of today's famous names - "
                      "survivorship flatters every number). Nothing written "
                      "outside this folder."),
    }
    with open(os.path.join(HERE, "results.json"), "w") as fh:
        json.dump(results, fh, indent=2, default=_json_default)
    print("\nDone. Wrote results.json, cells/*/*.json", flush=True)


if __name__ == "__main__":
    main()
