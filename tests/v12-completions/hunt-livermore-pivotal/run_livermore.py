#!/usr/bin/env python3
"""Livermore Pivotal Points (hunt-livermore-pivotal, v12) — SPEC-FROZEN
construction (every piece CONSTRUCTED from Livermore's stated
principles, labeled in RESULTS). Universe: program pond. Market gate:
no longs unless SPY closes above its 200-day average. Pivot: prior
52-week high over bars [t-252, t-21]; ARMED after >=4 weeks (20 bars)
of quiet consolidation below it (all closes <= pivot and >= 0.85x
pivot). Breakout: first close above pivot. Normal-reaction
confirmation: within 10 sessions, no close back below the pivot and a
higher close than the breakout close -> enter at that close.
Sizing from his worked example: probe 40% of target weight, +30%
after a further +5% rise, +30% after a further +5%. Exit: close below
the pivot or -10% from weighted entry, whichever first. Portfolio:
max 5 concurrent, equal target weights (pot/5), candidates ranked by
days-since-arming then breakout strength. $100 pot, program costs
0.10%/side + $0.01 per sell. Native: no floor. House: v9 pot floor.
Placebos (LONG): each name's confirmation dates circularly shifted,
20 seeds."""
import json, os, sys, random, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from timerlib import *

HERE = os.path.dirname(os.path.abspath(__file__))

def name_events(bars):
    """Returns dict date -> (pivot, armed_days, strength) confirmation events."""
    closes = [b["c"] for b in bars]; n = len(bars)
    ev = {}
    state = "idle"; pivot = None; arm_start = None; brk_i = None; brk_close = None
    for t in range(n):
        if t < 252: continue
        if state == "idle":
            piv = max(closes[t-252:t-20])
            win = closes[t-20:t]
            if max(win) <= piv and min(win) >= 0.85 * piv:
                state = "armed"; pivot = piv; arm_start = t - 20
        elif state == "armed":
            if closes[t] > pivot:
                state = "confirm"; brk_i = t; brk_close = closes[t]
            elif closes[t] < 0.85 * pivot:
                state = "idle"; pivot = None
        elif state == "confirm":
            if closes[t] < pivot: state = "idle"; pivot = None
            elif closes[t] > brk_close and t - brk_i <= 10:
                ev[bars[t]["d"]] = (pivot, t - arm_start, closes[t] / pivot - 1)
                state = "idle"; pivot = None
            elif t - brk_i > 10: state = "idle"; pivot = None
    return ev

