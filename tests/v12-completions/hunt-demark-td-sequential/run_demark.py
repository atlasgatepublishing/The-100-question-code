#!/usr/bin/env python3
"""DeMark TD Sequential — frozen form (SPEC-FROZEN.md). Simulation only.
Buy setup: 9 consecutive closes < close 4 bars earlier. Intersection required
(high of setup bar 8/9 >= low of any setup bar 3-7). Countdown: bars with
close <= low 2 bars earlier count to 13 (bar-13 qualifier: its low <= close
of countdown bar 8, else defer at 12). Cancellation: opposite setup completes
or close above span high (TDST). Entry: FROZEN option (2) — first price flip
(close > close 4 bars earlier) after countdown-13, at that close.
Stop: lowest low of setup+countdown span - 0.1% (CONSTRUCTED tick), intraday
breach fills at stop. Exit: stop, or close on completion of opposite 9-setup.
Long-only translation. Per-asset pond + SPY + per-coin. Native no floor;
house v9 pair on stocks. Placebos: 20 seeds random entries matched on trade
count, exit = opposite setup or 60-day max hold (SPY, DECADE)."""
import json, os, random, statistics, sys
sys.path.insert(0, "/tmp/hs2")
from common import *
from eventlib import run_trades

HERE = os.path.dirname(os.path.abspath(__file__))
POND = ["AAPL","MSFT","AMZN","GOOGL","META","BRK-B","JPM","XOM","JNJ","PG","V","WMT","HD","BAC","CVX","PFE","VZ","T","DIS","NFLX","INTC","CSCO","GE","IBM","MMM","UNH","MA","KO","PEP","WFC"]

def demark_trades(bars):
    n = len(bars); C = [b["c"] for b in bars]; H = [b["h"] for b in bars]; L = [b["l"] for b in bars]
    trades = []
    # precompute setup completion flags
    def setup_series(kind):
        cnt = 0; done = [False]*n; span_start = [None]*n
        start = None
        for i in range(4, n):
            ok = (C[i] < C[i-4]) if kind == "buy" else (C[i] > C[i-4])
            if ok:
                if cnt == 0: start = i
                cnt += 1
                if cnt == 9:
                    done[i] = True; span_start[i] = start; cnt = 0
            else: cnt = 0
        return done, span_start
    buy_done, buy_start = setup_series("buy")
    sell_done, _ = setup_series("sell")
    i = 0
    while i < n:
        if not buy_done[i]: i += 1; continue
        s0 = buy_start[i]
        # intersection: high of bars 8/9 (indices s0+7, s0+8) >= low of any bar 3..7 (s0+2..s0+6)
        inter = max(H[s0+7], H[s0+8]) >= min(L[s0+2:s0+7])
        if not inter: i += 1; continue
        span_hi = max(H[s0:i+1]); span_lo = min(L[s0:i+1])
        # countdown
        cd = 0; cd8_close = None; j = i + 1; completed = None
        while j < n:
            if sell_done[j]: break  # cancellation: opposite setup
            if C[j] > span_hi: break  # TDST cancellation
            if buy_done[j]:  # recycling: restart countdown from new setup
                s0b = buy_start[j]
                if max(H[s0b+7], H[s0b+8]) >= min(L[s0b+2:s0b+7]):
                    s0 = s0b; i_cd_start = j; span_hi = max(H[s0:j+1]); span_lo = min(L[s0:j+1])
                    cd = 0; cd8_close = None
                j += 1; continue
            if j >= 2 and C[j] <= L[j-2]:
                if cd == 12:
                    if cd8_close is not None and L[j] <= cd8_close:
                        cd = 13; completed = j
                    # else defer at 12
                else:
                    cd += 1
                    if cd == 8: cd8_close = C[j]
                    if cd == 13: completed = j
            span_hi = max(span_hi, H[j]); span_lo = min(span_lo, L[j])
            if completed is not None: break
            j += 1
        if completed is None: i = max(j, i + 1); continue
        stop = span_lo * 0.999
        # entry: first price flip after countdown-13
        k = completed + 1; entry = None
        while k < n:
            if sell_done[k]: break
            if C[k] > span_hi: break
            if k >= 4 and C[k] > C[k-4]: entry = k; break
            if L[k] < stop: break
            k += 1
        if entry is None: i = k; continue
        # hold: exit on stop breach (intraday) or sell setup completion (close)
        exit_i, exit_px, at = n - 1, C[n-1], "close"
        for m in range(entry + 1, n):
            if L[m] < stop: exit_i, exit_px, at = m, stop, "intra"; break
            if sell_done[m]: exit_i, exit_px, at = m, C[m], "close"; break
        trades.append({"entry_i": entry, "entry_px": C[entry], "exit_i": exit_i, "exit_px": exit_px, "exit_at": at})
        i = exit_i + 1
    return trades

