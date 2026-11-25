#!/usr/bin/env python3
"""Kaufman KAMA (hunt-kaufman-kama, v12) — SPEC-FROZEN.md exactly.
ER(10); SC=[ER*(fastSC-slowSC)+slowSC]^2, fastSC=2/3, slowSC=2/31;
KAMA seeded at first close. FORM A (bare): in when KAMA last moved up,
out when it moved down (flat = hold state). FORM B (Kaufman filter,
CONSTRUCTED size): a direction change counts only when KAMA moves
>=1x SD of daily KAMA changes over prior 20 bars from the extreme of
the current direction. Long-only translation (original is long-short
futures), all-in $100, decide+execute at close. Stocks: SPY + pond,
0.10%/side + $0.01 sell fee. Coins: per-coin PIT universe, 0.60%/side,
BTC buy-hold is the bar; a coin whose series ends before 2026-06 with
a position still open is written to ZERO (program convention).
House: v9 floor pair on SPY/BTC (full daily simulator). Pond/pooled
finals use an equivalent segment-wise simulator (trades happen only
at state flips; identical arithmetic — the daily simulator's SPY
Form A LONG print, $101.23, is reproduced by construction of the
same rules on the same states). Placebos: 20-seed circular shifts
(SPY/BTC, daily simulator)."""
import json, os, sys, statistics
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from timerlib import *

HERE = os.path.dirname(os.path.abspath(__file__))

def kama_series(closes):
    c = np.asarray(closes, dtype=float); n = len(c)
    kama = np.empty(n); kama[0] = c[0]
    if n > 1:
        adiff = np.abs(np.diff(c))
        cs = np.concatenate([[0.0], np.cumsum(adiff)])
        fast, slow = 2 / 3.0, 2 / 31.0
        for t in range(1, n):
            if t >= 10:
                vol = cs[t] - cs[t - 10]
                er = abs(c[t] - c[t - 10]) / vol if vol > 0 else 0.0
            else:
                er = 0.0
            sc = (er * (fast - slow) + slow) ** 2
            kama[t] = kama[t - 1] + sc * (c[t] - kama[t - 1])
    return kama

def states_a(kama):
    st = np.zeros(len(kama), dtype=bool); cur = False
    d = np.diff(kama)
    for t in range(1, len(kama)):
        if d[t - 1] > 0: cur = True
        elif d[t - 1] < 0: cur = False
        st[t] = cur
    return st

def states_b(kama):
    n = len(kama); st = np.zeros(n, dtype=bool); cur = False; extreme = None
    diffs = np.diff(kama, prepend=kama[0])
    for t in range(1, n):
        if extreme is None: extreme = kama[t - 1]
        extreme = max(extreme, kama[t]) if cur else min(extreme, kama[t])
        if t >= 21:
            sd = float(np.std(diffs[t - 19:t + 1]))
            if sd > 0 and not cur and kama[t] - extreme >= sd: cur = True; extreme = kama[t]
            elif sd > 0 and cur and extreme - kama[t] >= sd: cur = False; extreme = kama[t]
        st[t] = cur
    return st

STATEFN = {"A": states_a, "B": states_b}

def fast_final(closes, states, cost, sell_fee=0.0):
    """Segment-wise equivalent of the daily close-execution simulator
    (no house floor). Trades occur only at state flips."""
    eq = START; orders = 0; inpos = False; pos_start = None
    n = len(closes)
    flips = [t for t in range(1, n) if bool(states[t]) != bool(states[t - 1])]
    events = [0] + flips + [n - 1]
    for t in events:
        want = bool(states[t])
        if want and not inpos:
            eq -= eq * cost; orders += 1; inpos = True; pos_start = t
        elif not want and inpos:
            eq = eq * (closes[t] / closes[pos_start])
            eq -= eq * cost + sell_fee; orders += 1; inpos = False; pos_start = None
    if inpos:
        eq = eq * (closes[n - 1] / closes[pos_start])
        eq -= eq * cost + sell_fee; orders += 1
    return round(eq, 2), orders

def asset_states(bars, form):
    closes = [b["c"] for b in bars]
    k = kama_series(closes)
    return STATEFN[form](k), closes

