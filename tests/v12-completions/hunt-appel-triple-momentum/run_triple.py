#!/usr/bin/env python3
"""Appel Triple Momentum Nasdaq model (2005) — SPEC-FROZEN exact.
TM = ROC5+ROC15+ROC25 (pct) of Nasdaq Composite closes; buy cross above 4, sell cross below 4.
Traded: QQQ (next-open). Per-coin mechanical port on own closes (close-exec).
NOTE: as run, common.py and the Yahoo caches lived in the ephemeral /tmp/hunt1
(wiped after the run); common.py is saved beside this script. See RESULTS.md data note."""
import json, os, sys
sys.path.insert(0, "/tmp/hunt1")
from common import *

HERE = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/hunt-appel-triple-momentum")
V4 = os.path.expanduser("~/workspace/stock-app/backtests/v4")

def tm_states(closes):
    states = []; pos = 0
    for i in range(len(closes)):
        if i >= 25:
            tm = sum((closes[i] / closes[i-k] - 1) * 100 for k in (5, 15, 25))
            ptm = sum((closes[i-1] / closes[i-1-k] - 1) * 100 for k in (5, 15, 25))
            if tm > 4 and ptm <= 4: pos = 1
            elif tm < 4 and ptm >= 4: pos = 0
        states.append(pos)
    return states

ixic = load_yahoo_file("/tmp/hunt1/ixic.json")
qqq = load_yahoo_file("/tmp/hunt1/y_QQQ.json")
ist = tm_states([b["c"] for b in ixic])
qstates = []
j = -1
for d in [b["d"] for b in qqq]:
    while j + 1 < len(ixic) and ixic[j+1]["d"] <= d: j += 1
    qstates.append(ist[j] if j >= 0 else 0)

out = {"family": "hunt-appel-triple-momentum",
       "holdings_grid": "NOT-APPLICABLE — single-asset timer, no selection", "stocks": {}, "coins": {}}
for road, (s, e) in ROADS.items():
    idx = [i for i, b in enumerate(qqq) if s <= b["d"] <= e]
    bars = [qqq[i] for i in idx]; states = [qstates[i] for i in idx]
    nat = sim_open_exec(bars, states); hou = sim_open_exec(bars, states, house=True)
    pls = [sim_open_exec(bars, placebo_shift(states, sd))["final"] for sd in range(1, 21)]
    out["stocks"][road] = {"native": nat, "house": hou, "qqq_buyhold": round(buyhold_open(bars), 2),
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
    cst = tm_states([b["c"] for b in bars])
    nat = sim_close_exec(bars, cst); hou = sim_close_exec(bars, cst, house=True)
    coins[info["symbol"]] = {"start": bars[0]["d"], "native_final": nat["final"], "house_final": hou["final"],
                             "buyhold": round(buyhold_close(bars), 2), "maxdd": nat["maxdd"], "trades": nat["trades"],
                             "curve": nat["curve"]}
out["coins"] = coins
out["coins_beat_hold_full"] = sum(1 for c in coins.values() if c["native_final"] > c["buyhold"])
out["coins_n"] = len(coins)
json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
print("QQQ:", {r: (v["native"]["final"], v["house"]["final"], v["qqq_buyhold"]) for r, v in out["stocks"].items()})
print("coins:", len(coins), "beat hold:", out["coins_beat_hold_full"])
