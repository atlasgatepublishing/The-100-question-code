#!/usr/bin/env python3
"""
W6b CADENCE SWEEP — F-10 Harmonic Gartley, FROZEN parameterization.
THE GREAT RETEST (v10). Simulation only. One clean shot, no tuning.

WHAT THIS SCRIPT DOES
  1. INTEGRITY (his rules, original form): re-runs the original v7 F-10
     engine logic (copied verbatim below as run_pot_original, with
     zigzag_pivots / extract_triggers / load_bars likewise verbatim) on
     the original windows/data (v4 program caches, pond bars from
     2017-06-01) and checks the published finals: CONT $101.02,
     VAL $100.00. W6 already established integrity to the cent in v10;
     this re-check is the sweep script's own gate and is recorded.
  2. DECADE CADENCE MATRIX: labeled window 2016-11-21 -> 2026-11-20,
     $100/cell, v9 protections. The pond bars the original used begin
     2017-06-01, so the traded road inside the labeled window is
     2017-06-01 -> 2026-11-20 — the same footing as W6's DECADE run,
     whose $103.49 the daily cell here should (and does) reproduce.
     7 cadences: daily, weekly, biweekly, monthly, quarterly,
     semi-annual, annual.

CADENCE TREATMENT (stated, per the SPEC's uniform definition; cadence =
pattern-completion evaluation frequency):
  - The pattern DEFINITION is the frozen parameterization at every
    cadence and is computed on daily closes exactly as frozen: ZigZag
    8% pivots, arming of completed X-A-B-C Gartleys (B 61.8% +/-3pts of
    XA, C 38.2-88.6% of AB), pattern expiry when the next pivot after C
    confirms, and invalidation on any close below X. None of that is
    cadence-gated — it is the definition, not the acting.
  - ACTING is cadence-gated: the D-touch entry check (first close at or
    below the projected D level, the 78.6% retracement of XA) is only
    performed on cadence dates. A D-touch on a non-cadence date does
    not trigger; the pattern stays armed and can still trigger on a
    later cadence date if price is at/below D then (and the pattern
    has not expired or been invalidated in the meantime). A trigger
    executes at the next session's open, as frozen.
  - Position review / exits (38.2%-of-AD target, close below X,
    126-trading-day cap) are evaluated only on cadence dates, per the
    SPEC's rule for event-driven strategies; exit signals execute at
    the next open, as frozen.
  - The v9 -15% floor is a protection overlay, not a strategy signal:
    checked at every close; on a halt everything liquidates at the
    next open, the pot sits in cash 90 calendar days, and restarts at
    the first cadence date on/after eligibility (the strategy's next
    regular decision point) under an episode-2 floor of -15% from the
    restart balance; a second halt ends the run.
  - Cadence dates: first trading day of each week / second week /
    month / calendar quarter / half-year / year inside the window;
    daily = every trading day (the calendar is the union of pond + SPY
    trading days, as in the original engine).

PLACEBOS: n/a, stated with reason in every cell — the frozen
parameterization produced exactly 2 trigger events in the entire data
span (9 armed patterns out of 1,874 ZigZag pivots); a 20-seed twin
distribution over <=2 acted-on events cannot discriminate anything.
The original program's own 20-seed random-entry placebo exists in the
v7 report for the original windows (CONT: ranked final beat 18/20,
median twin $99.00; VAL: no trades, all twins $100.00).

Costs: the engine's own — 0.10%/side + $0.01 per sell order.
End of window: open positions liquidate at the final close (sell cost
charged), as the original engine does.

Outputs (this folder): cells/<cadence>.json (full equity curve, halts
with dates, pattern/trigger counts, trades, placebo note),
_sweep_summary.json (integrity + cell records for results assembly).
"""
import json
import os
import time
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIRS = [
    os.path.expanduser("~/workspace/stock-app/backtests/v4/data"),
    os.path.expanduser("~/workspace/stock-app/backtests/v4/value-momentum-honest-data"),
]

