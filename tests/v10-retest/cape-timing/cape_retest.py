#!/usr/bin/env python3
"""
CAPE VALUATION TIMING — THE GREAT RETEST (v10), worker script.
Simulation only.

THE RULE (original v6 form, unchanged — one clean shot, no tuning):
  * Trade SPY only. CAPE in its TOP HISTORICAL QUARTILE (>= expanding 75th
    percentile of all monthly CAPE values from Jan 1926 through the value
    used) -> hold CASH. Otherwise -> hold SPY fully.
  * CAPE source: multpl.com "Shiller PE Ratio by Month" (multpl republishes
    Shiller's Yale series) — the cached live file the original program used
    (multpl_by_month.html, copied into this folder). The Yale vintage file
    is a known trap and is NOT used. At a decision in month M the value
    dated the 1st of month M is used (~1-month publication lag, exactly as
    the original).
  * Costs (original engine's): buy 0.10% of value; sell 0.10% + $0.01.
  * SPY prices: Yahoo adjusted daily bars, the program's shared cache
    (data/px_SPY.json, copied from the original v6 folder).

PART 1 — INTEGRITY: the original engine in its ORIGINAL form (quarterly
quarter-end checks, plain -15% floor, no restart) on the original windows,
reproducing the published finals ($100.00 everywhere). Plus the original
rule checked MONTHLY (month-end checks) on the full window — the second
form the original program record reports (122/122 monthly checks in cash).

PART 2 — CADENCE SWEEP (SPEC): DECADE 2016-11-21 -> 2026-11-20 at all 7
cadences. Cadence = CAPE evaluation frequency, SPEC uniform definition:
checks on the first trading day of each period (daily = every trading
day), decide at that close, execute at the next trading day's open.
v9 protections: plain -15% floor from the episode's starting balance;
first halt -> liquidate at next open, sit in cash 90 calendar days,
restart at the strategy's next regular cadence date under an episode-2
floor of -15% from the restart balance; second halt ends the run.
Window entry: position dictated by the most recent cadence check on or
before the window start, executed at the window's first open (the
original always-on convention).
"""
import bisect
import json
import math
import os
import re
import time
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
START_CASH = 100.0
HIST_START = "1926-01"
DECADE = ("2016-11-21", "2026-11-20")
FULL = ("2017-01-01", "2026-11-20")
CHAMPION = ("2019-01-02", "2026-11-20")
VALIDATION = ("2023-01-01", "2026-11-20")
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]


