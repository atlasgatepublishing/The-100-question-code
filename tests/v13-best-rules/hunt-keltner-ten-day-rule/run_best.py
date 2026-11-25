#!/usr/bin/env python3
"""Keltner Ten-Day Rule — v13 BEST RULES run (spec frozen in BEST-RULES-SPEC.md).
Signal: 1960 Form A exactly (10d SMA typical price, bands +/-1x 10d SMA range).
MY RULES: exit on close below LOWER band (published opposite-band translation,
replacing v12's constructed center-line exit); breadth basket over the 153-name
pond, up to 10 slots at 10% of equity, ranked by breakout strength
(close-upper)/avg-range; daily at close; no floor/stop/ladder; costs
0.10%/side + $0.01/sell. Placebos: 20-seed per-name circular state shifts.
Secondary diagnostic: SPY single-asset timer with the lower-band exit only."""
import json, os, sys, glob, random, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from timerlib import load_stock, simulate, period_stats, hold_final, STKDATA, STK_COST, STK_FEE, START

HERE = os.path.dirname(os.path.abspath(__file__))
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
SLOTS = 10; SLICE = 0.10

def keltner(bars):
    """Returns (states, strengths): state True after close t if in long state
    under lower-band exit; strength = (close-upper)/avg_range at t."""
    n = len(bars); st = [False]*n; sstr = [0.0]*n; cur = False
    tp = [(b["h"]+b["l"]+b["c"])/3 for b in bars]
    rg = [b["h"]-b["l"] for b in bars]
    for t in range(n):
        if t >= 9:
            cen = sum(tp[t-9:t+1])/10; rng = sum(rg[t-9:t+1])/10
            up, lo = cen + rng, cen - rng
            if not cur and bars[t]["c"] > up: cur = True
            elif cur and bars[t]["c"] < lo: cur = False
            if rng > 0: sstr[t] = (bars[t]["c"] - up)/rng
        st[t] = cur
    return st, sstr

def basket(dates, data, start, end):
    """data: sym -> {idx: date->bar_i, bars, st, sstr}. Fresh $100, flat at start."""
    cash = START; pos = {}  # sym -> shares
    lastpx = {}
    curve = []; costs = 0.0; orders = 0; entries = 0
    for d in dates:
        if d < start or d > end: continue
        # mark
        for sym, dd in data.items():
            i = dd["idx"].get(d)
            if i is not None: lastpx[sym] = dd["bars"][i]["c"]
        eq = cash + sum(sh*lastpx.get(s, 0.0) for s, sh in pos.items())
        # exits first
        for sym in list(pos):
            dd = data[sym]; i = dd["idx"].get(d)
            if i is not None and not dd["st"][i]:
                px = dd["bars"][i]["c"]; gross = pos.pop(sym)*px
                cst = gross*STK_COST + STK_FEE; costs += cst; cash += gross - cst; orders += 1
        # entries
        free = SLOTS - len(pos)
        if free > 0:
            eq = cash + sum(sh*lastpx.get(s, 0.0) for s, sh in pos.items())
            cands = []
            for sym, dd in data.items():
                if sym in pos: continue
                i = dd["idx"].get(d)
                if i is not None and dd["st"][i]: cands.append((dd["sstr"][i], sym, i))
            cands.sort(reverse=True)
            for _, sym, i in cands[:free]:
                px = data[sym]["bars"][i]["c"]
                amt = SLICE*eq
                if amt > cash: amt = cash
                if amt <= 0: break
                cst = amt*STK_COST; costs += cst
                pos[sym] = (amt - cst)/px; cash -= amt; orders += 1; entries += 1
        eq = cash + sum(sh*lastpx.get(s, 0.0) for s, sh in pos.items())
        curve.append([d, round(eq, 4)])
    final = curve[-1][1] if curve else START
    peak = START; maxdd = 0.0
    for _, v in curve: peak = max(peak, v); maxdd = max(maxdd, 1 - v/peak)
    return {"final": round(final, 2), "max_dd": round(maxdd, 4), "costs": round(costs, 2),
            "orders": orders, "entries": entries, "curve": curve}

