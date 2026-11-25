#!/usr/bin/env python3
"""Fetch Yahoo chart payloads (raw OHLC + dividend/split events) for every
ticker that was an S&P 500 member at any point 2010-2026 per the PIT
membership file. Resumable: existing non-empty files are skipped.
Throttled: 3 workers, small stagger. A 429 stops the whole fetch (hard stop).
"""
import csv, json, os, sys, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
os.makedirs(DATA, exist_ok=True)

rows = list(csv.DictReader(open(os.path.join(DATA, "sp500_ticker_start_end.csv"))))
def overlaps(s, e, a, b):
    return (s <= b) and (e == "" or e >= a)
tickers = sorted({r["ticker"] for r in rows
                  if overlaps(r["start_date"], r["end_date"], "2010-01-01", "2026-11-20")})
tickers.append("SPY")
P1, P2 = 1259625600, 1795564800  # 2009-12-01 .. 2026-11-21 UTC

stop = {"flag": False, "code": None}

def fetch(t):
    if stop["flag"]:
        return (t, "skipped-stop")
    path = os.path.join(DATA, f"px_{t}.json")
    if os.path.exists(path) and os.path.getsize(path) > 200:
        return (t, "cached")
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(t)}"
           f"?period1={P1}&period2={P2}&interval=1d&events=div,split")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        json.loads(data)  # validate
        with open(path, "wb") as f:
            f.write(data)
        return (t, "ok")
    except urllib.error.HTTPError as e:
        if e.code == 429:
            stop["flag"] = True; stop["code"] = 429
            return (t, "HTTP429-STOP")
        return (t, f"http{e.code}")
    except Exception as e:
        return (t, f"err:{type(e).__name__}")

import urllib.parse  # noqa: E402  (used inside fetch)

if __name__ == "__main__":
    done = {}
    with ThreadPoolExecutor(max_workers=3) as ex:
        for i, res in enumerate(ex.map(fetch, tickers)):
            done[res[1]] = done.get(res[1], 0) + 1
            if i % 100 == 0:
                print(f"{i}/{len(tickers)} {done}", flush=True)
            time.sleep(0.05)
    print("FINAL", done, "stop:", stop)
    with open(os.path.join(DATA, "fetch_summary.json"), "w") as f:
        json.dump({"counts": done, "stop": stop, "n_tickers": len(tickers)}, f, indent=1)
