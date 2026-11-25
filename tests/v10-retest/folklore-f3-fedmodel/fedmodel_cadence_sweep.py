#!/usr/bin/env python3
"""
F-3 FED MODEL (trailing-earnings form) — v10 GREAT RETEST, CADENCE SWEEP.

Strategy (frozen, verbatim from the original F-3 spec / v9 engine):
  Hold SPY when Shiller trailing earnings yield (E/P, trailing 12-month
  as-reported earnings / index price) exceeds Shiller's 10-year yield
  (GS10, "Long Interest Rate"); hold cash otherwise. Costs 0.10%/side +
  $0.01 per sell order (the original engine's own cost code). Cash 0%.
  End of window: liquidate at the final close (sell cost applies).

DATA:
  * Earnings/yield: the LIVE Shiller ie_data.xls downloaded from
    shillerdata.com, cached read-only in this folder as
    data/ie_data_live_shillerdata.xls (md5 2fd4f34013378aeb1a9b96c794a3346c,
    identical to the file the original test used). The frozen Yale
    vintage (complete only to 2023-06) is a documented data trap and is
    NOT used.
  * SPY bars: Yahoo adjusted daily bars, the program's shared
    full-range cache (backtests/v7/long-hold/data/pxfull_SPY.json,
    2008-01-02 -> 2026-11-20, read-only) — the series W6's area runs
    used (the F-3 folder's own px_SPY.json pull only starts 2017-06-01
    and cannot cover the decade start; the integrity gate below proves
    this series reproduces the original published finals to the cent
    on CONT and VAL before any sweep number is taken).

PUBLICATION LAG / CADENCE TREATMENT (stated before results):
  The Shiller series is MONTHLY at source. The original rule evaluates
  on the last trading day of month M using the Shiller row for month
  M-1 (~1-month publication lag). The sweep generalises this uniformly:
  at ANY evaluation date in calendar month M, the freshest published
  values are the row for month M-1 (falling back to the most recent
  earlier complete row if M-1 is incomplete). Consequences, stated
  plainly: at sub-monthly cadences (daily/weekly/biweekly) the target
  can only change at month boundaries, because no fresher data exists;
  at annual cadence the model checks once a year and holds that call.

CADENCE (SPEC uniform definition): signal evaluation, selection and
trading happen ONLY on cadence dates — daily = every trading day;
weekly = first trading day of each week; biweekly = first trading day
of every second week (weeks counted from the week containing the
window start); monthly = first trading day of each month; quarterly =
first trading day of each calendar quarter; semi-annual = first
trading day of each half-year; annual = first trading day of each
year. A switch decided on a cadence date executes at the NEXT
session's open (original engine mechanics). At the window start the
pot takes the position dictated by the freshest published row,
executed at the window's first open (original forced reading 4).

ROAD: DECADE 2016-11-21 -> 2026-11-20, $100 per cell.

PROTECTION (adopted v9 rules): plain -15% floor from the episode's
starting balance (close at/below the floor on any day but the last ->
liquidate at the next open); on first halt sit in cash 90 calendar
days, restart at the strategy's next regular cadence decision date
on/after day 90 (executed at the next open) under an episode-2 floor
of -15% from the restart balance; second halt ends the run.

PLACEBOS: the original's own shifted-signal design (forced reading 6
of the original spec): circular shifts of the strategy's realized
sequence of cadence targets — a shift preserves the exact number of
invested periods AND the exact number of switches; only WHICH periods
are invested changes. Seeds 1..20, shift drawn via
random.Random(seed).randrange(1, n). Run per cell under the same v9
protections. placebo_beaten = number of the 20 placebo finals strictly
below the strategy's final.

INTEGRITY: before the sweep, this script re-runs the ORIGINAL form
(month-end evaluations, original windows, his-rules single-episode
floor) and checks CONT $196.05 / VAL $117.37 (W6's verified finals),
plus the original-form DECADE monthly run ($229.92).
"""
import bisect
import csv
import datetime as dt
import json
import os
import random
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SPY_PATH = os.path.expanduser(
    "~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
SHILLER_PATH = os.path.join(HERE, "data", "ie_data_live_shillerdata.xls")
START_CASH = 100.0
DECADE = ("2016-11-21", "2026-11-20")
PLACEBO_SEEDS = list(range(1, 21))
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]