def simulate(dates, closes_by, events_by, spy, road_start, road_end, house=False, ev_shift=0, seed=0):
    idx = {d: i for i, d in enumerate(dates)}
    days = [d for d in dates if road_start <= d <= road_end]
    spy_c = {b["d"]: b["c"] for b in spy}
    spy_dates = [b["d"] for b in spy]
    sma200 = {}
    sc = [b["c"] for b in spy]
    for i, b in enumerate(spy):
        if i >= 199: sma200[b["d"]] = sum(sc[i-199:i+1]) / 200
    cash = START; pos = {}  # sym -> {shares, pivot, wentry, target, adds}
    curve = []; costs = 0.0; orders = 0; trades = 0
    anchor = START; halts = 0; halt_until = None; ended = False
    rng = random.Random(seed)
    # shifted events for placebo
    ev_by_date = {}
    for sym, ev in events_by.items():
        for d, v in ev.items():
            if ev_shift:
                j = (idx[d] + ev_shift) % len(dates); d = dates[j]
            ev_by_date.setdefault(d, []).append((sym, v))
    for d in days:
        # exits first
        for sym in list(pos):
            p = pos[sym]; c = closes_by[sym].get(d)
            if c is None: continue
            if c < p["pivot"] or c <= 0.90 * p["wentry"]:
                gross = p["shares"] * c; cst = gross * STK_COST + STK_FEE; costs += cst
                cash += gross - cst; orders += 1; del pos[sym]
        # adds
        for sym, p in pos.items():
            c = closes_by[sym].get(d)
            if c is None: continue
            gain = c / p["wentry"] - 1
            stage = 1 + (1 if gain >= 0.05 else 0) + (1 if gain >= 0.10 else 0)
            want_frac = [0.4, 0.7, 1.0][stage - 1]
            have_frac = p["frac"]
            if want_frac > have_frac and cash > 1.0:
                spend = min(cash, p["target"] * (want_frac - have_frac))
                cst = spend * STK_COST; costs += cst
                add_sh = (spend - cst) / c
                p["wentry"] = (p["wentry"] * p["shares"] + c * add_sh) / (p["shares"] + add_sh)
                p["shares"] += add_sh; p["frac"] = want_frac; orders += 1
        # entries
        if not ended and (halt_until is None or d > halt_until) and len(pos) < 5:
            gate = sma200.get(d) is not None and spy_c.get(d, 0) > sma200[d]
            if gate and d in ev_by_date:
                cands = sorted(ev_by_date[d], key=lambda x: (-x[1][1], -x[1][2]))
                for sym, (piv, armed_days, strength) in cands:
                    if len(pos) >= 5 or sym in pos: break
                    c = closes_by[sym].get(d)
                    if c is None: continue
                    target = START / 5.0
                    spend = min(cash, target * 0.4)
                    if spend < 1.0: break
                    cst = spend * STK_COST; costs += cst
                    pos[sym] = {"shares": (spend - cst) / c, "pivot": piv, "wentry": c,
                                "target": target, "frac": 0.4}
                    orders += 1; trades += 1
        val = cash + sum(p["shares"] * closes_by[s].get(d, 0) for s, p in pos.items()
                         if closes_by[s].get(d) is not None)
        # names with no bar today: carry last known via dict default 0 would understate; use last close map
        curve.append([d, round(val, 4)])
        if house and not ended and val <= 0.85 * anchor:
            for sym in list(pos):
                c = closes_by[sym].get(d)
                if c is None: continue
                gross = pos[sym]["shares"] * c; cst = gross * STK_COST + STK_FEE; costs += cst
                cash += gross - cst; orders += 1; del pos[sym]
            halts += 1
            if halts >= 2: ended = True
            else:
                from datetime import date, timedelta
                y, m, dd = int(d[:4]), int(d[5:7]), int(d[8:10])
                halt_until = str(date(y, m, dd) + timedelta(days=90)); anchor = cash
            curve[-1][1] = round(cash, 4)
    peak = START; maxdd = 0.0
    for _, v in curve: peak = max(peak, v); maxdd = max(maxdd, 1 - v / peak)
    return {"final": round(curve[-1][1], 2) if curve else START, "max_dd": round(maxdd, 4),
            "costs": round(costs, 2), "orders": orders, "entries": trades, "halts": halts, "curve": curve}

def main():
    spy = load_stock("SPY")
    dates = [b["d"] for b in spy]
    pond = sorted(os.path.basename(p)[7:-5] for p in glob.glob(os.path.join(STKDATA, "pxfull_*.json")))
    pond = [t for t in pond if t != "SPY"]
    closes_by = {}; events_by = {}
    for t in pond:
        bars = load_stock(t)
        if len(bars) < 400: continue
        m = {}
        last = None
        bd = {b["d"]: b["c"] for b in bars}
        for d in dates:
            if d in bd: last = bd[d]
            if last is not None: m[d] = last
        closes_by[t] = m
        events_by[t] = name_events(bars)
    res = {"family": "hunt-livermore-pivotal", "n_names": len(closes_by),
           "n_confirmation_events": sum(len(v) for v in events_by.values()), "roads": {}}
    for road, s0 in ROADS.items():
        rn = simulate(dates, closes_by, events_by, spy, s0, END)
        rh = simulate(dates, closes_by, events_by, spy, s0, END, house=True)
        rb = slice_road(spy, s0, END)
        res["roads"][road] = {"native": rn, "house": rh, "hold": hold_final(rb),
                              "period_stats_monthly": period_stats(rn["curve"])}
        print(road, "native", rn["final"], "house", rh["final"], "entries", rn["entries"], flush=True)
    beaten = 0; twins = []
    for s in range(1, 21):
        rng = random.Random(3100 + s); off = rng.randrange(120, 3000)
        rr = simulate(dates, closes_by, events_by, spy, ROADS["LONG"], END, ev_shift=off, seed=s)
        twins.append(rr["final"]); beaten += 1 if res["roads"]["LONG"]["native"]["final"] > rr["final"] else 0
    res["placebo_LONG"] = {"beaten_of_20": beaten, "twin_finals": twins}
    print("placebo LONG beaten", beaten, flush=True)
    # coins: single-asset form per coin is NOT the portfolio system; spec says run per-coin.
    # Per-coin application: same pivot/confirm/pyramid logic on the single coin, all-in target.
    res["coins"] = coin_run()
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("saved")

