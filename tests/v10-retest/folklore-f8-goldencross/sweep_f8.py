#!/usr/bin/env python3
"""
W6b CADENCE SWEEP — F-8 Golden Cross / Death Cross (SMA50 vs SMA200), SPY.
THE GREAT RETEST (v10). Simulation only. One clean shot, frozen spec.

WHAT THIS SCRIPT DOES
  1. INTEGRITY (his rules, original form): re-runs the original v7 F-8
     engine logic (copied verbatim below as run_cross_original) on the
     original windows/data (v4 cache px_SPY.json, 2017-06-01 start) and
     checks the published finals: CONT $82.66 (halted 2020-03-20),
     VAL $152.04. W6 already established integrity to the cent in v10;
     this re-check is the sweep script's own gate and is recorded.
  2. DECADE CADENCE MATRIX: 2016-11-21 -> 2026-11-20, $100/cell, on the
     long SPY bars (read-only shared cache
     backtests/v7/long-hold/data/pxfull_SPY.json, Yahoo 2008->2026,
     champion construction: open scaled by adjclose/close, close =
     adjclose; SMAs computed on the full series, point-in-time).
     7 cadences: daily, weekly, biweekly, monthly, quarterly,
     semi-annual, annual. Per the SPEC's uniform definition, the timer
     evaluates its signal ONLY on cadence dates (cadence date = first
     trading day of the week / second week / month / quarter / half /
     year; daily = every trading day). A switch signalled at a cadence
     date's close executes at the next trading day's open, exactly as
     the original engine executes. The v9 -15% floor is a protection
     overlay, not a strategy signal: it is checked at every close
     (unchanged from v9), liquidates at the next open, sits out 90
     calendar days, restarts once at the first trading day on/after
     eligibility (signal evaluation then resumes on cadence dates)
     under an episode-2 floor of -15% from the restart balance; a
     second halt ends the run.
  3. PLACEBOS (20 seeds/cell): circular-shift twins of the strategy's
     own daily desired-state series (the design F-3 in this same
     folklore batch used: shifting preserves the exact time-in-market
     and switch count of the unshifted daily rule and destroys only the
     timing alignment). Each twin is run through the identical cadence
     machinery and v9 protection. Seeds 1..20, shift drawn per seed.

Costs: 0.10%/side + $0.01 per sell order (the original engine's own).
End of window: any open position is liquidated at the final close
(sell cost charged), as the original engine does.

Outputs (this folder): cells/<cadence>.json (full equity curve, halts
with dates, all 20 placebo twin finals), results.json (SPEC sweep
format), RESULTS.md.
"""
import json
import os
import random
import time
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
V4_PX = os.path.expanduser("~/workspace/stock-app/backtests/v4/data/px_SPY.json")
LONG_PX = os.path.expanduser(
    "~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")

START_CASH = 100.0
COST_RATE = 0.001
SELL_FEE = 0.01
DEC_START, DEC_END = "2016-11-21", "2026-11-20"
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]


# ------------------------------------------------------------------ data
def load_bars(path):
    with open(path, "rb") as f:
        j = json.loads(f.read())
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, c = q["open"][i], q["close"][i]
        if c is None or o is None:
            continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        bars.append({"d": d, "o": o * ratio, "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars


def add_indicators(bars):
    closes = [b["c"] for b in bars]
    run50 = run200 = 0.0
    for i, c in enumerate(closes):
        run50 += c
        run200 += c
        if i >= 50:
            run50 -= closes[i - 50]
        if i >= 200:
            run200 -= closes[i - 200]
        b50 = run50 / 50.0 if i >= 49 else None
        b200 = run200 / 200.0 if i >= 199 else None
        bars[i]["sma50"], bars[i]["sma200"] = b50, b200
        bars[i]["want"] = (b50 > b200) if (b50 is not None and b200 is not None) else None
    return bars


def buy_hold(bars, start, end):
    idx = [i for i, b in enumerate(bars) if start <= b["d"] <= end]
    first, last = bars[idx[0]], bars[idx[-1]]
    shares = START_CASH / (first["o"] * (1.0 + COST_RATE))
    val = shares * last["c"]
    final = val - (val * COST_RATE + SELL_FEE)
    peak, maxdd = -1.0, 0.0
    curve = []
    for i in idx:
        v = shares * bars[i]["c"]
        curve.append([bars[i]["d"], round(v, 2)])
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 2),
            "curve": curve}


