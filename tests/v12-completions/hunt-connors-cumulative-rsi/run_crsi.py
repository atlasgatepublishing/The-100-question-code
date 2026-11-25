#!/usr/bin/env python3
"""Connors Cumulative RSI — frozen form (SPEC-FROZEN.md). Simulation only.
Entry: close > SMA200 AND CRSI(2-day sum of RSI(2)) < 35, at signal close.
Exit: RSI(2) > 65, at signal close. No stop native. House = v9 floor pair.
Runs: SPY headline + pond-30 per-asset + crypto per-coin (mechanical port).
Costs: stocks 0.10%/side + $0.01/sell; crypto 0.60%/side.
Placebos: 20 seeds, entry threshold U[25,45], exit threshold U[55,75] (SPY, DECADE+VAL)."""
import json, os, random, statistics, sys
sys.path.insert(0, "/tmp/hs2")
from common import *

HERE = os.path.dirname(os.path.abspath(__file__))
POND = ["AAPL","MSFT","AMZN","GOOGL","META","BRK-B","JPM","XOM","JNJ","PG","V","WMT","HD","BAC","CVX","PFE","VZ","T","DIS","NFLX","INTC","CSCO","GE","IBM","MMM","UNH","MA","KO","PEP","WFC"]

def crsi_state(bars, entry_thr=35.0, exit_thr=65.0):
    closes = [b["c"] for b in bars]
    s200 = sma(closes, 200); r2 = rsi_wilder(closes, 2)
    state = [0]*len(bars); pos = 0
    for i in range(len(bars)):
        if pos == 0:
            if i >= 1 and s200[i] and r2[i] is not None and r2[i-1] is not None:
                if closes[i] > s200[i] and (r2[i] + r2[i-1]) < entry_thr: pos = 1
        else:
            if r2[i] is not None and r2[i] > exit_thr: pos = 0
        state[i] = pos
    return state

def run_asset(bars, cost, fee, floor_pair=True):
    st = crsi_state(bars)
    out = {}
    for road, (s, e) in ROADS.items():
        nat = run_state_timer(bars, st, s, e, cost=cost, sell_fee=fee, floor=False)
        hou = run_state_timer(bars, st, s, e, cost=cost, sell_fee=fee, floor=True, restart=True) if floor_pair else None
        bh = buyhold(bars, s, e, cost=cost, sell_fee=fee)
        out[road] = {"native": nat, "house": hou, "buyhold": bh}
    return out, st

def main():
    res = {"family": "hunt-connors-cumulative-rsi", "spec": "CRSI<35 entry w/ 200d filter; RSI(2)>65 exit; close-entry"}
    spy, _ = load_bars("SPY")
    spy_runs, spy_state = run_asset(spy, STOCK_COST, SELL_FEE)
    res["spy"] = {r: {"native_final": v["native"]["final"], "house_final": v["house"]["final"],
                      "buyhold_final": v["buyhold"]["final"], "native_trades": v["native"]["trades"],
                      "native_maxdd_pct": max_dd(v["native"]["curve"]),
                      "periods_monthly_native": period_stats(v["native"]["curve"], "monthly")}
                  for r, v in spy_runs.items()}
    res["spy_curves"] = {r: {"native": v["native"]["curve"], "house": v["house"]["curve"]} for r, v in spy_runs.items()}
    # pond per-asset (native, DECADE + VAL summary)
    pond = {}
    for t in POND:
        try: bars, _ = load_bars(t)
        except Exception: continue
        runs, _ = run_asset(bars, STOCK_COST, SELL_FEE)
        pond[t] = {r: {"native": runs[r]["native"]["final"], "house": runs[r]["house"]["final"],
                       "buyhold": runs[r]["buyhold"]["final"]} for r in ROADS}
    res["pond"] = pond
    for road in ROADS:
        vals = [pond[t][road]["native"] for t in pond]
        res.setdefault("pond_median_native", {})[road] = round(statistics.median(vals), 2)
    # placebos on SPY
    rng_master = random.Random(42)
    pl = {}
    for road in ["DECADE", "VAL"]:
        s, e = ROADS[road]; finals = []
        for seed in range(1, 21):
            rng = random.Random(1000*seed + (0 if road=="DECADE" else 7))
            st = crsi_state(spy, rng.uniform(25, 45), rng.uniform(55, 75))
            r = run_state_timer(spy, st, s, e, floor=False)
            finals.append(r["final"])
        pl[road] = {"median": round(statistics.median(finals), 2),
                    "n_beaten_by_native": sum(1 for f in finals if res["spy"][road]["native_final"] > f),
                    "finals": finals}
    res["placebos_spy"] = pl
    # crypto per-coin mechanical port
    coins = load_crypto(); cres = {}
    for sym, cd in coins.items():
        bars = crypto_bars(cd["rows"])
        if len(bars) < 400: continue
        st = crsi_state(bars)
        nat = run_state_timer(bars, st, "2017-01-01", END, cost=CRYPTO_COST, sell_fee=0.0, floor=False)
        hou = run_state_timer(bars, st, "2017-01-01", END, cost=CRYPTO_COST, sell_fee=0.0, floor=True, restart=False)
        val = run_state_timer(bars, st, "2023-01-03", END, cost=CRYPTO_COST, sell_fee=0.0, floor=False)
        bh = buyhold(bars, "2017-01-01", END, cost=CRYPTO_COST, sell_fee=0.0)
        bhv = buyhold(bars, "2023-01-03", END, cost=CRYPTO_COST, sell_fee=0.0)
        if nat and bh: cres[sym] = {"full_native": nat["final"], "full_house": hou["final"], "full_buyhold": bh["final"],
                                    "val_native": val["final"] if val else None, "val_buyhold": bhv["final"] if bhv else None,
                                    "trades": nat["trades"], "first": bars[0]["d"]}
    res["crypto"] = cres
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print(json.dumps({r: res["spy"][r] for r in ROADS}, indent=1))
    print("pond median native:", res["pond_median_native"])
    print("placebos:", pl)
    print("crypto coins:", len(cres))

if __name__ == "__main__": main()
