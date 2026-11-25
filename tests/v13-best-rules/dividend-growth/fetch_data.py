#!/usr/bin/env python3
"""Fetch full Yahoo chart payloads (raw close + adjclose + dividend events)
for every Aristocrat roster ticker + SPY, into this folder's data/.
Order: v7 long-hold pxfull cache (read-only) -> v11 dogs cache -> fresh Yahoo.
Saves data/full_<T>.json (raw payload) for tickers not already saved."""
import json, os, sys, time, urllib.request, calendar

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data"); os.makedirs(DATA, exist_ok=True)
V12 = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/dividend-growth")
sys.path.insert(0, V12)
from rosters import ROSTERS, SUCCESSOR

V7 = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
TICKERS = sorted({t for v in ROSTERS.values() for t in v} | set(SUCCESSOR.values()) | {"SPY"})

def yahoo(t):
    t1 = calendar.timegm(time.strptime("2008-01-01", "%Y-%m-%d"))
    t2 = calendar.timegm(time.strptime("2026-11-22", "%Y-%m-%d"))
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{t}"
           f"?period1={t1}&period2={t2}&interval=1d&events=div,split")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())

report = {}
for t in TICKERS:
    out = os.path.join(DATA, f"full_{t}.json")
    if os.path.exists(out) and os.path.getsize(out) > 100:
        report[t] = "cached"; continue
    src = None
    p7 = os.path.join(V7, f"pxfull_{t}.json")
    if os.path.exists(p7) and os.path.getsize(p7) > 100:
        payload = json.load(open(p7)); src = "v7cache"
    else:
        try:
            payload = yahoo(t); src = "yahoo"
            time.sleep(0.3)
        except Exception as e:
            report[t] = f"FAIL {e}"; continue
    try:
        res = payload["chart"]["result"][0]
        n = len(res.get("timestamp") or [])
    except Exception:
        report[t] = "BADPAYLOAD"; continue
    if n < 10:
        report[t] = f"SHORT {n}"; continue
    json.dump(payload, open(out, "w"))
    report[t] = src
json.dump(report, open(os.path.join(DATA, "fetch_report.json"), "w"), indent=1)
ok = sum(1 for v in report.values() if v in ("cached", "v7cache", "yahoo"))
print(f"{ok}/{len(TICKERS)} ok")
for t, v in report.items():
    if v not in ("cached", "v7cache", "yahoo"):
        print("MISS", t, v)