# -------------------------------------------- original engine (verbatim
# logic from backtests/v7/folklore-f8-goldencross, his-rules floor)
def run_cross_original(bars, start, end, start_cash=100.0, floor=85.0):
    idx = [i for i, b in enumerate(bars) if start <= b["d"] <= end]
    cash, shares = start_cash, 0.0
    entry_cost = entry_date = halted = None
    trades, costs, curve, days_in = [], 0.0, [], 0
    pending = pending_kind = None
    for pos, i in enumerate(idx):
        b = bars[i]
        if pending == "buy" and shares == 0.0 and halted is None:
            px = b["o"]
            shares = cash / (px * (1.0 + COST_RATE))
            costs += shares * px * COST_RATE
            entry_cost, entry_date, cash = cash, b["d"], 0.0
        elif pending == "sell" and shares > 0.0:
            px = b["o"]
            val = shares * px
            scost = val * COST_RATE + SELL_FEE
            costs += scost
            trades.append({"entry": entry_date, "exit": b["d"],
                           "pnl": round(val - scost - entry_cost, 2),
                           "exit_reason": "floor" if pending_kind == "floor" else "signal"})
            cash, shares = val - scost, 0.0
            entry_cost = entry_date = None
        pending = pending_kind = None
        equity = cash + shares * b["c"]
        curve.append((b["d"], equity))
        if shares > 0.0:
            days_in += 1
        if pos == len(idx) - 1:
            break
        if halted is None and equity < floor:
            halted = b["d"]
            if shares > 0.0:
                pending, pending_kind = "sell", "floor"
            continue
        if halted is not None:
            continue
        if b["sma50"] is None or b["sma200"] is None:
            continue
        want_long = b["sma50"] > b["sma200"]
        if want_long and shares == 0.0:
            pending, pending_kind = "buy", "cross"
        elif not want_long and shares > 0.0:
            pending, pending_kind = "sell", "cross"
    if shares > 0.0:
        b = bars[idx[-1]]
        val = shares * b["c"]
        scost = val * COST_RATE + SELL_FEE
        costs += scost
        trades.append({"entry": entry_date, "exit": b["d"],
                       "pnl": round(val - scost - entry_cost, 2),
                       "exit_reason": "window_end"})
        cash = val - scost
        curve[-1] = (b["d"], cash)
    return {"final": round(cash, 2), "halted": halted, "trades": trades,
            "costs": round(costs, 2), "curve": curve}