UNIVERSE = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "BRK-B", "JPM", "XOM",
            "JNJ", "PG", "V", "WMT", "HD", "BAC", "CVX", "PFE", "VZ", "T",
            "DIS", "NFLX", "INTC", "CSCO", "GE", "IBM", "MMM", "UNH", "MA",
            "KO", "PEP", "WFC"]

START_CASH = 100.0
FLOOR = 85.0
COST_RATE = 0.001
SELL_FEE = 0.01

ZZ_THRESHOLD = 0.08
B_CENTER, B_BAND = 0.618, 0.03
C_LO, C_HI = 0.382, 0.886
D_FRAC = 0.786
TARGET_FRAC = 0.382
MAX_HOLD_DAYS = 126
MAX_POSITIONS = 5
SLICES = 5

END = "2026-11-20"
DEC_START, DEC_END = "2016-11-21", "2026-11-20"
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]

PLACEBO_NOTE = (
    "n/a — event counts are too low for a meaningful twin distribution: "
    "the frozen parameterization produced exactly 2 trigger events in "
    "the entire data span (9 armed patterns out of 1,874 ZigZag pivots), "
    "and each cadence cell acts on at most those 2. A 20-seed "
    "random-entry twin set built on <=2 events would differ only by coin "
    "flips over a handful of names/dates and could not discriminate the "
    "pattern from chance. The original program's own 20-seed "
    "random-entry placebo lives in the v7 report (CONT: ranked $101.02 "
    "beat 18/20 twins, median $99.00; VAL: no trades, all twins $100.00).")


# ---------------------------------------------------------------- data
# (verbatim from backtests/v7/folklore-f10-gartley/folklore-f10-gartley.py)
def load_bars(ticker):
    blob = None
    for d in CACHE_DIRS:
        p = os.path.join(d, f"px_{ticker}.json")
        if os.path.exists(p) and os.path.getsize(p) > 100:
            with open(p, "rb") as f:
                blob = f.read()
            break
    if blob is None:
        raise SystemExit(f"no cached prices for {ticker}")
    j = json.loads(blob)
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


# ------------------------------------------------------- ZigZag + F-10
# (verbatim from the v7 engine, except extract_triggers gains two
# recording/gating hooks that do not change the frozen definition:
#  - eval_dates: when given, the D-touch trigger check is performed
#    only on those dates (the cadence gate on ACTING; arming, expiry
#    and X-invalidation stay daily, as defined). With eval_dates=None
#    the function is byte-for-byte the original behavior.
#  - armed_records: every armed pattern is recorded with its outcome.)
def zigzag_pivots(bars, threshold=ZZ_THRESHOLD):
    closes = [b["c"] for b in bars]
    pivots = []
    if not closes:
        return pivots
    hi, hi_i = closes[0], 0
    lo, lo_i = closes[0], 0
    mode = None
    ext, ext_i = None, None
    for i in range(1, len(closes)):
        p = closes[i]
        if mode is None:
            if p > hi:
                hi, hi_i = p, i
            if p < lo:
                lo, lo_i = p, i
            if p <= hi * (1 - threshold):
                pivots.append({"kind": "H", "idx": hi_i,
                               "date": bars[hi_i]["d"], "price": hi,
                               "confirm_idx": i, "confirm_date": bars[i]["d"]})
                mode, ext, ext_i = "seek_low", p, i
            elif p >= lo * (1 + threshold):
                pivots.append({"kind": "L", "idx": lo_i,
                               "date": bars[lo_i]["d"], "price": lo,
                               "confirm_idx": i, "confirm_date": bars[i]["d"]})
                mode, ext, ext_i = "seek_high", p, i
        elif mode == "seek_high":
            if p > ext:
                ext, ext_i = p, i
            elif p <= ext * (1 - threshold):
                pivots.append({"kind": "H", "idx": ext_i,
                               "date": bars[ext_i]["d"], "price": ext,
                               "confirm_idx": i, "confirm_date": bars[i]["d"]})
                mode, ext, ext_i = "seek_low", p, i
        else:  # seek_low
            if p < ext:
                ext, ext_i = p, i
            elif p >= ext * (1 + threshold):
                pivots.append({"kind": "L", "idx": ext_i,
                               "date": bars[ext_i]["d"], "price": ext,
                               "confirm_idx": i, "confirm_date": bars[i]["d"]})
                mode, ext, ext_i = "seek_high", p, i
    return pivots


