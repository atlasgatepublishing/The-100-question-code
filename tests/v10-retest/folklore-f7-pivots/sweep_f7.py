#!/usr/bin/env python3
"""
CADENCE SWEEP — F-7 Monthly Pivot-Point Trend (SPY). THE GREAT RETEST (v10).
Simulation only. One clean shot, frozen spec. Worker task: DECADE cadence
matrix x 7 cadences for folklore-f7-pivots.

FROZEN RULE (verbatim from research/v7-completeness/folklore-audit.md, F-7):
classic floor-trader pivot from the PRIOR month's high H, low L, close C:
P = (H+L+C)/3. Hold SPY if the prior month closed above P, cash otherwise.
Native cadence = MONTHLY (sourced correction, established by W6: the frozen
form is explicitly a monthly pivot rule; the SPEC CADENCE GRID's grouping of
F-7 with daily-signal timers was wrong). Original test used the monthly form
too -> original_cadence_foreign = false.

HOW CADENCE INTERACTS WITH THE MONTHLY PIVOT CONSTRUCTION (stated per task):
  The pivot levels are ALWAYS computed from the prior calendar month, exactly
  as published, at every cadence. Cadence changes ONLY the signal-evaluation
  frequency (SPEC uniform definition). At any evaluation date, the signal is
  the pivot in force for that date's calendar month: prior month's C vs P.
  - daily: the signal is constant within a month (it can only change when a
    new monthly pivot takes force), so daily evaluation can only trade on
    the first trading day of a month -> mechanically identical to monthly.
  - weekly / biweekly: evaluation dates are the first trading day of each
    week / every second week; a month-change is acted on at the first such
    date on/after the month starts, i.e. the same monthly signal with a
    lag of 0-4 (weekly) or 0-11 (biweekly) trading days.
  - quarterly / semi-annual / annual: the monthly pivot signal is sampled
    only on the first trading day of each quarter / half-year / year and
    the resulting position is held until the next evaluation date.
  No cadence recomputes a pivot from a week/quarter/etc. — that would change
  the rule's definition. All 7 cells are therefore expressible; none is N/A.

EXECUTION: at an evaluation date, trade at THAT date's open (the frozen
F-7 form executes at the first open of the month; the signal uses only
prior-month closes, so same-day-open execution is point-in-time clean).
Costs: 0.10%/side + $0.01 per sell order (the original engine's own).
Basis: champion construction — o/h/l scaled by adjclose/close, c = adjclose
(the original engine's forced reading #1).

v9 PROTECTION (overlay, unchanged): plain -15% floor from the episode's
starting balance, checked at every close; on halt, liquidate at the next
open, sit in cash 90 calendar days, restart once at the next cadence
(evaluation) date on/after eligibility under an episode-2 floor of -15%
from the restart balance; second halt ends the run. End of window:
liquidate any open position at the final close (sell cost charged).

PLACEBOS (per cell, 20 seeds): the original F-7 placebo design — each
evaluation period's hold/cash state is an independent coin flip
(random.Random(seed), p=0.5, seeds 1..20) — drawn at that cell's own
evaluation dates and run through the identical cadence machinery, costs
and v9 protection. seeds_beaten = ranked final strictly greater than twin.

DATA: SPY bars only, read-only shared cache
backtests/v7/long-hold/data/pxfull_SPY.json (Yahoo 2008->2026).

INTEGRITY (gate, run first): the original monthly engine in its original
(his-rules, single-episode) form reproduces the published finals
CONT $168.05 / VAL $152.42, and the monthly cell under v9 on DECADE
reproduces W6's v10 area run $175.43; SPY DECADE buy-hold = $367.80.

Outputs (this folder): cells/<cadence>.json (full equity curve, halts with
dates, all 20 placebo twin finals), results.json (SPEC sweep format),
RESULTS.md.
"""
import json
import os
import random
import time
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
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
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if c is None or o is None:
            continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        bars.append({"d": d, "o": o * ratio, "h": h * ratio if h else a,
                     "l": l * ratio if l else a, "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars


def monthly_pivots(bars):
    """{(y,m): pivot in force that month, from the PRIOR month's H/L/C} —
    the original engine's construction, verbatim in substance."""
    by_month = {}
    for b in bars:
        by_month.setdefault((int(b["d"][:4]), int(b["d"][5:7])), []).append(b)
    out = {}
    months = sorted(by_month)
    for i in range(1, len(months)):
        prev = by_month[months[i - 1]]
        H = max(b["h"] for b in prev)
        L = min(b["l"] for b in prev)
        C = prev[-1]["c"]
        out[months[i]] = {"H": H, "L": L, "C": C, "P": (H + L + C) / 3.0}
    return out


def buy_hold(bars, start, end):
    days = [b for b in bars if start <= b["d"] <= end]
    first, last = days[0], days[-1]
    shares = START_CASH / (first["o"] * (1.0 + COST_RATE))
    val = shares * last["c"]
    final = val - (val * COST_RATE + SELL_FEE)
    peak, maxdd = -1.0, 0.0
    for b in days:
        v = shares * b["c"]
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 2)}


