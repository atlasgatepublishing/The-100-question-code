#!/usr/bin/env python3
"""
THE GREAT RETEST (v10) — re-macro-regime cadence sweep.

Strategy: FOUR-BOX MACRO-REGIME TILT (Bridgewater shadow, long-only).
Regime from Philly Fed Real-Time Data Set vintages (PCPI / IPT), classified
exactly as the original v7 engine (within-vintage YoY now vs YoY 6
observation-months earlier, for growth (IP) and inflation (CPI)); fixed
four-box weights over SPY/TLT/GLD/DBC. Point-in-time: a decision for month M
uses ONLY the vintage column for month M.

TIMER CADENCE TREATMENT (SPEC uniform rule): cadence = signal-evaluation
frequency. The macro series publishes MONTHLY: a new vintage (and therefore
a possibly new classification) exists only at each month-end decision. At
any evaluation date D the signal in force is the classification from the
latest completed month-end decision (latest month M whose last trading day
is <= D). Faster cadences (daily/weekly/biweekly) therefore re-read the
SAME vintage between month-ends — they can only re-balance to the in-force
target weights (drift correction); they can never see a newer regime than
the monthly form. Slower cadences (quarterly/semi-annual/annual) evaluate
on the SPEC dates (first trading day of the period) and apply the latest
completed month-end classification, then hold it unreviewed until the next
evaluation. Monthly cell: SPEC date (first trading day of month), signal =
the just-completed month-end vintage — fills land one trading day after
the original engine's month-end-decision fills; that one-day shift is the
only difference from the original form.

Costs: program standard 0.10%/side + $0.01 per sell order (original engine's
own cost code). Protection: v9 — plain -15% floor from the EPISODE's
starting balance, checked on every daily close; on breach, liquidate at
next open, sit in cash 90 calendar days, restart at the next regular
cadence evaluation under an episode-2 floor of -15% from the restart
balance; a second halt ends the run.

Placebos: the original's own design — permute the window's monthly weight
vectors across its decision months (same multiset of regime allocations,
shuffled timing), seeds 1..20, run through the identical cell mechanics
(including v9 protection). placebo_beaten = seeds the strategy out-earns.

Road: DECADE 2016-11-21 -> 2026-11-20 for every cell. Also runs the
champion-comparison windows (LONG 2010-01-04, CONT 2019-01-02, VAL
2023-01-03, all -> 2026-11-20) at the native monthly cadence.
"""
import json, math, os, random, statistics, sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# Reuse the original engine's data machinery verbatim (vintage parsing,
# classification, price loading conventions) — imported from the integrity
# copy so the classification code is literally the original's.
import integrity_original as orig

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = orig.ASSETS
WEIGHTS = orig.WEIGHTS
COST_RATE = orig.COST_RATE
SELL_FEE = orig.SELL_FEE
START_CASH = 100.0

# Point the price loader at this folder's retained copies (byte-identical
# copies of the shared backtests/v3/data_etf cache the original used).
orig.PRICE_CACHE = os.path.join(HERE, "prices")
orig.SERIES = {t: orig.load_series(t) for t in ASSETS}
orig.CAL = sorted(orig.SERIES["SPY"].keys())
orig.CAL_IDX = {d: i for i, d in enumerate(orig.CAL)}
CAL = orig.CAL
close_on, open_on = orig.close_on, orig.open_on

END = "2026-11-20"


# ---------------------------------------------------------------- schedule
def month_iter(y0, m0, y1, m1):
    y, m = y0, m0
    while (y, m) <= (y1, m1):
        yield (y, m)
        m += 1
        if m == 13:
            y, m = y + 1, 1


_LTD = {}
for _d in CAL:
    _LTD[_d[:7]] = _d  # CAL is sorted: last write per month = its last trading day


def last_trading_day(y, m):
    return _LTD.get(f"{y:04d}-{m:02d}")


def build_monthly_signal(mat_cpi, mat_ip, first_dec, last_dec):
    """decision_month 'YYYY-MM' -> weights, using the original classify()."""
    sig = {}
    for (y, m) in month_iter(*first_dec, *last_dec):
        g, _ = orig.classify(mat_ip, y, m)
        i, _ = orig.classify(mat_cpi, y, m)
        sig[f"{y:04d}-{m:02d}"] = dict(WEIGHTS[(g, i)])
    return sig


import bisect


def _timeline(sig):
    months = sorted(sig.keys())
    return months, [_LTD[m] for m in months]


def signal_in_force(sig, date, timeline=None):
    """Weights from the latest month-end decision completed by `date`."""
    months, ltds = timeline if timeline is not None else _timeline(sig)
    i = bisect.bisect_right(ltds, date) - 1
    return sig[months[i]] if i >= 0 else None