def extract_triggers(ticker, bars, eval_dates=None):
    closes = [b["c"] for b in bars]
    pivots = zigzag_pivots(bars)
    piv_by_confirm = {}
    for pv in pivots:
        piv_by_confirm.setdefault(pv["confirm_idx"], []).append(pv)

    census = {"pivots": len(pivots), "armed": 0, "triggered": 0,
              "expired": 0, "invalid_armed": 0, "invalid_prearm": 0}
    events = []
    armed_records = []
    confirmed = []
    armed = None

    for i, b in enumerate(bars):
        for pv in piv_by_confirm.get(i, []):
            if armed is not None:
                census["expired"] += 1
                armed["outcome"] = "expired"
                armed["outcome_date"] = b["d"]
                armed = None
            confirmed.append(pv)
            if len(confirmed) >= 4:
                x, a, bb, c = confirmed[-4:]
                if (x["kind"], a["kind"], bb["kind"], c["kind"]) == \
                        ("L", "H", "L", "H"):
                    xa = a["price"] - x["price"]
                    if xa > 0:
                        b_ratio = (a["price"] - bb["price"]) / xa
                        ab = a["price"] - bb["price"]
                        c_ratio = (c["price"] - bb["price"]) / ab if ab > 0 else None
                        if (B_CENTER - B_BAND <= b_ratio <= B_CENTER + B_BAND
                                and c_ratio is not None
                                and C_LO <= c_ratio <= C_HI):
                            if any(closes[j] < x["price"]
                                   for j in range(x["idx"], i + 1)):
                                census["invalid_prearm"] += 1
                            else:
                                d_level = a["price"] - D_FRAC * xa
                                armed = {
                                    "ticker": ticker,
                                    "x_date": x["date"], "x": x["price"],
                                    "a_date": a["date"], "a": a["price"],
                                    "b_date": bb["date"], "b": bb["price"],
                                    "c_date": c["date"], "c": c["price"],
                                    "b_ratio": round(b_ratio, 4),
                                    "c_ratio": round(c_ratio, 4),
                                    "d_level": d_level,
                                    "target": d_level + TARGET_FRAC * (a["price"] - d_level),
                                    "arm_date": b["d"],
                                    "outcome": "open", "outcome_date": None,
                                }
                                census["armed"] += 1
                                armed_records.append(armed)
        if armed is not None:
            if b["c"] < armed["x"]:
                census["invalid_armed"] += 1
                armed["outcome"] = "invalid_below_x"
                armed["outcome_date"] = b["d"]
                armed = None
            elif (eval_dates is None or b["d"] in eval_dates) \
                    and b["c"] <= armed["d_level"]:
                ev = dict(armed)
                ev["trigger_date"] = b["d"]
                ev["trigger_close"] = b["c"]
                events.append(ev)
                census["triggered"] += 1
                armed["outcome"] = "triggered"
                armed["outcome_date"] = b["d"]
                armed = None
    return events, census, armed_records


