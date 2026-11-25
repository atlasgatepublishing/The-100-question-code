#!/usr/bin/env python3
"""Buffett Indicator gauge timer — SPEC-FROZEN exact (CONSTRUCTED timer on published bands).
Ratio = Wilshire 5000 level (Yahoo ^W5000, the WILL5000INDFC-equivalent index level) /
nominal GDP (FRED, current vintage — ALFRED vintages require an API key; fallback per spec
(d), caveat printed) x100. GDP quarter used from 1 month after quarter-end (advance-estimate
timing per spec (c)). Monthly check at last trading day: ratio >=115 -> cash; <=90 -> enter
SPY; between -> hold. Fill next open. Native no floor; house v9 plain floor.
BTC: same state series as external gate, close-exec.
NOTE: as run, common.py and the data caches lived in the ephemeral /tmp/hunt1
(wiped after the run); common.py is saved beside this script. See HUNT-LOG.md."""
import csv, json, os, sys
sys.path.insert(0, "/tmp/hunt1")
from common import *

HERE = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/hunt-buffett-indicator")
gdp = []
for row in csv.reader(open("/tmp/hunt1/gdp.csv")):
    if row and row[0][0].isdigit(): gdp.append((row[0], float(row[1])))
gdp.sort()
def gdp_available(d):
    val = None
    for qd, v in gdp:
        y, m = int(qd[:4]), int(qd[5:7])
        am = m + 3; ay = y + (am - 1) // 12; am = (am - 1) % 12 + 1
        if f"{ay:04d}-{am:02d}-28" <= d: val = v
    return val

w5 = load_yahoo_file("/tmp/hunt1/y_%5EW5000.json")
wmap = {b["d"]: b["c"] for b in w5}
spy = load_pxfull("SPY"); dates = [b["d"] for b in spy]
month_last = {}
for d in dates: month_last[d[:7]] = d
ratio_m = {}
for mk, d in month_last.items():
    g = gdp_available(d)
    cands = [dd for dd in wmap if dd <= d]
    if g and cands: ratio_m[mk] = wmap[max(cands)] / g * 100
states = [0] * len(dates); pos = 0
mk_sorted = sorted(month_last)
state_by_month = {}
for k, mk in enumerate(mk_sorted):
    if mk in ratio_m:
        r = ratio_m[mk]
        if r >= 115: pos = 0
        elif r <= 90: pos = 1
    state_by_month[mk] = pos
for i, d in enumerate(dates):
    mk = d[:7]; y, m = int(mk[:4]), int(mk[5:7]); pm = m - 1; py = y
    if pm == 0: pm = 12; py -= 1
    states[i] = state_by_month.get(f"{py:04d}-{pm:02d}", 0)

out = {"family": "hunt-buffett-indicator", "holdings_grid": "NOT-APPLICABLE — gauge timer, no selection",
       "data_note": "GDP: FRED current vintage (ALFRED vintage retrieval requires API key — spec (d) fallback, bias FLATTERS mildly, printed). Numerator: Yahoo ^W5000 level as WILL5000INDFC-equivalent.",
       "ratio_sample": {k: round(ratio_m[k], 1) for k in list(sorted(ratio_m))[-6:]},
       "stocks": {}, "btc_external": {}}
for road, (s, e) in ROADS.items():
    idx = [i for i, b in enumerate(spy) if s <= b["d"] <= e]
    bars = [spy[i] for i in idx]; st = [states[i] for i in idx]
    nat = sim_open_exec(bars, st); hou = sim_open_exec(bars, st, house=True)
    pls = [sim_open_exec(bars, placebo_shift(st, sd))["final"] for sd in range(1, 21)]
    out["stocks"][road] = {"native": nat, "house": hou, "spy_buyhold": round(buyhold_open(bars), 2),
                           "champion_vm": CHAMP[road], "placebos_beaten": sum(1 for p in pls if nat["final"] > p),
                           "placebo_finals": [round(p, 2) for p in pls],
                           "periods_monthly": period_stats(nat["curve"], "monthly")}
btc = load_cm("btc")
smap = {d: states[i] for i, d in enumerate(dates)}
last = 0; bst = []
for b in btc:
    if b["d"] in smap: last = smap[b["d"]]
    bst.append(last)
for wname, (s, e) in {"FULL": ("2010-07-18", "2026-11-20"), "VAL": ("2023-01-01", "2026-11-20")}.items():
    idx = [i for i, b in enumerate(btc) if s <= b["d"] <= e]
    bars = [btc[i] for i in idx]; st = [bst[i] for i in idx]
    nat = sim_close_exec(bars, st)
    out["btc_external"][wname] = {"native": nat, "btc_buyhold": round(buyhold_close(bars), 2),
                                  "periods_monthly": period_stats(nat["curve"], "monthly")}
json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
print({r: (v["native"]["final"], v["house"]["final"], v["spy_buyhold"]) for r, v in out["stocks"].items()})