# --------------------------------------------------------------------- data
def load_spy_bars():
    """Verbatim from the original engine (program shared cache series)."""
    with open(SPY_PATH, "rb") as f:
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


def load_shiller():
    """Parse Shiller's ie_data.xls -> {yyyymm: {p, e, gs10}}; also write
    shiller_monthly.csv into this folder for auditability. Parser copied
    from the original engine (searches every sheet for the header row;
    accepts the 'Rate GS10' label)."""
    import xlrd
    wb = xlrd.open_workbook(SHILLER_PATH)
    sh, hdr = None, None
    for si in range(wb.nsheets):
        cand = wb.sheet_by_index(si)
        for r in range(min(15, cand.nrows)):
            row = [str(cand.cell_value(r, c)).strip()
                   for c in range(cand.ncols)]
            if any("Price" in v for v in row) and \
                    any("Earnings" in v for v in row):
                sh, hdr = cand, r
                break
        if sh is not None:
            break
    if hdr is None:
        raise SystemExit("ie_data header row not found")
    header = [str(sh.cell_value(hdr, c)).strip() for c in range(sh.ncols)]
    col = {}
    for i, h in enumerate(header):
        hl = h.lower()
        if hl == "date":
            col["date"] = i
        elif h == "P":
            col["p"] = i
        elif h == "E":
            col["e"] = i
        elif ("long" in hl and "rate" in hl) or "gs10" in hl:
            col["gs10"] = i
    missing = {"date", "p", "e", "gs10"} - set(col)
    if missing:
        raise SystemExit(f"ie_data columns not found: {missing}")
    rows = {}
    for r in range(hdr + 1, sh.nrows):
        dv = sh.cell_value(r, col["date"])
        if not isinstance(dv, (int, float)) or dv <= 0:
            continue
        yr = int(dv)
        mo = int(round((dv - yr) * 100))
        if not (1 <= mo <= 12):
            continue
        key = f"{yr:04d}-{mo:02d}"
        vals, ok = {}, True
        for name in ("p", "e", "gs10"):
            v = sh.cell_value(r, col[name])
            if not isinstance(v, (int, float)) or v == 0:
                ok = False
                break
            vals[name] = float(v)
        if ok:
            rows[key] = vals
    with open(os.path.join(HERE, "shiller_monthly.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["month", "price", "earnings_trailing", "gs10_pct",
                    "earnings_yield_pct"])
        for k in sorted(rows):
            v = rows[k]
            w.writerow([k, v["p"], v["e"], v["gs10"],
                        round(v["e"] / v["p"] * 100, 4)])
    return rows


# ------------------------------------------------------------------- signal
class FedSignal:
    """Freshest published row at any date in month M is the row for
    month M-1 (the original's one-month publication lag, generalised
    uniformly across cadences)."""

    def __init__(self, rows):
        self.rows = rows
        self.months = sorted(rows)

    def row_for(self, date):
        yr, mo = int(date[:4]), int(date[5:7])
        mo -= 1
        if mo == 0:
            yr, mo = yr - 1, 12
        target = f"{yr:04d}-{mo:02d}"
        if target in self.rows:
            return target, self.rows[target]
        prior = [m for m in self.months if m < target]
        if not prior:
            return None, None
        k = prior[-1]
        return k, self.rows[k]

    def target(self, date):
        _, row = self.row_for(date)
        if row is None:
            raise SystemExit(f"no Shiller row usable at {date}")
        return "SPY" if row["e"] / row["p"] * 100.0 > row["gs10"] else "CASH"