# --------------------------------------- original engine (his rules)
# run_pot copied verbatim from the v7 engine (placebo path removed —
# it was never taken by the ranked run; floor ends the run, his rules).
def run_pot_original(bars_by, idx_by, calendar, events_by_date):
    cash = START_CASH
    positions = {}
    pending_entries = []
    pending_exits = {}
    pending_liquidation = False
    halted = None
    halt_signal_date = None
    trades = []
    orders = 0
    total_costs = 0.0
    curve = []
    skips = []
    days_invested = 0

    def close_on_or_before(t, d):
        bars = bars_by[t]
        j = idx_by[t].get(d)
        if j is None:
            lo, hi = 0, len(bars) - 1
            best = None
            while lo <= hi:
                mid = (lo + hi) // 2
                if bars[mid]["d"] <= d:
                    best = mid
                    lo = mid + 1
                else:
                    hi = mid - 1
            return bars[best]["c"] if best is not None else None
        return bars[j]["c"]

    def pot_value(d):
        v = cash
        for t, pos in positions.items():
            c = close_on_or_before(t, d)
            if c:
                v += pos["shares"] * c
        return v

    def sell_position(t, price, dt, reason):
        nonlocal cash, total_costs, orders
        pos = positions.pop(t)
        val = pos["shares"] * price
        cost = val * COST_RATE + SELL_FEE
        total_costs += cost
        orders += 1
        proceeds = val - cost
        cash += proceeds
        trades.append({
            "ticker": t,
            "entry_date": pos["entry_date"], "entry_price": round(pos["entry_price"], 2),
            "exit_date": dt, "exit_price": round(price, 2),
            "pnl": round(proceeds - pos["cost_basis"], 2),
            "ret_pct": round((proceeds / pos["cost_basis"] - 1.0) * 100, 2),
            "exit_reason": reason,
            "pattern": pos.get("pattern"),
        })

    last_day = calendar[-1] if calendar else None
    for d in calendar:
        if pending_liquidation:
            for t in list(positions):
                j = idx_by[t].get(d)
                if j is not None:
                    sell_position(t, bars_by[t][j]["o"], d, "floor")
            pending_entries = []
            pending_exits = {}
            if not positions:
                pending_liquidation = False
                halted = halt_signal_date
        else:
            for t in list(pending_exits):
                if t in positions:
                    j = idx_by[t].get(d)
                    if j is not None:
                        sell_position(t, bars_by[t][j]["o"], d, pending_exits.pop(t))
            still_pending = []
            for od in pending_entries:
                t = od["ticker"]
                j = idx_by[t].get(d)
                if j is None:
                    still_pending.append(od)
                    continue
                if t in positions:
                    skips.append({"date": od["signal_date"], "ticker": od["signal_ticker"],
                                  "reason": "name_held_at_execution"})
                    continue
                px = bars_by[t][j]["o"]
                buy_val = min(od["slice"], cash / (1.0 + COST_RATE))
                if buy_val <= 0.005:
                    skips.append({"date": od["signal_date"], "ticker": od["signal_ticker"],
                                  "reason": "no_cash"})
                    continue
                cost = buy_val * COST_RATE
                total_costs += cost
                orders += 1
                cash -= buy_val + cost
                positions[t] = {
                    "shares": buy_val / px, "entry_date": d,
                    "entry_price": px, "cost_basis": buy_val + cost,
                    "target": od["target"], "stop": od["stop"],
                    "entry_idx": j, "pattern": od.get("pattern"),
                }
            pending_entries = still_pending

        v = pot_value(d)
        curve.append((d, v))
        if positions:
            days_invested += 1
        if halted is not None:
            break

        is_last = d == last_day
        if not is_last and v <= FLOOR:
            pending_liquidation = True
            halt_signal_date = d
            pending_entries = []
            pending_exits = {}
            continue
        if is_last:
            break

        for t, pos in list(positions.items()):
            j = idx_by[t].get(d)
            if j is None:
                continue
            c = bars_by[t][j]["c"]
            if c < pos["stop"]:
                pending_exits[t] = "invalid_below_x"
            elif c >= pos["target"]:
                pending_exits[t] = "target_38.2"
            elif j - pos["entry_idx"] >= MAX_HOLD_DAYS:
                pending_exits[t] = "time_126d"

        for ev in events_by_date.get(d, []):
            held_names = set(positions) | {od["ticker"] for od in pending_entries}
            if len(held_names) >= MAX_POSITIONS:
                skips.append({"date": d, "ticker": ev["ticker"], "reason": "book_full"})
                continue
            slice_val = v / SLICES
            if ev["ticker"] in held_names:
                skips.append({"date": d, "ticker": ev["ticker"], "reason": "name_held"})
                continue
            pending_entries.append({
                "ticker": ev["ticker"], "signal_ticker": ev["ticker"],
                "signal_date": d, "slice": slice_val,
                "target": ev["target"], "stop": ev["x"],
                "pattern": {"x_date": ev["x_date"], "a_date": ev["a_date"],
                            "b_date": ev["b_date"], "c_date": ev["c_date"],
                            "b_ratio": ev["b_ratio"], "c_ratio": ev["c_ratio"],
                            "d_level": round(ev["d_level"], 2),
                            "arm_date": ev["arm_date"]},
            })

    if positions:
        for t in list(positions):
            c = close_on_or_before(t, last_day)
            sell_position(t, c, last_day, "window_end")
        if curve:
            curve[-1] = (last_day, cash)

    final = cash
    peak, maxdd = -1.0, 0.0
    for d, val in curve:
        if val > peak:
            peak = val
        if peak > 0:
            maxdd = max(maxdd, (peak - val) / peak)
    return {
        "final": round(final, 2), "orders": orders,
        "costs": round(total_costs, 2), "trades_n": len(trades),
        "trades": trades, "halted": halted,
        "max_drawdown_pct": round(maxdd * 100, 2),
        "time_in_market_pct": round(100.0 * days_invested / len(calendar), 1) if calendar else None,
    }


