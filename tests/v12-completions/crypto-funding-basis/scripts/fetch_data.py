#!/usr/bin/env python3
"""Fetch Binance public-archive funding rates + perp 8h klines (data.binance.vision).
Free, no key. Parallel + resumable: per-month parts in ../data/parts/, then assembled."""
import io, os, zipfile
from concurrent.futures import ThreadPoolExecutor
import requests

BASE = "https://data.binance.vision/data/futures/um/monthly"
ROOT = os.path.join(os.path.dirname(__file__), "..", "data")
PARTS = os.path.join(ROOT, "parts")
os.makedirs(PARTS, exist_ok=True)
COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
MONTHS = []
y, m = 2020, 1
while (y, m) <= (2026, 10):
    MONTHS.append(f"{y:04d}-{m:02d}")
    m += 1
    if m == 13:
        y, m = y + 1, 1

def job(args):
    kind, coin, mo = args
    part = os.path.join(PARTS, f"{coin}_{kind}_{mo}.csv")
    if os.path.exists(part):
        return (kind, coin, mo, "cached")
    if kind == "fundingRate":
        url = f"{BASE}/fundingRate/{coin}/{coin}-fundingRate-{mo}.zip"
    else:
        url = f"{BASE}/klines/{coin}/8h/{coin}-8h-{mo}.zip"
    try:
        r = requests.get(url, timeout=60)
    except Exception as e:
        return (kind, coin, mo, f"ERR {e}")
    if r.status_code != 200:
        open(part + ".404", "w").write("")
        return (kind, coin, mo, "404")
    z = zipfile.ZipFile(io.BytesIO(r.content))
    text = z.read(z.namelist()[0]).decode()
    lines = text.strip().splitlines()
    if lines and (lines[0].startswith("calc_time") or lines[0].startswith("open_time")):
        lines = lines[1:]
    if kind == "klines":
        lines = [",".join(ln.split(",")[:7]) for ln in lines]
    with open(part, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return (kind, coin, mo, "ok")

tasks = [(k, c, mo) for c in COINS for k in ("fundingRate", "klines") for mo in MONTHS]
with ThreadPoolExecutor(max_workers=16) as ex:
    res = list(ex.map(job, tasks))
from collections import Counter
print(Counter(r[3] for r in res))

for coin in COINS:
    with open(os.path.join(ROOT, f"{coin}_funding.csv"), "w") as ff, \
         open(os.path.join(ROOT, f"{coin}_klines8h.csv"), "w") as fk:
        ff.write("calc_time,funding_interval_hours,last_funding_rate\n")
        fk.write("open_time,open,high,low,close,volume,close_time\n")
        nf = nk = 0
        for mo in MONTHS:
            p = os.path.join(PARTS, f"{coin}_fundingRate_{mo}.csv")
            if os.path.exists(p):
                ff.write(open(p).read()); nf += 1
            p = os.path.join(PARTS, f"{coin}_klines_{mo}.csv")
            if os.path.exists(p):
                fk.write(open(p).read()); nk += 1
        print(coin, "funding months", nf, "kline months", nk)
print("done")
