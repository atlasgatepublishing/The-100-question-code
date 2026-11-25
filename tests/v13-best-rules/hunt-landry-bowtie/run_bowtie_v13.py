#!/usr/bin/env python3
"""V13 Best Rules — Landry Bowtie. Implements BEST-RULES-SPEC.md exactly:
knot-permitting signal (down-fan within prior 12 sessions, first up-fan since),
published 10SMA/20EMA/30EMA, buy stop signal-high x1.001 live 2 sessions,
stop signal-low x0.999, fan-break exit (10SMA<20EMA at close), no time cap,
5-slot equal-target portfolio over the pond, no pot floor, 0.10%/side+$0.01.
Placebos: 20 seeds, signal indices circularly shifted by a common offset."""
import json, os, sys, glob, statistics, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from timerlib import load_stock, period_stats, STK_COST, STK_FEE, START

HERE = os.path.dirname(os.path.abspath(__file__))
STKDATA = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
SLOTS = 5

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
    """First up-fan day with a down-fan day within prior 12 sessions and no
    up-fan day since the most recent down-fan day."""
    sma10, ema20, ema30 = averages(bars)
    sig = []
    last_down = -10**9; last_up = -10**9
    for t in range(len(bars)):
        if None in (sma10[t], ema20[t], ema30[t]): continue
        down = sma10[t] < ema20[t] < ema30[t]
        up = sma10[t] > ema20[t] > ema30[t]
        if down: last_down = t
        if up:
            if t - last_down <= 12 and last_up < last_down:
                sig.append(t)
            last_up = t
    return sig, (sma10, ema20, ema30)

def run_portfolio(data, start, end, slots=SLOTS, sig_override=None):
    """data: {sym: (bars, avgs, signals)}. Daily loop over union of dates."""
    dates = sorted({b["d"] for bars, _, _ in data.values() for b in bars if start <= b["d"] <= end})
    idx = {s: {b["d"]: i for i, b in enumerate(bars)} for s, (bars, _, _) in data.items()}
    pend = {}   # sym -> (signal_i, expiry_i) in that asset's bar index
    for s, (bars, _, sigs) in data.items():
        use = sig_override[s] if sig_override else sigs
        for si in use:
            if start <= bars[si]["d"] <= end:
                pend.setdefault(bars[si]["d"], []).append((s, si))
    cash = START; pos = {}  # sym -> [shares, entry_px, stop]
    marks = {}
    curve = []; costs = 0.0; trades = 0; wins = 0; trade_pnls = []
    active_orders = {}  # sym -> (trig, stop, expiry_date)
    for d in dates:
        # register new pending orders from signals on day d (they trade from d+1)
        for s, si in sorted(pend.get(d, [])):
            bars = data[s][0]
            if si + 2 < len(bars):
                exp = bars[min(si+2, len(bars)-1)]["d"]
                active_orders[s] = (bars[si]["h"]*1.001, bars[si]["l"]*0.999, exp, si)
        for s in sorted(data):
            bars, (sma10, ema20, ema30), _ = data[s]
            i = idx[s].get(d)
            if i is None: continue
            b = bars[i]
            # stop-loss intraday for held position
            if s in pos:
                sh, ep, stop = pos[s]
                if b["l"] <= stop:
                    px = b["o"] if b["o"] < stop else stop
                    gross = sh*px; cst = gross*STK_COST + STK_FEE; costs += cst
                    trade_pnls.append((gross-cst) - sh*ep)
                    if gross - cst > sh*ep: wins += 1
                    cash += gross - cst; del pos[s]
            # entry trigger (order registered on an earlier day, live while d <= expiry and signal was >=1 bar ago)
            if s not in pos and s in active_orders:
                trig, stop, exp, si = active_orders[s]
                if d > exp or d <= bars[si]["d"]:
                    if d > exp: del active_orders[s]
                elif len(pos) < slots and b["h"] >= trig:
                    pval = cash + sum(pos[k][0]*marks.get(k, pos[k][1]) for k in pos)
                    spend = min(cash, pval/slots)
                    if spend > 1.0:
                        px = max(b["o"], trig)
                        cst = spend*STK_COST; costs += cst
                        pos[s] = [(spend-cst)/px, px, stop]
                        cash -= spend; trades += 1
                    del active_orders[s]
                elif d >= exp:
                    del active_orders[s]
            # fan-break exit at close
            if s in pos and sma10[i] is not None and sma10[i] < ema20[i]:
                sh, ep, stop = pos[s]
                gross = sh*b["c"]; cst = gross*STK_COST + STK_FEE; costs += cst
                if gross - cst > sh*ep: wins += 1
                trade_pnls.append((gross-cst) - sh*ep)
                cash += gross - cst; del pos[s]
            marks[s] = b["c"]
        val = cash + sum(pos[k][0]*marks.get(k, pos[k][1]) for k in pos)
        curve.append([d, round(val, 4)])
    # force-exit at each asset's last in-window close
    for s in list(pos):
        bars = data[s][0]
        last = [b for b in bars if start <= b["d"] <= end][-1]
        sh, ep, stop = pos[s]
        gross = sh*last["c"]; cst = gross*STK_COST + STK_FEE; costs += cst
        if gross - cst > sh*ep: wins += 1
        trade_pnls.append((gross-cst) - sh*ep)
        cash += gross - cst; del pos[s]
    if curve: curve[-1][1] = round(cash, 4)
    peak = START; maxdd = 0.0
    for _, v in curve: peak = max(peak, v); maxdd = max(maxdd, 1 - v/peak)
    expct = round(statistics.mean(trade_pnls), 2) if trade_pnls else None
    return {"final": round(cash, 2), "max_dd": round(maxdd, 4), "costs": round(costs, 2),
            "trades": trades, "wins": wins, "closed": len(trade_pnls),
            "expectancy_per_closed_trade": expct, "curve": curve}

