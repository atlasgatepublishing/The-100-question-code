#!/usr/bin/env python3
"""Scrape CoinMarketCap weekly (Sunday) historical snapshots, top-20 each,
2017-01-01 -> 2026-11-15. Same free CMC historical pages v4 used monthly.
Parser validated against v4's 2022-05-01 snapshot (exact top-20 match).
Output: data/weekly_snapshots.json {YYYY-MM-DD: {snapshot_date, top20:[...]}}
"""
import json, os, re, time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "weekly_snapshots.json")
H = {"User-Agent": "Mozilla/5.0"}
PAT = re.compile(r'cmc-static-icon-(\d+)"?/?><a href="/currencies/([a-z0-9\-]+)/" '
                 r'title="[^"]*" class="cmc-table__column-name--symbol cmc-link">([A-Z0-9]+)</a>')

def fetch(d):
    ds = d.strftime("%Y%m%d")
    for attempt in range(3):
        try:
            r = requests.get(f"https://coinmarketcap.com/historical/{ds}/", headers=H, timeout=25)
            if r.status_code != 200:
                time.sleep(2); continue
            out, seen = [], set()
            for m in PAT.finditer(r.text):
                cid = int(m.group(1))
                if cid in seen: continue
                seen.add(cid)
                out.append({"rank": len(out)+1, "symbol": m.group(3),
                            "slug": m.group(2), "cmc_id": cid, "mcap": None})
                if len(out) >= 20: break
            if len(out) >= 15:
                return d.strftime("%Y-%m-%d"), {"snapshot_date": ds, "top20": out}
            time.sleep(2)
        except Exception:
            time.sleep(2)
    return d.strftime("%Y-%m-%d"), None

def main():
    days = []
    d = date(2017, 1, 1)  # a Sunday
    while d <= date(2026, 11, 15):
        days.append(d); d += timedelta(days=7)
    print(f"{len(days)} Sundays", flush=True)
    res, fails = {}, []
    with ThreadPoolExecutor(max_workers=6) as ex:
        for k, v in ex.map(fetch, days):
            if v is None: fails.append(k)
            else: res[k] = v
    print(f"ok={len(res)} fails={fails}", flush=True)
    with open(OUT, "w") as f:
        json.dump(res, f, indent=1)
    coins = {}
    for info in res.values():
        for c in info["top20"]:
            coins.setdefault(c["cmc_id"], c["symbol"])
    print(f"distinct coins ever in a weekly top-20: {len(coins)}", flush=True)

if __name__ == "__main__":
    main()
