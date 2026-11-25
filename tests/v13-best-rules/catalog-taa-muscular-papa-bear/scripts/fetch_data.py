#!/usr/bin/env python3
"""Fetch Yahoo chart JSON (adjclose) for the Papa Bear universe + SPY into ../data.
Same source and format as the v12 run (Yahoo chart API, dividend+split-adjusted closes)."""
import json, os, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data")
TICKERS = ["VTV", "VUG", "VIOV", "VIOG", "VEA", "VWO", "VNQ", "PDBC", "IAU",
           "EDV", "VGIT", "VCLT", "BNDX", "SPY"]
P1 = 1230768000  # 2009-01-01 UTC
P2 = 1796000000  # ~2026-12

os.makedirs(DATA, exist_ok=True)
for t in TICKERS:
    path = os.path.join(DATA, f"{t}.json")
    if os.path.exists(path):
        print(t, "cached"); continue
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{t}"
           f"?period1={P1}&period2={P2}&interval=1d&events=div%2Csplit")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.load(r)
    res = d["chart"]["result"][0]
    n = len(res["timestamp"])
    adj = res["indicators"]["adjclose"][0]["adjclose"]
    assert len(adj) == n and adj[-1] is not None
    json.dump(d, open(path, "w"))
    print(t, "rows", n)
    time.sleep(0.3)
print("DONE")
