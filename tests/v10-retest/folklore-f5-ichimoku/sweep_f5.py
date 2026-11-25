#!/usr/bin/env python3
"""
W6b CADENCE SWEEP — F-5 Ichimoku Cloud (9/26/52), SPY. THE GREAT RETEST
(v10). Simulation only. One clean shot, frozen spec — no tuning.

WHAT THIS SCRIPT DOES
  1. INTEGRITY (his rules, original form): re-runs the original v7 F-5
     engine logic (copied verbatim below as run_timer_original, with the
     v7 ichimoku/entry_ok/exit_ok construction) on the original data
     (v4 cache px_SPY.json) and original windows, and checks the
     published finals: FULL (2019-01-01->2026-11-20) $204.72,
     VALIDATION (2023-01-01->2026-11-20) $165.08. W6 already established
     integrity to the cent in v10; this re-check is the sweep script's
     own gate and is recorded in results.json.
  2. DECADE CADENCE MATRIX: 2016-11-21 -> 2026-11-20, $100/cell, on the
     long SPY OHLC bars (read-only shared cache
     backtests/v7/long-hold/data/pxfull_SPY.json, Yahoo 2008->2026;
     adjusted OHLC by the champion/v7 ratio method: every OHLC field
     scaled by adjclose/close, close = adjclose; Ichimoku computed on
     the full series, point-in-time — the cloud compared on day t is
     formed by span values computed from data through day t-26).
     7 cadences: daily, weekly, biweekly, monthly, quarterly,
     semi-annual, annual. Per the SPEC's uniform definition, the timer
     evaluates its signal ONLY on cadence dates (cadence date = first
     trading day of the week / second week / month / quarter / half /
     year; daily = every trading day). A switch signalled at a cadence
     date's close executes at the next trading day's open, exactly as
     the original engine executes. The v9 -15% floor is a protection
     overlay, not a strategy signal: it is checked at every close
     (close at/below the floor -> liquidate at next open), sits out 90
     calendar days, restarts once at the first trading day on/after
     eligibility (signal evaluation then resumes on cadence dates)
     under an episode-2 floor of -15% from the restart balance; a
     second halt ends the run.
  3. PLACEBOS (20 seeds/cell): the original F-5 engine's own placebo
     design (random-toggle twins: the desired long/flat state flips on
     randomly drawn toggle days, the count of toggles equal to the
     strategy cell's own executed signal switches), adapted to the
     uniform cadence rule — toggle days are drawn from the cell's own
     cadence evaluation dates (excluding the final day, which has no
     next open). Seeds 1..20. Each twin runs through the identical
     cadence machinery and v9 protection.

Strategy (Spec F-5, frozen, verbatim): hold SPY when the close is above
the cloud AND Tenkan > Kijun; exit to cash when the close falls below
the cloud OR Tenkan < Kijun. Tenkan = (9-day high + 9-day low)/2;
Kijun = (26-day high + 26-day low)/2; cloud on day t from spans
computed through t-26 (Senkou A = (Tenkan+Kijun)/2, Senkou B = 52-day
midpoint, both displaced 26 days).

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
    """Adjusted OHLC from a shared Yahoo payload, v7/champion ratio
    method (identical to the original F-5 loader)."""
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
        if c is None or o is None or h is None or l is None:
            continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        bars.append({"d": d, "o": o * ratio, "h": h * ratio,
                     "l": l * ratio, "c": a})
    bars.sort(key=lambda b: b["d"])
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


# ------------------------------------------------- ichimoku (v7 verbatim)
def ichimoku(bars):
    H = [b["h"] for b in bars]
    L = [b["l"] for b in bars]
    n = len(bars)

    def mid(i, k):
        if i < k - 1:
            return None
        return (max(H[i - k + 1:i + 1]) + min(L[i - k + 1:i + 1])) / 2.0

    tenkan = [mid(i, 9) for i in range(n)]
    kijun = [mid(i, 26) for i in range(n)]
    span_a_at = [((tenkan[i] + kijun[i]) / 2.0)
                 if tenkan[i] is not None and kijun[i] is not None else None
                 for i in range(n)]
    span_b_at = [mid(i, 52) for i in range(n)]
    out = []
    for t in range(n):
        src = t - 26
        a = span_a_at[src] if src >= 0 else None
        b = span_b_at[src] if src >= 0 else None
        if a is None or b is None:
            top = bot = None
        else:
            top, bot = max(a, b), min(a, b)
        out.append({"tenkan": tenkan[t], "kijun": kijun[t],
                    "cloud_top": top, "cloud_bot": bot})
    return out


def entry_ok(bars, ich, i):
    x = ich[i]
    if x["cloud_top"] is None or x["tenkan"] is None or x["kijun"] is None:
        return False
    return bars[i]["c"] > x["cloud_top"] and x["tenkan"] > x["kijun"]


def exit_ok(bars, ich, i):
    x = ich[i]
    if x["cloud_bot"] is None or x["tenkan"] is None or x["kijun"] is None:
        return False
    return bars[i]["c"] < x["cloud_bot"] or x["tenkan"] < x["kijun"]


# --------------------------------------- original engine (v7 logic,
# his-rules floor: halt liquidates at next open and the run ENDS)
def run_timer_original(bars, ich, start, end):
    days = [i for i, b in enumerate(bars) if start <= b["d"] <= end]
    cash = START_CASH
    shares = 0.0
    pending = None
    trades = []
    total_costs = 0.0
    halted = None
    end_date = bars[days[-1]]["d"]
    for k, i in enumerate(days):
        d = bars[i]["d"]
        if pending == "BUY" and shares == 0.0:
            buy_val = cash / 1.001
            sh = buy_val / bars[i]["o"]
            c = buy_val * 0.001
            cash -= buy_val + c
            total_costs += c
            shares = sh
            trades.append((d, "BUY"))
        elif pending == "SELL" and shares > 0.0:
            val = shares * bars[i]["o"]
            c = val * 0.001 + 0.01
            cash += val - c
            total_costs += c
            trades.append((d, "SELL"))
            shares = 0.0
        pending = None
        if shares == 0.0 and entry_ok(bars, ich, i):
            pending = "BUY"
        elif shares > 0.0 and exit_ok(bars, ich, i):
            pending = "SELL"
        v = cash + shares * bars[i]["c"]
        if v <= 85.0 and k < len(days) - 1:
            halted = d
            if shares > 0.0:
                nd = bars[days[k + 1]]
                val = shares * nd["o"]
                c = val * 0.001 + 0.01
                cash += val - c
                total_costs += c
                trades.append((nd["d"], "SELL-HALT"))
                shares = 0.0
                end_date = nd["d"]
            return {"final": cash, "costs": total_costs, "halted": halted,
                    "trades": trades, "end": end_date}
    if shares > 0.0:
        last = bars[days[-1]]
        val = shares * last["c"]
        c = val * 0.001 + 0.01
        cash += val - c
        total_costs += c
        trades.append((last["d"], "SELL-END"))
        shares = 0.0
    return {"final": cash, "costs": total_costs, "halted": None,
            "trades": trades, "end": end_date}


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


def run_episode(bars, ich, idx, eval_set, start_cash, floor,
                toggles=None):
    """One v9 episode. Strategy mode: the F-5 state machine is consulted
    only on cadence dates. Placebo mode (toggles = set of bar indices):
    the desired state flips on toggle dates (all toggle dates are
    cadence dates). Floor checked at every close (champion semantics:
    close at/below floor). Returns running state; the caller liquidates
    at window end only for a completed run."""
    cash, shares = start_cash, 0.0
    halted = None
    liq_date = None
    trades, costs, orders, switches, curve, days_in = [], 0.0, 0, 0, [], 0
    pending = pending_kind = None
    desired_long = False
    for pos, i in enumerate(idx):
        b = bars[i]
        if pending == "BUY" and shares == 0.0 and halted is None:
            buy_val = cash / (1.0 + COST_RATE)
            shares = buy_val / b["o"]
            c = buy_val * COST_RATE
            cash -= buy_val + c
            costs += c
            orders += 1
            switches += 1
            trades.append((b["d"], "BUY"))
        elif pending == "SELL" and shares > 0.0:
            val = shares * b["o"]
            c = val * COST_RATE + SELL_FEE
            cash += val - c
            costs += c
            orders += 1
            if pending_kind == "signal":
                switches += 1
            trades.append((b["d"], "SELL-HALT" if pending_kind == "floor"
                           else "SELL"))
            shares = 0.0
            if pending_kind == "floor":
                liq_date = b["d"]
        pending = pending_kind = None
        equity = cash + shares * b["c"]
        curve.append([b["d"], round(equity, 2)])
        if shares > 0.0:
            days_in += 1
        if pos == len(idx) - 1:
            break
        if halted is None and equity <= floor:
            halted = b["d"]
            if shares > 0.0:
                pending, pending_kind = "SELL", "floor"
            continue
        if halted is not None:
            continue
        if b["d"] not in eval_set:
            continue
        if toggles is not None:
            if i in toggles:
                desired_long = not desired_long
                if desired_long and shares == 0.0:
                    pending, pending_kind = "BUY", "signal"
                elif not desired_long and shares > 0.0:
                    pending, pending_kind = "SELL", "signal"
        else:
            if shares == 0.0 and entry_ok(bars, ich, i):
                pending, pending_kind = "BUY", "signal"
            elif shares > 0.0 and exit_ok(bars, ich, i):
                pending, pending_kind = "SELL", "signal"
    return {"cash": cash, "shares": shares, "halted": halted,
            "liq_date": liq_date, "trades": trades, "costs": costs,
            "orders": orders, "switches": switches, "curve": curve,
            "days_in": days_in}


def run_cell(bars, ich, cadence, toggles=None):
    """Full v9 run over the DECADE window at one cadence."""
    idx_all = [i for i, b in enumerate(bars) if DEC_START <= b["d"] <= DEC_END]
    days = [bars[i]["d"] for i in idx_all]
    eval_set = cadence_dates(days, cadence)

    halts = []
    restart = False
    second_halt = False
    total_costs = 0.0
    total_orders = 0
    total_switches = 0
    total_days_in = 0
    curve = []
    start, start_cash, floor = DEC_START, START_CASH, 0.85 * START_CASH
    final = None
    for episode in (1, 2):
        idx = [i for i in idx_all if bars[i]["d"] >= start]
        ep = run_episode(bars, ich, idx, eval_set, start_cash, floor,
                         toggles=toggles)
        total_costs += ep["costs"]
        total_orders += ep["orders"]
        total_switches += ep["switches"]
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
    yrs = (date.fromisoformat(DEC_END) -
           date.fromisoformat(DEC_START)).days / 365.25
    return {
        "final": round(final, 2),
        "cagr_pct": round(((final / START_CASH) ** (1.0 / yrs) - 1.0) * 100, 2),
        "max_dd_pct": round(maxdd * 100, 2),
        "halts": halts, "restart": restart, "second_halt": second_halt,
        "costs": round(total_costs, 2), "orders": total_orders,
        "switches": total_switches,
        "time_in_market_pct": round(100.0 * total_days_in / len(days), 1),
        "n_eval_dates": len(eval_set),
    }, curve


def main():
    # ---- integrity: original engine, original windows, original data
    bars_v4 = load_bars(V4_PX)
    ich_v4 = ichimoku(bars_v4)
    integ = {}
    for name, (ws, we), pub in (("FULL", ("2019-01-01", "2026-11-20"), 204.72),
                                ("VAL", ("2023-01-01", "2026-11-20"), 165.08)):
        r = run_timer_original(bars_v4, ich_v4, ws, we)
        integ[name] = {"window": [ws, we], "published_final": pub,
                       "reproduced_final": round(r["final"], 2),
                       "match": abs(round(r["final"], 2) - pub) < 0.005,
                       "halted": r["halted"]}
        print(f"INTEGRITY {name}: published ${pub} reproduced "
              f"${r['final']:,.2f} match={integ[name]['match']} "
              f"halted={r['halted']}", flush=True)
    assert all(v["match"] for v in integ.values()), "integrity FAILED"
    del bars_v4, ich_v4

    # ---- decade bars + SPY control
    bars = load_bars(LONG_PX)
    ich = ichimoku(bars)
    spy = buy_hold(bars, DEC_START, DEC_END)
    print(f"SPY DECADE buy-hold: ${spy['final']} maxDD {spy['max_dd_pct']}%",
          flush=True)

    idx_all = [i for i, b in enumerate(bars) if DEC_START <= b["d"] <= DEC_END]
    days = [bars[i]["d"] for i in idx_all]

    os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)
    cells = {}
    for cad in CADENCES:
        rec, curve = run_cell(bars, ich, cad)
        # placebos: original F-5 random-toggle design, toggles drawn
        # from this cell's cadence evaluation dates (minus final day)
        eval_set = cadence_dates(days, cad)
        cand_idx = [i for i in idx_all
                    if bars[i]["d"] in eval_set][:-1]
        twins = []
        for seed in range(1, 21):
            rng = random.Random(seed)
            toggles = set(rng.sample(
                cand_idx, min(rec["switches"], len(cand_idx))))
            trec, _ = run_cell(bars, ich, cad, toggles=toggles)
            twins.append({"seed": seed, "final": trec["final"],
                          "n_toggles": len(toggles)})
        beaten = sum(1 for t in twins if rec["final"] > t["final"])
        rec["placebo_beaten"] = beaten
        rec["placebo_note"] = (
            "20 random-toggle twins (the original F-5 engine's own "
            "placebo design, seeds 1-20): the desired long/flat state "
            "flips on toggle days drawn at random from this cell's "
            "cadence evaluation dates, the toggle count equal to the "
            "strategy cell's executed signal switches; each twin runs "
            "through the identical cadence machinery and v9 protection.")
        cell_doc = {"slug": "folklore-f5-ichimoku", "cadence": cad,
                    "window": [DEC_START, DEC_END], "start_cash": START_CASH,
                    **rec, "placebo_twins": twins,
                    "equity_curve": curve}
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump(cell_doc, f, indent=1)
        cells[cad] = rec
        print(f"{cad.upper():11s} final ${rec['final']} CAGR "
              f"{rec['cagr_pct']}% maxDD {rec['max_dd_pct']}% costs "
              f"${rec['costs']} orders {rec['orders']} TIM "
              f"{rec['time_in_market_pct']}% placebo beaten {beaten}/20 "
              f"halts {len(rec['halts'])}", flush=True)

    with open(os.path.join(HERE, "_sweep_summary.json"), "w") as f:
        json.dump({"integrity": integ,
                   "spy": {"final": spy["final"],
                           "max_dd_pct": spy["max_dd_pct"]},
                   "cells": cells}, f, indent=1)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
