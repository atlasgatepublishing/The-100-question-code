#!/usr/bin/env python3
"""
W6b CADENCE SWEEP — F-4 Dow Theory confirmation (DIA/IYT joint 52-week
extreme confirmation within 20 sessions -> hold SPY, else cash).
THE GREAT RETEST (v10). Simulation only. One clean shot, frozen spec.

WHAT THIS SCRIPT DOES
  1. INTEGRITY (original form, his rules): re-runs the original v7 F-4
     engine logic (copied verbatim below: confirmation core + run_pot)
     on the original data (backtests/v7/folklore-f4-dowtheory/data,
     Yahoo 2015->2026) and original windows, checking the published
     finals CONT $178.06 / VAL $164.31. W6 already established this
     integrity to the cent in v10; this re-check is the sweep script's
     own gate and is recorded in results.json.
  2. DECADE CADENCE MATRIX: 2016-11-21 -> 2026-11-20, $100/cell.
     Data: SPY from the read-only shared cache
     backtests/v7/long-hold/data/pxfull_SPY.json; DIA/IYT from this
     folder's extended payloads data/pxfull_DIA.json / pxfull_IYT.json
     (W6's pulls, Yahoo 2008->2026). Only the three index series are
     loaded (shared-RAM discipline). Champion construction throughout:
     close = adjclose, open scaled by adjclose/close; DIA/IYT closes
     forward-filled onto the SPY master calendar.
     Confirmation flags/events are computed on the FULL history
     (252-session lookback fully warmed before the window), exactly as
     the original engine computes them. Per the SPEC's uniform cadence
     definition for TIMERS, cadence = signal-evaluation frequency: the
     strategy's desired state (the position implied by all in-window
     confirmation events so far; the pot starts flat at the window open
     regardless of pre-window confirmations, as in the original spec)
     is only READ on cadence dates — daily = every trading day; weekly
     = first trading day of each week; biweekly = first trading day of
     every second week; monthly / quarterly / semi-annual / annual =
     first trading day of the month / quarter / half-year / year. A
     switch decided at a cadence date's close executes at the next
     trading day's open, exactly as the original engine executes.
     The v9 -15% floor is a protection overlay, not a strategy signal:
     checked at every close; on breach, liquidate at the next open,
     sit in cash 90 calendar days, restart ONCE at the strategy's next
     regular decision point (the first cadence date on/after
     eligibility) under an episode-2 floor of -15% from the restart
     balance; a second halt ends the run.
  3. PLACEBOS (20 seeds/cell): the original F-4 chassis' own design —
     spell-matched random placement. Each twin takes the cell's own
     invested spells (same count, same lengths, same total invested
     days), re-places them at random over the window (internal cash
     gaps >= 1 session so spells stay separate), and runs through the
     identical cadence machinery and v9 protection. Only the PLACEMENT
     is randomized. Seeds 1..20.

Costs: 0.10%/side + $0.01 per sell order (the original engine's own).
End of window: any open position is liquidated at the final close
(sell cost charged), as the original engine does. Cash earns 0%.

Outputs (this folder): cells/<cadence>.json (full equity curve, halts
with dates, all 20 placebo twin finals), _sweep_summary.json;
results.json (SPEC sweep format) and RESULTS.md are assembled from
these saved files.
"""
import json
import os
import random
import time
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
V7_DIR = os.path.expanduser("~/workspace/stock-app/backtests/v7/folklore-f4-dowtheory")
SPY_LONG = os.path.expanduser(
    "~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")

START_CASH = 100.0
COST_RATE = 0.001           # 0.10% per side (original engine)
SELL_FEE = 0.01              # $0.01 per sell order (original engine)
LOOKBACK = 252               # 52 weeks of sessions (original spec)
PAIR_WINDOW = 20             # rolling sessions for the pair (original)
DEC_START, DEC_END = "2016-11-21", "2026-11-20"
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]