# ------------------------------------------------------------- cadence set
def cadence_dates(days, cadence):
    """Evaluation dates per the SPEC's uniform definition: first trading
    day of each week / second week / month / quarter / half / year;
    daily = every trading day. (Biweekly anchor: weeks counted from the
    first week of the window, every even week — same anchor as the F-8
    sweep in this batch.)"""
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


# ----------------------------------------------------------------- engine
def run_episode(bars, days_idx, eval_set, want_fn, start_cash, floor):
    """One episode. want_fn(date_str) -> bool desired state, consulted ONLY
    on evaluation dates; trades execute at the evaluation date's open.
    Floor checked at every close; on breach (not the final day) liquidate
    at the next day's open and end the episode."""
    cash, shares = start_cash, 0.0
    trades, costs, orders, curve, days_in = [], 0.0, 0, [], 0
    halted = liq_date = None
    n = len(days_idx)
    for pos, i in enumerate(days_idx):
        b = bars[i]
        if b["d"] in eval_set:
            want = want_fn(b["d"])
            if want and shares == 0.0:
                buy_val = cash / (1.0 + COST_RATE)
                if buy_val > 0.005:
                    shares = buy_val / b["o"]
                    costs += buy_val * COST_RATE
                    orders += 1
                    trades.append([b["d"], "BUY", round(buy_val, 2)])
                    cash = 0.0
            elif not want and shares > 0.0:
                val = shares * b["o"]
                sc = val * COST_RATE + SELL_FEE
                costs += sc
                orders += 1
                trades.append([b["d"], "SELL", round(val - sc, 2)])
                cash, shares = val - sc, 0.0
        equity = cash + shares * b["c"]
        curve.append([b["d"], round(equity, 2)])
        if shares > 0.0:
            days_in += 1
        if equity <= floor and pos < n - 1:
            halted = b["d"]
            nb = bars[days_idx[pos + 1]]
            if shares > 0.0:
                val = shares * nb["o"]
                sc = val * COST_RATE + SELL_FEE
                costs += sc
                orders += 1
                trades.append([nb["d"], "SELL-HALT", round(val - sc, 2)])
                cash, shares = val - sc, 0.0
            liq_date = nb["d"]
            break
    return {"cash": cash, "shares": shares, "halted": halted,
            "liq_date": liq_date, "trades": trades, "costs": costs,
            "orders": orders, "curve": curve, "days_in": days_in}


def run_cell(bars, pivots, cadence, placebo_seed=None,
             window=(DEC_START, DEC_END)):
    """Full v9 run at one cadence. placebo_seed=None -> ranked pivot rule;
    else coin-flip states at the cell's evaluation dates."""
    ws, we = window
    idx_all = [i for i, b in enumerate(bars) if ws <= b["d"] <= we]
    days = [bars[i]["d"] for i in idx_all]
    eval_set = cadence_dates(days, cadence)
    rng = random.Random(placebo_seed) if placebo_seed is not None else None

    def want_fn(d):
        if rng is not None:
            return rng.random() < 0.5
        pv = pivots[(int(d[:4]), int(d[5:7]))]
        return pv["C"] > pv["P"]

    halts = []
    restart = False
    restart_date = None
    second_halt = False
    total_costs = total_orders = total_days_in = 0
    curve = []
    start, start_cash, floor = ws, START_CASH, 0.85 * START_CASH
    final = None
    for episode in (1, 2):
        idx = [i for i in idx_all if bars[i]["d"] >= start]
        ep = run_episode(bars, idx, eval_set, want_fn, start_cash, floor)
        total_costs += ep["costs"]
        total_orders += ep["orders"]
        total_days_in += ep["days_in"]
        if episode == 1:
            curve = ep["curve"]
        else:
            gap = [[d, round(start_cash, 2)] for d in days
                   if curve[-1][0] < d < ep["curve"][0][0]]
            curve = [c for c in curve if c[0] < ep["curve"][0][0]] \
                + gap + ep["curve"]
        if ep["halted"] is None:
            if ep["shares"] > 0.0:
                b = bars[idx[-1]]
                val = ep["shares"] * b["c"]
                sc = val * COST_RATE + SELL_FEE
                total_costs += sc
                total_orders += 1
                final = val - sc
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
        rest = [d for d in sorted(eval_set) if d >= elig]
        if not rest:
            final = ep["cash"]
            break
        restart = True
        restart_date = rest[0]
        halts[-1]["restart_date"] = restart_date
        halts[-1]["restart_balance"] = round(ep["cash"], 2)
        start, start_cash = rest[0], ep["cash"]
        floor = 0.85 * start_cash
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    yrs = (date.fromisoformat(we) - date.fromisoformat(ws)).days / 365.25
    rec = {"final": round(final, 2),
           "cagr_pct": round(((final / START_CASH) ** (1.0 / yrs) - 1.0)
                             * 100, 2),
           "max_dd_pct": round(maxdd * 100, 2),
           "halts": halts, "restart": restart, "restart_date": restart_date,
           "second_halt": second_halt,
           "costs": round(total_costs, 2), "orders": total_orders,
           "time_in_market_pct": round(100.0 * total_days_in / len(days), 1),
           "n_eval_dates": len(eval_set)}
    return rec, curve


