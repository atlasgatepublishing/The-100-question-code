#!/usr/bin/env python3
"""Extend CUSIP->ticker mapping to all ranks. Family's own two stages:
stage 2 (SEC name match, local) first for speed, then stage 1 (OpenFIGI)
for the remainder. All caches written ONLY in this folder. The v10
cusip_map.json is read (never written) as the seed."""
import importlib.util, json, os, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
V10D = os.path.expanduser("~/workspace/stock-app/backtests/v10-retest/cloning-13f/data")
spec = importlib.util.spec_from_file_location("clone_engine", os.path.expanduser("~/workspace/stock-app/backtests/v10-retest/cloning-13f/engine.py"))
ENG = importlib.util.module_from_spec(spec); spec.loader.exec_module(ENG)

books = json.load(open(os.path.join(HERE, "books.json")))
names = {c: tuple(v) for c, v in books["cusip_names"].items()}
seed = json.load(open(os.path.join(V10D, "cusip_map.json")))
cmap = {c: v["ticker"] for c, v in seed.items() if v.get("ticker")}
print(f"seed tickers: {len(cmap)} / {len(names)} cusips", flush=True)

todo = {c: names[c] for c in names if c not in cmap}
fb, fb_log = ENG.name_map(todo)   # reads cached company_tickers.json only
for c, t in fb.items():
    cmap[c] = t
print(f"after name match: {len(cmap)} (+{len(fb)})", flush=True)
json.dump(fb_log, open(os.path.join(HERE, "name_match_log.json"), "w"), indent=1)

# OpenFIGI for the rest, own cache
cache_path = os.path.join(HERE, "figi_cache.json")
fcache = json.load(open(cache_path)) if os.path.exists(cache_path) else {}
rest = [c for c in names if c not in cmap and c not in fcache]
print(f"figi todo: {len(rest)}", flush=True)
for i in range(0, len(rest), 5):
    batch = rest[i:i + 5]
    jobs = [{"idType": "ID_CUSIP", "idValue": c} for c in batch]
    try:
        req = urllib.request.Request("https://api.openfigi.com/v3/mapping",
                                     data=json.dumps(jobs).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            resp = json.loads(r.read())
        for c, res in zip(batch, resp):
            data = res.get("data") or []
            us = [x for x in data if x.get("exchCode") == "US" and x.get("marketSector") == "Equity"]
            pick = None
            if us:
                cs = [x for x in us if x.get("securityType") == "Common Stock"]
                pick = cs[0] if cs else us[0]
            fcache[c] = {"ticker": (pick["ticker"].replace("/", "-") if pick else None),
                         "figi_name": (pick["name"] if pick else None)}
    except Exception as e:
        print("figi batch failed", i, e, flush=True)
        for c in batch:
            fcache.setdefault(c, {"ticker": None, "figi_name": None, "error": str(e)})
    json.dump(fcache, open(cache_path, "w"), indent=1)
    if i % 200 == 0:
        print(f"  figi {i}/{len(rest)} mapped so far {len(cmap) + sum(1 for v in fcache.values() if v.get('ticker'))}", flush=True)
    time.sleep(3)
for c, v in fcache.items():
    if v.get("ticker"):
        cmap.setdefault(c, v["ticker"])
unmapped = [c for c in names if c not in cmap]
print(f"FINAL mapped {len(cmap)} / {len(names)}; unmapped {len(unmapped)}", flush=True)
json.dump({"map": cmap, "unmapped": unmapped}, open(os.path.join(HERE, "cusip_map_ext.json"), "w"), indent=1)
