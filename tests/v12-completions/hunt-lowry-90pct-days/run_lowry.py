#!/usr/bin/env python3
"""Lowry 90% Days (hunt-lowry-90pct-days, v12) — SPEC-FROZEN construction.
Four Lowry totals CONSTRUCTED from the program pond stack (pxfull,
~155 survivor-leaning names — NOT the full NYSE list; bias per spec:
flatters stability / understates panic intensity, some true 90% days
will not print -> fewer signals). Split-adjusted price changes
(adjclose diffs); volume split by sign of change.
90% Downside Day: downside vol share >=90% AND points-lost share >=90%.
Armed for 90 calendar days. Confirmation while armed: a 90% Upside Day
or two consecutive 80% Upside Days (both shares >=80%). Entry: SPY at
next session open, all-in; exit at open of first session after the
12-month anniversary. Fresh cycles while holding do not extend.
Native no floor; house = v9 floor during holds (breach -> exit next
open, 90d halt, one restart on a later fresh confirmation; second
breach ends). Placebos: random entry dates matched on count, 12-month
holds, 20 seeds. Program costs."""
import json, os, sys, random, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from timerlib import *
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))

def dplus(ds, days):
    y, m, d = int(ds[:4]), int(ds[5:7]), int(ds[8:10])
    return str(date(y, m, d) + timedelta(days=days))

def build_totals():
    spy = load_stock("SPY")
    dates = [b["d"] for b in spy]
    series = {}
    for p in sorted(glob.glob(os.path.join(STKDATA, "pxfull_*.json"))):
        t = os.path.basename(p)[7:-5]
        if t == "SPY": continue
        bars = load_stock(t)
        series[t] = {b["d"]: b for b in bars}
    totals = []
    for k in range(1, len(dates)):
        d, prev = dates[k], dates[k-1]
        uv = dv = pg = pl = 0.0; n = 0
        for t, m in series.items():
            if d in m and prev in m:
                chg = m[d]["c"] - m[prev]["c"]; vol = m[d]["v"] or 0
                n += 1
                if chg > 0: uv += vol; pg += chg
                elif chg < 0: dv += vol; pl += -chg
        if uv + dv > 0 and pg + pl > 0:
            totals.append({"d": d, "up_vol_share": uv/(uv+dv), "pts_gain_share": pg/(pg+pl), "n": n})
    return spy, totals

def find_entries(totals):
    entries = []  # confirmation dates (signal day index in totals)
    arm_until = None
    prev80 = False
    for i, t in enumerate(totals):
        down90 = t["up_vol_share"] <= 0.10 and t["pts_gain_share"] <= 0.10
        up90 = t["up_vol_share"] >= 0.90 and t["pts_gain_share"] >= 0.90
        up80 = t["up_vol_share"] >= 0.80 and t["pts_gain_share"] >= 0.80
        if down90: arm_until = dplus(t["d"], 90)
        armed = arm_until is not None and t["d"] <= arm_until
        if armed and (up90 or (up80 and prev80)):
            entries.append(t["d"]); arm_until = None; prev80 = False; continue
        prev80 = up80
    return entries

def simulate(spy, entries, house=False, seed_entries=None):
    idx = {b["d"]: i for i, b in enumerate(spy)}
    ents = seed_entries if seed_entries is not None else entries
    # entry executes at open of next session after confirmation date
    execs = []
    for d in ents:
        if d in idx and idx[d] + 1 < len(spy): execs.append(idx[d] + 1)
    execs = sorted(set(execs))
    eq = START; curve = []; costs = 0.0; orders = 0; trades = []
    pos = None; ei = 0
    anchor = START; halts = 0; halt_until_i = -1; ended = False
    ex_i = 0
    for i, b in enumerate(spy):
        if pos is not None:
            exit_due = b["d"] > dplus(spy[ei]["d"], 365)
            if exit_due:
                gross = pos * b["o"]; cst = gross * STK_COST + STK_FEE; costs += cst
                trades.append([spy[ei]["d"], b["d"], round(gross - cst, 2)]); eq = gross - cst; pos = None; orders += 1
        if pos is None and not ended and i > halt_until_i:
            while ex_i < len(execs) and execs[ex_i] < i: ex_i += 1
            if ex_i < len(execs) and execs[ex_i] == i:
                cst = eq * STK_COST; costs += cst; pos = (eq - cst) / b["o"]; ei = i; orders += 1
        val = pos * b["c"] if pos else eq
        if house and pos and not ended and val <= 0.85 * anchor:
            gross = pos * b["c"]; cst = gross * STK_COST + STK_FEE; costs += cst
            eq = gross - cst; pos = None; orders += 1; halts += 1
            trades.append([spy[ei]["d"], b["d"], round(eq, 2)])
            if halts >= 2: ended = True
            else: halt_until_i = i + 63; anchor = eq
            val = eq
        curve.append([b["d"], round(val, 4)])
    if pos is not None:
        gross = pos * spy[-1]["c"]; cst = gross * STK_COST + STK_FEE; costs += cst
        eq = gross - cst; trades.append([spy[ei]["d"], spy[-1]["d"], round(eq, 2)])
        curve[-1][1] = round(eq, 4)
    peak = START; maxdd = 0.0
    for _, v in curve: peak = max(peak, v); maxdd = max(maxdd, 1 - v/peak)
    return {"final": round(eq, 2), "max_dd": round(maxdd, 4), "costs": round(costs, 2),
            "orders": orders, "halts": halts, "trades": trades, "curve": curve}

def main():
    spy, totals = build_totals()
    entries = find_entries(totals)
    res = {"family": "hunt-lowry-90pct-days", "n_names_in_stack": totals[0]["n"] if totals else 0,
           "confirmation_dates_all_history": entries, "roads": {}}
    print("confirmations:", entries, flush=True)
    for road, s0 in ROADS.items():
        rb = slice_road(spy, s0, END)
        ents = [d for d in entries if s0 <= d <= END]
        # simulate on the road slice: rebuild with sliced spy
        rn = simulate(rb, ents)
        rh = simulate(rb, ents, house=True)
        res["roads"][road] = {"native": rn, "house": rh, "hold": hold_final(rb),
                              "n_entries": len(ents), "period_stats_monthly": period_stats(rn["curve"])}
        print(road, "native", rn["final"], "house", rh["final"], "entries", len(ents), flush=True)
    # placebos on LONG: random entry dates, same count
    rb = slice_road(spy, ROADS["LONG"], END)
    ents = [d for d in entries if ROADS["LONG"] <= d <= END]
    beaten = 0; twins = []
    for s in range(1, 21):
        rng = random.Random(700+s)
        cand = [b["d"] for b in rb[:-260]]
        picks = sorted(rng.sample(cand, len(ents))) if ents else []
        rr = simulate(rb, picks)
        twins.append(rr["final"]); beaten += 1 if res["roads"]["LONG"]["native"]["final"] > rr["final"] else 0
    res["placebo_LONG"] = {"beaten_of_20": beaten, "twin_finals": twins}
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("saved")

if __name__ == "__main__":
    main()
