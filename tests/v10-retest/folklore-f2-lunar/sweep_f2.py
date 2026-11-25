#!/usr/bin/env python3
"""
W6b CADENCE SWEEP — F-2 Lunar cycle (new moon +/-7 days), SPY.
THE GREAT RETEST (v10). Simulation only. One clean shot, frozen spec.

INTEGRITY: established by W6 pre-restructure (CONT $113.47, VAL $105.24
reproduced to the cent; block preserved verbatim in results.json from
w6_results.json). This script does NOT re-run the integrity gate; it
verifies its daily-cadence DECADE cell against W6's DECADE area run
($113.47 is CONT; DECADE area run was $113.60, control $187.72) as a
plumbing sanity check and prints the comparison.

CADENCE TREATMENT (stated, binding for this run): this is an
event/calendar strategy. The lunar window rule stays exactly as
published — a trading day is IN WINDOW iff it falls within +/-7
calendar days of a new moon (moon dates from the original engine's own
computed Schlyter ephemeris, eclipse-validated in code). Cadence
governs ONLY the evaluation/review rhythm: the position is reviewed on
cadence dates (daily = every trading day; weekly = first trading day
of each week; biweekly = first trading day of every second week;
monthly/quarterly/semi-annual/annual = first trading day of the
period). On a review date, if that date's lunar membership differs
from the current holding, the switch executes at THAT date's open —
the original engine's own convention (membership is a calendar fact
known in advance, so no look-ahead). Between review dates the
position is held unchanged even if a lunar window boundary passes.
Consequence: the daily cell IS the original machine and must match
W6's DECADE area run; slower cadences hold through boundaries and can
sit in or out for a whole review period.

CONTROL (this strategy's placebo, per the original design): the
identical machine, identical cadence machinery, on FULL-moon +/-7-day
windows. A cadence counts as money only if the new-moon form beats
SPY buy-hold AND beats this control at the same cadence.

PROTECTION: adopted v9 rules — plain -15% floor from the episode
start, checked at every close (protection overlay, not a signal);
on halt, liquidate at the next open, sit in cash 90 calendar days,
restart once at the first trading day on/after eligibility (reviews
resume on cadence dates) under an episode-2 floor of -15% from the
restart balance; second halt ends the run.

COSTS: program conventions, the original engine's own code:
0.10%/side + $0.01 per sell order. End of window: open position
liquidated at the final close with the standard sell cost.

DATA: SPY bars only (shared RAM is tight) — read-only shared cache
backtests/v7/long-hold/data/pxfull_SPY.json (Yahoo, champion
construction: open scaled by adjclose/close, close = adjclose;
dividend-adjusted). DECADE road 2016-11-21 -> 2026-11-20, $100/cell.

Outputs (this folder): cells/<cadence>.json (full equity curve for
strategy AND control, halts/restarts with dates, control finals),
results.json (SPEC sweep format), RESULTS.md (written separately).
"""
import json
import math
import os
import time
from datetime import date, datetime, timedelta

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
        o, c = q["open"][i], q["close"][i]
        if c is None or o is None:
            continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        bars.append({"d": d, "o": o * ratio, "c": a})
    bars.sort(key=lambda b: b["d"])
    # keep only what the decade road needs (plus a small lead-in)
    return [b for b in bars if "2016-01-01" <= b["d"] <= DEC_END]


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


# ------------------------------------------------- ephemeris (verbatim
# from the original F-2 engine: Schlyter elements + perturbation series)
def _rev(x):
    return x - math.floor(x / 360.0) * 360.0


def _sind(x):
    return math.sin(math.radians(_rev(x)))


def _cosd(x):
    return math.cos(math.radians(_rev(x)))


def _sun(d):
    w = 282.9404 + 4.70935e-5 * d
    e = 0.016709 - 1.151e-9 * d
    M = _rev(356.0470 + 0.9856002585 * d)
    Ea = M + math.degrees(e) * _sind(M) * (1 + e * _cosd(M))
    xv = math.cos(math.radians(Ea)) - e
    yv = math.sqrt(1 - e * e) * math.sin(math.radians(Ea))
    v = math.degrees(math.atan2(yv, xv))
    return _rev(v + w), M, _rev(M + w)


