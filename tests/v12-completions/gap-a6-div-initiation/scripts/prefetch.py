#!/usr/bin/env python3
"""Parallel prefetch of Yahoo daily bars for every COMMON universe ticker
+ SPY, into ./data (same cache format run.py reads). Serial fetching was
throttled to hours; 6 workers finish the pool in minutes. Failures are
logged to prefetch_failures.json and treated by run.py as 'no bars'
(placebo candidates without bars are skipped by the frozen coverage rule).
"""
import json, os, time, calendar, urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
H = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}

def fetch_one(t):
    path = os.path.join(DATA, f"yahoo_{t}.json")
    if os.path.exists(path) and os.path.getsize(path) > 100:
        return (t, "cached")
    t1 = calendar.timegm(time.strptime("2005-01-01", "%Y-%m-%d"))
    t2 = calendar.timegm(time.strptime("2026-11-21", "%Y-%m-%d"))
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{t}"
           f"?period1={t1}&period2={t2}&interval=1d&events=div,split")
    last = None
    for i in range(3):
        try:
            r = urllib.request.Request(url, headers=H)
            b = urllib.request.urlopen(r, timeout=45).read()
            json.loads(b)["chart"]["result"][0]
            open(path, "wb").write(b)
            return (t, "ok")
        except Exception as e:
            last = str(e); time.sleep(1.5 * (i + 1))
    return (t, f"FAIL {last}")

def main():
    classes = json.load(open(os.path.join(ROOT, "security_classes.json")))
    tickers = sorted(t for t, v in classes.items() if v["class"] == "COMMON") + ["SPY"]
    print(f"prefetch {len(tickers)} tickers", flush=True)
    fails = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        for i, (t, st) in enumerate(ex.map(fetch_one, tickers)):
            if st.startswith("FAIL"): fails.append({"ticker": t, "error": st})
            if i % 50 == 0: print(f"  {i}/{len(tickers)}", flush=True)
    json.dump(fails, open(os.path.join(ROOT, "prefetch_failures.json"), "w"), indent=1)
    print(f"done; failures: {len(fails)}")

if __name__ == "__main__":
    main()
