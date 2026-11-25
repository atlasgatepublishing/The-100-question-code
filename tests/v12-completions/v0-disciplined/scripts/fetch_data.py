#!/usr/bin/env python3
"""Fetch Yahoo daily bars 2009-01-01..2026-11-21 for SPY/QQQ/IWM/GLD/TLT,
cache as CSV in ../data/ (same source/convention as the original v0 engines:
split-adjusted, NOT dividend-adjusted)."""
import csv, json, os, subprocess
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
os.makedirs(DATA, exist_ok=True)
ET = ZoneInfo("America/New_York")
P1 = int(datetime(2009, 1, 1, tzinfo=timezone.utc).timestamp())
P2 = int(datetime(2026, 11, 22, tzinfo=timezone.utc).timestamp())

for sym in ["SPY", "QQQ", "IWM", "GLD", "TLT"]:
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
           f"?period1={P1}&period2={P2}&interval=1d")
    out = subprocess.run(["curl", "-s", "-m", "60", "-A", "Mozilla/5.0 (X11; Linux x86_64)", url],
                         capture_output=True, text=True)
    result = json.loads(out.stdout)["chart"]["result"][0]
    q = result["indicators"]["quote"][0]
    rows = []
    for ts, o, h, l, c, v in zip(result["timestamp"], q["open"], q["high"], q["low"], q["close"], q["volume"]):
        if None in (o, h, l, c):
            continue
        d = datetime.fromtimestamp(ts, tz=ET).strftime("%Y-%m-%d")
        rows.append({"date": d, "open": o, "high": h, "low": l, "close": c, "volume": v or 0})
    rows.sort(key=lambda r: r["date"])
    # de-dupe by date, keep last
    dedup = {}
    for r in rows: dedup[r["date"]] = r
    rows = [dedup[d] for d in sorted(dedup)]
    with open(os.path.join(DATA, f"{sym}.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "open", "high", "low", "close", "volume"])
        w.writeheader(); w.writerows(rows)
    print(sym, rows[0]["date"], rows[-1]["date"], len(rows))