def run_original(bars, pivots, ws, we):
    """Original his-rules form: monthly cadence, single episode, plain
    -15% floor ends the run (no restart) — the v7 engine's semantics."""
    idx = [i for i, b in enumerate(bars) if ws <= b["d"] <= we]
    days = [bars[i]["d"] for i in idx]
    eval_set = cadence_dates(days, "monthly")

    def want_fn(d):
        pv = pivots[(int(d[:4]), int(d[5:7]))]
        return pv["C"] > pv["P"]

    ep = run_episode(bars, idx, eval_set, want_fn, START_CASH, 85.0)
    if ep["halted"] is None and ep["shares"] > 0.0:
        b = bars[idx[-1]]
        val = ep["shares"] * b["c"]
        return round(val - (val * COST_RATE + SELL_FEE), 2), None
    return round(ep["cash"], 2), ep["halted"]


def main():
    bars = load_bars(LONG_PX)
    pivots = monthly_pivots(bars)

    # ---- integrity gate: original form, original windows
    integ = {}
    for name, (ws, we), pub in (("CONT", ("2019-01-02", "2026-11-20"), 168.05),
                                ("VAL", ("2023-01-03", "2026-11-20"), 152.42)):
        fin, halted = run_original(bars, pivots, ws, we)
        integ[name] = {"window": [ws, we], "published_final": pub,
                       "reproduced_final": fin,
                       "match": abs(fin - pub) < 0.005, "halted": halted}
        print(f"INTEGRITY {name}: published ${pub} reproduced ${fin} "
              f"match={integ[name]['match']} halted={halted}", flush=True)
    assert all(v["match"] for v in integ.values()), "INTEGRITY FAILED"

    spy = buy_hold(bars, DEC_START, DEC_END)
    print(f"SPY DECADE buy-hold: ${spy['final']} maxDD {spy['max_dd_pct']}%",
          flush=True)
    assert abs(spy["final"] - 367.80) < 0.01, "SPY DECADE mismatch"

    os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)
    cells = {}
    for cad in CADENCES:
        rec, curve = run_cell(bars, pivots, cad)
        twins = []
        for seed in range(1, 21):
            trec, _ = run_cell(bars, pivots, cad, placebo_seed=seed)
            twins.append({"seed": seed, "final": trec["final"]})
        beaten = sum(1 for t in twins if rec["final"] > t["final"])
        rec["placebo_beaten"] = beaten
        rec["placebo_note"] = (
            "20 coin-flip twins (seeds 1-20, p=0.5 per evaluation date, the "
            "original F-7 placebo design) run through the identical cadence "
            "machinery, costs and v9 protection at this cadence.")
        cell_doc = {"slug": "folklore-f7-pivots", "cadence": cad,
                    "window": [DEC_START, DEC_END], "start_cash": START_CASH,
                    "decade_spy_final": spy["final"],
                    **rec, "placebo_twins": twins, "equity_curve": curve}
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump(cell_doc, f, indent=1)
        cells[cad] = rec
        print(f"{cad.upper():11s} final ${rec['final']} CAGR "
              f"{rec['cagr_pct']}% maxDD {rec['max_dd_pct']}% costs "
              f"${rec['costs']} orders {rec['orders']} TIM "
              f"{rec['time_in_market_pct']}% placebo {beaten}/20 halts "
              f"{len(rec['halts'])}", flush=True)

    # monthly cell must reproduce W6's DECADE area run
    m = cells["monthly"]["final"]
    print(f"W6 DECADE monthly check: W6 $175.43 vs sweep ${m} "
          f"match={abs(m - 175.43) < 0.005}", flush=True)

    with open(os.path.join(HERE, "_sweep_summary.json"), "w") as f:
        json.dump({"integrity": integ, "spy": spy, "cells": cells},
                  f, indent=1)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
