#!/usr/bin/env python3
"""Fetch Binance public-archive funding rates + USD-M daily klines for every
PIT top-20 coin with a mapped perpetual. Free, no key (data.binance.vision).
Per-month parts in ../data/parts/, assembled per-symbol CSVs in ../data/.
Resumable: existing parts are skipped. 404 months are recorded (.404 marker)
-- a symbol's first/last real month IS its listing/delisting record."""
import io, os, zipfile, json
from concurrent.futures import ThreadPoolExecutor
import requests

BASE = "https://data.binance.vision/data/futures/um/monthly"
ROOT = os.path.join(os.path.dirname(__file__), "..", "data")
PARTS = os.path.join(ROOT, "parts")
os.makedirs(PARTS, exist_ok=True)

SNAP = "/home/hatch/workspace/stock-app/backtests/v12-completions/crypto-basket-pit/data/weekly_snapshots.json"
EXCLUDE = {"USDT","USDC","DAI","BUSD","TUSD","UST","USD1","USDE","WBTC"}
MAP = {"SHIB": "1000SHIBUSDT", "PEPE": "1000PEPEUSDT", "MIOTA": "IOTAUSDT"}

snaps = json.load(open(SNAP))
pit_syms = set()
for d, v in snaps.items():
    if d < "2020-01-01":
        continue  # run window starts 2020-02; pre-perp-era snapshots cannot enter the panel
    for c in v["top20"]:
        pit_syms.add(c["symbol"])
COINS = {}  # perp symbol -> cmc symbol
for s in sorted(pit_syms - EXCLUDE):
    perp = MAP.get(s, s + "USDT")
    COINS[perp] = s
print("candidate perps:", len(COINS))

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
    if os.path.exists(part) or os.path.exists(part + ".404"):
        return (kind, coin, mo, "cached")
    if kind == "fundingRate":
        url = f"{BASE}/fundingRate/{coin}/{coin}-fundingRate-{mo}.zip"
    else:
        url = f"{BASE}/klines/{coin}/1d/{coin}-1d-{mo}.zip"
    try:
        r = requests.get(url, timeout=60)
    except Exception as e:
        return (kind, coin, mo, f"ERR {type(e).__name__}")
    if r.status_code != 200:
        open(part + ".404", "w").write("")
        return (kind, coin, mo, "404")
    try:
        z = zipfile.ZipFile(io.BytesIO(r.content))
        text = z.read(z.namelist()[0]).decode()
    except Exception as e:
        return (kind, coin, mo, f"BADZIP {type(e).__name__}")
    lines = text.strip().splitlines()
    if lines and (lines[0].startswith("calc_time") or lines[0].startswith("open_time")):
        lines = lines[1:]
    if kind == "klines":
        lines = [",".join(ln.split(",")[:6]) for ln in lines]
    with open(part, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return (kind, coin, mo, "ok")

tasks = [(k, c, mo) for c in COINS for k in ("fundingRate", "klines") for mo in MONTHS]
with ThreadPoolExecutor(max_workers=12) as ex:
    res = list(ex.map(job, tasks))
from collections import Counter
print(Counter(r[3] for r in res))
errs = [r for r in res if r[3].startswith(("ERR", "BADZIP"))]
print("errors (retry by re-running):", len(errs), errs[:10])

spans = {}
for coin in COINS:
    with open(os.path.join(ROOT, f"{coin}_funding.csv"), "w") as ff, \
         open(os.path.join(ROOT, f"{coin}_klines1d.csv"), "w") as fk:
        ff.write("calc_time,funding_interval_hours,last_funding_rate\n")
        fk.write("open_time,open,high,low,close,volume\n")
        nf = nk = 0
        first = last = None
        for mo in MONTHS:
            p = os.path.join(PARTS, f"{coin}_fundingRate_{mo}.csv")
            if os.path.exists(p):
                ff.write(open(p).read()); nf += 1
                if first is None: first = mo
                last = mo
            p = os.path.join(PARTS, f"{coin}_klines_{mo}.csv")
            if os.path.exists(p):
                fk.write(open(p).read()); nk += 1
        spans[coin] = {"cmc": COINS[coin], "funding_months": nf, "kline_months": nk,
                       "first_funding_month": first, "last_funding_month": last}
        print(coin, COINS[coin], "funding months", nf, first, "->", last, "kline months", nk)
json.dump(spans, open(os.path.join(ROOT, "spans.json"), "w"), indent=1)
print("done")
