#!/usr/bin/env python3
"""
THE GREAT RETEST (v10) — CADENCE SWEEP for rsi2-mean-reversion.

Strategy (Connors RSI(2), ORIGINAL published form as verified by the
integrity run of rsi2_original.py in this folder):
  - Instrument: SPY only (the original engine is SPY-only; no QQQ leg
    exists in the published form). Whole $100 pot in or out; cash 0%.
  - BUY signal (at close): SPY close above its 200-day SMA AND Wilder
    RSI(2) < 10 -> buy at next open.
  - EXIT signal (at close): SPY close above its 5-day SMA -> sell at
    next open. (This close>SMA5 exit is the definitional exit of the
    published engine; it is what reproduces CONT $110.78 / VAL $105.06.)
  - Costs: program schedule — 0.10% of trade value per side + $0.01 per
    sell order. Fractional shares.
  - Protection: adopted v9 rules — plain -15% floor from the episode's
    starting balance; on first halt liquidate at next open, sit in cash
    90 calendar days, restart at the strategy's next regular decision
    point (next cadence date) under an episode-2 floor of -15% from
    the restart balance; second halt ends the run.

ROAD: DECADE 2016-11-21 -> 2026-11-20, $100 per cell.

CADENCE (SPEC uniform definition): signal evaluation, selection and
trading happen ONLY on cadence dates — daily = every trading day;
weekly = first trading day of each week; biweekly = first trading day
of every second week (weeks anchored at the window start); monthly =
first trading day of each month; quarterly = first trading day of
each calendar quarter; semi-annual = first trading day of each
half-year; annual = first trading day of each year. Signals are
evaluated at a cadence date's close and executed at the NEXT cadence
date's open, so no trade ever occurs off-cadence. BOTH the RSI(2)
entries AND the definitional close>SMA5 exits are evaluated only on
cadence dates — at slower cadences a position can sit for months past
its daily exit signal; that distortion is the sweep's question for
this strategy.

ONE exception, stated plainly: the -15% floor is a protection, not a
signal. Following the original engine, the floor is checked at every
close and a breach liquidates at the next trading day's open
regardless of cadence. (On this road the floor in fact never fires in
any cell — see results — so the exception changes nothing here.)

PLACEBOS (20 seeds per cell): random-entry twins. Each twin keeps the
200-day trend filter, the close>SMA5 exit rule, the cadence, the costs
and the v9 protections, but replaces the RSI(2)<10 entry condition
with a coin flip on each eligible cadence date (flat, active, close
above SMA200). The flip probability is calibrated per cell to the
real run: p = (real entries) / (real eligible cadence dates), so the
twins enter about as often as the strategy did — what is randomized
is WHEN, i.e. whether the oversold timing itself adds anything.

Data: SPY daily bars only, read from the read-only v6 cache copied
into this folder (px_SPY_long.json, Yahoo adjclose-based construction,
2015-06-01 -> 2026-11-20). Indicators (SMA5, SMA200, Wilder RSI(2))
computed on the full series from 2015 so the decade starts with a
genuine point-in-time 200-day average. No other instrument is loaded.
"""
import json
import os
import random
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
PX = os.path.join(HERE, "px_SPY_long.json")

START_CASH = 100.0
COST_RATE = 0.001      # 0.10% per side
SELL_FEE = 0.01        # $0.01 per sell order
FLOOR_FRAC = 0.85      # plain -15% floor from episode start balance
SIT_DAYS = 90          # calendar days in cash after a first halt

DEC_START, DEC_END = "2016-11-21", "2026-11-20"
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]


