#!/usr/bin/env python3
"""Cooper Expansion Breakout — frozen form (SPEC-FROZEN.md). Simulation only.
Setup: new 40-session high, range widest of last 10, close in top 25%.
Entry next session only: buy stop at setup high x1.001 (CONSTRUCTED tick
translation). Stop: setup-day low. Exits: stop / +7% intraday target
(CONSTRUCTED within published 3-7% range) / close of session 3 after entry.
Conservative same-bar convention: if a bar hits both stop and target, stop.
Per-asset pond runs + SPY + per-coin mechanical port. Native no floor;
house v9 pair on stocks. Placebos: 20 seeds random entry days matched on
trade count per asset (SPY + pond median, DECADE)."""
import json, os, random, statistics, sys
sys.path.insert(0, "/tmp/hs2")
from common import *
from eventlib import run_trades

HERE = os.path.dirname(os.path.abspath(__file__))
POND = ["AAPL","MSFT","AMZN","GOOGL","META","BRK-B","JPM","XOM","JNJ","PG","V","WMT","HD","BAC","CVX","PFE","VZ","T","DIS","NFLX","INTC","CSCO","GE","IBM","MMM","UNH","MA","KO","PEP","WFC"]

def cooper_trades(bars):
    trades = []; i = 40; n = len(bars); busy_until = -1
    while i < n - 1:
        if i <= busy_until: i += 1; continue
        b = bars[i]
        hi40 = max(x["h"] for x in bars[i-40:i])
        rng = b["h"] - b["l"]
        rng10 = max(x["h"] - x["l"] for x in bars[i-9:i+1])
        if b["h"] > hi40 and rng >= rng10 and rng > 0 and (b["c"] - b["l"]) / rng >= 0.75:
            trig = b["h"] * 1.001; stop = b["l"]; e = bars[i+1]
            if e["h"] >= trig:
                entry_px = max(trig, e["o"]) if e["o"] > trig else trig
                target = entry_px * 1.07
                exit_i, exit_px, at = i + 4 if i + 4 < n else n - 1, None, "close"
                exit_px = bars[exit_i]["c"]
                for j in range(i + 1, min(i + 5, n)):
                    bj = bars[j]
                    lo = bj["l"] if j > i + 1 else min(bj["l"], entry_px)  # entry day: only post-entry path unknown; conservative
                    if bj["l"] <= stop:
                        exit_i, exit_px, at = j, stop, "intra"; break
                    if bj["h"] >= target:
                        exit_i, exit_px, at = j, target, "intra"; break
                trades.append({"entry_i": i + 1, "entry_px": entry_px, "exit_i": exit_i,
                               "exit_px": exit_px, "exit_at": at})
                busy_until = exit_i
                i = exit_i + 1; continue
        i += 1
    return trades

def asset_runs(bars, cost, fee, restart):
    tr = cooper_trades(bars); out = {}
    for road, (s, e) in ROADS.items():
        nat = run_trades(bars, tr, s, e, cost=cost, fee=fee, floor=False)
        hou = run_trades(bars, tr, s, e, cost=cost, fee=fee, floor=True, restart=restart)
        out[road] = (nat, hou)
    return tr, out

def main():
    res = {"family": "hunt-cooper-expansion-breakout"}
    spy, _ = load_bars("SPY")
    tr, runs = asset_runs(spy, STOCK_COST, SELL_FEE, True)
    res["spy"] = {r: {"native_final": runs[r][0]["final"], "house_final": runs[r][1]["final"],
                      "trades": runs[r][0]["trades"], "maxdd_pct": max_dd(runs[r][0]["curve"]),
                      "periods_monthly_native": period_stats(runs[r][0]["curve"], "monthly")} for r in ROADS}
    res["spy_curves"] = {r: {"native": runs[r][0]["curve"]} for r in ROADS}
    res["spy_total_setups_traded"] = len(tr)
    pond = {}
    for t in POND:
        bars, _ = load_bars(t)
        _, rr = asset_runs(bars, STOCK_COST, SELL_FEE, True)
        pond[t] = {r: {"native": rr[r][0]["final"], "house": rr[r][1]["final"], "trades": rr[r][0]["trades"]} for r in ROADS}
    res["pond"] = pond
    res["pond_median_native"] = {r: round(statistics.median([pond[t][r]["native"] for t in pond]), 2) for r in ROADS}
    # placebos DECADE: random entry days matched on SPY trade count, 3-day hold at closes
    s, e = ROADS["DECADE"]; finals = []
    ntr = res["spy"]["DECADE"]["trades"]
    didx = [i for i, b in enumerate(spy) if s <= b["d"] <= e]
    for seed in range(1, 21):
        rng = random.Random(seed * 7)
        ents = sorted(rng.sample(didx[:-4], min(ntr, len(didx) - 4)))
        trs = [{"entry_i": i, "entry_px": spy[i]["o"], "exit_i": i + 3, "exit_px": spy[i+3]["c"], "exit_at": "close"} for i in ents]
        finals.append(run_trades(spy, trs, s, e, floor=False)["final"])
    res["placebos_spy_DECADE"] = {"median": round(statistics.median(finals), 2),
        "n_beaten_by_native": sum(1 for f in finals if res["spy"]["DECADE"]["native_final"] > f), "finals": finals}
    # crypto
    coins = load_crypto(); cres = {}
    for sym, cd in coins.items():
        bars = crypto_bars(cd["rows"])
        if len(bars) < 300: continue
        ctr = cooper_trades(bars)
        nat = run_trades(bars, ctr, "2017-01-01", END, cost=CRYPTO_COST, fee=0.0, floor=False)
        val = run_trades(bars, ctr, "2023-01-03", END, cost=CRYPTO_COST, fee=0.0, floor=False)
        bh = buyhold(bars, "2017-01-01", END, cost=CRYPTO_COST, sell_fee=0.0)
        if nat and bh: cres[sym] = {"full_native": nat["final"], "full_buyhold": bh["final"],
                                    "val_native": val["final"] if val else None, "trades": nat["trades"], "first": bars[0]["d"]}
    res["crypto"] = cres
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("SPY:", {r: res["spy"][r]["native_final"] for r in ROADS}, "pond median:", res["pond_median_native"])
    print("placebo:", res["placebos_spy_DECADE"]); print("crypto:", len(cres))

if __name__ == "__main__": main()
