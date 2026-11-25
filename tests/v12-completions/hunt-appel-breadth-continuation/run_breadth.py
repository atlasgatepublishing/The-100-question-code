#!/usr/bin/env python3
"""Appel Breadth Thrust Continuation — SPEC-FROZEN exact.
E(t) = 10-day EMA of Advances/(Advances+Declines) on the program's PIT price stack
(CONSTRUCTED breadth, same convention as hunt-mcclellan / hunt-zweig: pxfull_* non-SPY
daily series, unchanged excluded). Buy: E crosses above 0.615. Sell: after a buy, E
crosses below 0.50. SPY next-open, program costs. Native no floor; house v9 plain floor.
NOTE: as run, common.py lived in the ephemeral /tmp/hunt1 (wiped after the run);
common.py is saved beside this script."""
import glob, json, os, sys
sys.path.insert(0, "/tmp/hunt1")
from common import *

HERE = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/hunt-appel-breadth-continuation")

spy = load_pxfull("SPY")
spy_dates = [b["d"] for b in spy]
closes = {}
for p in sorted(glob.glob(os.path.join(V7, "pxfull_*.json"))):
    sym = os.path.basename(p)[7:-5]
    if sym == "SPY": continue
    try: bars = load_pxfull(sym)
    except Exception: continue
    closes[sym] = {b["d"]: b["c"] for b in bars}
ratio = []
for i, d in enumerate(spy_dates):
    if i == 0: ratio.append(0.5); continue
    adv = dec = 0
    pd = spy_dates[i-1]
    for sym, m in closes.items():
        if d in m and pd in m:
            if m[d] > m[pd]: adv += 1
            elif m[d] < m[pd]: dec += 1
    ratio.append(adv / (adv + dec) if adv + dec > 0 else 0.5)
E = ema_series(ratio, 10)
states = []; pos = 0
for i in range(len(spy_dates)):
    if i > 0:
        if pos == 0 and E[i] > 0.615 and E[i-1] <= 0.615: pos = 1
        elif pos == 1 and E[i] < 0.50 and E[i-1] >= 0.50: pos = 0
    states.append(pos)

out = {"family": "hunt-appel-breadth-continuation", "breadth_series_n": len(closes),
       "holdings_grid": "NOT-APPLICABLE — market timer, no selection", "stocks": {}}
for road, (s, e) in ROADS.items():
    idx = [i for i, b in enumerate(spy) if s <= b["d"] <= e]
    bars = [spy[i] for i in idx]; st = [states[i] for i in idx]
    nat = sim_open_exec(bars, st); hou = sim_open_exec(bars, st, house=True)
    pls = [sim_open_exec(bars, placebo_shift(st, sd))["final"] for sd in range(1, 21)]
    out["stocks"][road] = {"native": nat, "house": hou, "spy_buyhold": round(buyhold_open(bars), 2),
                           "champion_vm": CHAMP[road], "placebos_beaten": sum(1 for p in pls if nat["final"] > p),
                           "placebo_finals": [round(p, 2) for p in pls],
                           "periods_monthly": period_stats(nat["curve"], "monthly"),
                           "periods_daily": period_stats(nat["curve"], "daily")}
json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
print({r: (v["native"]["final"], v["house"]["final"], v["spy_buyhold"], v["native"]["trades"]) for r, v in out["stocks"].items()})