# ------------------------------------------------------------------ data
def load_payload_series(path):
    """date -> (adj_open, adj_close) from a Yahoo chart payload.
    The raw payload is freed immediately (three series only, RAM)."""
    with open(path, "rb") as f:
        data = json.loads(f.read())
    res = data["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = None
    if "adjclose" in res["indicators"]:
        adj = res["indicators"]["adjclose"][0]["adjclose"]
    out = {}
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        c = q["close"][i]
        o = q["open"][i]
        if c is None or o is None:
            continue
        if adj is not None and adj[i]:
            ratio = adj[i] / c
            out[d] = (o * ratio, adj[i])
        else:
            out[d] = (o, c)
    del data
    return out


def build_universe(spy_path, dia_path, iyt_path):
    """Returns (cal, opens, closes) with closes/opens as per-ticker
    lists aligned to the SPY master calendar (forward-filled closes;
    open falls back to the last close, the original house convention)."""
    series = {}
    for t, p in (("SPY", spy_path), ("DIA", dia_path), ("IYT", iyt_path)):
        series[t] = load_payload_series(p)
    cal = sorted(series["SPY"].keys())
    closes, opens = {}, {}
    for t in ("SPY", "DIA", "IYT"):
        s = series[t]
        cl, op, last = [], [], None
        for d in cal:
            if d in s:
                last = s[d][1]
                op.append(s[d][0])
            else:
                op.append(last)
            cl.append(last)
        closes[t], opens[t] = cl, op
    del series
    return cal, opens, closes


# ------------------------------------------------------- confirmation core
# (verbatim logic from the original v7 engine)
def extreme_flags(closes):
    n = len(closes)
    hi = [False] * n
    lo = [False] * n
    for i in range(LOOKBACK, n):
        window = closes[i - LOOKBACK:i]
        if closes[i] > max(window):
            hi[i] = True
        if closes[i] < min(window):
            lo[i] = True
    return hi, lo


def confirmation_events(cal, closes):
    """EVENTS[i] in {None,'bullish','bearish'} over the full calendar —
    the session the DIA/IYT pair completes (original logic verbatim)."""
    flags = {t: extreme_flags(closes[t]) for t in ("DIA", "IYT")}
    events = [None] * len(cal)
    collisions = []
    last_hi = {"DIA": None, "IYT": None}
    last_lo = {"DIA": None, "IYT": None}
    for i in range(len(cal)):
        bull = bear = False
        for t in ("DIA", "IYT"):
            if flags[t][0][i]:
                last_hi[t] = i
            if flags[t][1][i]:
                last_lo[t] = i
        lh = list(last_hi.values())
        ll = list(last_lo.values())
        if (flags["DIA"][0][i] or flags["IYT"][0][i]) and None not in lh \
                and max(lh) - min(lh) <= PAIR_WINDOW - 1:
            bull = True
        if (flags["DIA"][1][i] or flags["IYT"][1][i]) and None not in ll \
                and max(ll) - min(ll) <= PAIR_WINDOW - 1:
            bear = True
        if bull and bear:
            collisions.append(cal[i])
            events[i] = "bearish"        # risk-off precedence (original)
        elif bull:
            events[i] = "bullish"
        elif bear:
            events[i] = "bearish"
    return events, collisions


# ------------------------------------------- original engine (integrity)
def run_pot_original(cal, cal_idx, opens, closes, start, end,
                     desired_by_day, floor_on=True):
    """The original v7 run_pot, logic verbatim (his-rules floor: a
    breach liquidates at the next open and ENDS the run — no restart).
    desired_by_day: dict cal-index -> desired state decided at close."""
    days = [d for d in cal if start <= d <= end]
    cash = START_CASH
    shares = 0.0
    holding = False
    total_costs = 0.0
    n_orders = 0
    curve = []
    halted = None
    pending = None

    def buy_all(d):
        nonlocal cash, shares, holding, total_costs, n_orders
        o = opens["SPY"][cal_idx[d]]
        sh = (cash / (1.0 + COST_RATE)) / o
        c = cash - sh * o
        total_costs += c
        n_orders += 1
        cash = 0.0
        shares = sh
        holding = True

    def sell_all(d, at_open=True):
        nonlocal cash, shares, holding, total_costs, n_orders
        px = opens["SPY"][cal_idx[d]] if at_open else closes["SPY"][cal_idx[d]]
        val = shares * px
        c = val * COST_RATE + SELL_FEE
        total_costs += c
        n_orders += 1
        cash = val - c
        shares = 0.0
        holding = False
        return cash

    final = None
    for di, d in enumerate(days):
        if pending is not None:
            if pending and not holding:
                buy_all(d)
            elif not pending and holding:
                sell_all(d)
            pending = None
        v = cash + (shares * closes["SPY"][cal_idx[d]] if holding else 0.0)
        curve.append((d, v))
        if floor_on and v <= 85.0 and di < len(days) - 1:
            halted = d
            if holding:
                final = sell_all(days[di + 1], at_open=True)
            else:
                final = cash
            break
        want = desired_by_day.get(cal_idx[d])
        if want is not None and want != holding:
            pending = want
    if final is None:
        if holding:
            final = sell_all(days[-1], at_open=False)
        else:
            final = cash
    return {"final": round(final, 2), "halted": halted,
            "costs": round(total_costs, 2), "orders": n_orders}


def strategy_desired_original(cal, cal_idx, events, start, end):
    """Original strategy_desired: in-window events only, start flat."""
    desired = {}
    state = False
    for d in cal:
        if d < start or d > end:
            continue
        ev = events[cal_idx[d]]
        if ev is not None:
            new_state = (ev == "bullish")
            if new_state != state:
                state = new_state
                desired[cal_idx[d]] = state
    return desired


# ------------------------------------------------------- cadence engine
def cadence_dates(days, cadence):
    """Evaluation dates: first trading day of each cadence period."""
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
        else:  # annual
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


def run_episode(cal_idx, opens, closes, idx, eval_set, desired,
                start_cash, floor):
    """One v9 episode over bar indices idx. desired[i] = desired state
    decided at bar i's close, read ONLY on cadence dates; switches
    execute at the next open. Floor checked at every close (<= floor);
    on breach the position liquidates at the next open (or at the
    final close if the breach is on the last bar) and the episode ends.
    Returns running cash/shares WITHOUT end-of-window liquidation."""
    cash, shares = start_cash, 0.0
    halted = liq_date = None
    costs, orders, days_in = 0.0, 0, 0
    curve, states = [], []
    pending = pending_kind = None
    for pos, i in enumerate(idx):
        d = opens["__cal__"][i]
        if pending == "buy" and shares == 0.0 and halted is None:
            px = opens["SPY"][i]
            shares = cash / (px * (1.0 + COST_RATE))
            costs += shares * px * COST_RATE
            orders += 1
            cash = 0.0
        elif pending == "sell" and shares > 0.0:
            px = opens["SPY"][i]
            val = shares * px
            scost = val * COST_RATE + SELL_FEE
            costs += scost
            orders += 1
            cash, shares = val - scost, 0.0
            if pending_kind == "floor":
                liq_date = d
        pending = pending_kind = None
        equity = cash + shares * closes["SPY"][i]
        curve.append([d, round(equity, 2)])
        states.append(shares > 0.0)
        if shares > 0.0:
            days_in += 1
        if pos == len(idx) - 1:
            break
        if halted is None and equity <= floor:
            halted = d
            if shares > 0.0:
                pending, pending_kind = "sell", "floor"
            else:
                liq_date = d
            continue
        if halted is not None:
            continue
        if d not in eval_set:
            continue
        want = desired[i]
        if want and shares == 0.0:
            pending, pending_kind = "buy", "signal"
        elif not want and shares > 0.0:
            pending, pending_kind = "sell", "signal"
    if halted is not None and shares > 0.0:
        # breach on the final bar: liquidate at that close
        i = idx[-1]
        val = shares * closes["SPY"][i]
        scost = val * COST_RATE + SELL_FEE
        costs += scost
        orders += 1
        cash, shares = val - scost, 0.0
        liq_date = opens["__cal__"][i]
        curve[-1] = [opens["__cal__"][i], round(cash, 2)]
        states[-1] = False
    return {"cash": cash, "shares": shares, "halted": halted,
            "liq_date": liq_date, "costs": costs, "orders": orders,
            "curve": curve, "states": states, "days_in": days_in}


def run_cell(cal, cal_idx, opens, closes, cadence, desired):
    """Full v9 run over the DECADE window at one cadence. desired is a
    per-bar boolean list (strategy's or a placebo twin's)."""
    idx_all = [i for i, d in enumerate(cal) if DEC_START <= d <= DEC_END]
    days = [cal[i] for i in idx_all]
    eval_set = cadence_dates(days, cadence)
    opens["__cal__"] = cal

    halts = []
    restart = False
    second_halt = False
    total_costs = 0.0
    total_orders = 0
    total_days_in = 0
    curve = []
    states = []
    start, start_cash, floor = DEC_START, START_CASH, 0.85 * START_CASH
    final = None
    for episode in (1, 2):
        idx = [i for i in idx_all if cal[i] >= start]
        ep = run_episode(cal_idx, opens, closes, idx, eval_set, desired,
                         start_cash, floor)
        total_costs += ep["costs"]
        total_orders += ep["orders"]
        total_days_in += ep["days_in"]
        if episode == 1:
            curve, states = ep["curve"], ep["states"]
        else:
            pre = [c for c in curve if c[0] < ep["curve"][0][0]]
            pre_s = states[:len(pre)]
            gap_days = [d for d in days if curve[-1][0] < d < ep["curve"][0][0]]
            gap = [[d, round(start_cash, 2)] for d in gap_days]
            curve = pre + gap + ep["curve"]
            states = pre_s + [False] * len(gap_days) + ep["states"]
        if ep["halted"] is None:
            if ep["shares"] > 0.0:
                i = idx[-1]
                val = ep["shares"] * closes["SPY"][i]
                scost = val * COST_RATE + SELL_FEE
                total_costs += scost
                total_orders += 1
                final = val - scost
                curve[-1] = [cal[i], round(final, 2)]
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
        start = rest[0]
        start_cash = ep["cash"]
        floor = 0.85 * start_cash
    # if the run ended on a halt, extend the curve flat to the window end
    if len(curve) < len(days):
        have = {c[0] for c in curve}
        tail = [[d, round(final, 2)] for d in days if d not in have]
        curve = sorted(curve + tail, key=lambda c: c[0])
        states = states + [False] * (len(days) - len(states))
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    yrs = (date.fromisoformat(DEC_END) - date.fromisoformat(DEC_START)).days / 365.25
    rec = {
        "final": round(final, 2),
        "cagr_pct": round(((final / START_CASH) ** (1.0 / yrs) - 1.0) * 100, 2),
        "max_dd_pct": round(maxdd * 100, 2),
        "halts": halts, "restart": restart, "second_halt": second_halt,
        "costs": round(total_costs, 2), "orders": total_orders,
        "time_in_market_pct": round(100.0 * total_days_in / len(days), 1),
        "n_eval_dates": len(eval_set),
    }
    return rec, curve, states


def buy_hold(cal, opens, closes):
    idx = [i for i, d in enumerate(cal) if DEC_START <= d <= DEC_END]
    first, last = idx[0], idx[-1]
    shares = START_CASH / (opens["SPY"][first] * (1.0 + COST_RATE))
    val = shares * closes["SPY"][last]
    final = val - (val * COST_RATE + SELL_FEE)
    peak, maxdd = -1.0, 0.0
    for i in idx:
        v = shares * closes["SPY"][i]
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 2)}


