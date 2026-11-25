#!/usr/bin/env python3
"""Fetch SCHD daily bars and SPY bars+dividends from Yahoo chart API (public).
Writes data/SCHD.csv (date,adjclose,close) and data/SPY_yahoo.csv
(date,adjclose,close) and data/spy_div_monthly.csv (month-end, dist_sum)."""
import json, os, urllib.request
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data")
os.makedirs(DATA, exist_ok=True)

def fetch(sym):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
           f"?period1=1199000000&period2=1796000000&interval=1d&events=div,split")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        j = json.load(r)
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"]["adjclose"][0]["adjclose"]
    df = pd.DataFrame({"date": pd.to_datetime(ts, unit="s", utc=True).tz_convert("America/New_York").normalize().tz_localize(None),
                       "close": q["close"], "adjclose": adj}).dropna()
    divs = {}
    ev = res.get("events", {}).get("dividends", {})
    for v in ev.values():
        d = pd.to_datetime(v["date"], unit="s", utc=True).tz_convert("America/New_York").normalize().tz_localize(None)
        divs[d] = v["amount"]
    return df, pd.Series(divs).sort_index()

for sym in ("SCHD", "SPY"):
    df, divs = fetch(sym)
    name = "SCHD.csv" if sym == "SCHD" else "SPY_yahoo.csv"
    df.to_csv(os.path.join(DATA, name), index=False)
    print(sym, df["date"].iloc[0].date(), df["date"].iloc[-1].date(), len(df), "divs:", len(divs))
    if sym == "SPY":
        m = divs.groupby(divs.index.to_period("M")).sum()
        m.index = m.index.to_timestamp("M")
        m.to_csv(os.path.join(DATA, "spy_div_monthly.csv"), header=["dist"])
        print("spy div months:", len(m), "total dist 2025:", round(float(m[m.index.year == 2025].sum()), 4))
