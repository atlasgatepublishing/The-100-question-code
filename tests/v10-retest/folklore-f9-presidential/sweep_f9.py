#!/usr/bin/env python3
"""
CADENCE SWEEP — F-9 Presidential-Cycle Timing (term years 3-4), SPY only.
THE GREAT RETEST (v10). Simulation only. One clean shot, frozen spec.

THE STRATEGY (frozen, Spec F-9, backtests/v7/folklore-f9-presidential/):
hold SPY from the first trading day of term year 3 through the last
trading day of term year 4 of each presidential term; cash otherwise.
Term years are calendar years: a term inaugurated Jan of year Y has
year 3 = Y+2, year 4 = Y+3. Inaugurations [2013, 2017, 2021, 2025, 2029]
(+ [2005, 2009] backward extension used by W6 for the LONG window; the
DECADE window needs only 2013 on). Long years in DECADE: 2016 (yr 4 of
the 2013 term), 2019-2020, 2023-2024.

WHAT THIS SCRIPT DOES
  1. INTEGRITY: re-runs the ORIGINAL v7 engine logic (copied verbatim
     below) on the original data (v4 cache px_SPY.json) and original
     windows, checking the published finals CONT $248.67 / VAL $157.34.
     W6 established this in v10; this is the sweep script's own gate.
  2. DECADE CADENCE MATRIX: 2016-11-21 -> 2026-11-20, $100/cell, SPY
     bars only (read-only shared cache
     backtests/v7/long-hold/data/pxfull_SPY.json — the same long series
     W6's plumbing used; DECADE SPY buy-hold must come out $367.80).
     7 cadences under the SPEC's uniform definition: the position is
     reviewed ONLY on cadence dates (first trading day of each week /
     second week / month / quarter / half-year / year; daily = every
     trading day). Because the frozen rule's desired state is a known
     calendar state, a review that finds the position wrong trades at
     THAT cadence date's open — exactly the original engine's execution
     ("switches at the open of the first session of the period"). The
     cycle changes state only at calendar-year boundaries, and the
     first session of a year is simultaneously the first trading day of
     its week, month, quarter, half-year and year — so daily, weekly,
     monthly, quarterly, semi-annual and annual are expected to trade
     identically; biweekly (anchored on the window's first week, per
     the uniform cadence-date construction used across this batch) can
     miss a boundary week and delay a switch by 1-2 weeks. All seven
     are run and reported; the identity is stated, not assumed.
  3. PROTECTION (v9, every cell): plain -15% floor from the episode's
     starting balance, checked at every close (protection overlay, not
     a strategy signal); on first halt liquidate at the next open, sit
     in cash 90 calendar days, restart at the next cadence date on/after
     eligibility under an episode-2 floor of -15% from the restart
     balance; second halt ends the run.
  4. PLACEBOS (20 seeds/cell): circular-shift twins of the strategy's
     own daily desired-state series over the window (seeds 1-20, shift
     drawn per seed, 60..n-60 trading days) — the shifted-cycle placebo
     in the original's spirit: a shift preserves the exact time-in-
     market and the number of long blocks and destroys only the
     alignment with the presidential calendar. Each twin runs through
     the identical cadence machinery and v9 protection. ALSO recorded
     per cell (not counted in the 20): the deterministic cycle-offset-
     by-one-year twin (long years shifted +1: 2017, 2020-2021, 2024-2025
     within the window's span), the textbook shifted-cycle control.

Costs: 0.10%/side + $0.01 per sell order (the original engine's own).
End of window: liquidate any open position at the final close.

Outputs (this folder): cells/<cadence>.json (full equity curve, halts
with dates, all 20 placebo twin finals + the +1yr offset twin),
_sweep_summary.json (integrity + spy + cell summaries; RESULTS.md and
results.json are written from it by the worker).
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
INAUGURATIONS = [2005, 2009, 2013, 2017, 2021, 2025, 2029]


def term_year(cal_year):
    y0 = max(y for y in INAUGURATIONS if y <= cal_year)
    n = cal_year - y0 + 1
    return n if 1 <= n <= 4 else None


def is_long_year(cal_year):
    return term_year(cal_year) in (3, 4)


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


def buy_hold(bars, start, end):
    idx = [i for i, b in enumerate(bars) if start <= b["d"] <= end]
    first, last = bars[idx[0]], bars[idx[-1]]
    shares = START_CASH / (first["o"] * (1.0 + COST_RATE))
    val = shares * last["c"]
    final = val - (val * COST_RATE + SELL_FEE)
    peak, maxdd = -1.0, 0.0
    for i in idx:
        v = shares * bars[i]["c"]
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 2)}


# --------------------------- original v7 engine (verbatim logic, his
# rules: plain -15% floor, halt liquidates next open, never re-enters)
def run_window_original(bars, start, end):
    by_date = {b["d"]: b for b in bars}
    days = [b["d"] for b in bars if start <= b["d"] <= end]
    cash, shares = START_CASH, 0.0
    total_costs, trades, curve, days_in, halted = 0.0, [], [], 0, None
    floor0 = 85.0
    for di, d in enumerate(days):
        bar = by_date[d]
        want_long = is_long_year(int(d[:4]))
        if want_long and shares == 0.0 and cash > 0:
            buy_val = cash / 1.001
            c = buy_val * 0.001
            shares = buy_val / bar["o"]
            cash -= buy_val + c
            total_costs += c
            trades.append((d, "BUY"))
        elif not want_long and shares > 0:
            val = shares * bar["o"]
            c = val * 0.001 + 0.01
            cash += val - c
            total_costs += c
            trades.append((d, "SELL"))
            shares = 0.0
        v = cash + shares * bar["c"]
        curve.append((d, v))
        if shares > 0:
            days_in += 1
        if v <= floor0 and di < len(days) - 1:
            halted = d
            nd = days[di + 1]
            if shares > 0:
                val = shares * by_date[nd]["o"]
                c = val * 0.001 + 0.01
                cash += val - c
                total_costs += c
                trades.append((nd, "SELL-HALT"))
                shares = 0.0
            return {"final": round(cash, 2), "halted": halted,
                    "orders": len(trades), "costs": round(total_costs, 2)}
    last = days[-1]
    if shares > 0:
        val = shares * by_date[last]["c"]
        c = val * 0.001 + 0.01
        cash += val - c
        total_costs += c
        trades.append((last, "SELL-END"))
    return {"final": round(cash, 2), "halted": halted,
            "orders": len(trades), "costs": round(total_costs, 2)}


# ------------------------------------------------------- cadence engine
def cadence_dates(days, cadence):
    """Evaluation dates: first trading day of each cadence period inside
    the window (uniform SPEC construction, same as the sibling folklore
    sweeps; biweekly anchored on the window's first week)."""
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


def run_cell(bars, cadence, want_override=None):
    """Full v9 run over DECADE at one cadence. want_override: optional
    list of desired states aligned to the window's bars (placebos)."""
    wb = [b for b in bars if DEC_START <= b["d"] <= DEC_END]
    days = [b["d"] for b in wb]
    eval_set = cadence_dates(days, cadence)
    eval_sorted = sorted(eval_set)
    want = [is_long_year(int(b["d"][:4])) for b in wb]
    if want_override is not None:
        want = want_override

    halts = []
    restart = False
    second_halt = False
    total_costs = 0.0
    total_orders = 0
    days_in = 0
    curve = []
    trades = []

    cash = START_CASH
    ep_start_cash = START_CASH
    floor = 0.85 * START_CASH
    episode = 1
    pos = 0                      # index into wb where the live episode runs
    final = None
    while True:
        shares = 0.0
        halted = None
        liq_date = None
        i = pos
        while i < len(wb):
            b = wb[i]
            d = b["d"]
            # cadence review at today's open
            if d in eval_set:
                if want[i] and shares == 0.0:
                    c = cash * COST_RATE / (1.0 + COST_RATE)
                    shares = (cash - c) / b["o"]
                    total_costs += c
                    total_orders += 1
                    trades.append([d, "BUY", round(b["o"], 4)])
                    cash = 0.0
                elif not want[i] and shares > 0:
                    val = shares * b["o"]
                    c = val * COST_RATE + SELL_FEE
                    cash = val - c
                    total_costs += c
                    total_orders += 1
                    trades.append([d, "SELL", round(b["o"], 4)])
                    shares = 0.0
            v = cash + shares * b["c"]
            curve.append([d, round(v, 2)])
            if shares > 0:
                days_in += 1
            if i == len(wb) - 1:
                break
            # v9 floor at the close
            if v <= floor:
                halted = d
                nd = wb[i + 1]
                if shares > 0:
                    val = shares * nd["o"]
                    c = val * COST_RATE + SELL_FEE
                    cash = val - c
                    total_costs += c
                    total_orders += 1
                    trades.append([nd["d"], "SELL-HALT", round(nd["o"], 4)])
                    shares = 0.0
                    liq_date = nd["d"]
                    curve.append([nd["d"], round(cash, 2)])
                else:
                    liq_date = d
                break
            i += 1
        if halted is None:
            # completed the window: liquidate at final close
            if shares > 0:
                b = wb[-1]
                val = shares * b["c"]
                c = val * COST_RATE + SELL_FEE
                cash = val - c
                total_costs += c
                total_orders += 1
                trades.append([b["d"], "SELL-END", round(b["c"], 4)])
                curve[-1] = [b["d"], round(cash, 2)]
            final = cash
            break
        halts.append({"episode": episode, "signal_date": halted,
                      "liquidation_date": liq_date,
                      "proceeds": round(cash, 2),
                      "floor_in_effect": round(floor, 2)})
        if episode == 2:
            second_halt = True
            final = cash
            break
        # sit out 90 calendar days; restart at next cadence date
        elig = (date.fromisoformat(liq_date) + timedelta(days=90)).isoformat()
        rest = [d for d in eval_sorted if d >= elig]
        if not rest:
            final = cash
            break
        restart = True
        restart_date = rest[0]
        # cash-flat curve across the sit-out
        last_curve_d = curve[-1][0]
        for d in days:
            if last_curve_d < d < restart_date:
                curve.append([d, round(cash, 2)])
        curve.sort(key=lambda x: x[0])
        pos = days.index(restart_date)
        ep_start_cash = cash
        floor = 0.85 * ep_start_cash
        episode = 2
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    yrs = (date.fromisoformat(DEC_END)
           - date.fromisoformat(DEC_START)).days / 365.25
    rec = {
        "final": round(final, 2),
        "cagr_pct": round(((final / START_CASH) ** (1.0 / yrs) - 1.0) * 100, 2),
        "max_dd_pct": round(maxdd * 100, 2),
        "halts": halts, "restart": restart, "second_halt": second_halt,
        "costs": round(total_costs, 2), "orders": total_orders,
        "time_in_market_pct": round(100.0 * days_in / len(days), 1),
        "n_eval_dates": len(eval_set),
        "trades": trades,
    }
    return rec, curve


def main():
    # ---- integrity: original engine, original windows, original data
    bars_v4 = load_bars(V4_PX)
    integ = {}
    for name, (ws, we), pub in (("CONT", ("2019-01-02", "2026-11-20"), 248.67),
                                ("VAL", ("2023-01-01", "2026-11-20"), 157.34)):
        r = run_window_original(bars_v4, ws, we)
        integ[name] = {"window": [ws, we], "published_final": pub,
                       "reproduced_final": r["final"],
                       "match": abs(r["final"] - pub) < 0.005,
                       "halted": r["halted"]}
        print(f"INTEGRITY {name}: published ${pub} reproduced "
              f"${r['final']} match={integ[name]['match']}", flush=True)
    assert all(v["match"] for v in integ.values()), "integrity FAILED"

    # ---- decade bars (SPY only) + SPY control
    bars = load_bars(LONG_PX)
    spy = buy_hold(bars, DEC_START, DEC_END)
    print(f"SPY DECADE buy-hold: ${spy['final']} maxDD {spy['max_dd_pct']}%",
          flush=True)
    assert abs(spy["final"] - 367.80) < 0.005, "SPY decade mismatch"

    wb = [b for b in bars if DEC_START <= b["d"] <= DEC_END]
    want_series = [is_long_year(int(b["d"][:4])) for b in wb]
    n = len(want_series)
    # deterministic +1-year cycle-offset twin
    offset_want = [is_long_year(int(b["d"][:4]) - 1) for b in wb]

    os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)
    cells = {}
    for cad in CADENCES:
        rec, curve = run_cell(bars, cad)
        twins = []
        for seed in range(1, 21):
            rng = random.Random(seed)
            shift = rng.randrange(60, n - 60)
            twin = [want_series[(i - shift) % n] for i in range(n)]
            trec, _ = run_cell(bars, cad, want_override=twin)
            twins.append({"seed": seed, "shift_days": shift,
                          "final": trec["final"]})
        beaten = sum(1 for t in twins if rec["final"] > t["final"])
        orec, _ = run_cell(bars, cad, want_override=offset_want)
        rec["placebo_beaten"] = beaten
        rec["placebo_note"] = (
            "20 circular-shift twins of the daily desired-state series "
            "(seeds 1-20; a shift preserves the exact time-in-market and "
            "long-block count and destroys only the alignment with the "
            "presidential calendar — the shifted-cycle placebo), each run "
            "through the identical cadence machinery and v9 protection. "
            "Plus, recorded separately and not counted in the 20: the "
            "deterministic cycle-offset-by-one-year twin.")
        rec["placebo_cycle_offset_1yr_final"] = orec["final"]
        cell_doc = {"slug": "folklore-f9-presidential", "cadence": cad,
                    "window": [DEC_START, DEC_END], "start_cash": START_CASH,
                    **rec, "placebo_twins": twins, "equity_curve": curve}
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump(cell_doc, f, indent=1)
        cells[cad] = rec
        print(f"{cad.upper():11s} final ${rec['final']} CAGR "
              f"{rec['cagr_pct']}% maxDD {rec['max_dd_pct']}% costs "
              f"${rec['costs']} orders {rec['orders']} TIM "
              f"{rec['time_in_market_pct']}% placebo beaten {beaten}/20 "
              f"offset1yr ${orec['final']} halts {len(rec['halts'])}",
              flush=True)

    with open(os.path.join(HERE, "_sweep_summary.json"), "w") as f:
        json.dump({"integrity": integ,
                   "spy": {"final": spy["final"],
                           "max_dd_pct": spy["max_dd_pct"]},
                   "cells": cells}, f, indent=1)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
