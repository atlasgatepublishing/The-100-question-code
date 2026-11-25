#!/usr/bin/env python3
"""Appel MACD 12/26/9 signal-line crossover (1979 original) — SPEC-FROZEN exact.
SPY timer (next-open exec) + per-coin port (close-exec, crypto costs). EMA seeded
with first value (standard convention, printed). Signals allowed after 35 bars.
NOTE: as run, this script imported common.py from the ephemeral run cache
/tmp/hunt1 (wiped after the run); common.py is now saved beside this script —
point sys.path at this folder to re-run. Data caches fetched 2026-11-22:
Yahoo chart API (^IXIC/QQQ/indexes), CoinMetrics community API (BTC/ETH),
AAII mirror CSV, FRED GDP — sources named in each family's RESULTS/HUNT-LOG."""
import json, os, sys
sys.path.insert(0, "/tmp/hunt1")
from common import *

HERE = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/hunt-appel-macd")
V4 = os.path.expanduser("~/workspace/stock-app/backtests/v4")

def macd_states(closes):
    e12 = ema_series(closes, 12); e26 = ema_series(closes, 26)
    macd = [a - b for a, b in zip(e12, e26)]
    sig = ema_series(macd, 9)
    states = []; pos = 0
    for i in range(len(closes)):
        if i >= 35:
            if macd[i] > sig[i] and macd[i-1] <= sig[i-1]: pos = 1
            elif macd[i] < sig[i] and macd[i-1] >= sig[i-1]: pos = 0
        states.append(pos)
    return states

out = {"family": "hunt-appel-macd", "ema_seed": "EMA seeded at first close; first signal after 35 bars",
       "holdings_grid": "NOT-APPLICABLE — single-asset timer, no selection", "stocks": {}, "coins": {}}

spy = load_pxfull("SPY"); closes = [b["c"] for b in spy]; st = macd_states(closes)
for road, (s, e) in ROADS.items():
    idx = [i for i, b in enumerate(spy) if s <= b["d"] <= e]
    bars = [spy[i] for i in idx]; states = [st[i] for i in idx]
    nat = sim_open_exec(bars, states); hou = sim_open_exec(bars, states, house=True)
    pls = [sim_open_exec(bars, placebo_shift(states, sd))["final"] for sd in range(1, 21)]
    out["stocks"][road] = {"native": nat, "house": hou, "spy_buyhold": round(buyhold_open(bars), 2),
                           "champion_vm": CHAMP[road], "placebos_beaten": sum(1 for p in pls if nat["final"] > p),
                           "placebo_finals": [round(p, 2) for p in pls],
                           "periods_monthly": period_stats(nat["curve"], "monthly"),
                           "periods_daily": period_stats(nat["curve"], "daily")}

reg = json.load(open(os.path.join(V4, "crypto-basket-pit-results.json")))["registry"]
coins = {}
for cid_s, info in reg.items():
    if info["source"] == "excluded": continue
    kind, name = info["source"].split(":", 1)
    fn = {"yahoo": f"y_{name}.json", "binance": f"b_{name}.json", "kraken": f"k_{name}.json"}[kind]
    p = os.path.join(V4, "crypto-basket-pit-data", fn)
    if not os.path.exists(p): continue
    rows = json.load(open(p))
    bars = [{"d": r["d"], "o": r["c"], "c": r["c"]} for r in rows if r["d"] <= "2026-11-20"]
    if len(bars) < 200: continue
    cst = macd_states([b["c"] for b in bars])
    nat = sim_close_exec(bars, cst); hou = sim_close_exec(bars, cst, house=True)
    bh = buyhold_close(bars)
    vb = slice_bars(bars, "2023-01-01", "2026-11-20"); vst = None
    if len(vb) > 200:
        vidx = [i for i, b in enumerate(bars) if b["d"] >= "2023-01-01"]
        vst = sim_close_exec(vb, [cst[i] for i in vidx])
    coins[info["symbol"]] = {"start": bars[0]["d"], "native_final": nat["final"], "house_final": hou["final"],
                             "buyhold": round(bh, 2), "maxdd": nat["maxdd"], "trades": nat["trades"],
                             "val_native": vst["final"] if vst else None,
                             "curve": nat["curve"]}
out["coins"] = coins
out["coins_beat_hold_full"] = sum(1 for c in coins.values() if c["native_final"] > c["buyhold"])
out["coins_n"] = len(coins)
json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
print("SPY:", {r: (v["native"]["final"], v["house"]["final"], v["spy_buyhold"]) for r, v in out["stocks"].items()})
print("coins:", len(coins), "beat hold:", out["coins_beat_hold_full"])