# ---------------------------------------------------------------- placebos
def spells_of(state_series):
    spells, run = [], 0
    for s in state_series:
        if s:
            run += 1
        elif run:
            spells.append(run)
            run = 0
    if run:
        spells.append(run)
    return spells


def placebo_desired_series(cal, idx_all, state_series, seed):
    """The original F-4 placebo design: the strategy's own invested
    spells re-placed at random over the window (cash gaps re-drawn,
    internal gaps >= 1 session). Returns a per-bar desired list: the
    placed state for window day k is the state decided at that day's
    close (the same sampling convention the cadence engine applies to
    the strategy's own desired series)."""
    days = [cal[i] for i in idx_all]
    n = len(days)
    spells = spells_of(state_series)
    desired = [False] * len(cal)
    if not spells:
        return desired
    invested = sum(spells)
    cash_days = n - invested
    rng = random.Random(seed)
    n_gaps = len(spells) + 1
    internal = len(spells) - 1
    free = cash_days - internal
    gaps = [0] * n_gaps
    for g in range(1, n_gaps - 1):
        gaps[g] = 1
    for _ in range(free):
        gaps[rng.randrange(n_gaps)] += 1
    path = []
    for gi, g in enumerate(gaps):
        path.extend([False] * g)
        if gi < len(spells):
            path.extend([True] * spells[gi])
    assert len(path) == n
    for k, i in enumerate(idx_all):
        desired[i] = path[k]
    return desired