def main():
    res = {"family": "hunt-kaufman-kama", "forms": {}}
    spy = load_stock("SPY")
    pond = sorted(os.path.basename(p)[7:-5] for p in glob.glob(os.path.join(STKDATA, "pxfull_*.json")))
    pond = [t for t in pond if t != "SPY"]
    for form in ("A", "B"):
        f = {}
        st_full, closes = asset_states(spy, form)
        idx = {b["d"]: i for i, b in enumerate(spy)}
        spy_out = {}
        for road, s0 in ROADS.items():
            rb = slice_road(spy, s0, END); i0 = idx[rb[0]["d"]]
            rst = [bool(x) for x in st_full[i0:i0 + len(rb)]]
            rn = simulate(rb, rst, STK_COST, STK_FEE)
            rh = simulate(rb, rst, STK_COST, STK_FEE, house=True)
            rn["hold"] = hold_final(rb)
            spy_out[road] = {"native": rn, "house": rh}
        f["SPY"] = spy_out
        rb = slice_road(spy, ROADS["LONG"], END); i0 = idx[rb[0]["d"]]
        rst = [bool(x) for x in st_full[i0:i0 + len(rb)]]
        beaten, finals = placebo_beaten(rb, rst, spy_out["LONG"]["native"]["final"], STK_COST, STK_FEE)
        f["SPY_placebo_LONG"] = {"beaten_of_20": beaten, "twin_finals": finals}
        f["period_stats_SPY_LONG_native_monthly"] = period_stats(spy_out["LONG"]["native"]["curve"])
        pooled = {}
        for t in pond:
            bars = load_stock(t)
            if len(bars) < 300: continue
            st, cl = asset_states(bars, form)
            for road, s0 in ROADS.items():
                sel = [i for i, b in enumerate(bars) if s0 <= b["d"] <= END]
                if len(sel) < 30: continue
                seg_cl = [cl[i] for i in sel]; seg_st = st[sel]
                fin, _ = fast_final(seg_cl, seg_st, STK_COST, STK_FEE)
                pooled.setdefault(road, []).append((fin, hold_final([bars[i] for i in sel])))
        f["pond"] = {road: {"n": len(v), "median_final": round(statistics.median([x[0] for x in v]), 2),
                            "mean_final": round(statistics.mean([x[0] for x in v]), 2),
                            "beat_own_hold": sum(1 for x in v if x[1] is not None and x[0] > x[1])}
                     for road, v in pooled.items()}
        res["forms"][form] = f
        print(form, "SPY LONG native", spy_out["LONG"]["native"]["final"], "house", spy_out["LONG"]["house"]["final"], "placebo", beaten, flush=True)
    coins = {}
    btc = load_coin("BTC")
    for form in ("A", "B"):
        cf = {}
        st_full, closes = asset_states(btc, form)
        bidx = {b["d"]: i for i, b in enumerate(btc)}
        roads_out = {}
        for road, s0 in ROADS.items():
            rb = [b for b in btc if s0 <= b["d"] <= CEND]
            if len(rb) < 30: continue
            i0 = bidx[rb[0]["d"]]
            rst = [bool(x) for x in st_full[i0:i0 + len(rb)]]
            rn = simulate(rb, rst, CRY_COST, 0.0); rh = simulate(rb, rst, CRY_COST, 0.0, house=True)
            rn["hold"] = hold_final(rb)
            roads_out[road] = {"native": rn, "house": rh}
        full = simulate(btc, [bool(x) for x in st_full], CRY_COST, 0.0)
        cf["BTC"] = {"FULL": full, "roads": roads_out}
        beaten, _ = placebo_beaten(btc, [bool(x) for x in st_full], full["final"], CRY_COST, 0.0)
        cf["BTC_placebo_FULL"] = {"beaten_of_20": beaten}
        pooled = []
        for sym in coin_universe():
            bars = load_coin(sym)
            if len(bars) < 400: continue
            st, cl = asset_states(bars, form)
            fin, _ = fast_final(cl, st, CRY_COST, 0.0)
            if bars[-1]["d"] < "2026-06-01" and bool(st[-1]): fin = 0.0
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
