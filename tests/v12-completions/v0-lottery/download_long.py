#!/usr/bin/env python3
"""Download long-history daily bars (Yahoo chart API, the v0 channel) for the
frozen v0 candidate list + SPY, 2009-06-01 -> 2026-11-21, cached in
./data_long/ next to this script. Mirrors the v0/v10 fetchers exactly."""
import json, os, time, urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data_long")
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

def fetch(symbol):
    path = os.path.join(CACHE, f"{symbol}.json")
    if os.path.exists(path):
        return "cached"
    p1 = int(datetime(2009, 6, 1, tzinfo=timezone.utc).timestamp())
    p2 = int(datetime(2026, 11, 22, tzinfo=timezone.utc).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?period1={p1}&period2={p2}&interval=1d&events=div,split")
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        with open(path, "w") as f:
            json.dump({"error": str(e)}, f)
        return f"FAILED {e}"
    with open(path, "w") as f:
        json.dump(data, f)
    time.sleep(0.3)
    return "ok"

if __name__ == "__main__":
    for s in CANDIDATES + ["SPY"]:
        print(s, fetch(s), flush=True)
