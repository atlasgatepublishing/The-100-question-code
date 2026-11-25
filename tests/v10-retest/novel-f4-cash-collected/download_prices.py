#!/usr/bin/env python3
"""Download Yahoo chart-API prices (split/dividend-adjusted, same channel and
JSON shape as the champion's v4 cache) for the N-F4 universe + SPY,
2016-01-01 -> 2026-11-21, cached in this folder's data/ only.
The v4 shared cache starts 2017-06-01, after the DECADE start 2016-11-21,
so the decade road needs this pull. Read-only elsewhere."""
import json, os, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data")
UA = "AtlasGateResearch terry-research@example.com"
UNIVERSE = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "BRK-B", "JPM", "XOM",
            "JNJ", "PG", "V", "WMT", "HD", "BAC", "CVX", "PFE", "VZ", "T",
            "DIS", "NFLX", "INTC", "CSCO", "GE", "IBM", "MMM", "UNH", "MA",
            "KO", "PEP", "WFC", "SPY"]
P1 = 1451606400   # 2016-01-01 UTC
P2 = 1795305600   # 2026-11-21 UTC

os.makedirs(OUT, exist_ok=True)
for t in UNIVERSE:
    path = os.path.join(OUT, f"px_{t}.json")
    if os.path.exists(path) and os.path.getsize(path) > 10000:
        print(f"{t}: cached", flush=True)
        continue
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{t}"
           f"?period1={P1}&period2={P2}&interval=1d&events=div,splits")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        blob = r.read()
    j = json.loads(blob)
    ts = j["chart"]["result"][0]["timestamp"]
    print(f"{t}: {len(ts)} bars "
          f"{time.strftime('%Y-%m-%d', time.gmtime(ts[0]))}.."
          f"{time.strftime('%Y-%m-%d', time.gmtime(ts[-1]))}", flush=True)
    with open(path, "wb") as f:
        f.write(blob)
    time.sleep(0.3)
print("DONE")
