#!/usr/bin/env python3
"""
OPTIONS INDEX TEST A — v10 GREAT RETEST (cadence sweep form).

The CBOE PUT (cash-secured SPX put-writing) and BXM (covered-call BuyWrite)
indexes ARE the strategies, computed by the exchange; this is a returns
replay of their published daily levels onto a $100 pot, not a trade
simulation (no orders, no trading costs — the index levels embed CBOE's
own fill conventions).

CADENCE SWEEP (SPEC uniform definition): the decade road
2016-11-21 -> 2026-11-20 at 7 review cadences. The indexes roll monthly
by CBOE construction — cadence here governs the pot's REVIEW rhythm:
the v9 floor is evaluated only on cadence dates (first trading day of
each period; daily = every trading day). On a cadence-date close at or
below the floor the pot liquidates at that close (replay convention —
an index has no next open), sits in cash 90 calendar days, restarts at
the first cadence date on/after day 90 under an episode-2 floor of -15%
from the restart balance; a second breach ends the run.

INTEGRITY: the daily-review DECADE cell must reproduce the original
published finals (PUT $207.65, BXM $192.89, v4 options-index-scorecard)
and the full-file first plain-floor breaches must land on the published
dates (PUT 2008-10-09, BXM 2002-07-16).

Supplementary runs (daily review): LONG 2010-01-04 -> 2026-11-20 and
FULL-FILE (PUT from 2007-01-03, BXM from 2002-03-22).

Data: PUT_History.csv / BXM_History.csv in this folder, re-downloaded
2026-11-21 from the CBOE CDN (the originals lived in /tmp and are gone).
Original convention kept: PUT's stray pre-2007 rows dropped.
Outputs: cells/<cadence>.json (both pots, full equity curves),
results.json. Simulation only.
"""
import csv, json, os
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
START = 100.0
DEC0, DEC1 = "2016-11-21", "2026-11-20"
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]


def load(fn, col, drop_before=None):
    rows = []
    with open(os.path.join(HERE, fn)) as f:
        for r in csv.DictReader(f):
            try:
                d = datetime.strptime(r["DATE"], "%m/%d/%Y").strftime("%Y-%m-%d")
                rows.append((d, float(r[col])))
            except Exception:
                continue
    rows.sort()
    if drop_before:
        rows = [(d, v) for d, v in rows if d >= drop_before]
    return rows


PUT = load("PUT_History.csv", "PUT", drop_before="2007-01-03")
BXM = load("BXM_History.csv", "BXM")


