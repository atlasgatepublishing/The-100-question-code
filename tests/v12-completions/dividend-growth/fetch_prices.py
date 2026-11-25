#!/usr/bin/env python3
"""Fetch adjusted-close tapes for every roster ticker.
Order: v7 long-hold cache (read-only) -> fresh Yahoo chart pull -> Stooq CSV.
Saves data/px_<T>.json = {"src":..., "bars":[[date, adjclose],...]}"""
import json, os, sys, time, urllib.request, calendar, io, csv
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rosters import ROSTERS, SUCCESSOR

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data"); os.makedirs(DATA, exist_ok=True)
V7 = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
TICKERS = sorted({t for v in ROSTERS.values() for t in v} | {"SPY"})

def from_payload(payload):
    res = payload["chart"]["result"][0]
    ts = res["timestamp"]; q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        c = q["close"][i]
        if c is None: continue
        a = adj[i] if adj and adj[i] else c
        bars.append([time.strftime("%Y-%m-%d", time.gmtime(t)), round(float(a), 4)])
    return bars

def yahoo(t):
    p = os.path.join(V7, f"pxfull_{t}.json")
    if os.path.exists(p) and os.path.getsize(p) > 100:
        return from_payload(json.load(open(p))), "v7cache"
    t1 = calendar.timegm(time.strptime("2008-01-01", "%Y-%m-%d"))
    t2 = calendar.timegm(time.strptime("2026-11-22", "%Y-%m-%d"))
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{t}"
           f"?period1={t1}&period2={t2}&interval=1d&events=div,split")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return from_payload(json.loads(r.read())), "yahoo"

def stooq(t):
    url = f"https://stooq.com/q/d/l/?s={t.lower().replace('-','.')}.us&i=d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        txt = r.read().decode()
    rows = list(csv.DictReader(io.StringIO(txt)))
    bars = [[r["Date"], round(float(r["Close"]), 4)] for r in rows if r.get("Close") not in (None, "", "N/D")]
    return bars, "stooq"

report = {}
for t in TICKERS:
    out = os.path.join(DATA, f"px_{t}.json")
    if os.path.exists(out):
        j = json.load(open(out)); report[t] = (j["src"], j["bars"][0][0], j["bars"][-1][0], len(j["bars"])); continue
    got = None
    for fn in (yahoo, stooq):
        try:
            bars, src = fn(t)
            if bars and len(bars) > 50: got = (bars, src); break
        except Exception as e:
            print(f"{t}: {fn.__name__} failed: {e}", flush=True)
    if got is None and t in SUCCESSOR:
        try:
            bars, src = yahoo(SUCCESSOR[t]); got = (bars, src + f" via successor {SUCCESSOR[t]}")
        except Exception as e:
            print(f"{t}: successor failed: {e}", flush=True)
    if got:
        bars, src = got
        json.dump({"src": src, "bars": bars}, open(out, "w"))
        report[t] = (src, bars[0][0], bars[-1][0], len(bars))
    else:
        report[t] = ("NONE", None, None, 0)
    print(t, report[t], flush=True)
json.dump({k: list(v) for k, v in report.items()}, open(os.path.join(DATA, "fetch_report.json"), "w"), indent=1)
print("missing:", [t for t, v in report.items() if v[0] == "NONE"])