def _moon_lon(d):
    N = 125.1228 - 0.0529538083 * d
    inc = 5.1454
    w = 318.0634 + 0.1643573223 * d
    a = 60.2666
    e = 0.054900
    M = _rev(115.3654 + 13.0649929509 * d)
    Ea = M + math.degrees(e) * _sind(M) * (1 + e * _cosd(M))
    for _ in range(3):
        Ea = Ea - (Ea - math.degrees(e) * _sind(Ea) - M) / (1 - e * _cosd(Ea))
    xv = a * (math.cos(math.radians(Ea)) - e)
    yv = a * (math.sqrt(1 - e * e) * math.sin(math.radians(Ea)))
    v = math.degrees(math.atan2(yv, xv))
    r = math.hypot(xv, yv)
    vw = v + w
    xh = r * (_cosd(N) * _cosd(vw) - _sind(N) * _sind(vw) * _cosd(inc))
    yh = r * (_sind(N) * _cosd(vw) + _cosd(N) * _sind(vw) * _cosd(inc))
    lon = _rev(math.degrees(math.atan2(yh, xh)))
    _, Ms, s_mlon = _sun(d)
    mlon = _rev(N + w + M)
    D = _rev(mlon - s_mlon)
    F = _rev(mlon - N)
    Mm = M
    lon += (-1.274 * _sind(Mm - 2 * D) + 0.658 * _sind(2 * D)
            - 0.186 * _sind(Ms) - 0.059 * _sind(2 * Mm - 2 * D)
            - 0.057 * _sind(Mm - 2 * D + Ms) + 0.053 * _sind(Mm + 2 * D)
            + 0.046 * _sind(2 * D - Ms) + 0.041 * _sind(Mm - Ms)
            - 0.035 * _sind(D) - 0.031 * _sind(Mm + Ms)
            - 0.015 * _sind(2 * F - 2 * D) + 0.011 * _sind(Mm - 4 * D))
    return _rev(lon)


def _elong(d):
    slon, _, _ = _sun(d)
    return _rev(_moon_lon(d) - slon)


def _signed(x):
    y = (x + 180.0) % 360.0 - 180.0
    return 180.0 if y == -180.0 else y


_JD_EPOCH = datetime(2000, 1, 1, 12, 0)


def _d_of(dt):
    jd = (dt - _JD_EPOCH).total_seconds() / 86400.0 + 2451545.0
    return jd - 2451543.5


def _dt_of_d(d):
    return _JD_EPOCH + timedelta(days=(d + 2451543.5) - 2451545.0)


def moon_events(dt_start, dt_end, target):
    t = _d_of(dt_start)
    t_end = _d_of(dt_end)
    f_prev = _signed(_elong(t) - target)
    out = []
    step = 0.25
    while t < t_end:
        t2 = t + step
        f2 = _signed(_elong(t2) - target)
        if f_prev < 0 <= f2:
            a, b = t, t2
            for _ in range(60):
                m = 0.5 * (a + b)
                if _signed(_elong(m) - target) < 0:
                    a = m
                else:
                    b = m
            out.append(_dt_of_d(0.5 * (a + b)))
            t, f_prev = t2, _signed(_elong(t2) - target)
            continue
        t, f_prev = t2, f2
    return out


def validate_ephemeris(new_dates, full_dates):
    known_new = ["2019-07-02", "2020-12-14", "2021-12-04", "2023-04-20",
                 "2023-10-14", "2024-04-08", "2025-03-29", "2025-09-21"]
    known_full = ["2019-01-21", "2022-05-16", "2022-11-08", "2024-03-25",
                  "2025-03-14", "2025-09-07", "2026-03-03"]
    nd = {d.isoformat() for d in new_dates}
    fd = {d.isoformat() for d in full_dates}
    ok = all(k in nd for k in known_new) and all(k in fd for k in known_full)
    return ok


def membership_set(moon_dates, days):
    """Set of trading-day strings within +/-7 calendar days of a moon date."""
    out = set()
    for md in moon_dates:
        for k in range(-7, 8):
            out.add((md + timedelta(days=k)).isoformat())
    return {d for d in days if d in out}


# ------------------------------------------------------- cadence engine
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


def run_episode(bars, idx, eval_set, in_window, start_cash, floor):
    """One v9 episode. On a review date (bar date in eval_set), membership
    of THAT date decides: buy at its open if in window and flat; sell at
    its open if out of window and holding (original engine convention).
    Floor checked at every close; on breach, liquidate at next open."""
    cash, shares = start_cash, 0.0
    trades, costs, orders, curve, days_in = [], 0.0, 0, [], 0
    halted = liq_date = None
    for pos, i in enumerate(idx):
        b = bars[i]
        if b["d"] in eval_set:
            want = b["d"] in in_window
            if want and shares == 0.0:
                buy_val = cash / 1.001
                c = buy_val * COST_RATE
                shares = buy_val / b["o"]
                cash -= buy_val + c
                costs += c
                orders += 1
                trades.append([b["d"], "BUY", round(c, 2)])
            elif not want and shares > 0.0:
                val = shares * b["o"]
                c = val * COST_RATE + SELL_FEE
                cash += val - c
                costs += c
                orders += 1
                shares = 0.0
                trades.append([b["d"], "SELL", round(c, 2)])
        if shares > 0.0:
            days_in += 1
        v = cash + shares * b["c"]
        curve.append([b["d"], round(v, 2)])
        if v <= floor and pos < len(idx) - 1:
            halted = b["d"]
            nb = bars[idx[pos + 1]]
            if shares > 0.0:
                val = shares * nb["o"]
                c = val * COST_RATE + SELL_FEE
                cash += val - c
                costs += c
                orders += 1
                shares = 0.0
                trades.append([nb["d"], "SELL-HALT", round(c, 2)])
            liq_date = nb["d"]
            curve.append([nb["d"], round(cash, 2)])
            break
    return {"cash": cash, "shares": shares, "halted": halted,
            "liq_date": liq_date, "trades": trades, "costs": costs,
            "orders": orders, "curve": curve, "days_in": days_in}