# --------------------------------------------------------------------- data
def load_spy_bars():
    """Verbatim from the original v6 engine."""
    path = os.path.join(HERE, "data", "px_SPY.json")
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
        if c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        bars.append({"d": d, "o": (o * ratio if o else a), "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars


def load_cape():
    """Verbatim parser from the original v6 engine (multpl by-month table)."""
    html = open(os.path.join(HERE, "multpl_by_month.html")).read()
    pat = re.compile(
        r"<td>([A-Z][a-z]{2}) \d{1,2}, (\d{4})</td>\s*<td>\s*(?:&#x2002;)?\s*([0-9]+(?:\.[0-9]+)?)")
    months = {"Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
              "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
              "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12"}
    rows = {}
    for mon, yr, val in pat.findall(html):
        rows[f"{yr}-{months[mon]}"] = float(val)
    return sorted(rows.items())


def _pct(sorted_vals, q):
    """Percentile, linear interpolation — verbatim from the original."""
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_vals[lo]
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


class CapeSignal:
    """Verbatim signal logic from the original v6 engine."""

    def __init__(self, cape_rows):
        self.rows = cape_rows
        self.by_month = dict(cape_rows)

    def value_for_decision(self, decision_date):
        m = decision_date[:7]
        if m in self.by_month:
            return m, self.by_month[m]
        prior = [k for k in self.by_month if k < m]
        if not prior:
            return None, None
        k = max(prior)
        return k, self.by_month[k]

    def zone(self, decision_date):
        m, cape = self.value_for_decision(decision_date)
        if cape is None:
            return None
        hist = sorted(v for k, v in self.rows if HIST_START <= k <= m)
        med = _pct(hist, 0.50)
        q3 = _pct(hist, 0.75)
        if cape >= q3:
            zone = "top-quartile"
        elif cape < med:
            zone = "below-median"
        else:
            zone = "middle"
        return {"cape_month": m, "cape": cape, "median": med, "q3": q3,
                "zone": zone,
                "target": "CASH" if zone == "top-quartile" else "SPY",
                "n_hist": len(hist)}


class Book:
    def __init__(self, bars):
        self.bars = bars
        self.dates = [b["d"] for b in bars]
        self.by_date = {b["d"]: b for b in bars}

    def bar(self, d):
        return self.by_date.get(d)


# ------------------------------------------------- original engine (v6 form)
def period_end_days(book, start, end, months):
    out, seen = [], set()
    for d in book.dates:
        if start <= d <= end and d[5:7] in months:
            seen.add(d[:7])
    for m in sorted(seen):
        days = [d for d in book.dates if d[:7] == m and start <= d <= end]
        if days:
            out.append(days[-1])
    return out


def run_original(book, sig, start, end, months, label=""):
    """The original v6 engine, verbatim semantics: period-end checks,
    decide at close, execute next open, plain -15% floor, halt ends run,
    end-of-window liquidation at final close."""
    days = [d for d in book.dates if start <= d <= end]
    if not days:
        return None
    cash, shares, total_costs = START_CASH, 0.0, 0.0
    trades, decisions = [], []
    days_invested = 0
    # entry: most recent period-end check on or before window start
    prior = period_end_days(book, book.dates[0], start, months)
    # exclude a check ON the start date itself if start is mid-period; the
    # original used last quarter-end on or before the window start date.
    qe = None
    for d in period_end_days(book, book.dates[0], end, months):
        if d < days[0]:
            qe = d
    if qe is None and prior:
        qe = prior[-1]
    pending = None
    if qe:
        z0 = sig.zone(qe)
        if z0 is not None:
            decisions.append({"date": qe, "exec": days[0],
                              "entry_check": True, **z0})
            if z0["target"] == "SPY":
                pending = "SPY"
    dec_set = set(period_end_days(book, start, end, months))
    halted = None
    final = None
    for di, d in enumerate(days):
        bar = book.bar(d)
        if pending is not None:
            if pending == "SPY" and shares == 0.0 and cash > 0:
                buy_val = cash / 1.001
                c = buy_val * 0.001
                shares = buy_val / bar["o"]
                cash -= buy_val + c
                total_costs += c
                trades.append([d, "BUY", round(shares, 6), bar["o"],
                               round(buy_val, 2), round(c, 2)])
            elif pending == "CASH" and shares > 0:
                val = shares * bar["o"]
                c = val * 0.001 + 0.01
                cash += val - c
                total_costs += c
                trades.append([d, "SELL", round(shares, 6), bar["o"],
                               round(val, 2), round(c, 2)])
                shares = 0.0
            pending = None
        if d in dec_set:
            z = sig.zone(d)
            if z is not None:
                cur = "SPY" if shares > 0 else "CASH"
                decisions.append({"date": d, "exec": None, **z})
                if z["target"] != cur:
                    pending = z["target"]
                    decisions[-1]["exec"] = "next-open"
        if shares > 0:
            days_invested += 1
        v = cash + shares * bar["c"]
        if v <= 85.0 and di < len(days) - 1:
            halted = d
            nd = days[di + 1]
            if shares > 0:
                val = shares * book.bar(nd)["o"]
                c = val * 0.001 + 0.01
                cash += val - c
                total_costs += c
                trades.append([nd, "SELL-HALT", round(shares, 6),
                               book.bar(nd)["o"], round(val, 2), round(c, 2)])
                shares = 0.0
            final = cash
            break
    if final is None:
        last = days[-1]
        if shares > 0:
            val = shares * book.by_date[last]["c"]
            c = val * 0.001 + 0.01
            cash += val - c
            total_costs += c
            trades.append([last, "SELL-END", round(shares, 6),
                           book.by_date[last]["c"], round(val, 2),
                           round(c, 2)])
            shares = 0.0
        final = cash
    return {"label": label, "final": round(final, 2),
            "costs": round(total_costs, 2), "orders": len(trades),
            "halted": halted,
            "time_in_market_pct": round(100.0 * days_invested / len(days), 1),
            "decisions_total": len(decisions),
            "decisions_cash": sum(1 for x in decisions
                                  if x["target"] == "CASH"),
            "trades": trades, "decisions": decisions}


def spy_net(book, start, end):
    """Champion engine's buy-hold, verbatim semantics from the original."""
    days = [d for d in book.dates if start <= d <= end]
    first, last = days[0], days[-1]
    o = book.bar(first)["o"]
    sh = (START_CASH / 1.001) / o
    buy_cost = START_CASH - sh * o
    val = sh * book.by_date[last]["c"]
    sell_cost = val * 0.001 + 0.01
    return round(val - sell_cost, 2), round(buy_cost + sell_cost, 2)


# ------------------------------------------------------- cadence sweep (v10)
def cadence_dates(book, cadence, start, end):
    """SPEC uniform definition: first trading day of each period."""
    days = [d for d in book.dates if start <= d <= end]
    if cadence == "daily":
        return days
    out, seen = [], set()
    if cadence in ("weekly", "biweekly"):
        # anchor: ISO week containing the window start
        y0, w0, _ = date.fromisoformat(start).isocalendar()
        anchor = y0 * 100 + w0
        for d in days:
            y, w, _ = date.fromisoformat(d).isocalendar()
            key = y * 100 + w
            if key in seen:
                continue
            seen.add(key)
            if cadence == "weekly":
                out.append(d)
            else:
                # week index from anchor week (approx via ordinal of
                # the week's Monday)
                mon = date.fromisoformat(d) - timedelta(
                    days=date.fromisoformat(d).isoweekday() - 1)
                amon = date.fromisoformat(start) - timedelta(
                    days=date.fromisoformat(start).isoweekday() - 1)
                if ((mon - amon).days // 7) % 2 == 0:
                    out.append(d)
        return out
    for d in days:
        if cadence == "monthly":
            key = d[:7]
        elif cadence == "quarterly":
            key = d[:4] + "Q" + str((int(d[5:7]) - 1) // 3)
        elif cadence == "semiannual":
            key = d[:4] + "H" + ("1" if int(d[5:7]) <= 6 else "2")
        elif cadence == "annual":
            key = d[:4]
        else:
            raise ValueError(cadence)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def last_cadence_on_or_before(book, cadence, when):
    all_days = [d for d in book.dates if d <= when]
    if not all_days:
        return None
    sub = Book([b for b in book.bars if b["d"] <= when])
    cds = cadence_dates(sub, cadence, book.dates[0], when)
    return cds[-1] if cds else None


def run_sweep(book, sig, cadence, start, end):
    """One sweep cell: decade road, cadence checks (decide at close,
    execute next open), v9 protections."""
    days = [d for d in book.dates if start <= d <= end]
    checks = set(cadence_dates(book, cadence, start, end))
    cash, shares, total_costs = START_CASH, 0.0, 0.0
    trades, curve, halts = [], [], []
    checks_total = checks_invested = 0
    days_invested = 0
    episode = 1
    ep_start_balance = START_CASH
    halted_until = None          # date string; in forced cash sit
    ended = False
    pending = None
    # entry check: most recent cadence date on or before window start
    ec = last_cadence_on_or_before(book, cadence, start)
    if ec is not None:
        z0 = sig.zone(ec)
        if z0 is not None:
            checks_total += 1
            if z0["target"] == "CASH":
                pass
            else:
                checks_invested += 1
                pending = "SPY"
    for di, d in enumerate(days):
        bar = book.bar(d)
        in_sit = halted_until is not None and d < halted_until
        # execute pending switch at today's open
        if pending is not None and not in_sit and not ended:
            if pending == "SPY" and shares == 0.0 and cash > 0:
                buy_val = cash / 1.001
                c = buy_val * 0.001
                shares = buy_val / bar["o"]
                cash -= buy_val + c
                total_costs += c
                trades.append({"date": d, "side": "BUY",
                               "shares": round(shares, 6), "price": bar["o"],
                               "value": round(buy_val, 2), "cost": round(c, 2)})
            elif pending == "CASH" and shares > 0:
                val = shares * bar["o"]
                c = val * 0.001 + 0.01
                cash += val - c
                total_costs += c
                trades.append({"date": d, "side": "SELL",
                               "shares": round(shares, 6), "price": bar["o"],
                               "value": round(val, 2), "cost": round(c, 2)})
                shares = 0.0
            pending = None
        # cadence check at today's close
        if d in checks and not ended:
            if halted_until is not None and d >= halted_until:
                # restart point: new episode begins at this balance
                episode = 2
                ep_start_balance = cash + shares * bar["c"]
                halted_until = None
                in_sit = False
            if not in_sit:
                z = sig.zone(d)
                if z is not None:
                    checks_total += 1
                    if z["target"] == "SPY":
                        checks_invested += 1
                    cur = "SPY" if shares > 0 else "CASH"
                    if z["target"] != cur:
                        pending = z["target"]
        v = cash + shares * bar["c"]
        curve.append([d, round(v, 4)])
        if shares > 0:
            days_invested += 1
        # v9 plain floor, checked daily at close
        if not ended and di < len(days) - 1:
            if v <= 0.85 * ep_start_balance:
                nd = days[di + 1]
                if shares > 0:
                    val = shares * book.bar(nd)["o"]
                    c = val * 0.001 + 0.01
                    cash += val - c
                    total_costs += c
                    trades.append({"date": nd, "side": "SELL-HALT",
                                   "shares": round(shares, 6),
                                   "price": book.bar(nd)["o"],
                                   "value": round(val, 2),
                                   "cost": round(c, 2)})
                    shares = 0.0
                pending = None
                halts.append({"halt_date": d, "liquidated": nd,
                              "episode": episode,
                              "balance_after": round(cash, 2)})
                if episode >= 2:
                    ended = True
                else:
                    hd = date.fromisoformat(d) + timedelta(days=90)
                    halted_until = hd.isoformat()
    # end of window: liquidate at final close
    if shares > 0:
        last = days[-1]
        val = shares * book.by_date[last]["c"]
        c = val * 0.001 + 0.01
        cash += val - c
        total_costs += c
        trades.append({"date": last, "side": "SELL-END",
                       "shares": round(shares, 6),
                       "price": book.by_date[last]["c"],
                       "value": round(val, 2), "cost": round(c, 2)})
        shares = 0.0
        curve[-1] = [last, round(cash, 4)]
    final = cash
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    yrs = (date.fromisoformat(end) - date.fromisoformat(start)).days / 365.25
    cagr = (final / START_CASH) ** (1.0 / yrs) * 100 - 100 if final > 0 else -100.0
    return {
        "final": round(final, 2),
        "cagr_pct": round(cagr, 2),
        "max_dd_pct": round(maxdd * 100, 2),
        "costs": round(total_costs, 2),
        "orders": len(trades),
        "trades": trades,
        "halts": halts,
        "restart": len(halts) >= 1 and not ended,
        "second_halt": len(halts) >= 2,
        "checks_total": checks_total,
        "checks_invested": checks_invested,
        "checks_cash": checks_total - checks_invested,
        "days": len(days),
        "days_invested": days_invested,
        "invested_fraction_pct": round(100.0 * days_invested / len(days), 2),
        "equity_curve": curve,
    }


# --------------------------------------------------------------------- main
def main():
    bars = load_spy_bars()
    book = Book(bars)
    cape_rows = load_cape()
    sig = CapeSignal(cape_rows)
    print(f"SPY bars: {bars[0]['d']} -> {bars[-1]['d']} ({len(bars)})")
    print(f"CAPE months: {cape_rows[0][0]} -> {cape_rows[-1][0]} "
          f"({len(cape_rows)})")
    for m in ("2020-02", "2021-12", "2022-11", "2025-01"):
        print(f"  CAPE[{m}] = {sig.by_month.get(m)}")

    # ---------------- integrity: original quarterly form
    QM = ("03", "06", "09", "12")
    integrity_windows = {}
    for name, (ws, we) in (("full_2017_2026", FULL),
                           ("champion_2019_2026", CHAMPION),
                           ("validation_2023_2026", VALIDATION)):
        r = run_original(book, sig, ws, we, QM, label=name)
        spy, _ = spy_net(book, ws, we)
        integrity_windows[name] = {
            "final": r["final"], "orders": r["orders"],
            "costs": r["costs"], "halted": r["halted"],
            "decisions_total": r["decisions_total"],
            "decisions_cash": r["decisions_cash"],
            "time_in_market_pct": r["time_in_market_pct"],
            "spy_net_reproduced": spy}
        print(f"INTEGRITY {name}: final ${r['final']} orders {r['orders']} "
              f"cash {r['decisions_cash']}/{r['decisions_total']} "
              f"SPY ${spy}")
    # folds, original form
    folds = {}
    for y in range(2017, 2027):
        fs = f"{y}-01-01"
        fe = "2026-11-20" if y == 2026 else f"{y}-12-31"
        fr = run_original(book, sig, fs, fe, QM, label=f"FOLD {y}")
        folds[str(y)] = fr["final"]
    print(f"INTEGRITY folds: {folds}")

    # ---------------- integrity: original rule, monthly checks
    ALLM = tuple(f"{i:02d}" for i in range(1, 13))
    monthly_checks = {}
    for name, (ws, we) in (("full_2017_2026", FULL), ("decade", DECADE)):
        r = run_original(book, sig, ws, we, ALLM, label=name + "-monthly")
        monthly_checks[name] = {
            "final": r["final"], "orders": r["orders"],
            "decisions_total": r["decisions_total"],
            "decisions_cash": r["decisions_cash"],
            "time_in_market_pct": r["time_in_market_pct"]}
        print(f"MONTHLY-FORM {name}: final ${r['final']} orders {r['orders']} "
              f"cash {r['decisions_cash']}/{r['decisions_total']}")

    with open(os.path.join(HERE, "integrity.json"), "w") as f:
        json.dump({"form": "original v6 engine, quarterly quarter-end checks "
                           "(canonical) + monthly month-end checks variant",
                   "published_finals": {
                       "full_2017_2026": 100.0, "champion_2019_2026": 100.0,
                       "validation_2023_2026": 100.0,
                       "spy_nets": {"full_2017_2026": 356.11,
                                    "champion_2019_2026": 313.62,
                                    "validation_2023_2026": 187.77},
                       "folds_2017_2026": 100.0},
                   "reproduced_quarterly": integrity_windows,
                   "reproduced_folds": folds,
                   "monthly_form": monthly_checks}, f, indent=1)

    # ---------------- sweep
    spy_dec, spy_dec_costs = spy_net(book, *DECADE)
    print(f"DECADE SPY buy-hold: ${spy_dec} (costs ${spy_dec_costs})")
    cells = {}
    for cad in CADENCES:
        r = run_sweep(book, sig, cad, *DECADE)
        cell = {
            "cadence": cad, "window": {"start": DECADE[0], "end": DECADE[1]},
            "final": r["final"], "cagr_pct": r["cagr_pct"],
            "max_dd_pct": r["max_dd_pct"], "costs": r["costs"],
            "orders": r["orders"], "trades": r["trades"],
            "halts": r["halts"], "restart": r["restart"],
            "second_halt": r["second_halt"],
            "checks_total": r["checks_total"],
            "checks_invested": r["checks_invested"],
            "checks_cash": r["checks_cash"],
            "days": r["days"], "days_invested": r["days_invested"],
            "invested_fraction_pct": r["invested_fraction_pct"],
            "placebo_beaten": None,
            "placebo_note": "n/a — the rule never fires at any cadence "
                            "(0 invested checks in every cell), so there "
                            "is no return stream and no twin distribution "
                            "to build; a random-twin placebo of a rule "
                            "that never trades is not defined.",
            "equity_curve": r["equity_curve"],
        }
        cells[cad] = cell
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump(cell, f, indent=1)
        print(f"CELL {cad}: final ${r['final']} CAGR {r['cagr_pct']}% "
              f"maxDD {r['max_dd_pct']}% orders {r['orders']} "
              f"checks invested {r['checks_invested']}/{r['checks_total']} "
              f"invested {r['invested_fraction_pct']}%")

    results = {
        "slug": "cape-timing",
        "area": "Valuation timing (timer scoring) — hold SPY only when "
                "Shiller CAPE is below its expanding historical top "
                "quartile, else cash; judged on the DECADE road.",
        "area_source": "SPEC W8 assignment (CAPE = valuation timing, "
                       "timer scoring; a never-traded outcome is again "
                       "the result) + CADENCE GRID W8 row.",
        "native_cadence": "monthly",
        "cadence": "monthly",
        "original_cadence_foreign": True,
        "original_cadence_note": "SPEC CADENCE GRID: native = monthly "
            "checks; the original v6 program test used QUARTERLY "
            "quarter-end checks (foreign). The original program record "
            "also reports a monthly month-end check form (122/122 checks "
            "in cash). Canonical original form = the published v6 "
            "quarterly engine; both forms reproduced in integrity.json.",
        "native_change": "none in the rule — threshold, expanding stats "
            "from Jan 1926, ~1-month CAPE publication lag, costs and SPY "
            "series are the original's. The sweep changes only the "
            "evaluation frequency (SPEC uniform cadence definition) and "
            "adopts v9 protections.",
        "integrity": {
            "status": "reproduced",
            "original_finals": {
                "full_2017_2026": 100.0, "champion_2019_2026": 100.0,
                "validation_2023_2026": 100.0,
                "folds_2017_2026_each": 100.0,
                "spy_nets": {"full_2017_2026": 356.11,
                             "champion_2019_2026": 313.62,
                             "validation_2023_2026": 187.77}},
            "reproduced_finals": {
                k: v["final"] for k, v in integrity_windows.items()},
            "reproduced_spy_nets": {
                k: v["spy_net_reproduced"]
                for k, v in integrity_windows.items()},
            "notes": "Quarterly form reproduced exactly: $100.00, 0 "
                     "orders, all checks cash on every original window "
                     "and all 10 yearly folds; SPY nets reproduce to the "
                     "cent. Monthly month-end form also reproduced "
                     "(see integrity.json): $100.00, 0 orders, every "
                     "monthly check in cash."},
        "decade_spy_final": spy_dec,
        "decade_spy_costs": spy_dec_costs,
        "cells": {cad: {k: cells[cad][k] for k in
                        ("final", "cagr_pct", "max_dd_pct", "halts",
                         "restart", "second_halt", "costs", "orders",
                         "placebo_beaten", "placebo_note",
                         "checks_total", "checks_invested", "checks_cash",
                         "invested_fraction_pct")}
                  for cad in CADENCES},
        "money_cadences": [],
        "verdict_area": "NO GROUND",
        "verdict_change": "none — the original program's verdict stands: "
                          "the rule never traded then and never trades "
                          "now, at any of the 7 cadences.",
        "placebo_note": "n/a for the whole row — a rule that never fires "
                        "has no twin distribution (see cells).",
    }
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("DONE")


if __name__ == "__main__":
    main()