# ---------------------------------------------------------------- data
def load_bars():
    """Identical construction to the original v6 engine."""
    import time
    with open(PX, "rb") as f:
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
    """SMA5, SMA200 and Wilder RSI(2) — verbatim from the original."""
    closes = [b["c"] for b in bars]
    n = len(closes)
    sma5 = [None] * n
    sma200 = [None] * n
    run5 = 0.0
    run200 = 0.0
    for i, c in enumerate(closes):
        run5 += c
        run200 += c
        if i >= 5:
            run5 -= closes[i - 5]
        if i >= 200:
            run200 -= closes[i - 200]
        if i >= 4:
            sma5[i] = run5 / 5.0
        if i >= 199:
            sma200[i] = run200 / 200.0
    rsi = [None] * n
    if n > 2:
        gains = [max(closes[i] - closes[i - 1], 0.0) for i in range(1, n)]
        losses = [max(closes[i - 1] - closes[i], 0.0) for i in range(1, n)]
        ag = (gains[0] + gains[1]) / 2.0
        al = (losses[0] + losses[1]) / 2.0
        for i in range(2, n):
            if i > 2:
                ag = (ag * 1.0 + gains[i - 1]) / 2.0
                al = (al * 1.0 + losses[i - 1]) / 2.0
            if al == 0:
                rsi[i] = 100.0 if ag > 0 else 50.0
            else:
                rsi[i] = 100.0 - 100.0 / (1.0 + ag / al)
    for i, b in enumerate(bars):
        b["sma5"] = sma5[i]
        b["sma200"] = sma200[i]
        b["rsi2"] = rsi[i]
    return bars


