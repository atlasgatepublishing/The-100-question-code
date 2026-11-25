#!/usr/bin/env python3
"""
W6b CADENCE SWEEP — F-6 Heikin-Ashi color turns (SPY timer).
THE GREAT RETEST (v10). Simulation only. One clean shot, frozen spec.

WHAT THIS SCRIPT DOES
  1. INTEGRITY (his rules, original form): re-runs the original v7 F-6
     engine logic (copied verbatim below as run_window_original) on the
     original windows/data (v4 cache px_SPY.json, HA recursion seeded at
     the first cached bar 2017-06-01, never re-seeded) and checks the
     published finals: FULL $84.82 (halted 2023-03-06), VAL $100.36.
     W6 already established integrity to the cent in v10 (see
     w6_results.json); this re-check is the sweep script's own gate.
  2. DECADE CADENCE MATRIX: 2016-11-21 -> 2026-11-20, $100/cell, on the
     long SPY bars (read-only shared cache
     backtests/v7/long-hold/data/pxfull_SPY.json, Yahoo 2008->2026,
     champion construction: every OHLC price scaled by adjclose/close,
     close = adjclose; HA recursion seeded once at the first bar
     2008-01-02 and run over the full series, point-in-time).
     7 cadences: daily, weekly, biweekly, monthly, quarterly,
     semi-annual, annual. Per the SPEC's uniform definition, the timer
     evaluates its signal ONLY on cadence dates (cadence date = first
     trading day of the week / second week / month / quarter / half /
     year; daily = every trading day). The F-6 signal evaluated on a
     cadence date is the frozen rule itself, read off that date's
     candle: ENTER if that candle is the first green after a red
     (color G, prior trading day's color R) while flat; EXIT if that
     candle is red while long. A signal at a cadence date's close
     executes at the next trading day's open, exactly as the original
     engine executes. Slower cadences therefore mechanically cut the
     switching count — the cost line per cell is a first-class result.
     The v9 -15% floor is a protection overlay, not a strategy signal:
     checked at every close (unchanged from v9), liquidates at the
     next open, sits out 90 calendar days, restarts once at the first
     trading day on/after eligibility (signal evaluation then resumes
     on cadence dates) under an episode-2 floor of -15% from the
     restart balance; a second halt ends the run.
  3. PLACEBOS (20 seeds/cell): the original F-6 design (reading R5 of
     the frozen spec): preserve the ranked run's realized trade count
     and holding durations (window-position space: entry open to exit
     open, or to the window end for a final-close liquidation), shuffle
     their order, and re-place them as non-overlapping blocks at random
     positions (free days distributed across the gaps by multinomial
     assignment), seeds 1..20. Identical costs, floor and v9 restart;
     only the TIMING of the in/out switches is randomized.

Costs: 0.10%/side + $0.01 per sell order (the original engine's own).
End of window: any open position is liquidated at the final close
(sell cost charged), as the original engine does.

Outputs (this folder): cells/<cadence>.json (full equity curve, halts
with dates, all 20 placebo twin finals), results.json (SPEC sweep
format), RESULTS.md is written by hand from _sweep_summary.json.
Memory: only SPY bars are loaded (per task note; shared RAM is tight).
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
PLACEBO_SEEDS = list(range(1, 21))


# ------------------------------------------------------------------ data
def load_bars(path):
    """Adjusted OHLC, champion construction (ratio = adjclose/close)."""
    with open(path, "rb") as f:
        j = json.loads(f.read())
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, h, l, c = (q["open"][i], q["high"][i], q["low"][i],
                      q["close"][i])
        if c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0

        def ap(x):
            return x * ratio if x else a

        bars.append({"d": d, "o": ap(o), "h": ap(h), "l": ap(l), "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars


def heikin_ashi_colors(bars):
    """Frozen recursion. Green iff HA-Close > HA-Open, else red."""
    colors = []
    ha_o = ha_c = None
    for i, b in enumerate(bars):
        ha_c = (b["o"] + b["h"] + b["l"] + b["c"]) / 4.0
        ha_o = (b["o"] + b["c"]) / 2.0 if i == 0 else (ha_o + ha_c) / 2.0
        colors.append("G" if ha_c > ha_o else "R")
    return colors


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


# -------------------------------------------- original engine (verbatim
# logic from backtests/v7/folklore-f6-heikinashi, his-rules floor, no
# restart — used ONLY for the integrity gate)
def run_window_original(bars, day_idx, colors, start_cash=100.0,
                        floor=85.0):
    cash, shares = start_cash, 0.0
    total_costs, trades, curve, halted, pending = 0.0, [], [], None, None
    open_entry = None
    n = len(day_idx)

    def do_buy(pos, gi):
        nonlocal cash, shares, total_costs, open_entry
        o = bars[gi]["o"]
        buy_val = cash / 1.001
        c = buy_val * 0.001
        shares = buy_val / o
        cash -= buy_val + c
        total_costs += c
        open_entry = (pos, buy_val + c)
        trades.append({"pos": pos, "date": bars[gi]["d"], "side": "BUY"})

    def do_sell(pos, gi, kind, price):
        nonlocal cash, shares, total_costs, open_entry
        val = shares * price
        c = val * 0.001 + 0.01
        cash += val - c
        total_costs += c
        trades.append({"pos": pos, "date": bars[gi]["d"], "side": kind})
        shares = 0.0
        open_entry = None

    for pos, gi in enumerate(day_idx):
        if pending is not None:
            if pending == "BUY" and shares == 0:
                do_buy(pos, gi)
            elif pending == "SELL" and shares > 0:
                do_sell(pos, gi, "SELL", bars[gi]["o"])
            pending = None
        if shares == 0 and pending is None:
            if colors[gi] == "G" and colors[gi - 1] == "R":
                pending = "BUY"
        elif shares > 0 and pending is None:
            if colors[gi] == "R":
                pending = "SELL"
        v = cash + shares * bars[gi]["c"]
        curve.append((bars[gi]["d"], v))
        if v <= floor and pos < n - 1:
            halted = bars[gi]["d"]
            ngi = day_idx[pos + 1]
            if shares > 0:
                do_sell(pos + 1, ngi, "SELL-HALT", bars[ngi]["o"])
            return {"final": cash, "costs": total_costs, "trades": trades,
                    "halted": halted, "curve": curve}
    if shares > 0:
        gi = day_idx[-1]
        do_sell(n - 1, gi, "SELL-END", bars[gi]["c"])
    return {"final": cash, "costs": total_costs, "trades": trades,
            "halted": None, "curve": curve}


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


def run_episode(bars, colors, day_idx, wpos_of, eval_set, mode,
                schedule, start_cash, floor):
    """One v9 episode over day_idx (global bar indices); wpos_of maps a
    global index to its position in the full window (for schedules).
    mode 'ha': F-6 signal evaluated only on eval_set dates.
    mode 'sched': placebo actions from schedule {wpos: [acts]} executed
    at that day's open (SELL before BUY). Floor checked at every close;
    on breach the position liquidates at the next open and the episode
    returns halted (the liquidation trade is included). No end-of-
    episode liquidation — the caller handles window end / halt cash."""
    cash, shares = start_cash, 0.0
    total_costs, trades, curve, days_in = 0.0, [], [], 0
    halted = liq_date = None
    pending = None
    open_entry = None
    n = len(day_idx)

    def do_buy(wpos, gi):
        nonlocal cash, shares, total_costs, open_entry
        o = bars[gi]["o"]
        buy_val = cash / 1.001
        c = buy_val * 0.001
        shares = buy_val / o
        cash -= buy_val + c
        total_costs += c
        open_entry = (wpos, buy_val + c)
        trades.append({"pos": wpos, "date": bars[gi]["d"], "side": "BUY",
                       "price": round(o, 4), "cost": round(c, 4)})

    def do_sell(wpos, gi, kind, price):
        nonlocal cash, shares, total_costs, open_entry
        val = shares * price
        c = val * 0.001 + 0.01
        cash += val - c
        total_costs += c
        trades.append({"pos": wpos, "date": bars[gi]["d"], "side": kind,
                       "price": round(price, 4), "cost": round(c, 4)})
        shares = 0.0
        open_entry = None

    for pos, gi in enumerate(day_idx):
        wpos = wpos_of[gi]
        # (1) execute at today's open
        if mode == "sched":
            for act in schedule.get(wpos, []):
                if act == "SELL" and shares > 0:
                    do_sell(wpos, gi, "SELL", bars[gi]["o"])
                elif act == "BUY" and shares == 0:
                    do_buy(wpos, gi)
        elif pending is not None:
            if pending == "BUY" and shares == 0:
                do_buy(wpos, gi)
            elif pending == "SELL" and shares > 0:
                do_sell(wpos, gi, "SELL", bars[gi]["o"])
            pending = None
        # (2) signal on today's candle — HA mode, cadence dates only
        if mode == "ha" and bars[gi]["d"] in eval_set:
            if shares == 0 and pending is None:
                if colors[gi] == "G" and colors[gi - 1] == "R":
                    pending = "BUY"
            elif shares > 0 and pending is None:
                if colors[gi] == "R":
                    pending = "SELL"
        # (3) mark to close; floor check (protection overlay, daily)
        v = cash + shares * bars[gi]["c"]
        curve.append([bars[gi]["d"], round(v, 2)])
        if shares > 0:
            days_in += 1
        if v <= floor and pos < n - 1:
            halted = bars[gi]["d"]
            ngi = day_idx[pos + 1]
            if shares > 0:
                do_sell(wpos_of[ngi], ngi, "SELL-HALT", bars[ngi]["o"])
                liq_date = bars[ngi]["d"]
            else:
                liq_date = halted
            break
    return {"cash": cash, "shares": shares, "costs": total_costs,
            "trades": trades, "curve": curve, "days_in": days_in,
            "halted": halted, "liq_date": liq_date}


def run_cell(bars, colors, cadence, mode="ha", schedule=None):
    """Full v9 run over the DECADE window. Returns (record, curve,
    trades) — record without curve/trades; trades carry window
    positions for placebo block extraction."""
    idx_all = [i for i, b in enumerate(bars) if DEC_START <= b["d"] <= DEC_END]
    days = [bars[i]["d"] for i in idx_all]
    wpos_of = {gi: p for p, gi in enumerate(idx_all)}
    eval_set = cadence_dates(days, cadence) if mode == "ha" else set()

    halts, all_trades, curve = [], [], []
    restart = second_halt = False
    total_costs, total_days_in = 0.0, 0
    start, start_cash, floor = DEC_START, START_CASH, 0.85 * START_CASH
    final = None
    for episode in (1, 2):
        idx = [i for i in idx_all if bars[i]["d"] >= start]
        ep = run_episode(bars, colors, idx, wpos_of, eval_set, mode,
                         schedule, start_cash, floor)
        total_costs += ep["costs"]
        total_days_in += ep["days_in"]
        all_trades += ep["trades"]
        if episode == 1:
            curve = ep["curve"]
        else:
            gap = [[d, round(start_cash, 2)] for d in days
                   if curve[-1][0] < d < ep["curve"][0][0]]
            curve = curve + gap + ep["curve"]
        if ep["halted"] is None:
            if ep["shares"] > 0:
                gi = idx[-1]
                val = ep["shares"] * bars[gi]["c"]
                scost = val * COST_RATE + SELL_FEE
                total_costs += scost
                all_trades.append({"pos": wpos_of[gi],
                                   "date": bars[gi]["d"], "side": "SELL-END",
                                   "price": round(bars[gi]["c"], 4),
                                   "cost": round(scost, 4)})
                final = val - scost
                curve[-1] = [bars[gi]["d"], round(final, 2)]
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
        start, start_cash = rest[0], ep["cash"]
        floor = 0.85 * start_cash
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
        "costs": round(total_costs, 2),
        "orders": len(all_trades),
        "time_in_market_pct": round(100.0 * total_days_in / len(days), 1),
        "n_eval_dates": len(eval_set) if mode == "ha" else None,
    }
    return rec, curve, all_trades, len(days)


def extract_blocks(trades, n_days):
    blocks, entry = [], None
    for t in trades:
        if t["side"] == "BUY":
            entry = t["pos"]
        elif entry is not None:
            ev = n_days if t["side"] == "SELL-END" else t["pos"]
            blocks.append((entry, ev))
            entry = None
    return blocks


def placebo_schedule(blocks, n_days, rng):
    """Original F-6 reading R5, verbatim placement logic."""
    durations = [ev - en for en, ev in blocks]
    rng.shuffle(durations)
    k = len(durations)
    free = n_days - sum(durations)
    gaps = [0] * (k + 1)
    for _ in range(max(free, 0)):
        gaps[rng.randrange(k + 1)] += 1
    schedule = {}
    s = gaps[0]
    for i, d in enumerate(durations):
        schedule.setdefault(s, []).append("BUY")
        e = s + d
        if e <= n_days - 1:
            schedule.setdefault(e, []).append("SELL")
        s = e + gaps[i + 1]
    for pos in schedule:
        schedule[pos].sort(key=lambda a: 0 if a == "SELL" else 1)
    return schedule


def main():
    # ---- integrity: original engine, original windows, original data
    bars_v4 = load_bars(V4_PX)
    colors_v4 = heikin_ashi_colors(bars_v4)
    integ = {}
    for name, ws, we, pub, pub_halt in (
            ("FULL", "2019-01-01", "2026-11-20", 84.82, "2023-03-06"),
            ("VAL", "2023-01-01", "2026-11-20", 100.36, None)):
        idx = [i for i, b in enumerate(bars_v4) if ws <= b["d"] <= we]
        r = run_window_original(bars_v4, idx, colors_v4)
        integ[name] = {"window": [ws, we], "published_final": pub,
                       "reproduced_final": round(r["final"], 2),
                       "match": abs(r["final"] - pub) < 0.005,
                       "halted": r["halted"]}
        print(f"INTEGRITY {name}: published ${pub} reproduced "
              f"${r['final']:,.2f} match={integ[name]['match']} "
              f"halted={r['halted']} (published halt {pub_halt})",
              flush=True)
    assert all(v["match"] for v in integ.values()), "integrity FAILED"

    # ---- decade bars + SPY control (SPY bars only, per memory note)
    bars = load_bars(LONG_PX)
    colors = heikin_ashi_colors(bars)
    spy = buy_hold(bars, DEC_START, DEC_END)
    print(f"SPY DECADE buy-hold: ${spy['final']} maxDD {spy['max_dd_pct']}%",
          flush=True)

    os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)
    cells = {}
    for cad in CADENCES:
        rec, curve, trades, n_days = run_cell(bars, colors, cad)
        blocks = extract_blocks(trades, n_days)
        twins = []
        for seed in PLACEBO_SEEDS:
            rng = random.Random(seed)
            sched = placebo_schedule(blocks, n_days, rng)
            trec, _, _, _ = run_cell(bars, colors, cad, mode="sched",
                                     schedule=sched)
            twins.append({"seed": seed, "final": trec["final"],
                          "costs": trec["costs"], "orders": trec["orders"],
                          "halts": trec["halts"]})
        beaten = sum(1 for t in twins if rec["final"] > t["final"])
        rec["placebo_beaten"] = beaten
        rec["placebo_note"] = (
            "20 seeds (1-20) of the original F-6 placebo design (frozen "
            "spec reading R5): the ranked run's realized holding "
            "durations at this cadence, shuffled and re-placed as "
            "non-overlapping blocks at random positions, run through "
            "identical costs, floor and v9 restart machinery. Only the "
            "timing of the switches is randomized.")
        cell_doc = {"slug": "folklore-f6-heikinashi", "cadence": cad,
                    "window": [DEC_START, DEC_END],
                    "start_cash": START_CASH, **rec,
                    "placebo_twins": twins, "equity_curve": curve}
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
