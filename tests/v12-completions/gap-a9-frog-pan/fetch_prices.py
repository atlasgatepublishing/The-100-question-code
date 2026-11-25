#!/usr/bin/env python3
"""Fetch Yahoo daily split-adjusted bars for every PIT S&P 500 constituent
appearing 2009-01-01..2026-11-20 in data/sp500_pit.csv, plus SPY.
Cache: data/yahoo/<TICKER>.json ([{d,o,c}]); failures: data/yahoo_failures.json.
Read-only wrt everything outside this folder."""
import csv, json, os, time
from datetime import datetime, timezone
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
CACHE = os.path.join(DATA, "yahoo")
os.makedirs(CACHE, exist_ok=True)

def pit_tickers():
    out = set()
    with open(os.path.join(DATA, "sp500_pit.csv")) as f:
        for row in csv.DictReader(f):
            if "2009-01-01" <= row["date"] <= "2026-11-20":
                out.update(t.strip() for t in row["tickers"].split(",") if t.strip())
    return sorted(out)

def fetch(ticker):
    path = os.path.join(CACHE, f"{ticker}.json")
    if os.path.exists(path):
        return "cached"
    ysym = ticker.replace(".", "-")
    p1 = int(datetime(2008, 1, 1, tzinfo=timezone.utc).timestamp())
    p2 = int(datetime(2026, 11, 22, tzinfo=timezone.utc).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ysym}"
           f"?period1={p1}&period2={p2}&interval=1d")
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        if r.status_code != 200:
            return f"http{r.status_code}"
        res = r.json()["chart"]["result"][0]
        ts = res["timestamp"]; q = res["indicators"]["quote"][0]
        rows = []
        for i, t in enumerate(ts):
            o, c = q["open"][i], q["close"][i]
            if o is None or c is None:
                continue
            d = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
            rows.append({"d": d, "o": float(o), "c": float(c)})
        if not rows:
            return "empty"
        with open(path, "w") as f:
            json.dump(rows, f)
        return "ok"
    except Exception as e:
        return f"err:{type(e).__name__}"

def main():
    from concurrent.futures import ThreadPoolExecutor
    tickers = pit_tickers()
    print(f"PIT tickers 2009-2026: {len(tickers)}", flush=True)
    fails = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        for i, (t, st) in enumerate(zip(tickers + ["SPY"], ex.map(fetch, tickers + ["SPY"]))):
            if st not in ("ok", "cached"):
                fails[t] = st
            if i % 100 == 0:
                print(f"{i}/{len(tickers)+1} fails={len(fails)}", flush=True)
    json.dump(fails, open(os.path.join(DATA, "yahoo_failures.json"), "w"), indent=1)
    print("DONE fails:", len(fails), flush=True)
    print(json.dumps(fails, indent=0)[:2000], flush=True)

if __name__ == "__main__":
    main()
