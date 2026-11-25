#!/usr/bin/env python3
"""Keltner Ten-Day Rule (hunt-keltner-ten-day-rule, v12) — SPEC-FROZEN.
FORM A (1960 literal, long-only translation): center = 10-day SMA of
typical price (H+L+C)/3; bands = center +/- 1x 10-day SMA of range
(H-L). Enter long at close above upper band; exit to cash at close
below CENTER line (CONSTRUCTED exit, nearest documented convention —
Keltner published entry/trend logic, no separate mechanical exit).
VARIANT B (Raschke modern): EMA(20) center, bands +/- 2x ATR(10)
(Wilder), same entry/exit. All-in $100, at close. Stocks SPY + pond
0.10%/side + $0.01 fee; coins per-coin 0.60%/side with H/L = OC-range
proxy (PIT coin cache holds open/close only — ranges narrower than
true, bands tighter: more signals, labeled). Dead-coin open position
at series end written to ZERO. House v9 pair on SPY/BTC; 20-seed
circular-shift placebos."""
import json, os, sys, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from timerlib import *

HERE = os.path.dirname(os.path.abspath(__file__))

def states_a(bars):
    n = len(bars); st = []; cur = False
    tp = [(b["h"]+b["l"]+b["c"])/3 for b in bars]
    rg = [b["h"]-b["l"] for b in bars]
    for t in range(n):
        if t >= 9:
            cen = sum(tp[t-9:t+1])/10; rng = sum(rg[t-9:t+1])/10
            if not cur and bars[t]["c"] > cen + rng: cur = True
            elif cur and bars[t]["c"] < cen: cur = False
        st.append(cur)
    return st

def states_b(bars):
    n = len(bars); st = []; cur = False
    closes = [b["c"] for b in bars]
    ema = [None]*n; atr = [None]*n
    k = 2/21.0; ema[0] = closes[0]
    for t in range(1, n): ema[t] = ema[t-1] + k*(closes[t]-ema[t-1])
    tr = [0.0]*n
    for t in range(n):
        pc = closes[t-1] if t >= 1 else bars[t]["c"]
        tr[t] = max(bars[t]["h"]-bars[t]["l"], abs(bars[t]["h"]-pc), abs(bars[t]["l"]-pc))
    for t in range(n):
        if t >= 9:
            atr[t] = sum(tr[t-9:t+1])/10 if atr[t-1] is None else atr[t-1] + (tr[t]-atr[t-1])/10
            if not cur and bars[t]["c"] > ema[t] + 2*atr[t]: cur = True
            elif cur and bars[t]["c"] < ema[t]: cur = False
        st.append(cur)
    return st

STATEFN = {"A": states_a, "B": states_b}

def run_asset(bars, form, cost, fee, house=False):
    st = STATEFN[form](bars)
    idx = {b["d"]: i for i, b in enumerate(bars)}
    out = {}
    for road, s0 in ROADS.items():
        rb = [b for b in bars if s0 <= b["d"] <= END]
        if len(rb) < 30: continue
        i0 = idx[rb[0]["d"]]
        r = simulate(rb, st[i0:i0+len(rb)], cost, fee, house=house)
        r["hold"] = hold_final(rb); out[road] = r
    return out, st

def main():
    res = {"family": "hunt-keltner-ten-day-rule", "forms": {}}
    spy = load_stock("SPY")
    pond = sorted(os.path.basename(p)[7:-5] for p in glob.glob(os.path.join(STKDATA, "pxfull_*.json")))
    pond = [t for t in pond if t != "SPY"]
    for form in ("A", "B"):
        f = {}
        r, st = run_asset(spy, form, STK_COST, STK_FEE)
        rh, _ = run_asset(spy, form, STK_COST, STK_FEE, house=True)
        f["SPY"] = {road: {"native": r[road], "house": rh[road]} for road in r}
        rb = slice_road(spy, ROADS["LONG"], END); i0 = next(i for i, b in enumerate(spy) if b["d"] == rb[0]["d"])
        beaten, finals = placebo_beaten(rb, st[i0:i0+len(rb)], r["LONG"]["final"], STK_COST, STK_FEE)
        f["SPY_placebo_LONG"] = {"beaten_of_20": beaten, "twin_finals": finals}
        pooled = {}
        for t in pond:
            bars = load_stock(t)
            if len(bars) < 300: continue
            rr, _ = run_asset(bars, form, STK_COST, STK_FEE)
            for road, v in rr.items(): pooled.setdefault(road, []).append((v["final"], v["hold"]))
        f["pond"] = {road: {"n": len(v), "median_final": round(statistics.median([x[0] for x in v]), 2),
                            "mean_final": round(statistics.mean([x[0] for x in v]), 2),
                            "beat_own_hold": sum(1 for x in v if x[1] is not None and x[0] > x[1])}
                     for road, v in pooled.items()}
        f["period_stats_SPY_LONG_native_monthly"] = period_stats(r["LONG"]["curve"])
        res["forms"][form] = f
        print(form, "SPY LONG native", r["LONG"]["final"], "house", rh["LONG"]["final"], "placebo", beaten, flush=True)
    coins = {}
    btc = load_coin("BTC")
    for form in ("A", "B"):
        cf = {}
        rb, st = run_asset(btc, form, CRY_COST, 0.0)
        rh, _ = run_asset(btc, form, CRY_COST, 0.0, house=True)
        full = simulate(btc, STATEFN[form](btc), CRY_COST, 0.0)
        cf["BTC"] = {"FULL": full, "roads": {road: {"native": rb[road], "house": rh[road]} for road in rb}}
        beaten, _ = placebo_beaten(btc, STATEFN[form](btc), full["final"], CRY_COST, 0.0)
        cf["BTC_placebo_FULL"] = {"beaten_of_20": beaten}
        pooled = []
        for sym in coin_universe():
            bars = load_coin(sym)
            if len(bars) < 400: continue
            s2 = STATEFN[form](bars)
            rr = simulate(bars, s2, CRY_COST, 0.0)
            fin = 0.0 if (bars[-1]["d"] < "2026-06-01" and s2[-1]) else rr["final"]
            pooled.append((sym, fin, hold_final(bars)))
        cf["pooled_FULL"] = {"n": len(pooled), "median_final": round(statistics.median([x[1] for x in pooled]), 2),
            "mean_final": round(statistics.mean([x[1] for x in pooled]), 2),
            "beat_own_hold": sum(1 for x in pooled if x[2] and x[1] > x[2]), "btc_hold_FULL": hold_final(btc)}
        cf["period_stats_BTC_FULL_native_monthly"] = period_stats(full["curve"])
        coins[form] = cf
        print("coin", form, "BTC FULL", full["final"], flush=True)
    res["coins"] = coins
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("saved")

if __name__ == "__main__":
    main()