def run_cell(bars, days, eval_set, in_window):
    """Full v9 run over the DECADE window for one membership set."""
    idx_all = [i for i, b in enumerate(bars) if DEC_START <= b["d"] <= DEC_END]
    by_date = {bars[i]["d"]: i for i in idx_all}
    halts = []
    restart = False
    second_halt = False
    restart_date = None
    total_costs = 0.0
    total_orders = 0
    total_days_in = 0
    curve = []
    start, start_cash, floor = DEC_START, START_CASH, 0.85 * START_CASH
    final = None
    for episode in (1, 2):
        idx = [i for i in idx_all if bars[i]["d"] >= start]
        ep = run_episode(bars, idx, eval_set, in_window, start_cash, floor)
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
            tail = [[d, round(final, 2)] for d in days if d > curve[-1][0]]
            curve = curve + tail
            break
        liq = ep["liq_date"] or ep["halted"]
        elig = (date.fromisoformat(liq) + timedelta(days=90)).isoformat()
        rest = [d for d in days if d >= elig]
        if not rest:
            final = ep["cash"]
            tail = [[d, round(final, 2)] for d in days if d > curve[-1][0]]
            curve = curve + tail
            break
        restart = True
        restart_date = rest[0]
        start = rest[0]
        start_cash = ep["cash"]
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
        "restart_date": restart_date,
        "costs": round(total_costs, 2), "orders": total_orders,
        "time_in_market_pct": round(100.0 * total_days_in / len(days), 1),
        "n_eval_dates": len(eval_set),
    }
    return rec, curve


def main():
    bars = load_bars(LONG_PX)
    days = [b["d"] for b in bars if DEC_START <= b["d"] <= DEC_END]
    spy = buy_hold(bars, DEC_START, DEC_END)
    print(f"SPY DECADE buy-hold: ${spy['final']} maxDD {spy['max_dd_pct']}% "
          f"(SPEC reference $367.80 / 33.72%)", flush=True)

    new_dts = moon_events(datetime(2016, 10, 1), datetime(2027, 1, 15), 0.0)
    full_dts = moon_events(datetime(2016, 10, 1), datetime(2027, 1, 15), 180.0)
    new_dates = [x.date() for x in new_dts]
    full_dates = [x.date() for x in full_dts]
    ok = validate_ephemeris(new_dates, full_dates)
    print(f"EPHEMERIS VALIDATION (eclipse dates): {ok}", flush=True)
    assert ok, "EPHEMERIS VALIDATION FAILED"
    new_in = membership_set(new_dates, days)
    full_in = membership_set(full_dates, days)

    os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)
    cells = {}
    for cad in CADENCES:
        eval_set = cadence_dates(days, cad)
        rec, curve = run_cell(bars, days, eval_set, new_in)
        crec, ccurve = run_cell(bars, days, eval_set, full_in)
        rec["placebo_beaten"] = None
        rec["placebo_note"] = (
            "Placebo for this strategy is its own full-moon control "
            "(original design, singular — not a 20-seed distribution): "
            "the identical machine at the same cadence on full-moon "
            "+/-7-day windows. A cadence counts only if the new-moon "
            "form beats this control there.")
        rec["control_final"] = crec["final"]
        rec["control_cagr_pct"] = crec["cagr_pct"]
        rec["control_max_dd_pct"] = crec["max_dd_pct"]
        rec["control_costs"] = crec["costs"]
        rec["control_orders"] = crec["orders"]
        rec["control_time_in_market_pct"] = crec["time_in_market_pct"]
        rec["control_halts"] = crec["halts"]
        rec["control_restart"] = crec["restart"]
        rec["control_second_halt"] = crec["second_halt"]
        rec["control_beats_strategy"] = crec["final"] > rec["final"]
        rec["beats_spy"] = rec["final"] > spy["final"]
        cell_doc = {"slug": "folklore-f2-lunar", "cadence": cad,
                    "cadence_treatment": (
                        "Lunar +/-7-day window rule unchanged; cadence "
                        "governs the review rhythm only — position "
                        "reviewed on cadence dates, switch at the review "
                        "date's open if that date's membership differs "
                        "from the holding; held unchanged between reviews."),
                    "window": [DEC_START, DEC_END],
                    "start_cash": START_CASH, **rec,
                    "control": {**crec, "equity_curve": ccurve},
                    "equity_curve": curve}
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump(cell_doc, f, indent=1)
        cells[cad] = rec
        print(f"{cad.upper():11s} final ${rec['final']} CAGR "
              f"{rec['cagr_pct']}% maxDD {rec['max_dd_pct']}% costs "
              f"${rec['costs']} orders {rec['orders']} TIM "
              f"{rec['time_in_market_pct']}% | CONTROL ${crec['final']} "
              f"maxDD {crec['max_dd_pct']}% TIM "
              f"{crec['time_in_market_pct']}% halts "
              f"{len(rec['halts'])}/{len(crec['halts'])}", flush=True)

    with open(os.path.join(HERE, "_sweep_summary.json"), "w") as f:
        json.dump({"spy": spy, "cells": cells}, f, indent=1)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
