#!/usr/bin/env python3
"""Fetch the EXTENDED-PULL dataset for the LONG road (CONSTRUCTION-SPEC (d)5):
same source and convention as the original v2 pull — Yahoo Finance chart API,
daily OHLCV, split-adjusted, NOT dividend-adjusted — but from 2009-01-01
(MA200 lead-in for a 2010-01-04 road start) to 2026-11-20. Cached as CSVs in
this folder's data/ in the exact v2 cache format. Also verifies the overlap
against the read-only v2 cache (2015-01-02 -> 2026-11-20) and writes the
audit to data/overlap_check.json. Mismatches are reported, never patched.
"""
import csv, json, os, time, urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
V2_DIR = os.path.expanduser("~/workspace/stock-app/backtests/v2/data")
os.makedirs(DATA_DIR, exist_ok=True)
TICKERS = ["SPY", "QQQ", "IWM", "GLD", "TLT"]
FETCH_FROM = int(datetime(2009, 1, 1, tzinfo=timezone.utc).timestamp())
FETCH_TO = int(datetime(2026, 11, 22, tzinfo=timezone.utc).timestamp())
ET = ZoneInfo("America/New_York")


def fetch(ticker):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={FETCH_FROM}&period2={FETCH_TO}&interval=1d"
           f"&events=history")
    payload = None
    for host in ("query1", "query2"):
        req = urllib.request.Request(url.replace("query1", host), headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) "
                          "AppleWebKit/537.36"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode())
            break
        except Exception:
            continue
    if payload is None:
        raise RuntimeError(f"could not fetch {ticker}")
    result = payload["chart"]["result"][0]
    ts = result["timestamp"]
    q = result["indicators"]["quote"][0]
    rows = []
    for i, t in enumerate(ts):
        vals = [q[k][i] for k in ("open", "high", "low", "close")]
        if any(v is None for v in vals):
            continue
        d = datetime.fromtimestamp(t, tz=ET).strftime("%Y-%m-%d")
        rows.append({"date": d, "open": vals[0], "high": vals[1],
                     "low": vals[2], "close": vals[3],
                     "volume": q["volume"][i] or 0})
    rows.sort(key=lambda r: r["date"])
    with open(os.path.join(DATA_DIR, f"{ticker}.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "open", "high", "low",
                                          "close", "volume"])
        w.writeheader()
        w.writerows(rows)
    time.sleep(0.3)
    return rows


def main():
    audit = {}
    for t in TICKERS:
        rows = fetch(t)
        with open(os.path.join(V2_DIR, f"{t}.csv")) as f:
            v2 = {r["date"]: r for r in csv.DictReader(f)}
        shared = [r for r in rows if r["date"] in v2]
        mism = []
        for r in shared:
            o = v2[r["date"]]
            for k in ("open", "high", "low", "close"):
                if abs(float(o[k]) - r[k]) > 1e-6:
                    mism.append({"date": r["date"], "field": k,
                                 "v2_cache": float(o[k]), "extended": r[k]})
        audit[t] = {"extended_rows": len(rows),
                    "extended_first": rows[0]["date"],
                    "extended_last": rows[-1]["date"],
                    "shared_dates": len(shared),
                    "mismatched_fields": len(mism),
                    "mismatch_examples": mism[:5]}
        print(t, audit[t]["extended_rows"], audit[t]["extended_first"],
              "->", audit[t]["extended_last"], "| shared", len(shared),
              "| mismatches", len(mism))
    with open(os.path.join(DATA_DIR, "overlap_check.json"), "w") as f:
        json.dump(audit, f, indent=2)


if __name__ == "__main__":
    main()
