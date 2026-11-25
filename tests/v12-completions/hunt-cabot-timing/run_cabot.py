#!/usr/bin/env python3
"""Cabot Market Timing — SPEC-FROZEN exact (CONSTRUCTED combination of published components).
Trend Lines (weekly): SPX & Nasdaq Composite vs 35-week MA; bullish when BOTH above for 2
straight weeks, bearish when BOTH below for 2 straight weeks, else prior state.
Tides (daily): 5 indexes (IXIC, NYA, GSPC, MID, SP600-as-SmallCap-600) vs 50-day SMA;
bullish when >=3 close above their 50d SMA AND that SMA is advancing (SMA50[t] > SMA50[t-5]).
LONG SPY only when Trend Lines bullish AND Tides bullish; next-open exec; program costs.
Two-Second Indicator: diagnostic only (constructed new-lows count from pxfull stack), never gates.
NOTE: as run, common.py and the Yahoo caches lived in the ephemeral /tmp/hunt1
(wiped after the run); common.py is saved beside this script."""
import glob, json, os, sys
sys.path.insert(0, "/tmp/hunt1")
from common import *

HERE = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/hunt-cabot-timing")
def closes_of(path):
    bars = load_yahoo_file(path); return {b["d"]: b["c"] for b in bars}, [b["d"] for b in bars]

spy = load_pxfull("SPY"); dates = [b["d"] for b in spy]
gspc, _ = closes_of("/tmp/hunt1/y_%5EGSPC.json")
ixic, _ = closes_of("/tmp/hunt1/ixic.json")
nya, _ = closes_of("/tmp/hunt1/y_%5ENYA.json")
mid, _ = closes_of("/tmp/hunt1/y_%5EMID.json")
sml, _ = closes_of("/tmp/hunt1/y_sp600.json")
idx_series = [ixic, nya, gspc, mid, sml]

def aligned(m):
    last = None; out = []
    for d in dates:
        if d in m: last = m[d]
        out.append(last)
    return out

G = aligned(gspc); X = aligned(ixic)
fridays = [i for i, d in enumerate(dates) if date.fromisoformat(d).weekday() == 4]
def weekly_vals(series):
    return [series[i] for i in fridays if series[i] is not None]
gw = weekly_vals(G); xw = weekly_vals(X)
n = min(len(gw), len(xw)); gw, xw = gw[:n], xw[:n]
gsma = sma_series(gw, 35); xsma = sma_series(xw, 35)
tl_state_w = []; state = 0; above_run = below_run = 0
for i in range(n):
    if gsma[i] is not None and xsma[i] is not None:
        if gw[i] > gsma[i] and xw[i] > xsma[i]: above_run += 1; below_run = 0
        elif gw[i] < gsma[i] and xw[i] < xsma[i]: below_run += 1; above_run = 0
        else: above_run = below_run = 0
        if above_run >= 2: state = 1
        elif below_run >= 2: state = 0
    tl_state_w.append(state)
tl_daily = [0] * len(dates)
fi = 0
for i, d in enumerate(dates):
    while fi < len(fridays) and fridays[fi] < i: fi += 1
    tl_daily[i] = tl_state_w[fi-1] if fi >= 1 and fi-1 < len(tl_state_w) else 0

tides = [0] * len(dates)
aligned_series = [aligned(m) for m in idx_series]
smas = []
for s in aligned_series:
    filled = [v if v is not None else 0.0 for v in s]
    smas.append(sma_series(filled, 50))
for i in range(len(dates)):
    cnt = 0
    for k in range(5):
        s = aligned_series[k]; sm = smas[k]
        if s[i] is not None and sm[i] is not None and i >= 5 and sm[i-5] is not None:
            if s[i] > sm[i] and sm[i] > sm[i-5]: cnt += 1
    tides[i] = 1 if cnt >= 3 else 0

states = [1 if (tl_daily[i] == 1 and tides[i] == 1) else 0 for i in range(len(dates))]

closes = {}
for p in sorted(glob.glob(os.path.join(V7, "pxfull_*.json"))):
    sym = os.path.basename(p)[7:-5]
    if sym == "SPY": continue
    try: closes[sym] = {b["d"]: b["c"] for b in load_pxfull(sym)}
    except Exception: continue
hist = {sym: [] for sym in closes}
nl_max = 0; nl_days40 = 0; nl_last = 0
for i, d in enumerate(dates):
    cnt = 0
    for sym, m in closes.items():
        if d in m:
            h = hist[sym]
            if len(h) >= 60 and m[d] <= min(h[-252:]): cnt += 1
            h.append(m[d])
    nl_last = cnt; nl_max = max(nl_max, cnt)
    if cnt > 40: nl_days40 += 1

out = {"family": "hunt-cabot-timing", "holdings_grid": "NOT-APPLICABLE — market timer, no selection",
       "two_second_diagnostic": {"max_new_lows_constructed": nl_max, "days_over_40": nl_days40,
                                 "note": "CONSTRUCTED count from 154-series survivor stack; understates true NYSE count; diagnostic only, never gated trades"},
       "stocks": {}}
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
print({r: (v["native"]["final"], v["house"]["final"], v["spy_buyhold"]) for r, v in out["stocks"].items()})
print("two-second:", out["two_second_diagnostic"])
