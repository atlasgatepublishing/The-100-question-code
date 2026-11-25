#!/usr/bin/env python3
"""
W6b CADENCE SWEEP — F-1 Fibonacci 61.8% retracement entries (pond form).
THE GREAT RETEST (v10). Simulation only. One clean shot, frozen spec.

INTEGRITY: taken as established from W6 (preserved in w6_results.json in
this folder): the original v7 engine reproduced its published finals to
the cent (CONT $220.73, VAL $175.44) and W6's native-cadence area runs
were LONG $440.04 / DECADE $219.56 / CONT $220.73 / VAL $175.44, verdict
NO GROUND. This script does NOT re-run the integrity gate; its daily
DECADE cell uses the same plumbing W6 used for the area runs (long-run
pond bars, backtests/v7/long-hold/data/pxfull_*.json, champion
adjclose construction) and is checked against W6's DECADE $219.56 in
the report.

STRATEGY (v7 Spec F-1, frozen, verbatim mechanics):
  - Universe: the champion's honest top-30 pond. GOOGL has no pxfull
    long bar file; GOOG (same issuer, class C) is substituted, as in
    the long-run pond construction. All other names as published.
  - ZigZag on daily closes, 10% reversal threshold; a swing is usable
    only once confirmed by a subsequent 10% reversal. Live setup = most
    recent completed up-swing L->H; qualifies only if H >= 1.20 x L.
    R = H - 0.618 x (H - L). Signal: close <= R while close > L; each
    completed swing fires at most once. Buy at next open, committing
    1/5 of the pot's signal-day close value; max 5 concurrent, one per
    name; same-day takes in alphabetical order.
  - Exit (first of): close >= H; close < L; 252 trading days held (in
    the entered ticker's own bars). Exit at next open.
  - Costs: 0.10%/side + $0.01 per sell order (the original engine's).

CADENCE (SPEC uniform definition): signal detection AND exit
evaluation happen ONLY on cadence dates (first trading day of the
week / second week / month / quarter / half-year / year; daily = every
trading day). ZigZag state is daily price knowledge, point-in-time as
of the evaluation close. Executions still occur at the next trading
day's open after an evaluation, exactly as the original engine does.

PROTECTION (v9, adopted): plain -15% floor from the episode's starting
balance, checked at every close (protection overlay, not a strategy
signal). First halt: liquidate at next open, sit in cash 90 calendar
days, restart at the next cadence (decision) date on/after eligibility
under an episode-2 floor of -15% from the restart balance. Second halt
ends the run. End of window: liquidate at final close.

PLACEBOS (v7 reading R8, the original chassis design): per cell, 20
seeds; each twin takes one entry attempt on every day the ranked pot
actually entered (keyed by execution date, generated the day before,
mirroring ranked mechanics), buying a random pond name not held in the
twin, sized at 1/5 of the twin's own prior-day close value, exits
referenced to that name's own most recent completed up-swing as of the
prior close (no 1.20 qualification — that is part of the ranked
signal). Identical exit rules, cadence gating, costs and v9 floor.

Window: DECADE 2016-11-21 -> 2026-11-20, $100/cell.
Outputs: cells/<cadence>.json (full equity curve, halts with dates,
all 20 placebo twin finals), _sweep_summary.json; results.json and
RESULTS.md are assembled from the saved cells.
"""
import bisect
import json
import os
import random
import time
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
LH_DATA = os.path.expanduser(
    "~/workspace/stock-app/backtests/v7/long-hold/data")

START_CASH = 100.0
COST_RATE = 0.001
SELL_FEE = 0.01
DEC_START, DEC_END = "2016-11-21", "2026-11-20"
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]
ZZ_THR = 0.10
RETR = 0.618
MIN_SWING = 1.20
MAX_POS = 5
MAX_HOLD_BARS = 252

UNIVERSE = ["AAPL", "MSFT", "AMZN", "GOOG", "META", "BRK-B", "JPM", "XOM",
            "JNJ", "PG", "V", "WMT", "HD", "BAC", "CVX", "PFE", "VZ", "T",
            "DIS", "NFLX", "INTC", "CSCO", "GE", "IBM", "MMM", "UNH", "MA",
            "KO", "PEP", "WFC"]


