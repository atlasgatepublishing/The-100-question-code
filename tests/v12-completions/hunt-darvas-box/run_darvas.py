#!/usr/bin/env python3
"""Darvas Box — frozen construction (SPEC-FROZEN.md). Simulation only.
Box: upper rail H confirmed after 3 consecutive days failing to touch/exceed
H; lower rail L = lowest low after that, confirmed after 3 days failing to
touch/break L. Breakout: intraday break above H (+0.1% tick translation),
volume >= 1.5x prior-20d average (CONSTRUCTED), SPY > SMA200 gate
(CONSTRUCTED from his market rule), candidate within 5% of cache-history
high. Earnings leg omitted for all pond names (spec prints this omission;
bias flatters). Stop: just below broken rail, trailing to just below the
lower rail of the most recent completed box. Box void on close below L or
6 months without breakout. Basket: max-5 native (CONSTRUCTED portfolio),
equal slots; holdings grid in grid/. Native no floor; house v9 pair.
Coins: price/volume legs only, per-coin, crypto costs (earnings leg N/A)."""
import json, os, statistics, sys
sys.path.insert(0, "/tmp/hs2")
from common import *
from eventlib import run_trades
from basketlib import run_basket

HERE = os.path.dirname(os.path.abspath(__file__))
POND = ["AAPL","MSFT","AMZN","GOOGL","META","BRK-B","JPM","XOM","JNJ","PG","V","WMT","HD","BAC","CVX","PFE","VZ","T","DIS","NFLX","INTC","CSCO","GE","IBM","MMM","UNH","MA","KO","PEP","WFC"]
COUNTS = [1, 2, 3, 5, 8, 10, 15, 20, 30, "ALL"]

def darvas_trades(bars, gate_state=None):
    n = len(bars); H_ = [b["h"] for b in bars]; L_ = [b["l"] for b in bars]; C = [b["c"] for b in bars]; V = [b["v"] for b in bars]
    trades = []
    phase = "seek_top"; H = None; cnt = 0; L = None; box_done_i = None; ath = 0.0
    stop = None; in_pos = False; cur = None; boxes_while_held = []
    i = 0
    while i < n:
        ath = max(ath, H_[i])
        if not in_pos:
            if phase == "seek_top":
                if H is None or H_[i] > H: H = H_[i]; cnt = 0
                elif H_[i] < H:
                    cnt += 1
                    if cnt == 3: phase = "seek_bot"; L = None; cnt = 0
            elif phase == "seek_bot":
                if L is None or L_[i] < L: L = L_[i]; cnt = 0
                elif L_[i] > L:
                    cnt += 1
                    if cnt == 3: phase = "watch"; box_done_i = i
                if H_[i] > H: phase = "seek_top"; H = H_[i]; cnt = 0  # new rise restarts
            elif phase == "watch":
                if C[i] < L or i - box_done_i > 126: phase = "seek_top"; H = H_[i]; cnt = 0
                elif H_[i] > H * 1.001:
                    v20 = sum(V[i-20:i]) / 20 if i >= 20 and sum(V[i-20:i]) > 0 else None
                    gate_ok = True if gate_state is None else bool(gate_state[i])
                    if v20 and V[i] >= 1.5 * v20 and gate_ok and H >= 0.95 * ath:
                        entry_px = H * 1.001
                        cur = {"entry_i": i, "entry_px": entry_px, "sig_i": box_done_i}
                        stop = H * 0.999; in_pos = True
                        phase = "seek_top"; H = None; cnt = 0; L = None
        else:
            # trailing box formation while held (fresh box cycle)
            if phase == "seek_top":
                if H is None or H_[i] > H: H = H_[i]; cnt = 0
                elif H_[i] < H:
                    cnt += 1
                    if cnt == 3: phase = "seek_bot"; L = None; cnt = 0
            elif phase == "seek_bot":
                if L is None or L_[i] < L: L = L_[i]; cnt = 0
                elif L_[i] > L:
                    cnt += 1
                    if cnt == 3:
                        stop = max(stop, L * 0.999); phase = "seek_top"; H = None; cnt = 0
                if H_[i] > (H or 0): phase = "seek_top"; H = H_[i]; cnt = 0
            if L_[i] < stop:
                cur.update({"exit_i": i, "exit_px": stop, "exit_at": "intra"})
                trades.append(cur); cur = None; in_pos = False
                phase = "seek_top"; H = None; cnt = 0; L = None
        i += 1
    if cur is not None:
        cur.update({"exit_i": n - 1, "exit_px": C[n-1], "exit_at": "close"}); trades.append(cur)
    return trades