def main():
    res = {"family": "hunt-demark-td-sequential"}
    spy, _ = load_bars("SPY")
    tr = demark_trades(spy)
    res["spy"] = {}
    curves = {}
    for road, (s, e) in ROADS.items():
        nat = run_trades(spy, tr, s, e, floor=False)
        hou = run_trades(spy, tr, s, e, floor=True, restart=True)
        res["spy"][road] = {"native_final": nat["final"], "house_final": hou["final"], "trades": nat["trades"],
                            "maxdd_pct": max_dd(nat["curve"]), "periods_monthly_native": period_stats(nat["curve"], "monthly")}
        curves[road] = nat["curve"]
    res["spy_curves"] = curves; res["spy_total_trades_all_history"] = len(tr)
    pond = {}
    for t in POND:
        bars, _ = load_bars(t); ttr = demark_trades(bars)
        pond[t] = {r: run_trades(bars, ttr, *ROADS[r], floor=False)["final"] for r in ROADS}
    res["pond_native"] = pond
    res["pond_median_native"] = {r: round(statistics.median([pond[t][r] for t in pond]), 2) for r in ROADS}
    # placebos SPY DECADE
    s, e = ROADS["DECADE"]; ntr = res["spy"]["DECADE"]["trades"]
    didx = [i for i, b in enumerate(spy) if s <= b["d"] <= e]
    finals = []
    for seed in range(1, 21):
        rng = random.Random(seed * 19)
        ents = sorted(rng.sample(didx[:-61], min(ntr, len(didx) - 61)))
        trs = [{"entry_i": i, "entry_px": spy[i]["c"], "exit_i": i + 60, "exit_px": spy[i+60]["c"], "exit_at": "close"} for i in ents]
        finals.append(run_trades(spy, trs, s, e, floor=False)["final"])
    res["placebos_spy_DECADE"] = {"median": round(statistics.median(finals), 2),
        "n_beaten_by_native": sum(1 for f in finals if res["spy"]["DECADE"]["native_final"] > f), "finals": finals}
    coins = load_crypto(); cres = {}
    for sym, cd in coins.items():
        bars = crypto_bars(cd["rows"])
        if len(bars) < 300: continue
        ctr = demark_trades(bars)
        nat = run_trades(bars, ctr, "2017-01-01", END, cost=CRYPTO_COST, fee=0.0, floor=False)
        val = run_trades(bars, ctr, "2023-01-03", END, cost=CRYPTO_COST, fee=0.0, floor=False)
        bh = buyhold(bars, "2017-01-01", END, cost=CRYPTO_COST, sell_fee=0.0)
        if nat and bh: cres[sym] = {"full_native": nat["final"], "full_buyhold": bh["final"],
                                    "val_native": val["final"] if val else None, "trades": nat["trades"], "first": bars[0]["d"]}
    res["crypto"] = cres
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("SPY:", {r: res["spy"][r]["native_final"] for r in ROADS}, "trades hist:", len(tr))
    print("pond median:", res["pond_median_native"]); print("placebo:", res["placebos_spy_DECADE"]["median"], res["placebos_spy_DECADE"]["n_beaten_by_native"])
    print("crypto:", len(cres), "BTC:", cres.get("BTC"))

if __name__ == "__main__": main()