# ------------------------------------------------------------------ data
def load_bars(ticker):
    """Champion construction from the read-only pxfull cache:
    open scaled by adjclose/close, close = adjclose. One file at a
    time; the payload is discarded after extraction (RAM discipline)."""
    with open(os.path.join(LH_DATA, f"pxfull_{ticker}.json"), "rb") as f:
        j = json.loads(f.read())
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, c = q["open"][i], q["close"][i]
        if c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        bars.append({"d": d, "o": (o * ratio if o else a), "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars


def zigzag_pivots(closes, thr=ZZ_THR):
    """Standard percentage ZigZag on closes (v7 engine, verbatim).
    Returns [(bar_idx, price, 'H'|'L', confirm_bar_idx), ...]."""
    pivots = []
    if len(closes) < 2:
        return pivots
    state = "none"
    hi_i = lo_i = 0
    hi = lo = closes[0]
    cand_i, cand = 0, closes[0]
    for i in range(1, len(closes)):
        c = closes[i]
        if state == "none":
            if c > hi:
                hi, hi_i = c, i
            if c < lo:
                lo, lo_i = c, i
            up_trig = c >= lo * (1 + thr) and lo_i < i
            dn_trig = c <= hi * (1 - thr) and hi_i < i
            if up_trig and (not dn_trig or lo_i <= hi_i):
                pivots.append((lo_i, lo, "L", i))
                state = "up"
                cand_i, cand = hi_i, hi
            elif dn_trig:
                pivots.append((hi_i, hi, "H", i))
                state = "down"
                cand_i, cand = lo_i, lo
        elif state == "up":
            if c > cand:
                cand, cand_i = c, i
            elif c <= cand * (1 - thr):
                pivots.append((cand_i, cand, "H", i))
                state = "down"
                cand_i, cand = i, c
        else:  # down
            if c < cand:
                cand, cand_i = c, i
            elif c >= cand * (1 + thr):
                pivots.append((cand_i, cand, "L", i))
                state = "up"
                cand_i, cand = i, c
    return pivots


def build_ticker_data():
    tdata = {}
    for t in UNIVERSE:
        bars = load_bars(t)
        closes = [b["c"] for b in bars]
        pivots = zigzag_pivots(closes)
        swings = []
        for a, b in zip(pivots, pivots[1:]):
            if a[2] == "L" and b[2] == "H":
                L, H = a[1], b[1]
                swings.append({
                    "id": len(swings), "L": L, "H": H,
                    "confirm_date": bars[b[3]]["d"],
                    "qualifies": H >= MIN_SWING * L,
                    "R": H - RETR * (H - L),
                })
        dates = [b["d"] for b in bars]
        tdata[t] = {
            "bars": bars, "dates": dates,
            "idx": {b["d"]: i for i, b in enumerate(bars)},
            "bar": {b["d"]: b for b in bars},
            "swings": swings,
            "confirms": [s["confirm_date"] for s in swings],
        }
    return tdata


def last_swing_asof(td, d):
    i = bisect.bisect_right(td["confirms"], d) - 1
    if i < 0:
        return None
    return td["swings"][i]


def close_on_or_before(td, d):
    i = bisect.bisect_right(td["dates"], d) - 1
    return td["bars"][i]["c"] if i >= 0 else None


def buy_hold_spy(spy_bars):
    idx = [b for b in spy_bars if DEC_START <= b["d"] <= DEC_END]
    first, last = idx[0], idx[-1]
    shares = START_CASH / (first["o"] * (1.0 + COST_RATE))
    val = shares * last["c"]
    final = val - (val * COST_RATE + SELL_FEE)
    peak, maxdd = -1.0, 0.0
    for b in idx:
        v = shares * b["c"]
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 2)}


# ------------------------------------------------------------- cadence set
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


