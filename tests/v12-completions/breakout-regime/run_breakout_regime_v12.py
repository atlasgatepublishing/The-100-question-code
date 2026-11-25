#!/usr/bin/env python3
"""
V12 COMPLETIONS - breakout-regime (frozen gated spec, re-run, NO changes).

Implements CONSTRUCTION-SPEC.md exactly:
  ENTRY: close at a new 252-day high AND SPY close > SPY 200-day average on
         the signal day (the CONSTRUCTED gate); fill next open.
  SIZE:  max 2 positions, 50% of equity each.
  EXIT:  next open after close below the 20-day average, or -8% intraday
         stop (stop-first; gaps at the open).
  COSTS: 0.10%/side + $0.01 per sell order.
  UNIVERSE: SPY QQQ NVDA TSLA AAPL MSFT AMZN META AMD AVGO (v2 cache,
         split-adjusted, NOT dividend-adjusted, read-only).

Road runs use v9 protections exactly as the v10 sweep did (plain -15%
floor per episode, 90-day cash sit, restart at next evaluation date,
second halt ends). Integrity runs use the ORIGINAL era rules (ladder
floor, halt ends run) and the original v4 module itself for the
validation placebo. The fast runner below is the v10 sweep runner,
copied unchanged in logic; v10 validated it cent-exact against the v4
engine in original mode on the full window.

Roads: DECADE 2016-11-21->2026-11-20, CONT 2019-01-02->2026-11-20,
VAL 2023-01-03->2026-11-20 (program road start). LONG 2010 not run -
the v2 cache begins 2015-01-02 (named blocker, CONSTRUCTION-SPEC.md).
Placebos: 20 seeds per road, v10 design (random entries, identical
exits, same gate, per-year filled-count matching; seeds 777001+7919*i).

Outputs: results.json in this folder.
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

import tournament as T

spec = importlib.util.spec_from_file_location(
    "breakout_regime_v4", os.path.join(V4_DIR, "breakout-regime.py"))
V4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V4)

UNIVERSE = T.STOCK_UNIVERSE
COST_RATE = T.COST_RATE
SELL_FEE = T.SELL_FEE

FULL = (date(2016, 11, 21), date(2026, 11, 20))
VAL_ORIG = (date(2023, 1, 1), date(2026, 11, 20))
ROADS = {
    "DECADE": (date(2016, 11, 21), date(2026, 11, 20)),
    "CONT": (date(2019, 1, 2), date(2026, 11, 20)),
    "VAL": (date(2023, 1, 3), date(2026, 11, 20)),
}
SPY_DIV_REF = {"DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
CHAMPION = {"DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}


# --- Fast runner: copied from v10 run_breakout_regime_v10.py (logic unchanged)
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


def run_fast(data, eval_idx, floor_mode="v9", placebo_sched=None):
    A = data.arr
    cash = 100.0
    lots = {}
    curve = []
    orders = 0
    costs = 0.0
    entries_by_year = {}
    pending_entries, pending_exits = [], []
    halts = []
    episode = 1
    floor = 85.0
    halt_pending = False
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
            else:
                curve.append((d, cash))
                continue
        for sym in pending_exits:
            if sym in lots:
                do_sell(p, sym, A[sym]["open"][p])
        pending_exits = []
        cands, pending_entries = pending_entries, []
        for sym in cands:
            if sym in lots or len(lots) >= 2:
                continue
            do_buy(d, p, sym)
        for sym in list(lots):
            entry = lots[sym][1]
            o, low = A[sym]["open"][p], A[sym]["low"][p]
            stop_px = entry * (1 - 0.08)
            if o <= stop_px:
                do_sell(p, sym, o)
            elif low <= stop_px:
                do_sell(p, sym, stop_px)
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
            pending_entries, pending_exits = [], []
            if t == n - 1:
                if episode == 2 and floor_mode == "v9":
                    second_halt = True
                break
            halt_pending = True
            continue
        if t == n - 1:
            break
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


def main():
    print("Loading data (v2 tournament cache, read-only)...")
    frames = V4.build_frames()

    # ---------- Integrity: original era rules (ladder floor) ----------
    integ = {}
    mkt_full = V4.make_market(frames, FULL)
    data_full = Data(frames, mkt_full)
    daily_full = set(range(data_full.n))
    r = run_fast(data_full, daily_full, floor_mode="original")
    integ["full_gated_100_fast"] = round(r["final"], 2)
    # ungated control via v4 engine (gate=False), original module
    _, r_ctl, _, _ = V4.run_window(frames, FULL, "breakout_ungated_control", gate=False)
    integ["full_ungated_100_engine"] = round(r_ctl["final"], 2)
    # VAL original window via v4 engine + its 1-seed placebo
    _, r_val, _, n_val = V4.run_window(frames, VAL_ORIG, "breakout_regime", gate=True)
    integ["validation_gated_100_engine"] = round(r_val["final"], 2)
    integ["validation_halt_100_engine"] = r_val["halt_date"]
    integ["validation_spy_net_engine"] = round(n_val, 2)
    mkt_val = V4.make_market(frames, VAL_ORIG)
    real_val = V4.run_breakout_regime(mkt_val, "breakout_regime")
    target_val = V4.entries_by_year(real_val)
    ppf, _meta = V4.run_placebo_matched(mkt_val, target_val)
    integ["validation_placebo_100_engine"] = round(
        T.score(ppf, mkt_val.test_dates[0])["final"], 2)
    expected = {"full_gated_100_fast": 359.44, "full_ungated_100_engine": 383.36,
                "validation_gated_100_engine": 124.82,
                "validation_halt_100_engine": "2026-08-14",
                "validation_placebo_100_engine": 177.92,
                "validation_spy_net_engine": 179.10}
    integ["expected"] = expected
    integ["all_match"] = all(integ[k] == v for k, v in expected.items())
    print("[integrity]", integ)

    # ---------- Roads: v9 protections, daily, 20-seed placebos ----------
    roads = {}
    for name, window in ROADS.items():
        mkt = V4.make_market(frames, window)
        data = Data(frames, mkt)
        eval_idx = set(range(data.n))
        res = run_fast(data, eval_idx, "v9")
        g_spy, n_spy = T.spy_benchmark(mkt)
        regime_days_on = int(sum(1 for p in data.pos_list if data.regime[p]))
        # gate-binding diagnostic: raw breakout signals vs gate-passing
        raw_sig, gated_sig = 0, 0
        for t in range(data.n):
            p = data.pos_list[t]
            for sym in UNIVERSE:
                if data.breakout(sym, p):
                    raw_sig += 1
                    if data.regime[p]:
                        gated_sig += 1
        target = {int(k): v for k, v in res["entries_by_year"].items()}
        twin_finals, twin_meta = [], []
        for i in range(20):
            seed = 777001 + 7919 * i
            pres, pmeta = run_placebo_cell(data, eval_idx, target, seed)
            twin_finals.append(round(pres["final"], 4))
            twin_meta.append(pmeta)
        beaten = sum(1 for f in twin_finals if res["final"] > f)
        roads[name] = {
            "window": [window[0].isoformat(), window[1].isoformat()],
            "final": round(res["final"], 2),
            "cagr_pct": round(res["cagr_pct"], 2),
            "max_dd_pct": round(res["max_dd_pct"], 2),
            "costs": round(res["costs"], 2), "orders": res["orders"],
            "entries": res["entries"],
            "entries_by_year": res["entries_by_year"],
            "halts": res["halts"], "restart": res["restart"],
            "restart_record": res["restart_record"],
            "second_halt": res["second_halt"],
            "spy_price_only_net": round(n_spy, 2),
            "spy_dividend_adjusted_ref": SPY_DIV_REF[name],
            "champion_vm": CHAMPION[name],
            "placebo_beaten": f"{beaten}/20",
            "placebo_finals": twin_finals, "placebo_meta": twin_meta,
            "regime_on_trading_days": regime_days_on,
            "regime_on_fraction": round(regime_days_on / data.n, 4),
            "raw_breakout_signals": raw_sig, "gate_passing_signals": gated_sig,
            "equity_curve": res["equity_curve"],
        }
        print(f"[{name}] final ${res['final']:,.2f} DD {res['max_dd_pct']:.1f}% "
              f"costs ${res['costs']:,.2f} orders {res['orders']} "
              f"entries {res['entries']} halts {len(res['halts'])} "
              f"placebo {beaten}/20 SPYnet ${n_spy:,.2f} "
              f"signals raw {raw_sig} gated {gated_sig}")

    out = {
        "family": "breakout-regime",
        "label": "CONSTRUCTED (program construction - the SPY 200-day gate has no published native form)",
        "spec": "CONSTRUCTION-SPEC.md (frozen before this run)",
        "integrity_original_era": integ,
        "roads_v9": roads,
        "long_road": "NOT RUN - named blocker: v2 tournament cache begins 2015-01-02; no 2010-start series for the frozen universe exists in the program's read-only caches.",
        "recorded_for_verification": {
            "v10_daily_decade": {"final": 359.44, "max_dd_pct": 30.22, "costs": 42.22,
                                 "orders": 281, "entries": 141, "placebo_beaten": "20/20"},
            "v4_validation_original": {"final": 124.82, "halt": "2026-08-14",
                                       "placebo_1seed": 177.92, "spy_net": 179.10},
        },
    }
    with open(os.path.join(HERE, "results.json"), "w") as fh:
        json.dump(out, fh, indent=2)
    print("Wrote results.json")


if __name__ == "__main__":
    main()
