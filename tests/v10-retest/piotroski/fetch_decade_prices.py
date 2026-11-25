#!/usr/bin/env python3
"""Fetch full-decade Yahoo prices (2016-01-01 -> 2026-11-21) for the
Piotroski pond + SPY, using EXACTLY the v4 engine's method (chart API,
split/dividend-adjusted via adjclose ratio) so the DECADE sweep road
2016-11-21 -> 2026-11-20 is fully covered. The v4 shared cache only
starts 2017-06-01. Raw payloads cached in ./data (this folder only).
Bars are written in the engine's format: {"d","o","c"} adjusted."""
import calendar
import json
import os
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data")
os.makedirs(OUT, exist_ok=True)

UNIVERSE = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "BRK-B", "JPM", "XOM",
            "JNJ", "PG", "V", "WMT", "HD", "BAC", "CVX", "PFE", "VZ", "T",
            "DIS", "NFLX", "INTC", "CSCO", "GE", "IBM", "MMM", "UNH", "MA",
            "KO", "PEP", "WFC"]

P1, P2 = "2016-01-01", "2026-11-21"


def fetch_bars(ticker):
    raw_path = os.path.join(OUT, f"raw_{ticker}.json")
    if os.path.exists(raw_path) and os.path.getsize(raw_path) > 100:
        blob = open(raw_path, "rb").read()
    else:
        t1 = calendar.timegm(time.strptime(P1, "%Y-%m-%d"))
        t2 = calendar.timegm(time.strptime(P2, "%Y-%m-%d"))
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
               f"?period1={t1}&period2={t2}&interval=1d&events=div,split")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        blob = urllib.request.urlopen(req, timeout=60).read()
        with open(raw_path, "wb") as f:
            f.write(blob)
    j = json.loads(blob)
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, c = q["open"][i], q["close"][i]
        if c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        bars.append({"d": d, "o": (o * ratio if o else a), "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars


if __name__ == "__main__":
    all_bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars = fetch_bars(t)
        all_bars[t] = bars
        print(f"{t}: {len(bars)} bars {bars[0]['d']}..{bars[-1]['d']}", flush=True)
        time.sleep(0.3)
    with open(os.path.join(OUT, "decade_bars.json"), "w") as f:
        json.dump(all_bars, f)
    print("DONE")