# ------------------------------------------------------- cadence engine
def cadence_dates(days, cadence):
    """Set of evaluation dates: first trading day of each cadence period
    inside the window (days = ordered trading-day strings in window)."""
    if cadence == "daily":
        return set(days)
    out = set()
    prev_key = None
    week_no = -1
    for d in days:
        dt = date.fromisoformat(d)
        if cadence == "weekly":
            key = (dt.isocalendar()[0], dt.isocalendar()[1])
        elif cadence == "biweekly":
            key = (dt.isocalendar()[0], dt.isocalendar()[1])
        elif cadence == "monthly":
            key = (dt.year, dt.month)
        elif cadence == "quarterly":
            key = (dt.year, (dt.month - 1) // 3)
        elif cadence == "semiannual":
            key = (dt.year, (dt.month - 1) // 6)
        elif cadence == "annual":
            key = (dt.year,)
        if key != prev_key:
            if cadence in ("weekly", "biweekly"):
                week_no += 1
            if cadence == "biweekly":
                if week_no % 2 == 0:
                    out.add(d)
            else:
                out.add(d)
            prev_key = key
    return out


def run_episode(bars, idx, eval_set, want_of, start_cash, floor):
    """One v9 episode. want_of(i) -> True/False/None desired state at bar i
    (evaluated only when bars[i]['d'] in eval_set). Floor checked daily.
    Returns dict with final (post-liquidation cash if halted, else the
    running cash/shares marked at end WITHOUT final liquidation — the
    caller liquidates at window end only for a completed run), curve,
    trades, costs, orders, halt info, end shares/cash."""
    cash, shares = start_cash, 0.0
    entry_cost = entry_date = halted = None
    liq_date = None
    trades, costs, orders, curve, days_in = [], 0.0, 0, [], 0
    pending = pending_kind = None
    for pos, i in enumerate(idx):
        b = bars[i]
        if pending == "buy" and shares == 0.0 and halted is None:
            px = b["o"]
            shares = cash / (px * (1.0 + COST_RATE))
            costs += shares * px * COST_RATE
            orders += 1
            entry_cost, entry_date, cash = cash, b["d"], 0.0
        elif pending == "sell" and shares > 0.0:
            px = b["o"]
            val = shares * px
            scost = val * COST_RATE + SELL_FEE
            costs += scost
            orders += 1
            trades.append({"entry": entry_date, "exit": b["d"],
                           "pnl": round(val - scost - entry_cost, 2),
                           "exit_reason": "floor" if pending_kind == "floor" else "signal"})
            cash, shares = val - scost, 0.0
            entry_cost = entry_date = None
            if pending_kind == "floor":
                liq_date = b["d"]
        pending = pending_kind = None
        equity = cash + shares * b["c"]
        curve.append([b["d"], round(equity, 2)])
        if shares > 0.0:
            days_in += 1
        if pos == len(idx) - 1:
            break
        if halted is None and equity < floor:
            halted = b["d"]
            if shares > 0.0:
                pending, pending_kind = "sell", "floor"
            continue
        if halted is not None:
            continue
        if b["d"] not in eval_set:
            continue
        want = want_of(i)
        if want is None:
            continue
        if want and shares == 0.0:
            pending, pending_kind = "buy", "cross"
        elif not want and shares > 0.0:
            pending, pending_kind = "sell", "cross"
    return {"cash": cash, "shares": shares, "entry_cost": entry_cost,
            "entry_date": entry_date, "halted": halted, "liq_date": liq_date,
            "trades": trades, "costs": costs, "orders": orders,
            "curve": curve, "days_in": days_in}


def run_cell(bars, cadence, want_override=None):
    """Full v9 run over the DECADE window at one cadence.
    want_override: optional list of desired states aligned to bars
    (placebo twins). Returns the cell record (without curve) + curve."""
    idx_all = [i for i, b in enumerate(bars) if DEC_START <= b["d"] <= DEC_END]
    days = [bars[i]["d"] for i in idx_all]
    eval_set = cadence_dates(days, cadence)

    def want_of(i):
        if want_override is not None:
            return want_override[i]
        return bars[i]["want"]

    halts = []
    restart = False
    second_halt = False
    total_costs = 0.0
    total_orders = 0
    total_days_in = 0
    curve = []
    start, start_cash, floor = DEC_START, START_CASH, 0.85 * START_CASH
    final = None
    for episode in (1, 2):
        idx = [i for i in idx_all if bars[i]["d"] >= start]
        ep = run_episode(bars, idx, eval_set, want_of, start_cash, floor)
        total_costs += ep["costs"]
        total_orders += ep["orders"]
        total_days_in += ep["days_in"]
        if episode == 1:
            curve = ep["curve"]
        else:
            pre = [c for c in curve if c[0] < ep["curve"][0][0]]
            gap = [[d, round(start_cash, 2)] for d in days
                   if curve[-1][0] < d < ep["curve"][0][0]]
            curve = pre + gap + ep["curve"]
        if ep["halted"] is None:
            # completed: liquidate any open position at final close
            if ep["shares"] > 0.0:
                b = bars[idx[-1]]
                val = ep["shares"] * b["c"]
                scost = val * COST_RATE + SELL_FEE
                total_costs += scost
                total_orders += 1
                final = val - scost
                curve[-1] = [b["d"], round(final, 2)]
            else:
                final = ep["cash"]
            break
        # halted: position liquidated at next open by the episode engine
        halts.append({"episode": episode, "signal_date": ep["halted"],
                      "liquidation_date": ep["liq_date"],
                      "proceeds": round(ep["cash"], 2),
                      "floor_in_effect": round(floor, 2)})
        if episode == 2:
            second_halt = True
            final = ep["cash"]
            break
        liq = ep["liq_date"] or ep["halted"]
        elig = (date.fromisoformat(liq) + timedelta(days=90)).isoformat()
        rest = [d for d in days if d >= elig]
        if not rest:
            final = ep["cash"]
            break
        restart = True
        start = rest[0]
        start_cash = ep["cash"]
        floor = 0.85 * start_cash
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    yrs = (date.fromisoformat(DEC_END) - date.fromisoformat(DEC_START)).days / 365.25
    return {
        "final": round(final, 2),
        "cagr_pct": round(((final / START_CASH) ** (1.0 / yrs) - 1.0) * 100, 2),
        "max_dd_pct": round(maxdd * 100, 2),
        "halts": halts, "restart": restart, "second_halt": second_halt,
        "costs": round(total_costs, 2), "orders": total_orders,
        "time_in_market_pct": round(100.0 * total_days_in / len(days), 1),
        "n_eval_dates": len(eval_set),
    }, curve


def main():
    # ---- integrity: original engine, original windows, original data
    bars_v4 = add_indicators(load_bars(V4_PX))
    integ = {}
    for name, (ws, we), pub in (("CONT", ("2019-01-02", DEC_END), 82.66),
                                ("VAL", ("2023-01-03", DEC_END), 152.04)):
        r = run_cross_original(bars_v4, ws, we)
        integ[name] = {"window": [ws, we], "published_final": pub,
                       "reproduced_final": r["final"],
                       "match": abs(r["final"] - pub) < 0.005,
                       "halted": r["halted"]}
        print(f"INTEGRITY {name}: published ${pub} reproduced ${r['final']} "
              f"match={integ[name]['match']} halted={r['halted']}", flush=True)
    assert all(v["match"] for v in integ.values()), "integrity FAILED"

    # ---- decade bars + SPY control
    bars = add_indicators(load_bars(LONG_PX))
    spy = buy_hold(bars, DEC_START, DEC_END)
    print(f"SPY DECADE buy-hold: ${spy['final']} maxDD {spy['max_dd_pct']}%",
          flush=True)

    # daily desired-state series for placebo shifts
    want_series = [b["want"] for b in bars]

    os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)
    cells = {}
    for cad in CADENCES:
        rec, curve = run_cell(bars, cad)
        # placebos: 20 circular-shift twins of the daily desired series
        n = len(want_series)
        twins = []
        for seed in range(1, 21):
            rng = random.Random(seed)
            shift = rng.randrange(60, n - 60)
            twin = [want_series[(i - shift) % n] for i in range(n)]
            trec, _ = run_cell(bars, cad, want_override=twin)
            twins.append({"seed": seed, "shift_days": shift,
                          "final": trec["final"]})
        beaten = sum(1 for t in twins if rec["final"] > t["final"])
        rec["placebo_beaten"] = beaten
        rec["placebo_note"] = (
            "20 circular-shift twins of the daily SMA50>SMA200 desired-state "
            "series (seeds 1-20; shift preserves time-in-market and switch "
            "count of the daily rule, destroys timing alignment), each run "
            "through the identical cadence machinery and v9 protection.")
        cell_doc = {"slug": "folklore-f8-goldencross", "cadence": cad,
                    "window": [DEC_START, DEC_END], "start_cash": START_CASH,
                    **rec, "placebo_twins": twins,
                    "equity_curve": curve}
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump(cell_doc, f, indent=1)
        cells[cad] = rec
        print(f"{cad.upper():11s} final ${rec['final']} CAGR {rec['cagr_pct']}% "
              f"maxDD {rec['max_dd_pct']}% costs ${rec['costs']} "
              f"orders {rec['orders']} TIM {rec['time_in_market_pct']}% "
              f"placebo beaten {beaten}/20 halts {len(rec['halts'])}",
              flush=True)

    with open(os.path.join(HERE, "_sweep_summary.json"), "w") as f:
        json.dump({"integrity": integ, "spy": {"final": spy["final"],
                                                "max_dd_pct": spy["max_dd_pct"]},
                   "cells": cells}, f, indent=1)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
