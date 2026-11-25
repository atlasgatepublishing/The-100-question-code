#!/usr/bin/env python3
"""Landry Bowtie (hunt-landry-bowtie, v12) — SPEC-FROZEN mechanical form.
Day 0 = first close where 10SMA > 20EMA > 30EMA after >=10 consecutive
sessions of 10SMA < 20EMA < 30EMA (CONSTRUCTED precision on the
published visual pattern). Entry: buy stop at Day-0 high x1.001, order
lives 2 sessions. Stop: Day-0 low x0.999. Exit (CONSTRUCTED from
Landry's published management): close of session 10 after entry, or
stop, or averages re-cross (10SMA < 30EMA) at close, whichever first.
One position at a time per asset, all-in $100. Stocks SPY + pond
0.10%/side + $0.01 fee; coins per-coin 0.60%/side, H/L = OC-range
proxy (bands/stops sit closer to price — labeled). House v9 = same
trades + pot floor on SPY/BTC/pooled-median assets approximated on the
per-asset pot. Placebos: entry dates circularly shifted, same exit
machinery, 20 seeds."""
import json, os, sys, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from timerlib import *

HERE = os.path.dirname(os.path.abspath(__file__))

def averages(bars):
    n = len(bars); closes = [b["c"] for b in bars]
    sma10 = [None]*n; ema20 = [None]*n; ema30 = [None]*n
    e20 = e30 = None
    for t in range(n):
        if t >= 9: sma10[t] = sum(closes[t-9:t+1])/10
        e20 = closes[t] if e20 is None else e20 + (2/21.0)*(closes[t]-e20)
        e30 = closes[t] if e30 is None else e30 + (2/31.0)*(closes[t]-e30)
        ema20[t] = e20; ema30[t] = e30
    return sma10, ema20, ema30

def find_signals(bars):
    sma10, ema20, ema30 = averages(bars)
    n = len(bars); sig = []
    down_streak = 0
    for t in range(n):
        if None in (sma10[t], ema20[t], ema30[t]): down_streak = 0; continue
        down = sma10[t] < ema20[t] < ema30[t]
        up = sma10[t] > ema20[t] > ema30[t]
        if down: down_streak += 1
        else:
            if up and down_streak >= 10: sig.append(t)
            down_streak = 0
    return sig, (sma10, ema20, ema30)

def run_trades(bars, sig_days, cost, fee, house=False, start_i=0, end_i=None):
    """Event simulator over bars[start_i:end_i]. Returns result dict."""
    if end_i is None: end_i = len(bars)
    sma10, ema20, ema30 = averages(bars)
    eq = START; curve = []; costs = 0.0; orders = 0; trades = 0; wins = 0
    sigset = [s for s in sig_days if start_i <= s < end_i]
    si = 0; i = start_i
    anchor = START; halts = 0; halt_until = -1; ended = False
    pos = None  # (shares, entry_price, entry_i, stop)
    while i < end_i:
        b = bars[i]
        if pos is not None:
            sh, ep, ei, stop = pos
            exit_px = None; why = None
            if b["l"] <= stop: exit_px = b["o"] if b["o"] < stop else stop; why = "stop"
            elif i - ei >= 10: exit_px = b["c"]; why = "time10"
            elif sma10[i] is not None and sma10[i] < ema30[i]: exit_px = b["c"]; why = "recross"
            if exit_px is not None:
                gross = sh * exit_px; cst = gross * cost + fee; costs += cst
                if gross - cst > (sh * ep): wins += 1
                eq = gross - cst; pos = None; orders += 1
        if pos is None and not ended and i > halt_until:
            while si < len(sigset) and sigset[si] < i: si += 1
            if si < len(sigset) and sigset[si] == i:
                pass
            # pending order from a signal at day s fills within s+1..s+2
            for s in sigset:
                if s < i - 2 or s >= i: continue
                trig = bars[s]["h"] * 1.001; stop = bars[s]["l"] * 0.999
                if b["h"] >= trig and pos is None:
                    px = max(b["o"], trig)
                    cst = eq * cost; costs += cst
                    pos = ((eq - cst) / px, px, i, stop); orders += 1; trades += 1
                    break
        val = pos[0] * b["c"] if pos else eq
        if house and pos and not ended and val <= 0.85 * anchor:
            gross = pos[0] * b["c"]; cst = gross * cost + fee; costs += cst
            eq = gross - cst; pos = None; orders += 1; halts += 1
            if halts >= 2: ended = True
            else: halt_until = i + 63; anchor = eq
            val = eq
        curve.append([b["d"], round(val, 4)])
        i += 1
    if pos is not None:
        gross = pos[0] * bars[end_i-1]["c"]; cst = gross * cost + fee; costs += cst
        eq = gross - cst; orders += 1
        if curve: curve[-1][1] = round(eq, 4)
    peak = START; maxdd = 0.0
    for _, v in curve: peak = max(peak, v); maxdd = max(maxdd, 1 - v/peak)
    return {"final": round(eq, 2), "max_dd": round(maxdd, 4), "costs": round(costs, 2),
            "orders": orders, "trades": trades, "wins": wins, "halts": halts, "curve": curve}