# ---------------------------------------------------------------- cadences
def cadence_dates(cadence, start, end):
    days = [d for d in CAL if start <= d <= end]
    if cadence == "daily":
        return set(days)
    out = set()
    if cadence == "weekly" or cadence == "biweekly":
        weeks = {}
        for d in days:
            iso = datetime.strptime(d, "%Y-%m-%d").isocalendar()
            weeks.setdefault((iso[0], iso[1]), []).append(d)
        keys = sorted(weeks)
        if cadence == "weekly":
            chosen = keys
        else:  # every second week, anchored on the first week of the window
            chosen = keys[::2]
        for k in chosen:
            out.add(min(weeks[k]))
    elif cadence == "monthly":
        bym = {}
        for d in days:
            bym.setdefault(d[:7], []).append(d)
        for ds in bym.values():
            out.add(min(ds))
    elif cadence == "quarterly":
        byq = {}
        for d in days:
            q = (int(d[5:7]) - 1) // 3
            byq.setdefault((d[:4], q), []).append(d)
        for ds in byq.values():
            out.add(min(ds))
    elif cadence == "semiannual":
        byh = {}
        for d in days:
            h = 0 if int(d[5:7]) <= 6 else 1
            byh.setdefault((d[:4], h), []).append(d)
        for ds in byh.values():
            out.add(min(ds))
    elif cadence == "annual":
        byy = {}
        for d in days:
            byy.setdefault(d[:4], []).append(d)
        for ds in byy.values():
            out.add(min(ds))
    else:
        raise ValueError(cadence)
    return out


# ---------------------------------------------------------------- engine
def simulate(start, end, sig, cadence):
    """sig: decision_month -> weights (real or placebo-permuted)."""
    days = [d for d in CAL if start <= d <= end]
    eval_days = cadence_dates(cadence, start, end)
    timeline = _timeline(sig)
    cash = START_CASH
    shares = {t: 0.0 for t in ASSETS}
    orders = 0
    total_costs = 0.0
    curve = []
    halts = []      # {episode, breach_date, liquidated_date, balance_after}
    restarts = []   # {date, balance}
    episode = 1
    ep_start_balance = START_CASH
    floor = 0.85 * ep_start_balance
    state = "active"          # active | cash-wait | done
    restart_eligible = None   # first date a restart evaluation may occur
    pending = signal_in_force(sig, days[0], timeline)  # invested from day one

    def equity(date, fn):
        eq = cash
        for t in ASSETS:
            if shares[t] > 0:
                p = fn(t, date)
                if p:
                    eq += shares[t] * p
        return eq

    def rebalance(date, targets):
        nonlocal cash, orders, total_costs
        eq_open = equity(date, open_on)
        for t in ASSETS:
            tgt = targets.get(t, 0.0) * eq_open
            cur = shares[t] * open_on(t, date)
            if cur - tgt > 0.01 and shares[t] > 0:
                val = min(cur - tgt, cur)
                cost = val * COST_RATE + SELL_FEE
                cash += val - cost
                shares[t] -= val / open_on(t, date)
                if shares[t] < 1e-9:
                    shares[t] = 0.0
                orders += 1
                total_costs += cost
        buys = []
        for t in ASSETS:
            tgt = targets.get(t, 0.0) * eq_open
            cur = shares[t] * open_on(t, date)
            if tgt - cur > 0.01:
                buys.append((t, tgt - cur))
        tot = sum(v for _, v in buys)
        if tot > 0:
            scale = min(1.0, cash / (tot * (1 + COST_RATE)))
            for t, diff in buys:
                val = diff * scale
                if val < 0.01:
                    continue
                cost = val * COST_RATE
                cash -= val + cost
                shares[t] += val / open_on(t, date)
                orders += 1
                total_costs += cost

    def liquidate(date, fn):
        nonlocal cash, orders, total_costs
        for t in ASSETS:
            if shares[t] > 0:
                val = shares[t] * fn(t, date)
                cost = val * COST_RATE + SELL_FEE
                cash += val - cost
                total_costs += cost
                orders += 1
                shares[t] = 0.0

    for di, d in enumerate(days):
        if state == "done":
            curve.append((d, cash))
            continue
        # execute pending rebalance at today's open
        if pending is not None and state == "active":
            rebalance(d, pending)
            pending = None
        eq_close = equity(d, close_on)
        curve.append((d, eq_close))
        # --- v9 floor check on the daily close ---
        if state == "active" and eq_close <= floor:
            if di + 1 < len(days):
                nd = days[di + 1]
                liquidate(nd, open_on)
                liq_date, bal = nd, cash
            else:
                liquidate(d, close_on)
                liq_date, bal = d, cash
            halts.append({"episode": episode, "breach_date": d,
                          "liquidated_date": liq_date,
                          "balance_after": round(bal, 2)})
            if episode == 1:
                episode = 2
                state = "cash-wait"
                restart_eligible = (datetime.strptime(liq_date, "%Y-%m-%d")
                                    + timedelta(days=90)).strftime("%Y-%m-%d")
                pending = None
                continue
            else:
                state = "done"
                # rewrite curve tail at cash value from liquidation on
                curve = [(dd, vv if dd < liq_date else bal) for dd, vv in curve]
                continue
        # --- cadence evaluation at today's close ---
        if d in eval_days and di + 1 < len(days):
            if state == "active":
                w = signal_in_force(sig, d, timeline)
                if w is not None:
                    pending = w
            elif state == "cash-wait" and d >= restart_eligible:
                w = signal_in_force(sig, d, timeline)
                if w is not None:
                    # restart fills at next open; episode-2 floor from the
                    # restart (all-cash) balance
                    ep_start_balance = cash
                    floor = 0.85 * ep_start_balance
                    restarts.append({"eval_date": d,
                                     "fill_date": days[di + 1],
                                     "balance": round(cash, 2)})
                    state = "active"
                    pending = w
    final = curve[-1][1] if curve else START_CASH
    return {"final": final, "curve": curve, "orders": orders,
            "costs": total_costs, "halts": halts, "restarts": restarts}


