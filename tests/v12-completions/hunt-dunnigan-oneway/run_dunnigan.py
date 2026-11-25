#!/usr/bin/env python3
"""Dunnigan One-Way Formula — frozen construction (SPEC-FROZEN.md). CONSTRUCTED.
Swing engine PUBLISHED: bars classified vs previous non-ignored bar (up =
higher high AND higher low; down = mirror; inside/outside IGNORED).
Swing top = high of last up bar before first down bar; bottom = mirror.
Maintrend CONSTRUCTED: UP while latest swing top > prior top AND latest
swing bottom > prior bottom; DOWN mirror; else UNDEFINED.
Reversal entry: close penetrates most recent swing top in DOWN/UNDEFINED
trend -> long at next open. Repeat entry: while UP and flat after a stop
exit, close above most recent swing top -> re-enter next open.
Stop: exit at close below most recent swing bottom (ratchets).
Long-only (mirror = exit to cash, printed adaptation). Per-asset + SPY;
basket max-5 ranked by signal recency (frozen) + holdings grid in grid/.
Native no floor; house v9 pair. Coins: mechanical port, per-coin.
Placebos: 20 seeds random entries matched on count, exit at swing-bottom
stop of a random twin (SPY, DECADE) — approximated by 40-day max hold."""
import json, os, random, statistics, sys
sys.path.insert(0, "/tmp/hs2")
from common import *
from eventlib import run_trades
from basketlib import run_basket

HERE = os.path.dirname(os.path.abspath(__file__))
POND = ["AAPL","MSFT","AMZN","GOOGL","META","BRK-B","JPM","XOM","JNJ","PG","V","WMT","HD","BAC","CVX","PFE","VZ","T","DIS","NFLX","INTC","CSCO","GE","IBM","MMM","UNH","MA","KO","PEP","WFC"]
COUNTS = [1, 2, 3, 5, 8, 10, 15, 20, 30, "ALL"]

def dunnigan_trades(bars):
    n = len(bars); H = [b["h"] for b in bars]; L = [b["l"] for b in bars]; C = [b["c"] for b in bars]; O = [b["o"] for b in bars]
    trades = []
    # accepted-bar swing construction
    tops = []   # (confirm_i, value)
    bots = []
    last = 0    # index of last accepted bar
    run_dir = 0  # +1 upswing, -1 downswing
    run_extreme = None; run_extreme_i = None
    in_pos = False; cur = None; stopped_out = False
    latest_top = None; latest_bot = None
    for i in range(1, n):
        # classify bar i vs last accepted bar
        if H[i] > H[last] and L[i] > L[last]: cls = 1
        elif H[i] < H[last] and L[i] < L[last]: cls = -1
        else: cls = 0  # inside or outside -> ignored
        if cls != 0:
            if run_dir == 0:
                run_dir = cls; run_extreme = H[i] if cls == 1 else L[i]; run_extreme_i = i
            elif cls == run_dir:
                if cls == 1 and H[i] > run_extreme: run_extreme = H[i]; run_extreme_i = i
                if cls == -1 and L[i] < run_extreme: run_extreme = L[i]; run_extreme_i = i
            else:
                # swing point confirmed
                if run_dir == 1: tops.append((i, run_extreme)); latest_top = run_extreme
                else: bots.append((i, run_extreme)); latest_bot = run_extreme
                run_dir = cls; run_extreme = H[i] if cls == 1 else L[i]; run_extreme_i = i
            last = i
        # maintrend
        trend = None
        if len(tops) >= 2 and len(bots) >= 2:
            if tops[-1][1] > tops[-2][1] and bots[-1][1] > bots[-2][1]: trend = "UP"
            elif tops[-1][1] < tops[-2][1] and bots[-1][1] < bots[-2][1]: trend = "DOWN"
            else: trend = "UNDEF"
        elif latest_top is not None: trend = "UNDEF"
        if in_pos:
            if latest_bot is not None and C[i] < latest_bot:
                cur.update({"exit_i": i, "exit_px": C[i], "exit_at": "close"})
                trades.append(cur); cur = None; in_pos = False; stopped_out = True
        else:
            if latest_top is not None and C[i] > latest_top and i + 1 < n:
                if trend in ("DOWN", "UNDEF") or (trend == "UP" and stopped_out):
                    cur = {"entry_i": i + 1, "entry_px": O[i+1], "sig_i": i}
                    in_pos = True; stopped_out = False
    if cur is not None:
        cur.update({"exit_i": n - 1, "exit_px": C[n-1], "exit_at": "close"}); trades.append(cur)
    return trades