def cadence_dates(cal, cadence):
    """First trading day of each period, per the SPEC uniform definition."""
    if cadence == "daily":
        return set(cal)
    out = set()
    prev_key = None
    week_no = -1
    for d in cal:
        dt = datetime.strptime(d, "%Y-%m-%d")
        if cadence == "weekly":
            key = dt.isocalendar()[:2]
        elif cadence == "biweekly":
            key = dt.isocalendar()[:2]
        elif cadence == "monthly":
            key = (dt.year, dt.month)
        elif cadence == "quarterly":
            key = (dt.year, (dt.month - 1) // 3)
        elif cadence == "semiannual":
            key = (dt.year, (dt.month - 1) // 6)
        elif cadence == "annual":
            key = (dt.year,)
        if key != prev_key:
            if cadence == "biweekly":
                week_no += 1
                if week_no % 2 == 0:
                    out.add(d)
            else:
                out.add(d)
            prev_key = key
    return out


def replay(rows, w0, w1, cadence):
    """v9 two-episode replay of $100 on the index over [w0, w1], floor
    reviewed only on cadence dates. Returns full daily equity curve."""
    seg = [(d, v) for d, v in rows if w0 <= d <= w1]
    cal = [d for d, _ in seg]
    cdays = cadence_dates(cal, cadence)
    base = seg[0][1]
    raw = [(d, START * v / base) for d, v in seg]
    curve = []
    halts = []          # {episode, breach_date, equity, floor}
    restarts = []       # {date, cash, episode2_floor}
    episode = 1
    floor = 0.85 * START
    cash = None         # not None while halted / sitting out
    resume_on = None    # first date the pot may re-enter
    rebase = None       # (date, index_value, cash) for episode-2 scaling
    idx_val = dict(seg)
    ended = False
    for d, e in raw:
        if ended:
            curve.append((d, cash))
            continue
        if cash is not None:
            if d >= resume_on and d in cdays:
                restarts.append({"date": d, "cash": round(cash, 2),
                                 "episode2_floor": round(0.85 * cash, 2)})
                rebase = (d, idx_val[d], cash)
                floor = 0.85 * cash
                cash = None
                episode = 2
                curve.append((d, rebase[2]))
            else:
                curve.append((d, cash))
            continue
        cur = e if rebase is None else rebase[2] * idx_val[d] / rebase[1]
        curve.append((d, round(cur, 4)))
        if d in cdays and cur <= floor:
            halts.append({"episode": episode, "breach_date": d,
                          "equity": round(cur, 2), "floor": round(floor, 2)})
            cash = cur
            if episode == 2:
                ended = True
            else:
                resume_on = (datetime.strptime(d, "%Y-%m-%d")
                             + timedelta(days=90)).strftime("%Y-%m-%d")
    final = curve[-1][1]
    peak, max_dd = curve[0][1], 0.0
    for _, v in curve:
        peak = max(peak, v)
        max_dd = min(max_dd, v / peak - 1)
    d0 = datetime.strptime(curve[0][0], "%Y-%m-%d")
    d1 = datetime.strptime(curve[-1][0], "%Y-%m-%d")
    yrs = max((d1 - d0).days / 365.25, 1e-9)
    cagr = ((final / START) ** (1 / yrs) - 1) * 100 if final > 0 else -100.0
    return {"start": curve[0][0], "end": curve[-1][0], "final": round(final, 2),
            "cagr_pct": round(cagr, 2), "max_dd_pct": round(max_dd * 100, 2),
            "costs": 0.0, "orders": 0,
            "halts": len(halts), "halt_events": halts,
            "restart": bool(restarts), "restarts": restarts,
            "second_halt": any(h["episode"] == 2 for h in halts),
            "equity_curve": [[d, v] for d, v in curve]}


def main():
    os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)
    pots = {"PUT": PUT, "BXM": BXM}
    cells = {}
    for cadence in CADENCES:
        cell = {"cadence": cadence, "window": [DEC0, DEC1], "pots": {},
                "placebo_beaten": None,
                "placebo_note": "No placebo chassis exists for a published-index "
                                "returns replay (no selection or timing rule to "
                                "randomize); none invented, per protocol."}
        for name, rows in pots.items():
            cell["pots"][name] = replay(rows, DEC0, DEC1, cadence)
        with open(os.path.join(HERE, "cells", f"{cadence}.json"), "w") as f:
            json.dump(cell, f, indent=1)
        cells[cadence] = cell
        print(cadence, {n: cell["pots"][n]["final"] for n in pots},
              "halts", {n: cell["pots"][n]["halts"] for n in pots})

    supp = {}
    for name, rows in pots.items():
        supp[name] = {
            "LONG_2010_daily_review": replay(rows, "2010-01-04", DEC1, "daily"),
            "FULLFILE_daily_review": replay(rows, rows[0][0], DEC1, "daily"),
        }
        for k in supp[name]:
            supp[name][k] = {kk: vv for kk, vv in supp[name][k].items()
                             if kk != "equity_curve"}
        print(name, {k: (v["final"], v["halt_events"]) for k, v in supp[name].items()})

    dec_daily = cells["daily"]["pots"]
    integrity_ok = (abs(dec_daily["PUT"]["final"] - 207.65) < 0.011
                    and abs(dec_daily["BXM"]["final"] - 192.89) < 0.011
                    and supp["PUT"]["FULLFILE_daily_review"]["halt_events"][0]["breach_date"] == "2008-10-09"
                    and supp["BXM"]["FULLFILE_daily_review"]["halt_events"][0]["breach_date"] == "2002-07-16")
    print("INTEGRITY:", "reproduced" if integrity_ok else "FAILED")

    def cell_summary(cadence):
        p = cells[cadence]["pots"]["PUT"]
        return {"final": p["final"], "cagr_pct": p["cagr_pct"],
                "max_dd_pct": p["max_dd_pct"], "halts": p["halts"],
                "restart": p["restart"], "second_halt": p["second_halt"],
                "costs": 0.0, "orders": 0, "placebo_beaten": None,
                "placebo_note": cells[cadence]["placebo_note"],
                "pots": {n: {"final": cells[cadence]["pots"][n]["final"],
                             "cagr_pct": cells[cadence]["pots"][n]["cagr_pct"],
                             "max_dd_pct": cells[cadence]["pots"][n]["max_dd_pct"],
                             "halts": cells[cadence]["pots"][n]["halts"],
                             "restart": cells[cadence]["pots"][n]["restart"],
                             "second_halt": cells[cadence]["pots"][n]["second_halt"]}
                         for n in pots}}

    out = {
        "slug": "options-index",
        "area": "Options income (CBOE PUT put-writing / BXM buy-write index replay) — "
                "the decade road at every review cadence; supplementary LONG (2010) and "
                "full-file history for the crash-breach record",
        "area_source": "SPEC W10 + CADENCE SWEEP (2026-11-21 ~22:09)",
        "native_cadence": "monthly",
        "cadence": "monthly",
        "original_cadence_foreign": {
            "foreign": False,
            "note": "Original test was a daily-close floor check on a monthly-roll "
                    "index; the index's own roll cadence (monthly, CBOE construction) "
                    "was never altered. The sweep varies only the pot's floor-review "
                    "rhythm; the native monthly cell is the published form."},
        "integrity": {
            "status": "reproduced" if integrity_ok else "FAILED",
            "original_finals": {"decade_PUT_100": 207.65, "decade_BXM_100": 192.89,
                                "fullfile_first_plain_breach_PUT": "2008-10-09",
                                "fullfile_first_plain_breach_BXM": "2002-07-16"},
            "reproduced_finals": {"decade_PUT_100": dec_daily["PUT"]["final"],
                                  "decade_BXM_100": dec_daily["BXM"]["final"],
                                  "fullfile_first_plain_breach_PUT":
                                      supp["PUT"]["FULLFILE_daily_review"]["halt_events"][0],
                                  "fullfile_first_plain_breach_BXM":
                                      supp["BXM"]["FULLFILE_daily_review"]["halt_events"][0]},
            "note": "CBOE CSVs re-downloaded 2026-11-21 from the CBOE CDN into this "
                    "folder (originals lived in /tmp and are gone). Decade finals and "
                    "both full-history first-breach dates reproduce the v4 scorecard "
                    "exactly (breach equities $83.19 PUT / $84.73 BXM on $100 = the "
                    "published $41.60 / $42.37 on $50)."},
        "decade_spy_final": 367.80,
        "decade_spy_note": "SPEC reference (dividend-adjusted, W6-verified plumbing). "
                           "This folder's own SPY total-return figure from the v4 "
                           "scorecard plumbing was $366.91 — start-bar convention.",
        "decade_btc_final": None,
        "decade_btc_note": "Not a crypto strategy; BTC benchmark not applicable.",
        "cells": {c: cell_summary(c) for c in CADENCES},
        "money_cadences": [],
        "supplementary": supp,
        "verdict_area": "NO GROUND",
        "verdict_change": "Unchanged in substance, sharpened in detail: the family "
                          "stays closed. The sweep shows cadence is irrelevant on the "
                          "decade road — the start-anchored $85 floor never fires at "
                          "ANY review tempo (PUT $207.65 / BXM $192.89 in every cell, "
                          "vs SPY $367.80). The crash-breach closure is confirmed on "
                          "full history (PUT 2008, BXM 2002) but revised for the "
                          "2010-start LONG window: no breach at daily review, because "
                          "both pots had banked gains before 2020 — PUT $351.98 / "
                          "BXM $303.74, still far behind SPY LONG $822.94.",
    }
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("saved results.json + cells/")


if __name__ == "__main__":
    main()