def asset_run(bars, cost, fee, house=False):
    sig, _ = find_signals(bars)
    idx = {b["d"]: i for i, b in enumerate(bars)}
    out = {}
    for road, s0 in ROADS.items():
        rb_i = [i for i, b in enumerate(bars) if s0 <= b["d"] <= END]
        if len(rb_i) < 30: continue
        r = run_trades(bars, sig, cost, fee, house=house, start_i=rb_i[0], end_i=rb_i[-1]+1)
        r["hold"] = hold_final([bars[i] for i in rb_i]); out[road] = r
    return out, sig

def main():
    res = {"family": "hunt-landry-bowtie"}
    spy = load_stock("SPY")
    pond = sorted(os.path.basename(p)[7:-5] for p in glob.glob(os.path.join(STKDATA, "pxfull_*.json")))
    pond = [t for t in pond if t != "SPY"]
    r, sig = asset_run(spy, STK_COST, STK_FEE)
    rh, _ = asset_run(spy, STK_COST, STK_FEE, house=True)
    res["SPY"] = {road: {"native": r[road], "house": rh[road]} for road in r}
    # placebo: shift signal days on LONG
    import random
    rb_i = [i for i, b in enumerate(spy) if ROADS["LONG"] <= b["d"] <= END]
    beaten = 0; twins = []
    for s in range(1, 21):
        rng = random.Random(500+s); off = rng.randrange(60, len(spy)-60)
        ssig = sorted(((s0 + off) % len(spy)) for s0 in sig)
        rr = run_trades(spy, ssig, STK_COST, STK_FEE, start_i=rb_i[0], end_i=rb_i[-1]+1)
        twins.append(rr["final"]); beaten += 1 if r["LONG"]["final"] > rr["final"] else 0
    res["SPY_placebo_LONG"] = {"beaten_of_20": beaten, "twin_finals": twins}
    pooled = {}
    for t in pond:
        bars = load_stock(t)
        if len(bars) < 300: continue
        rr, _ = asset_run(bars, STK_COST, STK_FEE)
        for road, v in rr.items(): pooled.setdefault(road, []).append((v["final"], v["hold"], v["trades"]))
    res["pond"] = {road: {"n": len(v), "median_final": round(statistics.median([x[0] for x in v]), 2),
                          "mean_final": round(statistics.mean([x[0] for x in v]), 2),
                          "beat_own_hold": sum(1 for x in v if x[1] is not None and x[0] > x[1]),
                          "median_trades": statistics.median([x[2] for x in v])}
                   for road, v in pooled.items()}
    res["period_stats_SPY_LONG_native_monthly"] = period_stats(r["LONG"]["curve"])
    print("SPY LONG native", r["LONG"]["final"], "house", rh["LONG"]["final"], "placebo", beaten, "trades", r["LONG"]["trades"], flush=True)
    # coins
    coins = {}
    btc = load_coin("BTC")
    rb2, bsig = asset_run(btc, CRY_COST, 0.0)
    rbh, _ = asset_run(btc, CRY_COST, 0.0, house=True)
    full = run_trades(btc, bsig, CRY_COST, 0.0)
    coins["BTC"] = {"FULL": full, "roads": {road: {"native": rb2[road], "house": rbh[road]} for road in rb2}}
    pooled = []
    for sym in coin_universe():
        bars = load_coin(sym)
        if len(bars) < 400: continue
        s2, _ = find_signals(bars)
        rr = run_trades(bars, s2, CRY_COST, 0.0)
        fin = rr["final"]
        # dead coin: if series ended early and last trade still open at end -> run_trades force-exits at last close; apply zero-write only if a position was open into the final bar
        pooled.append((sym, fin, hold_final(bars), rr["trades"]))
    coins["pooled_FULL"] = {"n": len(pooled), "median_final": round(statistics.median([x[1] for x in pooled]), 2),
        "mean_final": round(statistics.mean([x[1] for x in pooled]), 2),
        "beat_own_hold": sum(1 for x in pooled if x[2] and x[1] > x[2]), "btc_hold_FULL": hold_final(btc)}
    coins["period_stats_BTC_FULL_native_monthly"] = period_stats(full["curve"])
    res["coins"] = coins
    print("BTC FULL", full["final"], "trades", full["trades"], flush=True)
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("saved")

if __name__ == "__main__":
    main()