def metrics(final, curve, start):
    yrs = (datetime.strptime(curve[-1][0], "%Y-%m-%d")
           - datetime.strptime(start, "%Y-%m-%d")).days / 365.25
    cagr = (final / START_CASH) ** (1 / yrs) - 1 if yrs > 0 and final > 0 else 0.0
    peak, maxdd = -1e18, 0.0
    for _, eq in [(start, START_CASH)] + curve:
        peak = max(peak, eq)
        if peak > 0:
            maxdd = min(maxdd, eq / peak - 1.0)
    return round(cagr * 100, 2), round(maxdd * 100, 2)


def run_cell(mat_cpi, mat_ip, cadence, start, end, first_dec, last_dec,
             placebos=True):
    sig = build_monthly_signal(mat_cpi, mat_ip, first_dec, last_dec)
    res = simulate(start, end, sig, cadence)
    cagr, maxdd = metrics(res["final"], res["curve"], start)
    cell = {"final": round(res["final"], 2), "cagr_pct": cagr,
            "max_dd_pct": maxdd,
            "halts": len(res["halts"]),
            "halt_records": res["halts"],
            "restart": bool(res["restarts"]),
            "restart_records": res["restarts"],
            "second_halt": len(res["halts"]) >= 2,
            "costs": round(res["costs"], 2), "orders": res["orders"],
            "equity_curve": [[d, round(v, 2)] for d, v in res["curve"]]}
    if placebos:
        months = sorted(sig.keys())
        base = [sig[m] for m in months]
        twin_finals = []
        for seed in range(1, 21):
            rng = random.Random(seed)
            perm = base[:]
            rng.shuffle(perm)
            psig = {m: w for m, w in zip(months, perm)}
            pres = simulate(start, end, psig, cadence)
            twin_finals.append(round(pres["final"], 2))
        cell["placebo_beaten"] = sum(1 for f in twin_finals
                                     if res["final"] > f)
        cell["placebo_twin_finals"] = twin_finals
        cell["placebo_median"] = round(statistics.median(twin_finals), 2)
    else:
        cell["placebo_beaten"] = None
    return cell


def spy_buy_hold(start, end):
    return round(orig.buy_hold({"SPY": 1.0}, start, end), 2)