# ------------------------------------------------------------------ engine
def run_pot(tdata, days, eval_set, mode="ranked", entry_day_counts=None,
            rng=None):
    """One $100 pot over the DECADE window. mode='ranked' runs the
    frozen F-1 rule; mode='placebo' keys entries to the ranked run's
    entry execution days (v7 reading R8). v9 episodic protection."""
    cash = START_CASH
    floor = 0.85 * START_CASH
    episode = 1
    positions = {}
    trades = []
    total_costs = 0.0
    curve = []
    halts = []
    restart = False
    second_halt = False
    pending_entries = []
    pending_exits = []
    consumed = set()
    entry_events = {}
    days_in = 0
    state = "active"          # active | liquidating | sitout | ended
    halt_signal_date = None
    restart_date = None
    day_set = set(days)

    def portfolio_close(d):
        v = cash
        for t, p in positions.items():
            c = close_on_or_before(tdata[t], d)
            if c:
                v += p["shares"] * c
        return v

    def do_buy(d, t, commit, H, L, swing_id, signal_date):
        nonlocal cash, total_costs
        bar = tdata[t]["bar"].get(d)
        if not bar:
            return False
        o = bar["o"]
        buy_val = min(commit, cash / 1.001)
        if buy_val <= 0.005:
            return False
        sh = buy_val / o
        c = buy_val * COST_RATE
        cash -= buy_val + c
        total_costs += c
        positions[t] = {"shares": sh, "entry_date": d,
                        "entry_idx": tdata[t]["idx"][d],
                        "H": H, "L": L, "swing_id": swing_id,
                        "signal_date": signal_date, "commit": buy_val}
        trades.append((d, t, "BUY", round(sh, 6), round(o, 4),
                       round(buy_val, 2), round(c, 2)))
        return True

    def do_sell(d, t, tag, price=None):
        nonlocal cash, total_costs
        p = positions.get(t)
        if p is None:
            return
        if price is None:
            bar = tdata[t]["bar"].get(d)
            if not bar:
                return
            price = bar["o"]
        val = p["shares"] * price
        c = val * COST_RATE + SELL_FEE
        cash += val - c
        total_costs += c
        trades.append((d, t, tag, round(p["shares"], 6), round(price, 4),
                       round(val, 2), round(c, 2)))
        del positions[t]

    for di, d in enumerate(days):
        last_day = di == len(days) - 1

        if state == "liquidating":
            # halt liquidation at today's open
            for t in list(positions):
                if tdata[t]["bar"].get(d):
                    do_sell(d, t, "SELL-HALT")
            positions = {}
            pending_entries = []
            pending_exits = []
            halts.append({"episode": episode, "signal_date": halt_signal_date,
                          "liquidation_date": d,
                          "proceeds": round(cash, 2),
                          "floor_in_effect": round(floor, 2)})
            if episode == 2:
                second_halt = True
                state = "ended"
            else:
                elig = (date.fromisoformat(d) + timedelta(days=90)).isoformat()
                rest = [x for x in days if x >= elig and x in eval_set]
                if rest:
                    restart_date = rest[0]
                    state = "sitout"
                else:
                    state = "ended"
            curve.append([d, round(cash, 2)])
            continue

        if state == "sitout":
            if d < restart_date:
                curve.append([d, round(cash, 2)])
                continue
            # restart today: episode 2 begins at this decision point
            episode = 2
            restart = True
            floor = 0.85 * cash
            state = "active"
        if state == "ended":
            curve.append([d, round(cash, 2)])
            continue

        # ---- execute pending exits at today's open (before entries)
        still = []
        for t in pending_exits:
            if t in positions and tdata[t]["bar"].get(d):
                do_sell(d, t, "SELL")
            elif t in positions:
                still.append(t)
        pending_exits = still
        # ---- execute pending entries at today's open
        still = []
        for pe in pending_entries:
            t = pe["t"]
            if t in positions:
                continue
            if tdata[t]["bar"].get(d):
                if do_buy(d, t, pe["commit"], pe["H"], pe["L"],
                          pe["swing_id"], pe["signal_date"]):
                    entry_events[d] = entry_events.get(d, 0) + 1
            else:
                still.append(pe)
        pending_entries = still

        if positions:
            days_in += 1

        is_eval = d in eval_set
        if not last_day and is_eval:
            # ---- exit evaluation on today's close
            for t, p in list(positions.items()):
                bar = tdata[t]["bar"].get(d)
                if not bar:
                    continue
                c = bar["c"]
                held = tdata[t]["idx"][d] - p["entry_idx"]
                if c >= p["H"] or c < p["L"] or held >= MAX_HOLD_BARS:
                    if t not in pending_exits:
                        pending_exits.append(t)
            # ---- entry signals
            if mode == "ranked":
                pv = portfolio_close(d)
                for t in sorted(UNIVERSE):
                    bar = tdata[t]["bar"].get(d)
                    if not bar:
                        continue
                    sw = last_swing_asof(tdata[t], d)
                    if sw is None or not sw["qualifies"]:
                        continue
                    key = (t, sw["id"])
                    if key in consumed:
                        continue
                    c = bar["c"]
                    if c <= sw["R"] and c > sw["L"]:
                        consumed.add(key)
                        taken = (t not in positions
                                 and all(pe["t"] != t for pe in pending_entries)
                                 and t not in pending_exits
                                 and len(positions) + len(pending_entries)
                                 < MAX_POS)
                        if taken:
                            pending_entries.append(
                                {"t": t, "commit": pv / MAX_POS,
                                 "H": sw["H"], "L": sw["L"],
                                 "swing_id": sw["id"], "signal_date": d})
            else:  # placebo: attempts for tomorrow's ranked executions
                n_attempts = 0
                if di + 1 < len(days):
                    n_attempts = (entry_day_counts or {}).get(days[di + 1], 0)
                if n_attempts:
                    prev_close = curve[-1][1] if curve else START_CASH
                    for _ in range(n_attempts):
                        if len(positions) + len(pending_entries) >= MAX_POS:
                            break
                        cands = []
                        for t in sorted(UNIVERSE):
                            if t in positions or t in pending_exits:
                                continue
                            if any(pe["t"] == t for pe in pending_entries):
                                continue
                            if not tdata[t]["bar"].get(days[di + 1]):
                                continue
                            sw = last_swing_asof(tdata[t], d)
                            if sw is None:
                                continue
                            cands.append((t, sw))
                        if not cands:
                            break
                        t, sw = rng.choice(cands)
                        pending_entries.append(
                            {"t": t, "commit": prev_close / MAX_POS,
                             "H": sw["H"], "L": sw["L"],
                             "swing_id": sw["id"], "signal_date": d})

        # ---- floor check on the close (protection overlay, daily)
        v = portfolio_close(d)
        curve.append([d, round(v, 2)])
        if v <= floor and not last_day:
            halt_signal_date = d
            state = "liquidating"

    # ---- end of window: liquidate at final close
    last = days[-1]
    if positions:
        for t in list(positions):
            c_ = close_on_or_before(tdata[t], last)
            if c_:
                do_sell(last, t, "SELL-END", price=c_)
        curve[-1] = [last, round(cash, 2)]
    final = cash
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    yrs = (date.fromisoformat(DEC_END)
           - date.fromisoformat(DEC_START)).days / 365.25
    return {
        "final": round(final, 2),
        "cagr_pct": round(((final / START_CASH) ** (1.0 / yrs) - 1.0) * 100, 2),
        "max_dd_pct": round(maxdd * 100, 2),
        "halts": halts, "restart": restart, "second_halt": second_halt,
        "costs": round(total_costs, 2), "orders": len(trades),
        "time_in_market_pct": round(100.0 * days_in / len(days), 1),
        "trades": trades, "entry_events": entry_events,
    }, curve


