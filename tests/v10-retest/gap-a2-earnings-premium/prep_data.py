#!/usr/bin/env python3
"""
Data prep for the v10 cadence sweep of gap-a2-earnings-premium.

The original v7 test only needed EDGAR Item 2.02 dates from 2017-06-01
and Yahoo prices from 2017-06-01 (its windows started 2019). The v10
DECADE road starts 2016-11-21, so this script extends both series
backwards, caching everything inside THIS folder only:

1. EDGAR: downloads the submissions blocks overlapping
   2015-01-01..2017-07-15 that the original fetch skipped, into
   edgar-cache-ext/, then rebuilds the Item 2.02 earnings-date table
   over 2015-01-01..2026-11-21 from (a) the copied original cache in
   edgar-cache/ and (b) the new blocks. Saved as earnings_dates_ext.json.
   Sanity check: restricted to >= 2017-06-01 it must equal the original
   cached earnings_dates.json exactly.

2. Prices: downloads Yahoo chart payloads 2016-09-01..2017-07-15 for the
   30-name pond + SPY into px-ext/, parses them with the champion
   engine's exact adjustment method (close = adjclose; open scaled by
   adjclose/close), splices the pre-2017-06-01 bars onto the front of
   the champion cache bars, rescaling the early segment by the ratio of
   cached/downloaded close on the first common date (2017-06-01) so the
   series is continuous. Saved as px-ext/bars_<ticker>.json.
"""
import importlib.util
import json
import os
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ORIG_CACHE = os.path.join(HERE, "edgar-cache")
EXT_CACHE = os.path.join(HERE, "edgar-cache-ext")
PX = os.path.join(HERE, "px-ext")
os.makedirs(EXT_CACHE, exist_ok=True)
os.makedirs(PX, exist_ok=True)

spec = importlib.util.spec_from_file_location(
    "engine", os.path.join(HERE, "engine.py"))
ENG = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ENG)
E = ENG.E
UNIVERSE = ENG.UNIVERSE
UA = E.UA

EXT_FROM, EXT_TO = "2015-01-01", "2026-11-21"
NEED_FROM, NEED_TO = "2015-01-01", "2017-07-15"


def fetch_cached(url, path):
    if os.path.exists(path) and os.path.getsize(path) > 100:
        with open(path, "rb") as f:
            return f.read()
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        blob = r.read()
    with open(path, "wb") as f:
        f.write(blob)
    time.sleep(0.15)
    return blob


def filings_from_block(block, out):
    forms = block.get("form", [])
    dates = block.get("filingDate", [])
    items = block.get("items", [])
    for i, form in enumerate(forms):
        if form not in ("8-K", "8-K/A"):
            continue
        fd = dates[i] if i < len(dates) else ""
        if not fd or fd < EXT_FROM or fd > EXT_TO:
            continue
        it = items[i] if i < len(items) else ""
        if "2.02" in [s.strip() for s in it.split(",")]:
            out.append(fd)


def build_earnings_dates():
    out = {}
    for t in UNIVERSE:
        sub = json.load(open(os.path.join(ORIG_CACHE, f"sub_{t}.json")))
        dates = []
        filings_from_block(sub["filings"]["recent"], dates)
        for extra in sub["filings"].get("files", []):
            if extra["filingTo"] < EXT_FROM or extra["filingFrom"] > EXT_TO:
                continue
            name = extra["name"]
            local = os.path.join(ORIG_CACHE, f"sub_{t}_{name}")
            ext = os.path.join(EXT_CACHE, f"sub_{t}_{name}")
            if os.path.exists(local):
                block = json.loads(open(local, "rb").read())
            else:
                block = json.loads(fetch_cached(
                    f"https://data.sec.gov/submissions/{name}", ext))
            filings_from_block(block, dates)
        out[t] = sorted(set(dates))
        print(f"  EDGAR {t}: {len(out[t])} dates "
              f"({out[t][0] if out[t] else '-'}..{out[t][-1] if out[t] else '-'})",
              flush=True)
    with open(os.path.join(HERE, "earnings_dates_ext.json"), "w") as f:
        json.dump(out, f, indent=1)
    # sanity: >= 2017-06-01 must match the original cached table exactly
    orig = json.load(open(os.path.join(ORIG_CACHE, "earnings_dates.json")))
    bad = []
    for t in UNIVERSE:
        mine = [d for d in out[t] if d >= "2017-06-01"]
        if mine != sorted(orig.get(t, [])):
            bad.append(t)
    print("SANITY vs original cache (>=2017-06-01):",
          "MATCH all 30" if not bad else f"MISMATCH {bad}", flush=True)
    return out


def parse_yahoo(blob):
    j = json.loads(blob)
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, c = q["open"][i], q["close"][i]
        if c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        bars.append({"d": d, "o": (o * ratio if o else a), "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars


def build_prices():
    import calendar
    t1 = calendar.timegm(time.strptime("2016-09-01", "%Y-%m-%d"))
    t2 = calendar.timegm(time.strptime("2017-07-15", "%Y-%m-%d"))
    for t in UNIVERSE + ["SPY"]:
        cached = E.get_prices(t)  # champion cache, starts 2017-06-01
        raw_path = os.path.join(PX, f"px_{t}.json")
        if os.path.exists(raw_path) and os.path.getsize(raw_path) > 100:
            blob = open(raw_path, "rb").read()
        else:
            url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{t}"
                   f"?period1={t1}&period2={t2}&interval=1d&events=div,split")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                blob = r.read()
            with open(raw_path, "wb") as f:
                f.write(blob)
            time.sleep(0.15)
        dl = parse_yahoo(blob)
        early = [b for b in dl if b["d"] < "2017-06-01"]
        # splice scale: ratio on first common date
        dlmap = {b["d"]: b for b in dl}
        common = next(b["d"] for b in cached if b["d"] in dlmap)
        k = next(b["c"] for b in cached if b["d"] == common) / dlmap[common]["c"]
        early = [{"d": b["d"], "o": b["o"] * k, "c": b["c"] * k} for b in early]
        bars = early + cached
        with open(os.path.join(PX, f"bars_{t}.json"), "w") as f:
            json.dump(bars, f)
        print(f"  PX {t}: {len(early)} early bars spliced (k={k:.6f}), "
              f"series {bars[0]['d']}..{bars[-1]['d']}", flush=True)


if __name__ == "__main__":
    print("Building extended EDGAR earnings dates...", flush=True)
    build_earnings_dates()
    print("Building spliced price series...", flush=True)
    build_prices()
    print("PREP DONE")
