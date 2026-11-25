#!/usr/bin/env python3
"""Connors VIX RSI — frozen form (SPEC-FROZEN.md). Simulation only.
SPY long when at close: SPY>SMA200, RSI(2) of VIX > 90, VIX open today >
VIX close yesterday, RSI(2) of SPY < 30. Exit RSI(2) of SPY > 65.
Close entry/exit. No stop native. House = v9 floor. Coins NOT-APPLICABLE.
Placebos: 20 seeds random entry days matched on signal count, exit rule kept."""
import json, os, random, statistics, sys
sys.path.insert(0, "/tmp/hs2")
from common import *

HERE = os.path.dirname(os.path.abspath(__file__))

def main():
    spy, _ = load_bars("SPY"); vix, _ = load_bars("VIX")
    vmap = {b["d"]: b for b in vix}
    closes = [b["c"] for b in spy]; s200 = sma(closes, 200); r2s = rsi_wilder(closes, 2)
    vcloses = [vmap[b["d"]]["c"] if b["d"] in vmap else None for b in spy]
    # VIX RSI on its own series, aligned by date
    vr = rsi_wilder([b["c"] for b in vix], 2); vrmap = {vix[i]["d"]: vr[i] for i in range(len(vix))}
    state = [0]*len(spy); pos = 0; signals = []
    for i, b in enumerate(spy):
        d = b["d"]; vb = vmap.get(d)
        if pos == 0:
            if (s200[i] and r2s[i] is not None and vb and vrmap.get(d) is not None
                    and closes[i] > s200[i] and vrmap[d] > 90 and r2s[i] < 30):
                prev = vix[[x["d"] for x in vix].index(d)-1] if False else None
                # yesterday's VIX close: previous VIX bar
                vi = [j for j, x in enumerate(vix) if x["d"] == d]
                if vi and vi[0] > 0 and vb["o"] > vix[vi[0]-1]["c"]:
                    pos = 1; signals.append(d)
        else:
            if r2s[i] is not None and r2s[i] > 65: pos = 0
        state[i] = pos
    res = {"family": "hunt-connors-vix-rsi", "n_signals_total": len(signals), "signal_dates": signals}
    curves = {}
    for road, (s, e) in ROADS.items():
        nat = run_state_timer(spy, state, s, e, floor=False)
        hou = run_state_timer(spy, state, s, e, floor=True, restart=True)
        bh = buyhold(spy, s, e)
        res[road] = {"native_final": nat["final"], "house_final": hou["final"], "buyhold_final": bh["final"],
                     "trades": nat["trades"], "maxdd_pct": max_dd(nat["curve"]),
                     "periods_monthly_native": period_stats(nat["curve"], "monthly")}
        curves[road] = {"native": nat["curve"], "house": hou["curve"]}
    res["curves"] = curves
    # placebos: random entries matched on in-road signal count, same exit rule
    pl = {}
    for road in ["DECADE", "VAL"]:
        s, e = ROADS[road]
        n_sig = sum(1 for d in signals if s <= d <= e)
        idxs = [i for i, b in enumerate(spy) if s <= b["d"] <= e and s200[i] and closes[i] > s200[i]]
        finals = []
        for seed in range(1, 21):
            rng = random.Random(seed*77 + len(road))
            entries = set(rng.sample(idxs, min(n_sig, len(idxs)))) if n_sig else set()
            st = [0]*len(spy); p = 0
            for i in range(len(spy)):
                if p == 0 and i in entries: p = 1
                elif p == 1 and r2s[i] is not None and r2s[i] > 65: p = 0
                st[i] = p
            finals.append(run_state_timer(spy, st, s, e, floor=False)["final"])
        pl[road] = {"n_signals": n_sig, "median": round(statistics.median(finals), 2),
                    "n_beaten_by_native": sum(1 for f in finals if res[road]["native_final"] > f), "finals": finals}
    res["placebos"] = pl
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print({r: res[r] for r in ROADS}); print("signals:", len(signals)); print(pl)

if __name__ == "__main__": main()
