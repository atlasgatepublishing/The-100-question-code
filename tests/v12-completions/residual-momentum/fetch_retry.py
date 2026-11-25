#!/usr/bin/env python3
"""Retry pass for missing tapes only. requests, timeout 20, 2 attempts."""
import csv, json, os, time
import requests
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
H = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

snaps = []
with open(os.path.join(DATA, "sp500_hist.csv")) as f:
    for row in csv.DictReader(f):
        snaps.append((row["date"], [t.strip() for t in row["tickers"].split(",") if t.strip()]))
need = {t for d, ts in snaps if d >= "2006-01-01" for t in ts} | {"SPY"}
have = {fn[3:-5] for fn in os.listdir(DATA) if fn.startswith("px_") and fn.endswith(".json")}
missing = sorted(need - have)
print(f"missing {len(missing)}", flush=True)

def fetch(t):
    sym = t.replace(".", "-")
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
           f"?period1=1136073600&period2=1795600000&interval=1d&events=div,split")
    for attempt in range(2):
        try:
            r = requests.get(url, headers=H, timeout=20)
            if r.status_code != 200:
                return t, f"http{r.status_code}"
            res = r.json()["chart"]["result"][0]
            ts = res.get("timestamp") or []
            if len(ts) < 50:
                return t, f"stub({len(ts)})"
            q = res["indicators"]["quote"][0]
            adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
            bars = []
            for i, tt in enumerate(ts):
                c = q["close"][i]
                if c is None:
                    continue
                a = adj[i] if adj and adj[i] else c
                bars.append([time.strftime("%Y-%m-%d", time.gmtime(tt)), round(float(a), 4)])
            if len(bars) < 50:
                return t, f"short({len(bars)})"
            with open(os.path.join(DATA, f"px_{t}.json"), "w") as f:
                json.dump({"src": "yahoo-retry", "bars": bars}, f)
            return t, f"ok({len(bars)})"
        except Exception as e:
            if attempt == 1:
                return t, f"ERR {str(e)[:60]}"
            time.sleep(1)

ok = 0; fails = {}
with ThreadPoolExecutor(max_workers=8) as ex:
    for t, s in ex.map(fetch, missing):
        if s.startswith("ok"):
            ok += 1
        else:
            fails[t] = s
print(f"retry ok {ok}; still missing {len(fails)}", flush=True)
with open(os.path.join(DATA, "fetch_retry_report.json"), "w") as f:
    json.dump(fails, f, indent=1)
print("still missing:", ", ".join(sorted(fails)), flush=True)