def main():
    res = {"family": "hunt-dunnigan-oneway", "label": "CONSTRUCTED throughout"}
    spy, _ = load_bars("SPY")
    str_ = dunnigan_trades(spy)
    res["spy"] = {}
    curves = {}
    for road, (s, e) in ROADS.items():
        nat = run_trades(spy, str_, s, e, floor=False)
        hou = run_trades(spy, str_, s, e, floor=True, restart=True)
        res["spy"][road] = {"native_final": nat["final"], "house_final": hou["final"], "trades": nat["trades"],
                            "maxdd_pct": max_dd(nat["curve"]), "periods_monthly_native": period_stats(nat["curve"], "monthly")}
        curves[road] = nat["curve"]
    res["spy_curves"] = curves
    bars_by = {}; trades_by = {}
    for t in POND:
        bars, _ = load_bars(t); bars_by[t] = bars; trades_by[t] = dunnigan_trades(bars)
    res["total_trades_pond"] = sum(len(v) for v in trades_by.values())
    out = {}
    for road, (s, e) in ROADS.items():
        nat = run_basket(bars_by, trades_by, s, e, 5, floor=False, priority="recent")
        hou = run_basket(bars_by, trades_by, s, e, 5, floor=True, priority="recent")
        out[road] = {"native_final": nat["final"], "house_final": hou["final"], "trades": nat["trades"],
                     "maxdd_pct": max_dd(nat["curve"]), "periods_monthly_native": period_stats(nat["curve"], "monthly"),
                     "curve_native": nat["curve"]}
    res["basket5"] = out
    os.makedirs(os.path.join(HERE, "grid"), exist_ok=True)
    grid = {}
    for road in ["DECADE", "VAL"]:
        s, e = ROADS[road]; grid[road] = {}
        for cnt in COUNTS:
            slots = 30 if cnt == "ALL" else cnt
            nat = run_basket(bars_by, trades_by, s, e, slots, floor=False, priority="recent")
            hou = run_basket(bars_by, trades_by, s, e, slots, floor=True, priority="recent")
            grid[road][str(cnt)] = {"native": nat["final"], "house": hou["final"]}
    json.dump(grid, open(os.path.join(HERE, "grid", "grid_results.json"), "w"), indent=1)
    res["grid"] = grid
    # placebos SPY DECADE: random entries, 40-day holds
    s, e = ROADS["DECADE"]; ntr = res["spy"]["DECADE"]["trades"]
    didx = [i for i, b in enumerate(spy) if s <= b["d"] <= e]
    finals = []
    for seed in range(1, 21):
        rng = random.Random(seed * 11)
        ents = sorted(rng.sample(didx[:-41], min(ntr, len(didx) - 41)))
        trs = [{"entry_i": i, "entry_px": spy[i]["o"], "exit_i": i + 40, "exit_px": spy[i+40]["c"], "exit_at": "close"} for i in ents]
        finals.append(run_trades(spy, trs, s, e, floor=False)["final"])
    res["placebos_spy_DECADE"] = {"median": round(statistics.median(finals), 2),
        "n_beaten_by_native": sum(1 for f in finals if res["spy"]["DECADE"]["native_final"] > f), "finals": finals}
    coins = load_crypto(); cres = {}
    for sym, cd in coins.items():
        bars = crypto_bars(cd["rows"])
        if len(bars) < 300: continue
        ctr = dunnigan_trades(bars)
        nat = run_trades(bars, ctr, "2017-01-01", END, cost=CRYPTO_COST, fee=0.0, floor=False)
        val = run_trades(bars, ctr, "2023-01-03", END, cost=CRYPTO_COST, fee=0.0, floor=False)
        bh = buyhold(bars, "2017-01-01", END, cost=CRYPTO_COST, sell_fee=0.0)
        if nat and bh: cres[sym] = {"full_native": nat["final"], "full_buyhold": bh["final"],
                                    "val_native": val["final"] if val else None, "trades": nat["trades"], "first": bars[0]["d"]}
    res["crypto"] = cres
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("SPY:", {r: res["spy"][r]["native_final"] for r in ROADS})
    print("basket5:", {r: out[r]["native_final"] for r in ROADS}, "pond trades:", res["total_trades_pond"])
    print("grid DECADE:", grid["DECADE"]); print("placebo:", res["placebos_spy_DECADE"])
    print("crypto:", len(cres), "BTC:", cres.get("BTC"))

if __name__ == "__main__": main()