# --------------------------------------------------------------------- main
def main():
    # ---- integrity: original engine, original data, original windows
    cal7, opens7, closes7 = build_universe(
        os.path.join(V7_DIR, "data", "SPY.json"),
        os.path.join(V7_DIR, "data", "DIA.json"),
        os.path.join(V7_DIR, "data", "IYT.json"))
    idx7 = {d: i for i, d in enumerate(cal7)}
    ev7, _ = confirmation_events(cal7, closes7)
    integ = {}
    for name, (ws, we), pub in (("CONT", ("2019-01-01", "2026-11-20"), 178.06),
                                ("VAL", ("2023-01-01", "2026-11-20"), 164.31)):
        des = strategy_desired_original(cal7, idx7, ev7, ws, we)
        r = run_pot_original(cal7, idx7, opens7, closes7, ws, we, des,
                             floor_on=True)
        integ[name] = {"window": [ws, we], "published_final": pub,
                       "reproduced_final": r["final"],
                       "match": abs(r["final"] - pub) < 0.005,
                       "halted": r["halted"]}
        print(f"INTEGRITY {name}: published ${pub} reproduced "
              f"${r['final']} match={integ[name]['match']} "
              f"halted={r['halted']}", flush=True)
    del cal7, opens7, closes7, ev7
    assert all(v["match"] for v in integ.values()), "integrity FAILED"

    # ---- decade bars (three index series only) + SPY control
    cal, opens, closes = build_universe(
        SPY_LONG,
        os.path.join(HERE, "data", "pxfull_DIA.json"),
        os.path.join(HERE, "data", "pxfull_IYT.json"))
    cal_idx = {d: i for i, d in enumerate(cal)}
    events, collisions = confirmation_events(cal, closes)
    spy = buy_hold(cal, opens, closes)
    print(f"SPY DECADE buy-hold: ${spy['final']} maxDD {spy['max_dd_pct']}% "
          f"(collisions: {collisions})", flush=True)

    # strategy desired-state series over the decade: start flat at the
    # window open; state = position implied by in-window events so far
    desired = [False] * len(cal)
    state = False
    idx_all = [i for i, d in enumerate(cal) if DEC_START <= d <= DEC_END]
    for i in idx_all:
        if events[i] is not None:
            state = (events[i] == "bullish")
        desired[i] = state

    os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)
    cells = {}
    for cad in CADENCES:
        rec, curve, states = run_cell(cal, cal_idx, opens, closes, cad,
                                      desired)
        twins = []
        for seed in range(1, 21):
            twin_desired = placebo_desired_series(cal, idx_all, states,
                                                  seed)
            trec, _, _ = run_cell(cal, cal_idx, opens, closes, cad,
                                  twin_desired)
            twins.append({"seed": seed, "final": trec["final"]})
        beaten = sum(1 for t in twins if rec["final"] > t["final"])
        rec["placebo_beaten"] = beaten
        rec["placebo_note"] = (
            "20 spell-matched random-placement twins (the original F-4 "
            "chassis' own placebo design, seeds 1-20): each twin keeps "
            "this cell's own invested spells — same count, lengths and "
            "total invested days — re-placed at random over the window, "
            "and runs through the identical cadence machinery and v9 "
            "protection. Only the placement is randomized.")
        cell_doc = {"slug": "folklore-f4-dowtheory", "cadence": cad,
                    "cadence_key": "daily-signal" if cad == "daily" else cad,
                    "window": [DEC_START, DEC_END],
                    "start_cash": START_CASH, **rec,
                    "drawdown_saving_vs_spy_pts": round(
                        spy["max_dd_pct"] - rec["max_dd_pct"], 2),
                    "spy_final": spy["final"],
                    "spy_max_dd_pct": spy["max_dd_pct"],
                    "placebo_twins": twins,
                    "equity_curve": curve}
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump(cell_doc, f, indent=1)
        cells[cad] = rec
        print(f"{cad.upper():11s} final ${rec['final']} CAGR "
              f"{rec['cagr_pct']}% maxDD {rec['max_dd_pct']}% "
              f"(saving {round(spy['max_dd_pct']-rec['max_dd_pct'],2)} pts) "
              f"costs ${rec['costs']} orders {rec['orders']} "
              f"TIM {rec['time_in_market_pct']}% placebo beaten "
              f"{beaten}/20 halts {len(rec['halts'])}", flush=True)

    with open(os.path.join(HERE, "_sweep_summary.json"), "w") as f:
        json.dump({"integrity": integ,
                   "spy": {"final": spy["final"],
                           "max_dd_pct": spy["max_dd_pct"]},
                   "confirmation_collisions": collisions,
                   "cells": cells}, f, indent=1)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