def buy_hold_spy(spy_bars, start, end):
    idx = [i for i, b in enumerate(spy_bars) if start <= b["d"] <= end]
    first, last = spy_bars[idx[0]], spy_bars[idx[-1]]
    shares = START_CASH / (first["o"] * (1.0 + COST_RATE))
    val = shares * last["c"]
    return round(val - (val * COST_RATE + SELL_FEE), 2)


# ------------------------------------------------------- cadence engine
def cadence_dates(days, cadence):
    """Evaluation dates: first trading day of each cadence period inside
    the window (SPEC uniform definition; same construction as the F-8
    sweep)."""
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


def run_cell(bars_by, idx_by, calendar, events_by_date, eval_set):
    """One DECADE cell under v9 protections. events_by_date already
    carries only this cadence's gated triggers; exit checks run only
    on cadence dates; the floor is checked at every close."""
    cash = START_CASH
    positions = {}
    pending_entries = []
    pending_exits = {}
    pending_liquidation = False
    halt_signal_date = None
    episode = 1
    episode_floor = FLOOR
    state = "active"           # active | sitout | ended
    sitout_until = None
    halts = []
    restart = False
    second_halt = False
    trades = []
    orders = 0
    total_costs = 0.0
    curve = []
    skips = []
    days_invested = 0

    def close_on_or_before(t, d):
        bars = bars_by[t]
        j = idx_by[t].get(d)
        if j is None:
            lo, hi = 0, len(bars) - 1
            best = None
            while lo <= hi:
                mid = (lo + hi) // 2
                if bars[mid]["d"] <= d:
                    best = mid
                    lo = mid + 1
                else:
                    hi = mid - 1
            return bars[best]["c"] if best is not None else None
        return bars[j]["c"]

    def pot_value(d):
        v = cash
        for t, pos in positions.items():
            c = close_on_or_before(t, d)
            if c:
                v += pos["shares"] * c
        return v

    def sell_position(t, price, dt, reason):
        nonlocal cash, total_costs, orders
        pos = positions.pop(t)
        val = pos["shares"] * price
        cost = val * COST_RATE + SELL_FEE
        total_costs += cost
        orders += 1
        proceeds = val - cost
        cash += proceeds
        trades.append({
            "ticker": t,
            "entry_date": pos["entry_date"], "entry_price": round(pos["entry_price"], 2),
            "exit_date": dt, "exit_price": round(price, 2),
            "pnl": round(proceeds - pos["cost_basis"], 2),
            "ret_pct": round((proceeds / pos["cost_basis"] - 1.0) * 100, 2),
            "exit_reason": reason,
            "pattern": pos.get("pattern"),
        })

    last_day = calendar[-1]
    for d in calendar:
        # ---- restart: first cadence date on/after the 90-day sit-out
        if state == "sitout" and d >= sitout_until and d in eval_set:
            episode = 2
            episode_floor = 0.85 * cash
            restart = True
            state = "active"

        # ---- 1. executions at today's opens
        if pending_liquidation:
            for t in list(positions):
                j = idx_by[t].get(d)
                if j is not None:
                    sell_position(t, bars_by[t][j]["o"], d, "floor")
            pending_entries = []
            pending_exits = {}
            if not positions:
                pending_liquidation = False
                halts.append({"episode": episode,
                              "signal_date": halt_signal_date,
                              "liquidation_date": d,
                              "proceeds": round(cash, 2),
                              "floor_in_effect": round(episode_floor, 2)})
                if episode == 2:
                    second_halt = True
                    state = "ended"
                else:
                    sitout_until = (date.fromisoformat(d)
                                    + timedelta(days=90)).isoformat()
                    state = "sitout"
        elif state == "active":
            for t in list(pending_exits):
                if t in positions:
                    j = idx_by[t].get(d)
                    if j is not None:
                        sell_position(t, bars_by[t][j]["o"], d, pending_exits.pop(t))
            still_pending = []
            for od in pending_entries:
                t = od["ticker"]
                j = idx_by[t].get(d)
                if j is None:
                    still_pending.append(od)
                    continue
                if t in positions:
                    skips.append({"date": od["signal_date"], "ticker": od["signal_ticker"],
                                  "reason": "name_held_at_execution"})
                    continue
                px = bars_by[t][j]["o"]
                buy_val = min(od["slice"], cash / (1.0 + COST_RATE))
                if buy_val <= 0.005:
                    skips.append({"date": od["signal_date"], "ticker": od["signal_ticker"],
                                  "reason": "no_cash"})
                    continue
                cost = buy_val * COST_RATE
                total_costs += cost
                orders += 1
                cash -= buy_val + cost
                positions[t] = {
                    "shares": buy_val / px, "entry_date": d,
                    "entry_price": px, "cost_basis": buy_val + cost,
                    "target": od["target"], "stop": od["stop"],
                    "entry_idx": j, "pattern": od.get("pattern"),
                }
            pending_entries = still_pending

        # ---- 2. equity curve at today's close
        v = pot_value(d)
        curve.append([d, round(v, 2)])
        if positions:
            days_invested += 1
        if d == last_day:
            break
        if state != "active":
            continue

        # ---- 3. floor check at the close (protection overlay, daily)
        if v <= episode_floor:
            pending_liquidation = True
            halt_signal_date = d
            pending_entries = []
            pending_exits = {}
            continue

        # ---- 4/5. strategy acting only on cadence dates
        if d not in eval_set:
            continue
        for t, pos in list(positions.items()):
            j = idx_by[t].get(d)
            if j is None:
                continue
            c = bars_by[t][j]["c"]
            if c < pos["stop"]:
                pending_exits[t] = "invalid_below_x"
            elif c >= pos["target"]:
                pending_exits[t] = "target_38.2"
            elif j - pos["entry_idx"] >= MAX_HOLD_DAYS:
                pending_exits[t] = "time_126d"

        for ev in events_by_date.get(d, []):
            held_names = set(positions) | {od["ticker"] for od in pending_entries}
            if len(held_names) >= MAX_POSITIONS:
                skips.append({"date": d, "ticker": ev["ticker"], "reason": "book_full"})
                continue
            slice_val = v / SLICES
            if ev["ticker"] in held_names:
                skips.append({"date": d, "ticker": ev["ticker"], "reason": "name_held"})
                continue
            pending_entries.append({
                "ticker": ev["ticker"], "signal_ticker": ev["ticker"],
                "signal_date": d, "slice": slice_val,
                "target": ev["target"], "stop": ev["x"],
                "pattern": {"x_date": ev["x_date"], "a_date": ev["a_date"],
                            "b_date": ev["b_date"], "c_date": ev["c_date"],
                            "b_ratio": ev["b_ratio"], "c_ratio": ev["c_ratio"],
                            "d_level": round(ev["d_level"], 2),
                            "arm_date": ev["arm_date"]},
            })

    # ---- end of window: liquidate at the final close
    if positions:
        for t in list(positions):
            c = close_on_or_before(t, last_day)
            sell_position(t, c, last_day, "window_end")
        if curve:
            curve[-1] = [last_day, round(cash, 2)]

    final = cash
    peak, maxdd = -1.0, 0.0
    for _, val in curve:
        peak = max(peak, val)
        if peak > 0:
            maxdd = max(maxdd, (peak - val) / peak)
    yrs = (date.fromisoformat(DEC_END) - date.fromisoformat(DEC_START)).days / 365.25
    rec = {
        "final": round(final, 2),
        "cagr_pct": round(((final / START_CASH) ** (1.0 / yrs) - 1.0) * 100, 2),
        "max_dd_pct": round(maxdd * 100, 2),
        "halts": halts, "restart": restart, "second_halt": second_halt,
        "costs": round(total_costs, 2), "orders": orders,
        "time_in_market_pct": round(100.0 * days_invested / len(calendar), 1),
        "n_eval_dates": len(eval_set),
        "trades_n": len(trades), "trades": trades, "skips": skips,
    }
    return rec, curve


