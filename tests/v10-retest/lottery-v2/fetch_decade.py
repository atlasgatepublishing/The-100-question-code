#!/usr/bin/env python3
"""Fetch decade daily bars (2016-01-01..2026-11-22) for the v2 lottery
candidate list + SPY from Yahoo chart API. Caches raw JSON per symbol in
data_cache_decade/. SPY fetched with adjclose for the dividend-adjusted
decade benchmark."""
import json, os, time, urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data_cache_decade")
os.makedirs(CACHE, exist_ok=True)

CANDIDATES = [
    "PLUG", "FCEL", "BLDP", "SNDL", "ACB", "CGC", "TLRY", "OGI", "CRON",
    "BYND", "GERN", "IOVA", "RXRX", "PACB", "DNA", "EDIT", "OCGN", "SAVA",
    "BTBT", "SDIG", "GREE", "CAN", "EBON", "SOS", "MULN", "FFAI", "NKLA",
    "GOEV", "WKHS", "BLNK", "EVGO", "CHPT", "SPCE", "JBLU", "ULCC", "AMC",
    "BB", "NOK", "KOSS", "VFS", "PSNY", "NIO", "GRAB", "FINV", "NNDM",
    "DDD", "EXK", "FSM", "HYMC", "TEF", "BBAI", "OPEN", "PTON", "TDOC",
    "LCID", "CLOV", "ACHR", "CIFR", "AGEN", "INO", "NVAX", "LX", "IQ",
    "TUYA", "NGD", "BTG", "DNN", "CLNE", "GEVO",
]

P1 = int(datetime(2016, 1, 1, tzinfo=timezone.utc).timestamp())
P2 = int(datetime(2026, 11, 22, tzinfo=timezone.utc).timestamp())

def fetch(sym, extra=""):
    path = os.path.join(CACHE, f"{sym}.json")
    if os.path.exists(path):
        return "cached"
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
           f"?period1={P1}&period2={P2}&interval=1d{extra}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        return f"FAILED {e}"
    res = data.get("chart", {}).get("result")
    if not res or not res[0].get("timestamp"):
        return "FAILED no-data"
    with open(path, "w") as f:
        json.dump(data, f)
    return f"ok {len(res[0]['timestamp'])} bars"

if __name__ == "__main__":
    for sym in CANDIDATES + ["SPY"]:
        print(sym, fetch(sym), flush=True)
        time.sleep(0.25)
    print("SPY_adj", fetch("SPY", extra="&events=div,split"), flush=True)
