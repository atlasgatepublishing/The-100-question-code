#!/usr/bin/env python3
"""Period-by-period record at the strategy's NATIVE tempo: the 8-hour funding
settlement itself. Reuses run_carry.py's frozen engine unchanged; only the
reporting cadence differs. Saves period_stats_8h.json."""
import json, os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from run_carry import load, run_book, POT

def stats_8h(s):
    vals = np.concatenate([[POT], s.values])
    rets = np.diff(vals) / vals[:-1]
    win = rets > 0
    flat = rets == 0
    longest_loss = cur = 0
    for w in win:
        cur = 0 if w else cur + 1
        longest_loss = max(longest_loss, cur)
    peak = vals[0]; since = 0; gap = 0
    for v in vals[1:]:
        if v >= peak:
            peak = v; since = 0
        else:
            since += 1; gap = max(gap, since)
    return {"tempo": "8-hour funding settlement", "periods": int(len(rets)),
            "pct_periods_profitable": round(100 * float(win.mean()), 1),
            "pct_periods_exactly_zero": round(100 * float(flat.mean()), 1),
            "median_period_pct": round(100 * float(np.median(rets)), 4),
            "best_period_pct": round(100 * float(rets.max()), 3),
            "worst_period_pct": round(100 * float(rets.min()), 3),
            "longest_losing_streak_periods": int(longest_loss),
            "longest_stretch_between_new_highs_periods": int(gap),
            "mean_period_pct_secondary_average": round(100 * float(rets.mean()), 4)}

out = {}
for coin in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
    f = load(coin)
    trail = f["last_funding_rate"].rolling(21).mean().shift(1)
    gate = (trail > 0).fillna(True).values
    A = run_book(f, f["t"].iloc[0], gate=None)
    B = run_book(f, f["t"].iloc[0], gate=gate)
    out[coin] = {"formA": stats_8h(A["equity"]), "formB": stats_8h(B["equity"])}
    print(coin, "done")
with open(os.path.join(os.path.dirname(__file__), "..", "period_stats_8h.json"), "w") as fh:
    json.dump(out, fh, indent=1)
print(json.dumps(out, indent=1))
