#!/usr/bin/env python3
"""
W12 CADENCE SWEEP -- Golden-Cross TOURNAMENT form (v2 tournament style D).
THE GREAT RETEST (v10). Simulation only. One clean shot, frozen spec.

DISTINCT FROM FOLKLORE F-8: the signal formula is the same family --
all-in SPY while SMA50 > SMA200, cash otherwise -- but the tournament's
construction differs from F-8's in five concrete ways:
  1. DATA: tournament ran on split-adjusted (NOT dividend-adjusted)
     Yahoo bars cached in backtests/v2/tournament-data/SPY.csv
     (2015-01-02 -> 2026-11-20). F-8 ran on dividend-adjusted
     (adjclose) bars from the v4 cache (2017-06-01 ->).
  2. INITIAL SEEDING: the tournament seeds its starting state from the
     close BEFORE the window opens (2016-11-18): if SMA50 > SMA200
     there, it buys at the FIRST open of the window (2016-11-21).
     F-8 starts in cash and its first possible entry is the second
     open, off the first in-window close.
  3. FLOOR (original form): the tournament-era LADDER -- $85, rising
     to $100 at a $125 close and $125 at a $150 close; a close AT or
     BELOW the floor liquidates at the next open and ENDS the run
     (no restart). F-8's original used a plain $85 floor (close below).
  4. WINDOW: the tournament's only window is the DECADE
     2016-11-21 -> 2026-11-20. F-8's originals were CONT (2019) and
     VAL (2023) fresh pots.
  5. END OF WINDOW: the tournament marks any open position to the
     final close (no end liquidation, no final sell cost). F-8
     liquidates at the final close with the sell cost charged.

WHAT THIS SCRIPT DOES
  1. INTEGRITY (tournament original, ORIGINAL rules): re-runs style D
     exactly as backtests/v2/tournament.py runs it (run_golden_cross +
     Portfolio buy/sell/ladder semantics, copied faithfully below) on
     the tournament's own split-adjusted SPY cache, DECADE window.
     Published target: final $95.46, 4 orders, 2 closed trades,
     costs $0.46, max DD 32.6%, HALTED 2020-03-23 (liquidation date;
     floor triggered at the 2020-03-20 close). Also reproduces the
     tournament SPY benchmark: $314.74 gross / $314.10 net (price-only).
  2. DECADE CADENCE MATRIX under v9 protections: 2016-11-21 ->
     2026-11-20, $100/cell. SUBSTITUTION (stated per SPEC): sweep bars
     are the dividend-adjusted long SPY bars (read-only shared cache
     backtests/v7/long-hold/data/pxfull_SPY.json, champion
     construction: open scaled by adjclose/close, close = adjclose) --
     the SAME bars the F-8 sweep used, so the two golden-cross rows
     stay comparable. The cross is computed on daily bars by
     construction; cadence governs evaluation/entry/exit dates only:
     the SMA50>SMA200 state is READ only on cadence dates (first
     trading day of each week / second week / month / quarter / half /
     year; daily = every day), and a switch signalled at a cadence
     date's close executes at the next trading day's open. The
     tournament's initial seeding is preserved at every cadence: the
     pre-window daily cross state (close of 2016-11-18) decides the
     first-open position. The v9 -15% floor is a protection overlay,
     checked at every close: liquidate next open, sit out 90 calendar
     days, restart once at the first trading day on/after eligibility
     (signal evaluation then resumes on cadence dates) under an
     episode-2 floor of -15% from the restart balance; second halt
     ends the run. End of window: open position liquidated at the
     final close (sell cost charged) -- the v9/sweep convention, as
     in the F-8 sweep (a stated substitution from the tournament's
     mark-to-market end).
  3. PLACEBOS (20 seeds/cell): circular-shift twins of the daily
     desired-state series -- the SAME twin design the F-8 sweep used
     (shift preserves time-in-market and switch count of the daily
     rule, destroys only timing alignment), each run through the
     identical cadence machinery (including seeding from the twin's
     pre-window state) and v9 protection. Seeds 1..20.

Costs: 0.10%/side + $0.01 per sell order (the tournament's own).

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
TOURN_SPY_CSV = os.path.expanduser(
    "~/workspace/stock-app/backtests/v2/tournament-data/SPY.csv")
LONG_PX = os.path.expanduser(
    "~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")

START_CASH = 100.0
COST_RATE = 0.001
SELL_FEE = 0.01
DEC_START, DEC_END = "2016-11-21", "2026-11-20"
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]


# ------------------------------------------------------------------ data
def load_tourn_bars():
    bars = []
    with open(TOURN_SPY_CSV) as f:
        header = f.readline()
        for line in f:
            p = line.strip().split(",")
            if len(p) < 5:
                continue
            bars.append({"d": p[0], "o": float(p[1]), "c": float(p[4])})
    bars.sort(key=lambda b: b["d"])
    return bars


def load_long_bars(path):
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
        bars[i]["want"] = (b50 > b200) if (b50 is not None
                                          and b200 is not None) else None
    return bars


def buy_hold(bars, start, end, dividend_adjusted=True):
    idx = [i for i, b in enumerate(bars) if start <= b["d"] <= end]
    first, last = bars[idx[0]], bars[idx[-1]]
    shares = START_CASH / (first["o"] * (1.0 + COST_RATE))
    val = shares * last["c"]
    final = val - (val * COST_RATE + SELL_FEE)
    gross = START_CASH / first["o"] * last["c"]
    peak, maxdd = -1.0, 0.0
    curve = []
    for i in idx:
        v = shares * bars[i]["c"]
        curve.append([bars[i]["d"], round(v, 2)])
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(final, 2), "gross": round(gross, 2),
            "max_dd_pct": round(maxdd * 100, 2), "curve": curve}


# --------------------------------------- tournament original (faithful
# re-implementation of v2 tournament.py run_golden_cross + Portfolio)
def run_tournament_original(bars):
    idx = [i for i, b in enumerate(bars) if DEC_START <= b["d"] <= DEC_END]
    first = idx[0]
    cash, shares = START_CASH, 0.0
    entry_price = entry_date = None
    entry_cost_total = 0.0
    round_trips, trades, costs = [], [], 0.0
    floor = 85.0
    halt_pending = False
    halt_trigger = halt_date = None
    curve = [(bars[first]["d"], START_CASH)]  # score() prepends start cash
    # seeding: state from the close before the window opens
    prev = bars[first - 1]
    pending_switch = bool(prev["sma50"] > prev["sma200"])
    last_pos = len(idx) - 1
    for t, i in enumerate(idx):
        b = bars[i]
        if halt_pending:
            # liquidate all at this open, run ends
            if shares > 0:
                val = shares * b["o"]
                cost = COST_RATE * val + SELL_FEE
                costs += cost
                cash = val - cost
                trades.append({"date": b["d"], "side": "sell",
                               "price": b["o"], "value": round(val, 2),
                               "cost": round(cost, 4),
                               "reason": "floor-liquidation"})
                round_trips.append({"entry": entry_date, "exit": b["d"],
                                    "pnl": cash - entry_cost_total})
                shares = 0.0
            halt_date = b["d"]
            curve.append((b["d"], cash))
            break
        if pending_switch is True and shares <= 0:
            eq_open = cash  # no holdings: equity at open = cash
            value = min(eq_open, cash / (1 + COST_RATE))
            cost = COST_RATE * value
            costs += cost
            shares = value / b["o"]
            cash -= value + cost
            entry_price, entry_date = b["o"], b["d"]
            entry_cost_total = value + cost
            trades.append({"date": b["d"], "side": "buy", "price": b["o"],
                           "value": round(value, 2), "cost": round(cost, 4),
                           "reason": "cross-up"})
        elif pending_switch is False and shares > 0:
            val = shares * b["o"]
            cost = COST_RATE * val + SELL_FEE
            costs += cost
            cash = val - cost
            trades.append({"date": b["d"], "side": "sell", "price": b["o"],
                           "value": round(val, 2), "cost": round(cost, 4),
                           "reason": "cross-down"})
            round_trips.append({"entry": entry_date, "exit": b["d"],
                                "pnl": cash - entry_cost_total})
            shares = 0.0
        pending_switch = None
        eq_close = cash + shares * b["c"]
        curve.append((b["d"], eq_close))
        # ladder floor check at the close
        if eq_close >= 150.0:
            floor = max(floor, 125.0)
        elif eq_close >= 125.0:
            floor = max(floor, 100.0)
        touched = eq_close <= floor
        if touched:
            halt_trigger = b["d"]
            if t == last_pos:
                halt_date = b["d"]
                break
            halt_pending = True
        if t == last_pos:
            break
        if bars[i]["sma50"] is None or bars[i]["sma200"] is None:
            continue
        desired_long = bool(bars[i]["sma50"] > bars[i]["sma200"])
        if desired_long != (shares > 0):
            pending_switch = desired_long
    # score(): final = last curve point (start-cash point included in DD)
    final = curve[-1][1]
    peak, maxdd = START_CASH, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    yrs = (date.fromisoformat(curve[-1][0])
           - date.fromisoformat(DEC_START)).days / 365.25
    wins = [r for r in round_trips if r["pnl"] > 0]
    return {"final": round(final, 2),
            "cagr_pct": round(((final / START_CASH) ** (1 / yrs) - 1) * 100, 2),
            "max_dd_pct": round(maxdd * 100, 1),
            "orders": len(trades), "closed_trades": len(round_trips),
            "win_rate_pct": (round(100 * len(wins) / len(round_trips), 1)
                             if round_trips else None),
            "costs": round(costs, 2), "trades": trades,
            "halt_trigger_date": halt_trigger, "halt_date": halt_date,
            "curve": [[d, round(v, 2)] for d, v in curve[1:]]}


# ------------------------------------------------------- cadence engine
# (identical chassis to the F-8 sweep, plus tournament seeding)
def cadence_dates(days, cadence):
    if cadence == "daily":
        return set(days)
    out = set()
    prev_key = None
    week_no = -1
    for d in days:
        dt = date.fromisoformat(d)
        if cadence in ("weekly", "biweekly"):
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


def run_episode(bars, idx, eval_set, want_of, start_cash, floor,
                seed_want=None):
    """One v9 episode. seed_want: desired state from the close before the
    episode's first bar (tournament seeding; episode 1 only in practice --
    restarts re-enter only via cadence-date evaluations, as in F-8)."""
    cash, shares = start_cash, 0.0
    entry_cost = entry_date = halted = None
    liq_date = None
    trades, costs, orders, curve, days_in = [], 0.0, 0, [], 0
    pending = pending_kind = None
    if seed_want:
        pending, pending_kind = "buy", "cross"
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
                           "exit_reason": "floor" if pending_kind == "floor"
                           else "signal"})
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
    idx_all = [i for i, b in enumerate(bars) if DEC_START <= b["d"] <= DEC_END]
    days = [bars[i]["d"] for i in idx_all]
    eval_set = cadence_dates(days, cadence)

    def want_of(i):
        if want_override is not None:
            return want_override[i]
        return bars[i]["want"]

    # tournament seeding: state at the close before the window
    seed_idx = idx_all[0] - 1
    seed_want = want_of(seed_idx)
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
        ep = run_episode(bars, idx, eval_set, want_of, start_cash, floor,
                         seed_want=seed_want if episode == 1 else None)
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
    # ---- integrity: tournament original, its own data and rules
    tbars = add_indicators(load_tourn_bars())
    orig = run_tournament_original(tbars)
    spy_t = buy_hold(tbars, DEC_START, DEC_END)
    pub = {"final": 95.46, "orders": 4, "closed_trades": 2, "costs": 0.46,
           "max_dd_pct": 32.6, "halt_date": "2020-03-23",
           "spy_gross": 314.74, "spy_net": 314.10}
    checks = {
        "final": abs(orig["final"] - pub["final"]) < 0.005,
        "orders": orig["orders"] == pub["orders"],
        "closed_trades": orig["closed_trades"] == pub["closed_trades"],
        "costs": abs(orig["costs"] - pub["costs"]) < 0.005,
        "max_dd_pct": abs(orig["max_dd_pct"] - pub["max_dd_pct"]) < 0.05,
        "halt_date": orig["halt_date"] == pub["halt_date"],
        "spy_gross": abs(spy_t["gross"] - pub["spy_gross"]) < 0.005,
        "spy_net": abs(spy_t["final"] - pub["spy_net"]) < 0.005,
    }
    print(f"INTEGRITY tournament D: reproduced final ${orig['final']} "
          f"orders {orig['orders']} costs ${orig['costs']} "
          f"maxDD {orig['max_dd_pct']}% halt {orig['halt_date']} "
          f"(trigger {orig['halt_trigger_date']}); SPY gross ${spy_t['gross']} "
          f"net ${spy_t['final']}; checks={checks}", flush=True)
    assert all(checks.values()), "integrity FAILED"
    integ = {"status": "reproduced", "checks": checks,
             "published": pub,
             "reproduced": {k: orig[k] for k in
                            ("final", "cagr_pct", "max_dd_pct", "orders",
                             "closed_trades", "win_rate_pct", "costs",
                             "halt_trigger_date", "halt_date")},
             "reproduced_trades": orig["trades"],
             "reproduced_spy_benchmark": {"gross": spy_t["gross"],
                                          "net": spy_t["final"]}}
    os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)
    with open(os.path.join(HERE, "cells", "integrity-original.json"), "w") as f:
        json.dump({"slug": "golden-cross-tournament",
                   "form": "v2 tournament style D, original rules "
                           "(split-adjusted bars, ladder floor, no restart, "
                           "mark-to-market end)",
                   "window": [DEC_START, DEC_END], **integ,
                   "equity_curve": orig["curve"]}, f, indent=1)

    # ---- decade bars (dividend-adjusted, shared with the F-8 sweep)
    bars = add_indicators(load_long_bars(LONG_PX))
    spy = buy_hold(bars, DEC_START, DEC_END)
    print(f"SPY DECADE buy-hold (dividend-adjusted): ${spy['final']} "
          f"maxDD {spy['max_dd_pct']}%", flush=True)

    want_series = [b["want"] for b in bars]
    cells = {}
    for cad in CADENCES:
        rec, curve = run_cell(bars, cad)
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
            "count of the daily rule, destroys timing alignment) -- the same "
            "twin design the F-8 sweep used -- each run through the identical "
            "cadence machinery (including tournament seeding from the twin's "
            "pre-window state) and v9 protection.")
        cell_doc = {"slug": "golden-cross-tournament", "cadence": cad,
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
        json.dump({"integrity": integ,
                   "spy_decade_dividend_adjusted": {
                       "final": spy["final"], "max_dd_pct": spy["max_dd_pct"]},
                   "spy_decade_tournament_price_only": {
                       "gross": spy_t["gross"], "net": spy_t["final"]},
                   "cells": cells}, f, indent=1)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
