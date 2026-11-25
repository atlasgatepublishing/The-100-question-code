#!/usr/bin/env python3
"""Fetch daily adjclose for every ticker that was an S&P 500 member at any
snapshot 2009-01-01..2026-11-20 (per data/sp500_hist.csv). Reuses the v7
program daily cache (same Yahoo adjusted convention) where present; fetches
the rest from the Yahoo chart API. Class shares use Yahoo dash form;
FB is fetched as META successor segment handled in the runner (both tickers
fetched as listed). Failures recorded, never patched. Output: data/px_<T>.json
as [[date, adjclose], ...]. Simulation only."""
import csv, json, os, time, urllib.request, urllib.parse, glob
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
FAM = os.path.dirname(HERE)
DATA = os.path.join(FAM, "data")
V7 = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
UA = {"User-Agent": "Mozilla/5.0"}
P1, P2 = 1228003200, 1796000000  # 2008-12-01 .. 2026-12

def universe():
    rows = list(csv.reader(open(os.path.join(DATA, "sp500_hist.csv"))))[1:]
    u = set()
    for d, t in rows:
        if "2009-01-01" <= d <= "2026-11-20":
            u.update(t.split(","))
    return sorted(u)

def parse_chart(j):
    r = j["chart"]["result"][0]
    ts = r["timestamp"]; adj = r["indicators"]["adjclose"][0]["adjclose"]
    out = []
    for i, t in enumerate(ts):
        if adj[i] is None:
            continue
        out.append([time.strftime("%Y-%m-%d", time.gmtime(t)), round(float(adj[i]), 6)])
    return out


def write_rows(outp, rows):
    """Write with verification + retries: this sandbox intermittently EPERMs
    on flush, leaving 0-byte files. Verify size, retry, never fake success."""
    for attempt in range(6):
        try:
            tmp = outp + ".tmp"
            with open(tmp, "w") as f:
                json.dump(rows, f); f.flush(); os.fsync(f.fileno())
            if os.path.getsize(tmp) < 100:
                raise IOError("short write")
            os.replace(tmp, outp)
            if os.path.getsize(outp) >= 100:
                return True
        except Exception:
            time.sleep(1.5 * (attempt + 1))
    return False

def fetch_one(t):
    yahoo_t = t.replace(".", "-")
    outp = os.path.join(DATA, f"px_{t}.json")
    if os.path.exists(outp):
        return (t, "cached")
    cache = os.path.join(V7, f"pxfull_{yahoo_t}.json")
    if os.path.exists(cache):
        try:
            rows = parse_chart(json.load(open(cache)))
            rows = [r for r in rows if r[0] >= "2008-12-01"]
            if len(rows) >= 100:
                if write_rows(outp, rows): return (t, "v7cache")
                raise IOError("write failed")
        except Exception:
            pass
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/%s?period1=%d&period2=%d&interval=1d&events=div,split"
           % (urllib.parse.quote(yahoo_t), P1, P2))
    last = None
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers=UA)
            d = json.loads(urllib.request.urlopen(req, timeout=30).read())
            if not d["chart"]["result"]:
                raise ValueError("no result")
            rows = parse_chart(d)
            if len(rows) < 20:
                raise ValueError(f"too few bars {len(rows)}")
            if write_rows(outp, rows): return (t, "fetched")
            raise IOError("write failed")
        except Exception as e:
            last = str(e)
            if "429" in last:
                return (t, "RATE_LIMITED: " + last)
            if "404" in last:
                break  # delisted/vanished on Yahoo: retrying does not change it
            time.sleep(2 * (attempt + 1))
    return (t, "FAIL: " + str(last))

def main():
    import sys
    u = universe()
    if len(sys.argv) > 1:  # chunk mode: fetch tickers whose initial letter is in argv[1]
        u = [t for t in u if t[0] in sys.argv[1]]
    print("universe", len(u), flush=True)
    fails, stats = [], {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        for t, status in ex.map(fetch_one, u):
            stats[status.split(":")[0]] = stats.get(status.split(":")[0], 0) + 1
            if status.startswith(("FAIL", "RATE_LIMITED")):
                fails.append({"ticker": t, "error": status})
                print("FAIL", t, status, flush=True)
    prev = []
    fp = os.path.join(DATA, "price_failures.json")
    if os.path.exists(fp):
        prev = json.load(open(fp))
    merged = {f["ticker"]: f for f in prev + fails}
    # drop tickers that now have files
    merged = {t: f for t, f in merged.items() if not os.path.exists(os.path.join(DATA, f"px_{t}.json"))}
    json.dump(list(merged.values()), open(fp, "w"), indent=1)
    print("stats", stats, "failures", len(fails), flush=True)

if __name__ == "__main__":
    main()