def coin_run():
    """Per-coin application (spec: mechanically yes). Single-asset form:
    target = whole pot, probe 40% / +30% / +30%, exits as frozen; market
    gate = the coin's own close above its own 200-day average (the
    self-gate translation, labeled). Costs 0.60%/side. FULL window and
    RECENT2023; BTC buy-hold is the bar."""
    out = {}
    pooled = []
    for sym in coin_universe():
        bars = load_coin(sym)
        if len(bars) < 400: continue
        ev = name_events(bars)
        closes = [b["c"] for b in bars]
        sma = {}
        for i, b in enumerate(bars):
            if i >= 199: sma[b["d"]] = sum(closes[i-199:i+1]) / 200
        def run(bars_w, ev_w):
            cash = START; pos = None; costs = 0.0; orders = 0; curve = []
            evd = {d: v for d, v in ev_w.items() if bars_w[0]["d"] <= d <= bars_w[-1]["d"]}
            for b in bars_w:
                d = b["d"]; c = b["c"]
                if pos is not None:
                    if c < pos["pivot"] or c <= 0.90 * pos["wentry"]:
                        gross = pos["shares"] * c; cst = gross * CRY_COST; costs += cst
                        cash = gross - cst; pos = None; orders += 1
                if pos is not None:
                    gain = c / pos["wentry"] - 1
                    stage = 1 + (1 if gain >= 0.05 else 0) + (1 if gain >= 0.10 else 0)
                    want = [0.4, 0.7, 1.0][stage - 1]
                    if want > pos["frac"] and cash > 1.0:
                        spend = min(cash, START * (want - pos["frac"]))
                        cst = spend * CRY_COST; costs += cst
                        add = (spend - cst) / c
                        pos["wentry"] = (pos["wentry"] * pos["shares"] + c * add) / (pos["shares"] + add)
                        pos["shares"] += add; pos["frac"] = want; orders += 1
                if pos is None and d in evd and d in sma and c > sma[d]:
                    spend = min(cash, START * 0.4); cst = spend * CRY_COST; costs += cst
                    pos = {"shares": (spend - cst) / c, "pivot": evd[d][0], "wentry": c, "frac": 0.4}
                    orders += 1
                val = cash + (pos["shares"] * c if pos else 0.0)
                curve.append([d, round(val, 4)])
            if pos is not None:
                gross = pos["shares"] * bars_w[-1]["c"]; cst = gross * CRY_COST; costs += cst
                cash = gross - cst; curve[-1][1] = round(cash, 4)
            peak = START; maxdd = 0.0
            for _, v in curve: peak = max(peak, v); maxdd = max(maxdd, 1 - v / peak)
            return {"final": round(curve[-1][1], 2), "max_dd": round(maxdd, 4),
                    "costs": round(costs, 2), "orders": orders, "curve": curve}
        full = run(bars, ev)
        if bars[-1]["d"] < "2026-06-01":
            # open position at series end was force-exited in run(); if the coin died, hold = its fate
            pass
        recent = run([b for b in bars if b["d"] >= "2023-01-01"], ev)
        pooled.append((sym, full["final"], hold_final(bars), recent["final"]))
        if sym in ("BTC", "ETH"):
            out[sym] = {"FULL": full, "RECENT2023": recent, "hold_FULL": hold_final(bars),
                        "period_stats_FULL_monthly": period_stats(full["curve"])}
    out["pooled_FULL"] = {"n": len(pooled), "median_final": round(statistics.median([x[1] for x in pooled]), 2),
        "mean_final": round(statistics.mean([x[1] for x in pooled]), 2),
        "beat_own_hold": sum(1 for x in pooled if x[2] and x[1] > x[2])}
    return out

if __name__ == "__main__":
    main()
