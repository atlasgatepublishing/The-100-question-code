#!/usr/bin/env python3
"""Fetch full OHLC daily bars (UTC) for every registry coin, from the same
venues as the v4 source map, into THIS folder's data_ohlc/ (shared caches
are read-only). Yahoo chart API / Binance Vision monthly klines / Kraken
OHLC / Hyperliquid candleSnapshot. See HUNT-LOG.md hole 1."""
import csv, io, json, os, time, zipfile
from datetime import datetime, timezone
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data_ohlc"); os.makedirs(OUT, exist_ok=True)
V4RES = os.path.expanduser("~/workspace/stock-app/backtests/v4/crypto-basket-pit-results.json")
UA = {"User-Agent": "Mozilla/5.0"}
CREDIBLE_START = {2280: "2020-10-15", 11841: "2023-03-23", 22861: "2023-10-31"}
BINANCE_FIRST = {1720: "2017-11", 3890: "2019-04", 28321: "2024-09", 24478: "2023-05",
                 29470: "2023-12", 36148: "2025-05", 7083: "2020-09", 20947: "2023-05"}

def save(cid, rows):
    rows = [r for r in rows if r["c"] > 0 and r["h"] >= r["l"] > 0]
    rows.sort(key=lambda r: r["d"])
    if cid in CREDIBLE_START:
        rows = [r for r in rows if r["d"] >= CREDIBLE_START[cid]]
    with open(os.path.join(OUT, f"{cid}.json"), "w") as f: json.dump(rows, f)
    return len(rows)

def fetch_yahoo(cid, ticker):
    p1 = int(datetime(2015, 1, 1, tzinfo=timezone.utc).timestamp())
    p2 = int(datetime(2026, 11, 22, tzinfo=timezone.utc).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={p1}&period2={p2}&interval=1d")
    r = requests.get(url, headers=UA, timeout=30)
    res = r.json()["chart"]["result"]
    rows = []
    if res:
        ts = res[0]["timestamp"]; q = res[0]["indicators"]["quote"][0]
        for i, t in enumerate(ts):
            o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
            if None in (o, h, l, c): continue
            d = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
            rows.append({"d": d, "o": float(o), "h": float(h), "l": float(l), "c": float(c)})
    return save(cid, rows)

def fetch_binance(cid, pair):
    rows = {}
    y, m = int(BINANCE_FIRST[cid][:4]), int(BINANCE_FIRST[cid][5:7])
    while (y, m) <= (2026, 11):
        ym = f"{y:04d}-{m:02d}"
        url = (f"https://data.binance.vision/data/spot/monthly/klines/"
               f"{pair}/1d/{pair}-1d-{ym}.zip")
        try:
            r = requests.get(url, headers=UA, timeout=30)
            if r.status_code == 200:
                z = zipfile.ZipFile(io.BytesIO(r.content))
                for name in z.namelist():
                    if not name.endswith(".csv"): continue
                    for parts in csv.reader(io.TextIOWrapper(z.open(name))):
                        if not parts or not parts[0].strip().isdigit(): continue
                        tms = int(parts[0])
                        if tms > 10**14: tms //= 1000
                        d = datetime.fromtimestamp(tms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
                        rows[d] = {"d": d, "o": float(parts[1]), "h": float(parts[2]),
                                   "l": float(parts[3]), "c": float(parts[4])}
        except Exception:
            pass
        m += 1
        if m == 13: y, m = y + 1, 1
        time.sleep(0.05)
    return save(cid, list(rows.values()))

def fetch_kraken(cid, pair):
    r = requests.get(f"https://api.kraken.com/0/public/OHLC?pair={pair}&interval=1440",
                     headers=UA, timeout=30)
    j = r.json(); rows = []
    if not j.get("error"):
        key = [x for x in j["result"] if x != "last"][0]
        for x in j["result"][key]:
            d = datetime.fromtimestamp(int(x[0]), tz=timezone.utc).strftime("%Y-%m-%d")
            rows.append({"d": d, "o": float(x[1]), "h": float(x[2]),
                         "l": float(x[3]), "c": float(x[4])})
    return save(cid, rows)

def fetch_hype(cid):
    rows = {}
    start = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    end = int(datetime(2026, 11, 22, tzinfo=timezone.utc).timestamp() * 1000)
    step = 400 * 86400 * 1000; t = start
    while t < end:
        payload = {"type": "candleSnapshot", "req": {"coin": "HYPE", "interval": "1d",
                   "startTime": t, "endTime": min(t + step, end)}}
        r = requests.post("https://api.hyperliquid.xyz/info", json=payload, timeout=30)
        for x in r.json():
            d = datetime.fromtimestamp(x["t"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
            rows[d] = {"d": d, "o": float(x["o"]), "h": float(x["h"]),
                       "l": float(x["l"]), "c": float(x["c"])}
        t += step; time.sleep(0.3)
    return save(cid, list(rows.values()))

def main():
    reg = json.load(open(V4RES))["registry"]
    summary = {}
    for cid_s, info in reg.items():
        cid = int(cid_s)
        if info["source"] == "excluded":
            if cid == 32196:
                try: summary[cid_s] = {"symbol": "HYPE", "bars": fetch_hype(cid)}
                except Exception as e: summary[cid_s] = {"symbol": "HYPE", "error": str(e)}
            continue
        kind, name = info["source"].split(":", 1)
        path = os.path.join(OUT, f"{cid}.json")
        if os.path.exists(path):
            summary[cid_s] = {"symbol": info["symbol"], "bars": len(json.load(open(path))), "cached": True}
            continue
        try:
            if kind == "yahoo": n = fetch_yahoo(cid, name)
            elif kind == "binance": n = fetch_binance(cid, name)
            elif kind == "kraken": n = fetch_kraken(cid, name)
            summary[cid_s] = {"symbol": info["symbol"], "source": info["source"], "bars": n}
            print(cid, info["symbol"], info["source"], n, flush=True)
            time.sleep(0.2)
        except Exception as e:
            summary[cid_s] = {"symbol": info["symbol"], "source": info["source"], "error": str(e)}
            print(cid, info["symbol"], "ERROR", e, flush=True)
    with open(os.path.join(OUT, "fetch_summary.json"), "w") as f:
        json.dump(summary, f, indent=1)
    print("done", len(summary))

if __name__ == "__main__":
    main()