def main():
    mat_cpi = orig.load_matrix("CPI")
    mat_ip = orig.load_matrix("IP")
    decade = ("2016-11-21", END)
    spy_dec = spy_buy_hold(*decade)
    print(f"DECADE SPY buy-hold: ${spy_dec:.2f} (SPEC reference $367.80)")

    cells = {}
    for cad in ["daily", "weekly", "biweekly", "monthly", "quarterly",
                "semiannual", "annual"]:
        cell = run_cell(mat_cpi, mat_ip, cad, decade[0], decade[1],
                        (2016, 10), (2026, 10))
        cells[cad] = cell
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump(cell, f, indent=1)
        print(f"{cad:11s} final=${cell['final']:8.2f} CAGR={cell['cagr_pct']:+.2f}% "
              f"maxDD={cell['max_dd_pct']:.2f}% orders={cell['orders']} "
              f"costs=${cell['costs']:.2f} halts={cell['halts']} "
              f"placebo {cell.get('placebo_beaten')}/20")

    # champion-comparison windows at native (monthly) cadence
    champ = {}
    for label, start, fd in [("LONG", "2010-01-04", (2009, 12)),
                             ("CONT", "2019-01-02", (2018, 12)),
                             ("VAL", "2023-01-03", (2022, 12))]:
        c = run_cell(mat_cpi, mat_ip, "monthly", start, END, fd, (2026, 10),
                     placebos=(label != "LONG"))
        champ[label] = {"start": start, "end": END,
                        "final": c["final"], "cagr_pct": c["cagr_pct"],
                        "max_dd_pct": c["max_dd_pct"], "halts": c["halts"],
                        "restart": c["restart"],
                        "second_halt": c["second_halt"],
                        "costs": c["costs"], "orders": c["orders"],
                        "placebo_beaten": c.get("placebo_beaten"),
                        "spy_final": spy_buy_hold(start, END)}
        with open(os.path.join(HERE, "cells", f"monthly-{label.lower()}.json"), "w") as f:
            json.dump(c, f, indent=1)
        print(f"monthly {label:5s} final=${c['final']:.2f} SPY=${champ[label]['spy_final']:.2f} "
              f"placebo {c.get('placebo_beaten')}/20 halts={c['halts']}")

    money = [c for c, cell in cells.items()
             if cell["final"] > spy_dec
             and cell.get("placebo_beaten") is not None
             and cell["placebo_beaten"] > 10]
    out = {
        "slug": "re-macro-regime",
        "area": "Regime allocation (timer scoring) — four-box macro-regime tilt over SPY/TLT/GLD/DBC, judged on return and drawdown",
        "area_source": "SPEC W8: 'Macro-regime = regime allocation (timer scoring; point-in-time vintage data as the original)'; original spec research/v7-completeness/firm-reverse-engineering.md section 4.3",
        "cadence": "monthly",
        "native_cadence": "monthly (publication rhythm of the Philly Fed vintage CPI/IP releases; the original decided at each month-end close on that month's vintage)",
        "original_cadence_foreign": False,
        "original_cadence_note": "Original test ran the native monthly form; no foreign cadence. Sweep monthly cell uses SPEC first-trading-day evaluation dates with the just-completed month-end vintage, so fills land one trading day after the original form's fills.",
        "timer_cadence_treatment": "Cadence = signal-evaluation frequency. The macro series publishes monthly, so the classification in force at any date is the latest completed month-end vintage decision. Daily/weekly/biweekly evaluations re-read the same vintage (drift-correction rebalances only; no newer regime can be seen). Quarterly/semi-annual/annual evaluations apply the latest completed month-end classification and hold it unreviewed until the next evaluation.",
        "integrity": {
            "status": "reproduced",
            "original_finals": {"CONT_2019_2026": 230.81, "VAL_2023_2026": 137.99,
                                "CONT_spy": 313.62, "VAL_spy": 187.77,
                                "CONT_placebo_beaten": "14/20", "CONT_placebo_median": 200.31,
                                "VAL_placebo_beaten": "5/20", "VAL_placebo_median": 140.94,
                                "gates_promoted": False},
            "reproduced_finals": {"CONT_2019_2026": 230.81, "VAL_2023_2026": 137.99,
                                  "CONT_spy": 313.62, "VAL_spy": 187.77,
                                  "CONT_placebo_beaten": "14/20", "CONT_placebo_median": 200.31,
                                  "VAL_placebo_beaten": "5/20", "VAL_placebo_median": 140.94,
                                  "gates_promoted": False},
            "note": "Original v7 script re-run verbatim from this folder (integrity_original.py; integrity-results.json) against the retained Philly Fed vintage workbooks and the retained price cache copies. Every published number matched to the cent, including both placebo distributions' summary stats and the failed promotion gates.",
        },
        "decade_spy_final": spy_dec,
        "cells": {c: {k: v for k, v in cell.items()
                      if k not in ("equity_curve",)}
                  for c, cell in cells.items()},
        "champion_windows_monthly": champ,
        "champion_reference": {"LONG": 1415.62, "DECADE": 65.89,
                               "CONT": 544.47, "VAL": 288.05,
                               "note": "Champion DECADE $65.89 is the two-halt caveat figure from the lazy-quarterly test, per SPEC."},
        "money_cadences": money,
        "verdict_area": "NO GROUND" if not money else "REAL BUT SMALL",
        "verdict_change": "none — the original program's verdict (not promoted: failed SPY and the shuffled-regime placebo on validation) stands at every cadence" if not money else "PROVISIONAL — see RESULTS.md",
    }
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("money cadences:", money)
    print("DONE")


if __name__ == "__main__":
    main()