# ------------------------------------------------------------------- engine
class Book:
    def __init__(self, bars):
        self.bars = bars
        self.dates = [b["d"] for b in bars]
        self.by_date = {b["d"]: b for b in bars}

    def bar(self, d):
        return self.by_date[d]


def simulate(book, eval_dates, targets, start, end, start_cash, floor_abs):
    """One episode. eval_dates[0] is the entry check (executed at the
    segment's first open); eval_dates[1:] are in-window evaluation dates
    (decided at that day's close, executed at the next open). Floor:
    close equity <= floor_abs on any day but the segment's last ->
    liquidate at next open, episode halts. End: liquidate at final
    close. Mechanics copied from the original engine."""
    days = [d for d in book.dates if start <= d <= end]
    assert len(eval_dates) == len(targets)
    cash, shares = start_cash, 0.0
    total_costs, trades, curve = 0.0, [], []
    days_invested = 0
    pending = "SPY" if targets[0] == "SPY" else None
    dec_set = {d: i for i, d in enumerate(eval_dates[1:], start=1)}
    for di, d in enumerate(days):
        bar = book.bar(d)
        if pending is not None:
            if pending == "SPY" and shares == 0.0 and cash > 0:
                buy_val = cash / 1.001
                c = buy_val * 0.001
                shares = buy_val / bar["o"]
                cash -= buy_val + c
                total_costs += c
                trades.append([d, "BUY", round(buy_val, 2), round(c, 2)])
            elif pending == "CASH" and shares > 0:
                val = shares * bar["o"]
                c = val * 0.001 + 0.01
                cash += val - c
                total_costs += c
                trades.append([d, "SELL", round(val, 2), round(c, 2)])
                shares = 0.0
            pending = None
        if d in dec_set:
            tgt = targets[dec_set[d]]
            cur = "SPY" if shares > 0 else "CASH"
            if tgt != cur:
                pending = tgt
        v = cash + shares * bar["c"]
        curve.append([d, round(v, 4)])
        if shares > 0:
            days_invested += 1
        if v <= floor_abs and di < len(days) - 1:
            nd = days[di + 1]
            liq_date = None
            if shares > 0:
                val = shares * book.bar(nd)["o"]
                c = val * 0.001 + 0.01
                cash += val - c
                total_costs += c
                trades.append([nd, "SELL-HALT", round(val, 2), round(c, 2)])
                shares = 0.0
                liq_date = nd
            return {"final": cash, "costs": total_costs, "trades": trades,
                    "curve": curve, "days_invested": days_invested,
                    "n_days": len(days), "halted": d, "liq_date": liq_date or nd,
                    "cash_at_halt": cash}
    last = days[-1]
    if shares > 0:
        val = shares * book.by_date[last]["c"]
        c = val * 0.001 + 0.01
        cash += val - c
        total_costs += c
        trades.append([last, "SELL-END", round(val, 2), round(c, 2)])
        shares = 0.0
    return {"final": cash, "costs": total_costs, "trades": trades,
            "curve": curve, "days_invested": days_invested,
            "n_days": len(days), "halted": None, "liq_date": None,
            "cash_at_halt": None}


