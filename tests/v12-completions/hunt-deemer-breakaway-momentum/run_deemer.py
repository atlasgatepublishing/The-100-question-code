#!/usr/bin/env python3
"""Deemer Breakaway Momentum — frozen form (SPEC-FROZEN.md). Simulation only.
Trigger: 10-day NYSE A/D totals ratio > 1.97 OR 20-day ratio > 1.72.
A/D series CONSTRUCTED from the program pond-30 daily stack (named in spec;
bias: smaller universe -> less extreme totals -> fewer signals).
Entry: SPY at next session open on first trigger day; exit at open of first
session after 12-month anniversary (CONSTRUCTED exit). New signal while
holding does not extend. Native no floor; house v9 floor pair.
Placebos: 20 seeds random entry dates matched on count, same 12-mo hold."""
import json, os, random, statistics, sys
sys.path.insert(0, "/tmp/hs2")
from common import *
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
POND = ["AAPL","MSFT","AMZN","GOOGL","META","BRK-B","JPM","XOM","JNJ","PG","V","WMT","HD","BAC","CVX","PFE","VZ","T","DIS","NFLX","INTC","CSCO","GE","IBM","MMM","UNH","MA","KO","PEP","WFC"]

def build_ad(spy):
    adv = {}; dec = {}
    for t in POND:
        bars, _ = load_bars(t)
        for i in range(1, len(bars)):
            d = bars[i]["d"]
            if bars[i]["c"] > bars[i-1]["c"]: adv[d] = adv.get(d, 0) + 1
            elif bars[i]["c"] < bars[i-1]["c"]: dec[d] = dec.get(d, 0) + 1
    dates = [b["d"] for b in spy]
    A = [adv.get(d, 0) for d in dates]; D = [dec.get(d, 0) for d in dates]
    sig = []
    for i in range(len(dates)):
        fire = False
        if i >= 9:
            sa, sd = sum(A[i-9:i+1]), sum(D[i-9:i+1])
            if sd > 0 and sa/sd > 1.97: fire = True
        if i >= 19:
            sa, sd = sum(A[i-19:i+1]), sum(D[i-19:i+1])
            if sd > 0 and sa/sd > 1.72: fire = True
        sig.append(fire)
    return sig

def run_events(spy, entry_idxs, floor=False):
    """Entries at open of entry day; exit at open of first session >= entry+12mo.
    Overlapping entries ignored (already holding). Daily equity curve on closes."""
    n = len(spy); entry_set = set(entry_idxs)
    eq = 100.0; shares = 0.0; cash = 100.0; curve = []; trades = 0
    exit_ord = None; ep_start = 100.0; halts = 0; halt_until = None; dead = False
    for i, b in enumerate(spy):
        o = date.fromisoformat(b["d"]).toordinal()
        if shares > 0 and exit_ord is not None and o >= exit_ord:
            cash = shares * b["o"] * (1 - STOCK_COST) - SELL_FEE; shares = 0.0; trades += 1
        if halt_until and b["d"] >= halt_until: halt_until = None; ep_start = cash
        if not dead and halt_until is None and shares == 0 and i in entry_set:
            shares = cash * (1 - STOCK_COST) / b["o"]; cash = 0.0
            exit_ord = (date.fromisoformat(b["d"]) + timedelta(days=365)).toordinal()
        eq = cash + shares * b["c"]
        if floor and shares > 0 and eq < 0.85 * ep_start:
            cash = shares * b["c"] * (1 - STOCK_COST) - SELL_FEE; shares = 0.0; trades += 1; halts += 1
            if halts == 1: halt_until = (date.fromisoformat(b["d"]) + timedelta(days=90)).isoformat(); eq = cash
            else: dead = True; eq = cash
        curve.append((b["d"], round(eq, 4)))
    if shares > 0:
        cash = shares * spy[-1]["c"] * (1 - STOCK_COST) - SELL_FEE
        curve[-1] = (curve[-1][0], round(cash, 4)); trades += 1
    return {"final": round(curve[-1][1], 2), "curve": curve, "trades": trades}

def main():
    spy, _ = load_bars("SPY")
    sig = build_ad(spy)
    # entries: first trigger day of each cluster, only when flat — approximated by
    # cluster starts (a new cluster = trigger after >=1 non-trigger day); the
    # runner itself ignores entries while holding.
    entries = [i for i in range(1, len(spy)) if sig[i] and not sig[i-1]]
    res = {"family": "hunt-deemer-breakaway-momentum",
           "signal_clusters_total": len(entries),
           "signal_dates": [spy[i]["d"] for i in entries]}
    curves = {}
    for road, (s, e) in ROADS.items():
        i0 = next(i for i, b in enumerate(spy) if b["d"] >= s)
        i1 = max(i for i, b in enumerate(spy) if b["d"] <= e)
        sub_entries = [i - i0 + 0 for i in entries if i0 <= i <= i1]
        seg = spy[i0:i1+1]
        # entries relative to segment: entry executes at that day's open (day after signal close = signal idx+1)
        ent = sorted({min(x + 1, len(seg) - 1) for x in sub_entries})
        nat = run_events(seg, ent, floor=False)
        hou = run_events(seg, ent, floor=True)
        bh = buyhold(seg, s, e)
        res[road] = {"native_final": nat["final"], "house_final": hou["final"], "buyhold_final": bh["final"],
                     "entries_in_road": len(ent), "trades": nat["trades"], "maxdd_pct": max_dd(nat["curve"]),
                     "periods_monthly_native": period_stats(nat["curve"], "monthly")}
        curves[road] = {"native": nat["curve"], "house": hou["curve"]}
    res["curves"] = curves
    pl = {}
    for road in ["DECADE", "VAL"]:
        s, e = ROADS[road]
        i0 = next(i for i, b in enumerate(spy) if b["d"] >= s); i1 = max(i for i, b in enumerate(spy) if b["d"] <= e)
        seg = spy[i0:i1+1]; k = res[road]["entries_in_road"]; finals = []
        for seed in range(1, 21):
            rng = random.Random(seed * 31 + len(road))
            ent = sorted(rng.sample(range(len(seg)), k)) if k else []
            finals.append(run_events(seg, ent, floor=False)["final"])
        pl[road] = {"median": round(statistics.median(finals), 2),
                    "n_beaten_by_native": sum(1 for f in finals if res[road]["native_final"] > f), "finals": finals}
    res["placebos"] = pl
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print({r: res[r] for r in ROADS}); print("clusters:", len(entries), res["signal_dates"]); print(pl)

if __name__ == "__main__": main()