def main():
    res = {"family": "hunt-darvas-box", "earnings_leg": "OMITTED for all names (printed per spec; bias flatters)"}
    spy, _ = load_bars("SPY")
    spy_c = [b["c"] for b in spy]; s200 = sma(spy_c, 200)
    gate_by_date = {spy[i]["d"]: (1 if s200[i] and spy_c[i] > s200[i] else 0) for i in range(len(spy))}
    bars_by = {}; trades_by = {}
    for t in POND:
        bars, _ = load_bars(t); bars_by[t] = bars
        gate = [gate_by_date.get(b["d"], 0) for b in bars]
        trades_by[t] = darvas_trades(bars, gate)
    res["total_trades_pond"] = sum(len(v) for v in trades_by.values())
    # native basket (5) + house, all roads
    out = {}
    for road, (s, e) in ROADS.items():
        nat = run_basket(bars_by, trades_by, s, e, 5, floor=False)
        hou = run_basket(bars_by, trades_by, s, e, 5, floor=True)
        bh = buyhold(spy, s, e)
        out[road] = {"native_final": nat["final"], "house_final": hou["final"], "buyhold_spy": bh["final"],
                     "trades": nat["trades"], "maxdd_pct": max_dd(nat["curve"]),
                     "periods_monthly_native": period_stats(nat["curve"], "monthly"), "curve_native": nat["curve"]}
    res["basket5"] = out
    # per-asset native (context)
    pa = {}
    for t in POND:
        pa[t] = {r: run_trades(bars_by[t], trades_by[t], *ROADS[r], floor=False)["final"] for r in ROADS}
    res["per_asset_median_native"] = {r: round(statistics.median([pa[t][r] for t in pa]), 2) for r in ROADS}
    # grid
    os.makedirs(os.path.join(HERE, "grid"), exist_ok=True)
    grid = {}
    for road in ["DECADE", "VAL"]:
        s, e = ROADS[road]; grid[road] = {}
        for cnt in COUNTS:
            slots = 30 if cnt == "ALL" else cnt
            nat = run_basket(bars_by, trades_by, s, e, slots, floor=False)
            hou = run_basket(bars_by, trades_by, s, e, slots, floor=True)
            grid[road][str(cnt)] = {"native": nat["final"], "house": hou["final"]}
    json.dump(grid, open(os.path.join(HERE, "grid", "grid_results.json"), "w"), indent=1)
    res["grid"] = grid
    # placebos: random-name twins at count 5, DECADE — shift each asset's trades by random offset is complex;
    # use random entry dates matched on total trade count with per-asset random exits at the asset's median hold.
    import random
    finals = []
    all_tr = [(t, tr) for t, trs in trades_by.items() for tr in trs]
    holds = [tr["exit_i"] - tr["entry_i"] for _, tr in all_tr] or [10]
    med_hold = int(statistics.median(holds))
    s, e = ROADS["DECADE"]
    for seed in range(1, 21):
        rng = random.Random(seed * 3)
        ptr = {}
        for t in POND:
            bars = bars_by[t]
            didx = [i for i, b in enumerate(bars) if s <= b["d"] <= e]
            k = sum(1 for tt, tr in all_tr if tt == t and s <= bars[tr["entry_i"]]["d"] <= e)
            ents = sorted(rng.sample(didx[:-med_hold-1], min(k, max(0, len(didx) - med_hold - 1)))) if k else []
            ptr[t] = [{"entry_i": i, "entry_px": bars[i]["c"], "exit_i": i + med_hold,
                       "exit_px": bars[i + med_hold]["c"], "exit_at": "close", "sig_i": i} for i in ents]
        finals.append(run_basket(bars_by, ptr, s, e, 5, floor=False)["final"])
    res["placebos_basket5_DECADE"] = {"median": round(statistics.median(finals), 2),
        "n_beaten_by_native": sum(1 for f in finals if out["DECADE"]["native_final"] > f), "finals": finals}
    # crypto: price/volume legs only, per-coin all-in form
    coins = load_crypto(); cres = {}
    for sym, cd in coins.items():
        bars = crypto_bars(cd["rows"])
        if len(bars) < 300: continue
        ctr = darvas_trades(bars, None)
        nat = run_trades(bars, ctr, "2017-01-01", END, cost=CRYPTO_COST, fee=0.0, floor=False)
        val = run_trades(bars, ctr, "2023-01-03", END, cost=CRYPTO_COST, fee=0.0, floor=False)
        bh = buyhold(bars, "2017-01-01", END, cost=CRYPTO_COST, sell_fee=0.0)
        if nat and bh: cres[sym] = {"full_native": nat["final"], "full_buyhold": bh["final"],
                                    "val_native": val["final"] if val else None, "trades": nat["trades"], "first": bars[0]["d"]}
    res["crypto"] = cres
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("basket5:", {r: out[r]["native_final"] for r in ROADS}, "trades pond:", res["total_trades_pond"])
    print("grid DECADE:", grid["DECADE"]); print("placebo:", res["placebos_basket5_DECADE"]["median"], res["placebos_basket5_DECADE"]["n_beaten_by_native"])
    print("crypto:", len(cres), "BTC:", cres.get("BTC"))

if __name__ == "__main__": main()
