#!/usr/bin/env python3
"""Fetch missing Yahoo adjclose tapes for the PIT S&P500 roster (>=2006) + SPY
into this folder's data/. Same convention as the v12 residual-momentum
fetch_data.py (read-only reference). Resumable."""
import csv, json, os, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
snaps = []
with open(os.path.join(DATA, "sp500_hist.csv")) as f:
    for row in csv.DictReader(f):
        snaps.append((row["date"], [t.strip() for t in row["tickers"].split(",") if t.strip()]))
tickers = sorted({t for d, ts in snaps if d >= "2006-01-01" for t in ts} | {"SPY"})
print(f"roster tickers: {len(tickers)}", flush=True)

def fetch(t):
    out = os.path.join(DATA, f"px_{t}.json")
    if os.path.exists(out) and os.path.getsize(out) > 100:
        return t, "cached"
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(t.replace('.', '-'))}"
           f"?period1=1136073600&period2=1795600000&interval=1d&events=div,split")
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                payload = json.loads(r.read())
            res = payload["chart"]["result"][0]
            ts = res["timestamp"]; q = res["indicators"]["quote"][0]
            adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
            bars = []
            for i, tt in enumerate(ts):
                c = q["close"][i]
                if c is None: continue
                a = adj[i] if adj and adj[i] else c
                bars.append([time.strftime("%Y-%m-%d", time.gmtime(tt)), round(float(a), 4)])
            if len(bars) < 50:
                return t, f"short({len(bars)})"
            with open(out, "w") as f:
                json.dump({"src": "yahoo", "bars": bars}, f)
            return t, f"ok({len(bars)})"
        except Exception as e:
            if attempt == 2: return t, f"FAIL {type(e).__name__}"
            time.sleep(2 * (attempt + 1))

results = {}
with ThreadPoolExecutor(max_workers=12) as ex:
    for t, s in ex.map(fetch, tickers):
        results[t] = s
ok = [t for t, s in results.items() if s.startswith(("ok", "cached"))]
bad = {t: s for t, s in results.items() if t not in ok}
print(f"ok {len(ok)}/{len(tickers)} bad {len(bad)}", flush=True)
with open(os.path.join(HERE, "fetch_report.json"), "w") as f:
    json.dump({"ok": len(ok), "total": len(tickers), "failed": bad}, f, indent=1)
print("bad:", ", ".join(sorted(bad))[:1500], flush=True)