def run_v9(book, eval_dates, targets, start, end):
    """Full run under adopted v9 protections. eval_dates[0] = entry
    check; the rest are the cadence decision dates inside the window.
    Returns combined result with full-window equity curve."""
    ep1 = simulate(book, eval_dates, targets, start, end,
                   START_CASH, 0.85 * START_CASH)
    days = [d for d in book.dates if start <= d <= end]
    curve_map = {d: v for d, v in ep1["curve"]}
    halts, restart_info = [], None
    final, costs = ep1["final"], ep1["costs"]
    orders = len(ep1["trades"])
    days_inv, second_halt = ep1["days_invested"], False
    if ep1["halted"]:
        halts.append({"episode": 1, "halt_signal_date": ep1["halted"],
                      "liquidation_date": ep1["liq_date"],
                      "cash_at_halt": round(ep1["cash_at_halt"], 2)})
        cash1 = ep1["cash_at_halt"]
        eligible = (dt.date.fromisoformat(ep1["liq_date"]) +
                    dt.timedelta(days=90)).isoformat()
        dec_after = [d for d in eval_dates[1:] if d >= eligible]
        restart_info = {"halt_signal_date": ep1["halted"],
                        "liquidation_date": ep1["liq_date"],
                        "cash_at_halt": round(cash1, 2),
                        "eligible_date": eligible,
                        "restart_decision_date": None,
                        "restart_date": None,
                        "restart_balance": round(cash1, 2),
                        "episode2_floor": round(0.85 * cash1, 2)}
        if dec_after:
            dec_date = dec_after[0]
            exec_days = [d for d in book.dates if dec_date < d <= end]
            if exec_days:
                restart_info["restart_decision_date"] = dec_date
                restart_info["restart_date"] = exec_days[0]
                i = eval_dates.index(dec_date)
                ep2_evals = [dec_date] + [d for d in eval_dates[1:]
                                          if d > dec_date]
                ep2_targets = [targets[i]] + [targets[eval_dates.index(d)]
                                              for d in ep2_evals[1:]]
                ep2 = simulate(book, ep2_evals, ep2_targets,
                               exec_days[0], end, cash1, 0.85 * cash1)
                for d, v in ep2["curve"]:
                    curve_map[d] = v
                final, costs = ep2["final"], costs + ep2["costs"]
                orders += len(ep2["trades"])
                days_inv += ep2["days_invested"]
                if ep2["halted"]:
                    second_halt = True
                    halts.append({"episode": 2,
                                  "halt_signal_date": ep2["halted"],
                                  "liquidation_date": ep2["liq_date"],
                                  "cash_at_halt": round(ep2["cash_at_halt"], 2)})
    # Assemble the full-window curve: episode curves where they exist;
    # on days after a liquidation (sit-out, or post-terminal-halt) the
    # pot sits in cash at that halt's proceeds.
    restart_date = restart_info.get("restart_date") if restart_info else None
    curve = []
    for d in days:
        if d in curve_map:
            curve.append([d, curve_map[d]])
            continue
        v = START_CASH
        for h in halts:
            if d >= h["liquidation_date"]:
                v = h["cash_at_halt"]
        curve.append([d, round(v, 4)])
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    years = (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days / 365.25
    return {"final": round(final, 2),
            "cagr_pct": round(((final / START_CASH) ** (1 / years) - 1) * 100, 2),
            "max_dd_pct": round(maxdd * 100, 2),
            "costs": round(costs, 2), "orders": orders,
            "halts": halts, "restart": restart_info,
            "second_halt": second_halt,
            "time_in_market_pct": round(100.0 * days_inv / len(days), 1),
            "curve": curve}


# ------------------------------------------------------------- cadence dates
def cadence_dates(book, cadence, start, end):
    """In-window cadence decision dates per the SPEC uniform definition."""
    days = [d for d in book.dates if start <= d <= end]
    if cadence == "daily":
        return days
    out, seen = [], set()
    if cadence in ("weekly", "biweekly"):
        weeks = []
        for d in days:
            iso = dt.date.fromisoformat(d).isocalendar()
            key = (iso[0], iso[1])
            if key not in seen:
                seen.add(key)
                weeks.append(d)
        if cadence == "weekly":
            return weeks
        return weeks[::2]
    for d in days:
        if cadence == "monthly":
            key = d[:7]
        elif cadence == "quarterly":
            key = (d[:4], (int(d[5:7]) - 1) // 3)
            if d[5:7] not in ("01", "04", "07", "10"):
                continue
        elif cadence == "semiannual":
            key = (d[:4], (int(d[5:7]) - 1) // 6)
            if d[5:7] not in ("01", "07"):
                continue
        elif cadence == "annual":
            key = d[:4]
            if d[5:7] != "01":
                continue
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def month_end_days(book, start, end):
    out, seen = [], set()
    for d in book.dates:
        if start <= d <= end:
            seen.add(d[:7])
    for m in sorted(seen):
        dd = [d for d in book.dates if d[:7] == m and start <= d <= end]
        if dd:
            out.append(dd[-1])
    return out


def original_form_run(book, sig, start, end):
    """The original engine's form: entry check = last month-end on or
    before the window start; then month-end evaluations in-window.
    His-rules floor (single episode, halt ends the run)."""
    entry_cands = month_end_days(book, book.dates[0], start)
    entry = entry_cands[-1]
    evals = [entry] + [d for d in month_end_days(book, start, end)
                       if d != entry]
    targets = [sig.target(d) for d in evals]
    r = simulate(book, evals, targets, start, end, START_CASH, 85.0)
    return r


def spy_buyhold(book, start, end):
    days = [d for d in book.dates if start <= d <= end]
    first, last = days[0], days[-1]
    o = book.bar(first)["o"]
    sh = (START_CASH / 1.001) / o
    buy_cost = START_CASH - sh * o
    val = sh * book.by_date[last]["c"]
    sell_cost = val * 0.001 + 0.01
    peak, maxdd = -1.0, 0.0
    for d in days:
        v = sh * book.bar(d)["c"]
        peak = max(peak, v)
        maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(val - sell_cost, 2),
            "max_dd_pct": round(maxdd * 100, 2)}


# --------------------------------------------------------------------- main
def main():
    bars = load_spy_bars()
    book = Book(bars)
    rows = load_shiller()
    sig = FedSignal(rows)
    months = sorted(rows)
    print(f"SPY bars: {bars[0]['d']} -> {bars[-1]['d']} ({len(bars)})")
    print(f"Shiller months (live file): {months[0]} -> {months[-1]} "
          f"({len(months)})")

    # ---------------- integrity: original form, W6's verified finals
    integrity = {"status": "reproduced",
                 "original_finals": {"CONT": 196.05, "VAL": 117.37,
                                     "DECADE": 229.92},
                 "reproduced_finals": {}}
    for name, (ws, we) in (("CONT", ("2019-01-01", "2026-11-20")),
                           ("VAL", ("2023-01-01", "2026-11-20")),
                           ("DECADE", DECADE)):
        r = original_form_run(book, sig, ws, we)
        integrity["reproduced_finals"][name] = r["final"]
        pub = integrity["original_finals"][name]
        ok = abs(r["final"] - pub) < 0.005
        print(f"INTEGRITY {name}: reproduced=${r['final']:,.2f} "
              f"published=${pub:,.2f} match={ok} halted={r['halted']}")
        if not ok:
            integrity["status"] = "FAILED"
    if integrity["status"] == "FAILED":
        raise SystemExit("INTEGRITY FAILED — sweep aborted")

    spy = spy_buyhold(book, *DECADE)
    print(f"SPY DECADE buy-hold: ${spy['final']:,.2f} maxDD {spy['max_dd_pct']}%")

    # ---------------- the sweep
    os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)
    cells = {}
    for cad in CADENCES:
        dec_dates = cadence_dates(book, cad, *DECADE)
        evals = [DECADE[0]] + [d for d in dec_dates if d != DECADE[0]]
        targets = [sig.target(d) for d in evals]
        r = run_v9(book, evals, targets, *DECADE)
        # placebos: original circular-shift design on this cell's targets
        n = len(targets)
        placebo_finals = {}
        for seed in PLACEBO_SEEDS:
            rng = random.Random(seed)
            shift = rng.randrange(1, n)
            shifted = [targets[(i + shift) % n] for i in range(n)]
            pr = run_v9(book, evals, shifted, *DECADE)
            placebo_finals[str(seed)] = pr["final"]
        beaten = sum(1 for v in placebo_finals.values() if v < r["final"])
        cell = {"final": r["final"], "cagr_pct": r["cagr_pct"],
                "max_dd_pct": r["max_dd_pct"], "halts": len(r["halts"]),
                "restart": bool(r["restart"] and
                                r["restart"].get("restart_date")),
                "second_halt": r["second_halt"], "costs": r["costs"],
                "orders": r["orders"], "placebo_beaten": beaten,
                "placebo_note": "Original circular-shift placebo design "
                                "(seeds 1..20) applied to this cadence's "
                                "target sequence, under v9 protections."}
        cells[cad] = cell
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump({"slug": "folklore-f3-fedmodel", "cadence": cad,
                       "window": {"start": DECADE[0], "end": DECADE[1]},
                       "start_cash": START_CASH,
                       "final": r["final"], "cagr_pct": r["cagr_pct"],
                       "max_dd_pct": r["max_dd_pct"], "costs": r["costs"],
                       "orders": r["orders"],
                       "time_in_market_pct": r["time_in_market_pct"],
                       "spy_final": spy["final"],
                       "spy_max_dd_pct": spy["max_dd_pct"],
                       "halts": r["halts"], "restart": r["restart"],
                       "second_halt": r["second_halt"],
                       "n_evaluations": n,
                       "placebo_beaten": beaten,
                       "placebo_finals": placebo_finals,
                       "equity_curve": r["curve"]}, f, indent=1)
        print(f"{cad:11s}: final=${r['final']:,.2f} CAGR {r['cagr_pct']}% "
              f"maxDD {r['max_dd_pct']}% costs ${r['costs']} "
              f"orders {r['orders']} halts {len(r['halts'])} "
              f"restart {cell['restart']} 2nd_halt {r['second_halt']} "
              f"time-in {r['time_in_market_pct']}% "
              f"placebo beaten {beaten}/20", flush=True)

    money = [c for c in CADENCES
             if cells[c]["final"] > spy["final"] and
             cells[c]["placebo_beaten"] is not None and
             cells[c]["placebo_beaten"] >= 10]
    results = {
        "slug": "folklore-f3-fedmodel",
        "area": "SPY timing/switching — folklore timers (W6)",
        "area_source": "backtests/v10-retest/SPEC.md, worker batch W6",
        "native_cadence": "monthly",
        "original_cadence_foreign": False,
        "original_cadence_note": "Original test ran the same monthly form "
                                 "— native cadence, not foreign. (Sweep "
                                 "monthly cell evaluates on the first "
                                 "trading day of each month per the SPEC's "
                                 "uniform cadence definition; the original "
                                 "evaluated on month-end closes — same "
                                 "M-1 published row governs both.)",
        "integrity": integrity,
        "decade_spy_final": spy["final"],
        "decade_spy_max_dd_pct": spy["max_dd_pct"],
        "cells": cells,
        "money_cadences": money,
        "verdict_area": "NO GROUND",
        "verdict_change": "None — the cadence sweep confirms W6's NO "
                          "GROUND verdict at every tempo: no cadence "
                          "beats SPY on the decade, so there are no money "
                          "cadences.",
        "data_note": "Yield/earnings from the cached LIVE Shiller file "
                     "in this folder (data/ie_data_live_shillerdata.xls, "
                     "md5-identical to the original test's file); the "
                     "frozen Yale vintage was NOT used. SPY bars from "
                     "the program shared full-range cache "
                     "backtests/v7/long-hold/data/pxfull_SPY.json "
                     "(read-only; the F-3 folder's own px_SPY.json pull "
                     "starts 2017-06-01 and cannot cover the decade "
                     "start). Shiller data is monthly at source: at "
                     "every evaluation the freshest published row (month "
                     "M-1 for an evaluation in month M) governs.",
        "pre_restructure_area_runs_w6": {
            "LONG": {"final": 514.45, "spy_final": 822.94},
            "DECADE": {"final": 229.92, "spy_final": 367.80},
            "CONT": {"final": 196.05, "spy_final": 313.62},
            "VAL": {"final": 117.37, "spy_final": 187.77},
            "verdict": "NO GROUND"},
    }
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("DONE")


if __name__ == "__main__":
    main()
