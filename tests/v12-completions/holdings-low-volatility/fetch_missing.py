#!/usr/bin/env python3
"""Fetch member tickers missing from data/merged_prices.json from the Yahoo
chart API (same source/convention as the v12 low-volatility fetcher), into
data/px_<T>.json in THIS folder only. Failures recorded, never patched."""
import csv, json, os, time, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
SRC = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/low-volatility/data/sp500_hist.csv")
UA = {"User-Agent": "Mozilla/5.0"}
P1, P2 = 1228003200, 1796000000

merged = json.load(open(os.path.join(DATA, "merged_prices.json")))
rows = list(csv.reader(open(SRC)))[1:]
universe = set()
for d, t in rows:
    if "2009-01-01" <= d <= "2026-11-20":
        universe.update(t.split(","))
missing = sorted(t for t in universe if t not in merged)
print("universe", len(universe), "missing", len(missing), flush=True)

def parse_chart(j):
    r = j["chart"]["result"][0]
    ts = r["timestamp"]; adj = r["indicators"]["adjclose"][0]["adjclose"]
    return [[time.strftime("%Y-%m-%d", time.gmtime(x)), round(float(a), 6)]
            for x, a in zip(ts, adj) if a is not None]

def fetch_one(t):
    outp = os.path.join(DATA, f"px_{t}.json")
    if os.path.exists(outp):
        return (t, "cached")
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/%s?period1=%d&period2=%d&interval=1d&events=div,split"
           % (urllib.parse.quote(t.replace(".", "-")), P1, P2))
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=UA)
            d = json.loads(urllib.request.urlopen(req, timeout=60).read())
            if not d["chart"]["result"]:
                raise ValueError("no result")
            rows_ = parse_chart(d)
            if len(rows_) < 20:
                raise ValueError(f"too few bars {len(rows_)}")
            json.dump(rows_, open(outp, "w"))
            return (t, "fetched")
        except Exception as e:
            last = str(e)
            if "429" in last:
                return (t, "RATE_LIMITED: " + last)
            time.sleep(2 * (attempt + 1))
    return (t, "FAIL: " + str(last))

fails, stats = [], {}
with ThreadPoolExecutor(max_workers=4) as ex:
    for t, status in ex.map(fetch_one, missing):
        stats[status.split(":")[0]] = stats.get(status.split(":")[0], 0) + 1
        if status.startswith(("FAIL", "RATE_LIMITED")):
            fails.append({"ticker": t, "error": status})
json.dump(fails, open(os.path.join(DATA, "price_failures.json"), "w"), indent=1)
print("stats", stats, "failures", len(fails), flush=True)