def main():
    syms = sorted(os.path.basename(p)[7:-5] for p in glob.glob(os.path.join(STKDATA, "pxfull_*.json")))
    data = {}
    for s in syms:
        bars = load_stock(s)
        if len(bars) < 300: continue
        sigs, avgs = find_signals(bars)
        data[s] = (bars, avgs, sigs)
    print("universe", len(data), "total signals", sum(len(v[2]) for v in data.values()), flush=True)
    res = {"family": "hunt-landry-bowtie", "form": "v13-best-rules", "universe_n": len(data)}
    for road, (s0, e0) in ROADS.items():
        r = run_portfolio(data, s0, e0)
        res[road] = r
        res[f"period_stats_{road}_monthly"] = period_stats(r["curve"])
        print(road, r["final"], "dd", r["max_dd"], "trades", r["trades"], flush=True)
    # SPY single-asset secondary, all-in 1 slot
    spy = {"SPY": data["SPY"]}
    res["SPY_single"] = {}
    for road, (s0, e0) in ROADS.items():
        r = run_portfolio(spy, s0, e0, slots=1)
        res["SPY_single"][road] = {k: r[k] for k in ("final", "max_dd", "trades", "wins", "costs")}
    print("SPY single LONG", res["SPY_single"]["LONG"], flush=True)
    # placebos on LONG: common seeded index offset per asset
    real = res["LONG"]["final"]; beaten = 0; twins = []
    s0, e0 = ROADS["LONG"]
    for seed in range(1, 21):
        rng = random.Random(9000+seed); off = rng.randrange(60, 1200)
        ov = {}
        for s, (bars, avgs, sigs) in data.items():
            ov[s] = sorted({(si+off) % len(bars) for si in sigs})
        r = run_portfolio(data, s0, e0, sig_override=ov)
        twins.append(r["final"]); beaten += 1 if real > r["final"] else 0
        print("placebo", seed, r["final"], flush=True)
    res["placebo_LONG"] = {"beaten_of_20": beaten, "twin_finals": twins,
                           "twin_median": round(statistics.median(twins), 2)}
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("saved")

if __name__ == "__main__":
    main()
