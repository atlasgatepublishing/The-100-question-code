#!/usr/bin/env python3
"""
Fetch daily UTC bars WITH VOLUME for the v4 PIT coin registry, from the same
source per coin as the v4 registry (Yahoo / Binance), into this folder only.
v4 caches (read-only) carry open/close only; Amihud ILLIQ needs dollar volume.
Kraken TON -> Binance TONUSDT (frozen substitution, see CONSTRUCTION-SPEC).
HYPE -> Hyperliquid candleSnapshot (includes base volume).
"""
import json, os, time
from datetime import datetime, timezone
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
V4 = os.path.join(HERE, "..", "..", "v4")
os.makedirs(DATA, exist_ok=True)
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) research-fetch"})

def yahoo(ticker):
    p1 = int(datetime(2014, 1, 1, tzinfo=timezone.utc).timestamp())
    p2 = int(datetime(2026, 11, 22, tzinfo=timezone.utc).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={p1}&period2={p2}&interval=1d")
    r = S.get(url, timeout=30); r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    ts = res["timestamp"]; q = res["indicators"]["quote"][0]
    rows = {}
    for i, t in enumerate(ts):
        c, v = q["close"][i], q["volume"][i]
        if c is None or c <= 0: continue
        d = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
        rows[d] = {"d": d, "o": q["open"][i] if q["open"][i] else c, "c": c,
                   "v": float(v) if v else 0.0}
    return [rows[d] for d in sorted(rows)]

def binance(pair):
    rows = {}
    start = int(datetime(2017, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    end = int(datetime(2026, 11, 22, tzinfo=timezone.utc).timestamp() * 1000)
    while start < end:
        r = S.get("https://data-api.binance.vision/api/v3/klines",
                  params={"symbol": pair, "interval": "1d", "startTime": start,
                          "endTime": end, "limit": 1000}, timeout=30)
        r.raise_for_status()
        kl = r.json()
        if not kl: break
        for k in kl:
            d = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
            rows[d] = {"d": d, "o": float(k[1]), "c": float(k[4]), "qv": float(k[7]),
                       "v": float(k[5])}
        start = kl[-1][0] + 86400000
        time.sleep(0.2)
    return [rows[d] for d in sorted(rows)]

def hyperliquid():
    rows = {}
    start = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    end = int(datetime(2026, 11, 22, tzinfo=timezone.utc).timestamp() * 1000)
    step = 400 * 86400 * 1000; t = start
    while t < end:
        r = S.post("https://api.hyperliquid.xyz/info",
                   json={"type": "candleSnapshot", "req": {"coin": "HYPE", "interval": "1d",
                         "startTime": t, "endTime": min(t + step, end)}}, timeout=30)
        r.raise_for_status()
        for x in r.json():
            d = datetime.fromtimestamp(x["t"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
            c = float(x["c"])
            if c > 0: rows[d] = {"d": d, "o": float(x["o"]), "c": c, "v": float(x["v"])}
        t += step; time.sleep(0.3)
    return [rows[d] for d in sorted(rows)]

def main():
    with open(os.path.join(V4, "crypto-basket-pit-results.json")) as f:
        reg = json.load(f)["registry"]
    log = {}
    for cid_s, info in reg.items():
        cid = int(cid_s); src = info["source"]
        if src == "excluded":
            log[cid_s] = {"symbol": info["symbol"], "status": "excluded-v4", "reason": info["reason"]}
            continue
        kind, name = src.split(":", 1)
        path = os.path.join(DATA, f"vol_{cid}.json")
        if os.path.exists(path):
            with open(path) as f: rows = json.load(f)
            log[cid_s] = {"symbol": info["symbol"], "status": "cached", "bars": len(rows)}
            continue
        try:
            if kind == "yahoo": rows = yahoo(name)
            elif kind == "binance": rows = binance(name)
            elif kind == "kraken": rows = binance("TONUSDT")  # frozen substitution
            else: raise ValueError(kind)
        except Exception as e:
            log[cid_s] = {"symbol": info["symbol"], "status": "FAILED", "error": str(e)[:200]}
            print("FAIL", cid_s, info["symbol"], e); continue
        with open(path, "w") as f: json.dump(rows, f)
        nz = sum(1 for r in rows if (r.get("qv") or r.get("v") or 0) > 0)
        log[cid_s] = {"symbol": info["symbol"], "status": "ok", "source": src,
                      "bars": len(rows), "vol_days": nz,
                      "first": rows[0]["d"] if rows else None, "last": rows[-1]["d"] if rows else None}
        print("ok", cid_s, info["symbol"], len(rows), "vol_days", nz)
        time.sleep(0.3)
    # HYPE
    path = os.path.join(DATA, "vol_32196.json")
    if not os.path.exists(path):
        rows = hyperliquid()
        with open(path, "w") as f: json.dump(rows, f)
    else:
        with open(path) as f: rows = json.load(f)
    log["32196"] = {"symbol": "HYPE", "status": "ok", "source": "hyperliquid:HYPE",
                    "bars": len(rows), "first": rows[0]["d"], "last": rows[-1]["d"]}
    with open(os.path.join(DATA, "fetch_log.json"), "w") as f: json.dump(log, f, indent=1)
    ok = sum(1 for v in log.values() if v["status"] in ("ok", "cached"))
    print(f"DONE ok={ok} total={len(log)}")

if __name__ == "__main__":
    main()
