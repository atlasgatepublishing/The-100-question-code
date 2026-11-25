#!/usr/bin/env python3
"""Threaded version of fetch_data.py (same outputs, same sources; skips
files already fetched). 6 workers; SEC fair access is 10 req/s total and
observed latency keeps us well under it."""
import json, os, sys, time, urllib.request, urllib.parse, datetime
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_data import DATA, SEC_H, YH_H, CONCEPTS, get, tradable_seed


def one_concepts(cik):
    p = os.path.join(DATA, f"concepts_{cik:010d}.json")
    if os.path.exists(p) and os.path.getsize(p) > 50:
        return (cik, "skip")
    bundle = {}
    try:
        for tax, concept in CONCEPTS:
            u = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/{tax}/{concept}.json"
            try:
                bundle[f"{tax}:{concept}"] = json.loads(get(u, SEC_H))
            except Exception as e:
                bundle[f"{tax}:{concept}"] = {"error": str(e)}
        json.dump(bundle, open(p, "w"))
        return (cik, "ok")
    except Exception as e:
        return (cik, f"FAIL {e}")


def one_price(t):
    p = os.path.join(DATA, f"pxfull_{t}.json")
    if os.path.exists(p) and os.path.getsize(p) > 1000:
        return (t, "skip")
    p1 = int(datetime.datetime(2008, 1, 1, tzinfo=datetime.timezone.utc).timestamp())
    p2 = int(datetime.datetime(2026, 11, 22, tzinfo=datetime.timezone.utc).timestamp())
    u = ("https://query1.finance.yahoo.com/v8/finance/chart/%s"
         "?period1=%d&period2=%d&interval=1d&events=div,split"
         % (urllib.parse.quote(t), p1, p2))
    try:
        blob = get(u, YH_H)
        d = json.loads(blob)
        if not d["chart"]["result"]:
            raise ValueError("empty result")
        open(p, "wb").write(blob)
        return (t, "ok")
    except Exception as e:
        return (t, f"FAIL {e}")


if __name__ == "__main__":
    seed, dropped = tradable_seed()
    print(f"tradable seed: {len(seed)} CIKs", flush=True)
    with ThreadPoolExecutor(max_workers=4) as ex:
        res = list(ex.map(one_concepts, sorted(seed)))
    fails = [r for r in res if r[1].startswith("FAIL")]
    print(f"concepts: ok/skip={len(res) - len(fails)} fail={len(fails)} {fails[:10]}", flush=True)
    tickers = sorted({v["ticker"] for v in seed.values()}) + ["SPY"]
    with ThreadPoolExecutor(max_workers=4) as ex:
        res = list(ex.map(one_price, tickers))
    fails = [{"ticker": t, "error": e} for t, e in res if e.startswith("FAIL")]
    json.dump(fails, open(os.path.join(DATA, "price_failures.json"), "w"), indent=1)
    print(f"prices: ok/skip={len(res) - len(fails)} fail={len(fails)} {[f['ticker'] for f in fails[:20]]}", flush=True)
    print("ALL FETCH DONE", flush=True)