def cadence_indices(bars, idx, cadence):
    """Set of bar indices (within the window list idx) that are cadence
    dates, per the SPEC's uniform definition."""
    if cadence == "daily":
        return set(idx)
    out = []
    seen_keys = []
    for i in idx:
        d = bars[i]["d"]
        y, m, day = int(d[:4]), int(d[5:7]), int(d[8:10])
        if cadence in ("weekly", "biweekly"):
            iso = date(y, m, day).isocalendar()
            key = (iso[0], iso[1])
        elif cadence == "monthly":
            key = (y, m)
        elif cadence == "quarterly":
            key = (y, (m - 1) // 3)
        elif cadence == "semiannual":
            key = (y, (m - 1) // 6)
        elif cadence == "annual":
            key = (y,)
        else:
            raise ValueError(cadence)
        if key not in seen_keys:
            seen_keys.append(key)
            out.append(i)
    if cadence == "biweekly":
        out = out[::2]  # every second week, anchored at window start
    return set(out)


# ---------------------------------------------------------------- engine
def run_cell(bars, start, end, cadence, mode="signal", p_entry=None,
             seed=None):
    """One cadence cell. mode='signal' = the real strategy;
    mode='placebo' = random-entry twin (coin flip with prob p_entry on
    eligible cadence dates). Returns full metrics incl. equity curve."""
    idx = [i for i, b in enumerate(bars) if start <= b["d"] <= end]
    cad = cadence_indices(bars, idx, cadence)
    rng = random.Random(seed) if mode == "placebo" else None

    cash = START_CASH
    shares = 0.0
    entry_cost = None
    entry_date = None
    trades = []
    costs = 0.0
    orders = 0
    curve = []
    days_in = 0
    entries = 0
    eligible = 0

    episode = 1
    episode_start = START_CASH
    state = "active"           # active | sitting | ended
    halt_date = None
    halts = []                 # [{halt_date, episode, restart_date}]
    restart_date = None
    pending = None             # 'buy' | 'sell' — executes at next cadence open
    floor_sell = False         # floor liquidation pending at next open (any day)

    def do_buy(b):
        nonlocal cash, shares, entry_cost, entry_date, costs, orders, entries
        px = b["o"]
        shares = cash / (px * (1.0 + COST_RATE))
        costs += shares * px * COST_RATE
        orders += 1
        entry_cost = cash
        entry_date = b["d"]
        cash = 0.0
        entries += 1

    def do_sell(b, reason):
        nonlocal cash, shares, entry_cost, entry_date, costs, orders
        px = b["o"]
        val = shares * px
        scost = val * COST_RATE + SELL_FEE
        costs += scost
        orders += 1
        proceeds = val - scost
        trades.append({
            "entry": entry_date, "exit": b["d"],
            "pnl": round(proceeds - entry_cost, 2),
            "ret_pct": round((proceeds / entry_cost - 1.0) * 100, 2),
            "exit_reason": reason,
        })
        cash = proceeds
        shares = 0.0
        entry_cost = None
        entry_date = None
        return cash

    for pos, i in enumerate(idx):
        b = bars[i]
        is_cad = i in cad
        is_last = pos == len(idx) - 1

        # --- executions at this open. A pending signal order lives
        # until the NEXT CADENCE date's open (trading happens only on
        # cadence dates); it is cleared there whether or not it fills.
        if floor_sell:
            # protection liquidation: next open, cadence or not
            if shares > 0.0:
                do_sell(b, "floor")
            floor_sell = False
            if episode == 1:
                state = "sitting"
                halt_date = halts[-1]["halt_date"]
            else:
                state = "ended"
        elif is_cad:
            if pending == "buy" and shares == 0.0 and state == "active":
                do_buy(b)
            elif pending == "sell" and shares > 0.0:
                do_sell(b, "signal")
            pending = None

        # --- restart check (next regular decision point after 90 days)
        if state == "sitting" and is_cad and halt_date is not None:
            hd = date(int(halt_date[:4]), int(halt_date[5:7]), int(halt_date[8:10]))
            td = date(int(b["d"][:4]), int(b["d"][5:7]), int(b["d"][8:10]))
            if td >= hd + timedelta(days=SIT_DAYS):
                state = "active"
                episode = 2
                episode_start = cash
                restart_date = b["d"]
                halts[-1]["restart_date"] = restart_date

        equity = cash + shares * b["c"]
        curve.append([b["d"], round(equity, 4)])
        if shares > 0.0:
            days_in += 1
        if is_last:
            break

        # --- floor check at the close (protection; every close, as the
        # original engine does)
        if state == "active" and equity < FLOOR_FRAC * episode_start:
            halts.append({"halt_date": b["d"], "episode": episode,
                          "restart_date": None})
            if shares > 0.0:
                floor_sell = True
            elif episode == 1:
                state = "sitting"
                halt_date = b["d"]
            else:
                state = "ended"
            continue
        if state != "active":
            continue

        # --- signals at the close, cadence dates only
        if not is_cad:
            continue
        if shares == 0.0:
            if (b["sma200"] is not None and b["rsi2"] is not None
                    and b["c"] > b["sma200"]):
                eligible += 1
                if mode == "signal":
                    if b["rsi2"] < 10:
                        pending = "buy"
                else:
                    if rng.random() < p_entry:
                        pending = "buy"
        else:
            if b["sma5"] is not None and b["c"] > b["sma5"]:
                pending = "sell"

    # final liquidation at the last close, if still holding
    if shares > 0.0:
        b = bars[idx[-1]]
        val = shares * b["c"]
        scost = val * COST_RATE + SELL_FEE
        costs += scost
        orders += 1
        proceeds = val - scost
        trades.append({
            "entry": entry_date, "exit": b["d"],
            "pnl": round(proceeds - entry_cost, 2),
            "ret_pct": round((proceeds / entry_cost - 1.0) * 100, 2),
            "exit_reason": "window_end",
        })
        cash = proceeds
        shares = 0.0
        curve[-1] = [b["d"], round(cash, 4)]

    final = cash
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    yrs = (date(int(end[:4]), int(end[5:7]), int(end[8:10]))
           - date(int(start[:4]), int(start[5:7]), int(start[8:10]))).days / 365.25
    cagr = (final / START_CASH) ** (1.0 / yrs) * 100 - 100 if final > 0 else -100.0
    return {
        "start": start, "end": end, "cadence": cadence,
        "final": round(final, 2),
        "cagr_pct": round(cagr, 2),
        "max_dd_pct": round(maxdd * 100, 2),
        "costs": round(costs, 2),
        "orders": orders,
        "trades": len(trades),
        "win_rate_pct": round(100.0 * len(wins) / len(trades), 1) if trades else None,
        "avg_win": round(sum(t["pnl"] for t in wins) / len(wins), 2) if wins else None,
        "avg_loss": round(sum(t["pnl"] for t in losses) / len(losses), 2) if losses else None,
        "expectancy_per_trade": round(sum(t["pnl"] for t in trades) / len(trades), 2) if trades else None,
        "time_in_market_pct": round(100.0 * days_in / len(idx), 1) if idx else None,
        "halts": halts,
        "restart": restart_date is not None,
        "restart_date": restart_date,
        "second_halt": any(h["episode"] == 2 for h in halts),
        "entries": entries,
        "eligible_cadence_dates": eligible,
        "trade_log": trades,
        "equity_curve": curve,
    }


def buy_hold(bars, start, end):
    """SPY buy-hold, fresh $100, same costs, no floor (program
    convention, identical to the original engine's control)."""
    idx = [i for i, b in enumerate(bars) if start <= b["d"] <= end]
    first, last = bars[idx[0]], bars[idx[-1]]
    shares = START_CASH / (first["o"] * (1.0 + COST_RATE))
    val = shares * last["c"]
    final = val - (val * COST_RATE + SELL_FEE)
    peak, maxdd = -1.0, 0.0
    curve = []
    for i in idx:
        v = shares * bars[i]["c"]
        curve.append([bars[i]["d"], round(v, 4)])
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    curve[-1] = [last["d"], round(final, 4)]
    return {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 2),
            "equity_curve": curve}


def main():
    bars = add_indicators(load_bars())
    spy = buy_hold(bars, DEC_START, DEC_END)
    print(f"DECADE SPY buy-hold: ${spy['final']} maxDD={spy['max_dd_pct']}% "
          f"(SPEC reference $367.80)")

    cells = {}
    for cad in CADENCES:
        r = run_cell(bars, DEC_START, DEC_END, cad)
        p = (r["entries"] / r["eligible_cadence_dates"]
             if r["eligible_cadence_dates"] else 0.0)
        twin_finals = []
        for seed in range(1, 21):
            t = run_cell(bars, DEC_START, DEC_END, cad, mode="placebo",
                         p_entry=p, seed=seed)
            twin_finals.append(t["final"])
        beaten = sum(1 for f in twin_finals if r["final"] > f)
        cell = {
            "cadence": cad, "start": DEC_START, "end": DEC_END,
            "final": r["final"], "cagr_pct": r["cagr_pct"],
            "max_dd_pct": r["max_dd_pct"], "costs": r["costs"],
            "orders": r["orders"], "trades": r["trades"],
            "win_rate_pct": r["win_rate_pct"], "avg_win": r["avg_win"],
            "avg_loss": r["avg_loss"],
            "expectancy_per_trade": r["expectancy_per_trade"],
            "time_in_market_pct": r["time_in_market_pct"],
            "halts": r["halts"], "restart": r["restart"],
            "restart_date": r["restart_date"],
            "second_halt": r["second_halt"],
            "entries": r["entries"],
            "eligible_cadence_dates": r["eligible_cadence_dates"],
            "placebo_p_entry": round(p, 4),
            "placebo_twin_finals": twin_finals,
            "placebo_beaten": beaten,
            "trade_log": r["trade_log"],
            "equity_curve": r["equity_curve"],
        }
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump(cell, f, indent=1)
        cells[cad] = cell
        print(f"{cad:11s} final=${r['final']:7.2f} CAGR={r['cagr_pct']:+.2f}% "
              f"maxDD={r['max_dd_pct']:5.2f}% trades={r['trades']:3d} "
              f"win={r['win_rate_pct']}% exp={r['expectancy_per_trade']} "
              f"inMkt={r['time_in_market_pct']}% costs=${r['costs']} "
              f"halts={len(r['halts'])} placebo {beaten}/20 "
              f"(twins min={min(twin_finals)} max={max(twin_finals)})")

    summary = {
        "slug": "rsi2-mean-reversion",
        "decade_spy_final": spy["final"],
        "decade_spy_max_dd_pct": spy["max_dd_pct"],
        "cells": {c: {k: cells[c][k] for k in (
            "final", "cagr_pct", "max_dd_pct", "costs", "orders", "trades",
            "win_rate_pct", "avg_win", "avg_loss", "expectancy_per_trade",
            "time_in_market_pct", "halts", "restart", "second_halt",
            "placebo_beaten", "placebo_twin_finals")}
            for c in CADENCES},
    }
    with open(os.path.join(HERE, "sweep_summary.json"), "w") as f:
        json.dump(summary, f, indent=1)
    print("DONE")


if __name__ == "__main__":
    main()