def main():
    spy = load_stock("SPY")
    dates = [b["d"] for b in spy]
    pond = sorted(os.path.basename(p)[7:-5] for p in glob.glob(os.path.join(STKDATA, "pxfull_*.json")))
    pond = [t for t in pond if t != "SPY"]
    data = {}
    for t in pond:
        bars = load_stock(t)
        if len(bars) < 300: continue
        st, sstr = keltner(bars)
        data[t] = {"bars": bars, "idx": {b["d"]: i for i, b in enumerate(bars)}, "st": st, "sstr": sstr}
    print("pond names:", len(data), flush=True)
    res = {"family": "hunt-keltner-ten-day-rule", "variant": "v13-best-rules",
           "roads": {}, "placebos": {}, "spy_diagnostic_lowerband_exit": {}}
    # SPY diagnostic: single-asset timer, lower-band exit only
    sst, _ = keltner(spy)
    sidx = {b["d"]: i for i, b in enumerate(spy)}
    for road, (s0, e0) in ROADS.items():
        rb = [b for b in spy if s0 <= b["d"] <= e0]
        i0 = sidx[rb[0]["d"]]
        r = simulate(rb, sst[i0:i0+len(rb)], STK_COST, STK_FEE)
        res["spy_diagnostic_lowerband_exit"][road] = {k: r[k] for k in ("final", "max_dd", "costs", "orders")}
    # Basket roads
    for road, (s0, e0) in ROADS.items():
        r = basket(dates, data, s0, e0)
        r["period_stats_monthly"] = period_stats(r["curve"])
        res["roads"][road] = r
        print(road, "basket final", r["final"], "maxdd", r["max_dd"], "orders", r["orders"], flush=True)
    # Placebos: per-name circular shifts, 20 seeds per road
    for road, (s0, e0) in ROADS.items():
        finals = []
        for seed in range(1, 21):
            pdata = {}
            for sym, dd in data.items():
                n = len(dd["st"])
                rng = random.Random(hash((seed, sym)) & 0xffffffff)
                off = rng.randrange(20, n-20) if n > 40 else rng.randrange(1, n)
                pdata[sym] = {"bars": dd["bars"], "idx": dd["idx"],
                              "st": dd["st"][off:] + dd["st"][:off],
                              "sstr": dd["sstr"][off:] + dd["sstr"][:off]}
            pr = basket(dates, pdata, s0, e0)
            finals.append(pr["final"])
        real = res["roads"][road]["final"]
        res["placebos"][road] = {"beaten_of_20": sum(1 for f in finals if real > f), "twin_finals": finals}
        print(road, "placebo beaten", res["placebos"][road]["beaten_of_20"], "/20", flush=True)
    # Confirmation (frozen bars): only if a road beats champion V+M
    conf = {}
    for road, (s0, e0) in ROADS.items():
        if res["roads"][road]["final"] > CHAMP[road]:
            rd = [d for d in dates if s0 <= d <= e0]
            mid = rd[len(rd)//2]
            halves = {}
            for name, (hs, he) in {"H1": (s0, rd[len(rd)//2 - 1]), "H2": (mid, e0)}.items():
                br = basket(dates, data, hs, he)
                spyh = hold_final([b for b in spy if hs <= b["d"] <= he])
                halves[name] = {"window": [hs, he], "basket_final": br["final"], "spy_hold": spyh,
                                "beats_spy": br["final"] > spyh}
            years = sorted(set(d[:4] for d in rd))
            folds = {}
            for y in years:
                ys, ye = max(s0, y+"-01-01"), min(e0, y+"-12-31")
                folds[y] = basket(dates, data, ys, ye)["final"]
            pos_years = sum(1 for v in folds.values() if v > 100.0)
            conf[road] = {"halves": halves, "yearly_folds": folds,
                          "positive_years": pos_years, "n_years": len(folds),
                          "confirmed": all(h["beats_spy"] for h in halves.values()) and pos_years > len(folds)/2}
            print(road, "CONFIRMATION", conf[road]["confirmed"], flush=True)
    res["confirmation"] = conf
    res["bars"] = {"champion_VM": CHAMP, "SPY": SPYREF,
                   "published_v12_formA_SPY": {"LONG": 139.69, "DECADE": 142.22, "CONT": 140.89, "VAL": 116.86}}
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("saved")

if __name__ == "__main__":
    main()
