#!/usr/bin/env python3
"""Re-fetch price payloads that are missing or <=1000 bytes (truncated by
the killed earlier run). Writes via temp file + rename; verifies the JSON
parses and chart.result is non-empty before accepting."""
import json, os, sys, urllib.request, urllib.parse, datetime
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
YH_H = {"User-Agent": "Mozilla/5.0"}

def get(url, tries=3):
    import time
    for i in range(tries):
        try:
            r = urllib.request.Request(url, headers=YH_H)
            return urllib.request.urlopen(r, timeout=30).read()
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))

def one(t):
    p = os.path.join(DATA, f"pxfull_{t}.json")
    if os.path.exists(p) and os.path.getsize(p) > 1000:
        return (t, "skip")
    p1 = int(datetime.datetime(2008, 1, 1, tzinfo=datetime.timezone.utc).timestamp())
    p2 = int(datetime.datetime(2026, 11, 22, tzinfo=datetime.timezone.utc).timestamp())
    u = ("https://query1.finance.yahoo.com/v8/finance/chart/%s"
         "?period1=%d&period2=%d&interval=1d&events=div,split"
         % (urllib.parse.quote(t), p1, p2))
    try:
        blob = get(u)
        d = json.loads(blob)
        if not d["chart"]["result"]:
            raise ValueError("empty result")
        tmp = p + ".tmp"
        open(tmp, "wb").write(blob)
        if os.path.exists(p):
            os.unlink(p)  # overlayfs refuses rename-over-existing (EPERM)
        os.rename(tmp, p)
        return (t, "ok")
    except Exception as e:
        return (t, f"FAIL {e}")

if __name__ == "__main__":
    seed = json.load(open(os.path.join(DATA, "tradable_universe.json")))
    tickers = sorted({v["ticker"] for v in seed["tradable"].values()}) + ["SPY"]
    todo = [t for t in tickers
            if not (os.path.exists(os.path.join(DATA, f"pxfull_{t}.json"))
                    and os.path.getsize(os.path.join(DATA, f"pxfull_{t}.json")) > 1000)]
    print(f"to fetch: {len(todo)} of {len(tickers)}", flush=True)
    budget = float(os.environ.get("TIME_BUDGET", "0"))
    if budget:
        import time as _t
        t_end = _t.time() + budget
        res = []
        for t in todo:
            if _t.time() > t_end:
                break
            r = one(t)
            res.append(r)
            print(" ", r, flush=True)
        print(f"chunk done: {len(res)} attempted, {len(todo) - len(res)} remain", flush=True)
        sys.exit(0)
    with ThreadPoolExecutor(max_workers=3) as ex:
        res = list(ex.map(one, todo))
    fails = [(t, e) for t, e in res if e.startswith("FAIL")]
    print(f"done ok={len(res) - len(fails)} fail={len(fails)}", flush=True)
    for t, e in fails:
        print("FAIL", t, e, flush=True)
    json.dump([{"ticker": t, "error": e} for t, e in fails],
              open(os.path.join(DATA, "price_failures_fix.json"), "w"), indent=1)
    print("PRICE FIX DONE", flush=True)