def main():
    spy_bars = load_bars("SPY")
    spy = buy_hold_spy(spy_bars)
    print(f"SPY DECADE buy-hold: ${spy['final']} maxDD {spy['max_dd_pct']}%",
          flush=True)
    days = [b["d"] for b in spy_bars if DEC_START <= b["d"] <= DEC_END]
    del spy_bars
    tdata = build_ticker_data()
    print(f"tickers loaded: {len(tdata)}; window days: {len(days)}", flush=True)

    os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)
    cells = {}
    for cad in CADENCES:
        eval_set = cadence_dates(days, cad)
        rec, curve = run_pot(tdata, days, eval_set, mode="ranked")
        twins = []
        for seed in range(1, 21):
            rng = random.Random(seed)
            trec, _ = run_pot(tdata, days, eval_set, mode="placebo",
                              entry_day_counts=rec["entry_events"], rng=rng)
            twins.append({"seed": seed, "final": trec["final"]})
        beaten = sum(1 for t in twins if rec["final"] > t["final"])
        rec_out = {k: rec[k] for k in
                   ("final", "cagr_pct", "max_dd_pct", "halts", "restart",
                    "second_halt", "costs", "orders", "time_in_market_pct")}
        rec_out["placebo_beaten"] = beaten
        rec_out["placebo_note"] = (
            "20-seed random-entry twins (v7 reading R8): one entry attempt "
            "on every day the ranked pot entered at this cadence, random "
            "pond name, exits referenced to that name's own most recent "
            "completed up-swing, identical cadence gating, costs and v9 "
            "protection.")
        rec_out["n_eval_dates"] = len(eval_set)
        cell_doc = {"slug": "folklore-f1-fibonacci", "cadence": cad,
                    "window": [DEC_START, DEC_END], "start_cash": START_CASH,
                    **rec_out, "placebo_twins": twins,
                    "equity_curve": curve}
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump(cell_doc, f, indent=1)
        cells[cad] = rec_out
        print(f"{cad.upper():11s} final ${rec_out['final']} "
              f"CAGR {rec_out['cagr_pct']}% maxDD {rec_out['max_dd_pct']}% "
              f"costs ${rec_out['costs']} orders {rec_out['orders']} "
              f"TIM {rec_out['time_in_market_pct']}% "
              f"placebo beaten {beaten}/20 halts {len(rec_out['halts'])}",
              flush=True)

    with open(os.path.join(HERE, "_sweep_summary.json"), "w") as f:
        json.dump({"spy": spy, "cells": cells}, f, indent=1)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