def main():
    bars_by, idx_by = {}, {}
    for t in UNIVERSE + ["SPY"]:
        bars = load_bars(t)
        bars_by[t] = bars
        idx_by[t] = {b["d"]: i for i, b in enumerate(bars)}
    print(f"DATA pond+SPY loaded; SPY {bars_by['SPY'][0]['d']} -> "
          f"{bars_by['SPY'][-1]['d']}", flush=True)

    # ---- daily (ungated) extraction: census + armed records
    daily_events = {}
    census_total = {"pivots": 0, "armed": 0, "triggered": 0, "expired": 0,
                    "invalid_armed": 0, "invalid_prearm": 0}
    armed_all = []
    for t in UNIVERSE:
        evs, cen, recs = extract_triggers(t, bars_by[t])
        for k in census_total:
            census_total[k] += cen[k]
        armed_all.extend(recs)
        for ev in evs:
            daily_events.setdefault(ev["trigger_date"], []).append(ev)
    for d in daily_events:
        daily_events[d].sort(key=lambda e: e["ticker"])
    print(f"PATTERN CENSUS (full series): {census_total}", flush=True)

    # ---- integrity: original engine, original windows, his rules
    integ = {}
    for name, (ws, we), pub in (("CONT", ("2019-01-01", END), 101.02),
                                ("VAL", ("2023-01-01", END), 100.00)):
        calendar = sorted({b["d"] for t in UNIVERSE + ["SPY"]
                           for b in bars_by[t] if ws <= b["d"] <= we})
        ev_by = {d: evs for d, evs in daily_events.items() if ws <= d <= we}
        r = run_pot_original(bars_by, idx_by, calendar, ev_by)
        spy_bh = buy_hold_spy(bars_by["SPY"], ws, we)
        integ[name] = {"window": [ws, we], "published_final": pub,
                       "reproduced_final": r["final"],
                       "match": abs(r["final"] - pub) < 0.005,
                       "halted": r["halted"], "orders": r["orders"],
                       "trades_n": r["trades_n"],
                       "spy_buy_hold_reproduced": spy_bh}
        print(f"INTEGRITY {name}: published ${pub} reproduced "
              f"${r['final']} match={integ[name]['match']} "
              f"(SPY control ${spy_bh})", flush=True)
    assert all(v["match"] for v in integ.values()), "integrity FAILED"

    # ---- decade cadence matrix
    calendar = sorted({b["d"] for t in UNIVERSE + ["SPY"]
                       for b in bars_by[t] if DEC_START <= b["d"] <= DEC_END})
    armed_in_window = [r for r in armed_all
                       if DEC_START <= r["arm_date"] <= DEC_END]
    daily_triggers_in_window = [ev for d, evs in daily_events.items()
                                if DEC_START <= d <= DEC_END for ev in evs]
    print(f"DECADE calendar {calendar[0]} -> {calendar[-1]} "
          f"({len(calendar)} days); armed in window: "
          f"{len(armed_in_window)}; daily triggers in window: "
          f"{len(daily_triggers_in_window)}", flush=True)

    os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)
    cells = {}
    for cad in CADENCES:
        eval_set = cadence_dates(calendar, cad)
        if cad == "daily":
            ev_by = {d: evs for d, evs in daily_events.items()
                     if DEC_START <= d <= DEC_END}
            trig_in_window = daily_triggers_in_window
        else:
            ev_by = {}
            trig_in_window = []
            for t in UNIVERSE:
                evs, _, _ = extract_triggers(t, bars_by[t],
                                             eval_dates=eval_set)
                for ev in evs:
                    if DEC_START <= ev["trigger_date"] <= DEC_END:
                        ev_by.setdefault(ev["trigger_date"], []).append(ev)
                        trig_in_window.append(ev)
            for d in ev_by:
                ev_by[d].sort(key=lambda e: e["ticker"])
        rec, curve = run_cell(bars_by, idx_by, calendar, ev_by, eval_set)
        rec["patterns_armed_in_window"] = len(armed_in_window)
        rec["triggers_in_window"] = len(trig_in_window)
        rec["trigger_list"] = [
            {"ticker": ev["ticker"], "arm_date": ev["arm_date"],
             "trigger_date": ev["trigger_date"],
             "d_level": round(ev["d_level"], 2),
             "target": round(ev["target"], 2), "x": round(ev["x"], 2)}
            for ev in sorted(trig_in_window, key=lambda e: e["trigger_date"])]
        rec["placebo_beaten"] = None
        rec["placebo_note"] = PLACEBO_NOTE
        cell_doc = {"slug": "folklore-f10-gartley", "cadence": cad,
                    "window": [DEC_START, DEC_END],
                    "effective_first_trading_day": calendar[0],
                    "start_cash": START_CASH, **rec,
                    "equity_curve": curve}
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump(cell_doc, f, indent=1)
        cells[cad] = rec
        print(f"{cad.upper():11s} final ${rec['final']} CAGR "
              f"{rec['cagr_pct']}% maxDD {rec['max_dd_pct']}% costs "
              f"${rec['costs']} orders {rec['orders']} TIM "
              f"{rec['time_in_market_pct']}% triggers "
              f"{rec['triggers_in_window']} eval_dates "
              f"{rec['n_eval_dates']} halts {len(rec['halts'])}", flush=True)

    summary = {"integrity": integ, "census_full_series": census_total,
               "armed_in_window": [
                   {"ticker": r["ticker"], "arm_date": r["arm_date"],
                    "x_date": r["x_date"], "a_date": r["a_date"],
                    "b_date": r["b_date"], "c_date": r["c_date"],
                    "b_ratio": r["b_ratio"], "c_ratio": r["c_ratio"],
                    "d_level": round(r["d_level"], 2),
                    "outcome_daily": r["outcome"],
                    "outcome_date_daily": r["outcome_date"]}
                   for r in armed_in_window],
               "cells": cells}
    with open(os.path.join(HERE, "_sweep_summary.json"), "w") as f:
        json.dump(summary, f, indent=1)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
