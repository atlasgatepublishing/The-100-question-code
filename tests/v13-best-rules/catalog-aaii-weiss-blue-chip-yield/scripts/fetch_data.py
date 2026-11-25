#!/usr/bin/env python3
"""Fetch (public data only):
1) EDGAR frames 2009-2013 for concepts the W04 stack only carries 2014+:
   instant (CY{y}Q4I): AssetsCurrent, LiabilitiesCurrent, StockholdersEquity,
   LongTermDebtCurrent, LongTermDebtNoncurrent, DebtCurrent, Shares (dei);
   duration (CY{y}): NetIncomeLoss.
   Saved to data/frames/{name}_{y}{I|D}.json in W04 format {cik: val}.
2) Yahoo monthly chart tapes (close, high, adjclose) 2010-01..2026-11 for every
   W04 candidate ticker -> data/px_<T>.json { 'YYYY-MM': [adj, close, high] }.
"""
import json, os, time, urllib.request, calendar, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data"); FR = os.path.join(DATA, "frames")
os.makedirs(FR, exist_ok=True)
W04 = os.path.expanduser("~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data")
H = {"User-Agent": "AtlasGate v13 research research@atlasgate.example"}

def get(u, tries=3):
    for i in range(tries):
        try:
            r = urllib.request.Request(u, headers=H)
            return urllib.request.urlopen(r, timeout=90).read()
        except Exception:
            if i == tries - 1: raise
            time.sleep(2 * (i + 1))

def frame(tax, concept, unit, per):
    u = f"https://data.sec.gov/api/xbrl/frames/{tax}/{concept}/{unit}/{per}.json"
    d = json.loads(get(u))
    return {int(r["cik"]): r["val"] for r in d["data"]}

INSTANT = ["AssetsCurrent", "LiabilitiesCurrent", "StockholdersEquity",
           "LongTermDebtCurrent", "LongTermDebtNoncurrent", "DebtCurrent"]
report = {}
for c in INSTANT:
    for y in range(2009, 2014):
        p = os.path.join(FR, f"{c}_{y}I.json")
        if os.path.exists(p): continue
        try:
            json.dump(frame("us-gaap", c, "USD", f"CY{y}Q4I"), open(p, "w")); report[f"{c}_{y}"] = "ok"
        except Exception as e:
            report[f"{c}_{y}"] = f"MISS {e}"
        time.sleep(0.12)
for y in range(2009, 2014):
    p = os.path.join(FR, f"Shares_{y}I.json")
    if not os.path.exists(p):
        try:
            json.dump(frame("dei", "EntityCommonStockSharesOutstanding", "shares", f"CY{y}Q4I"), open(p, "w")); report[f"Shares_{y}"] = "ok"
        except Exception as e:
            report[f"Shares_{y}"] = f"MISS {e}"
        time.sleep(0.12)
    p = os.path.join(FR, f"NetIncomeLoss_{y}D.json")
    if not os.path.exists(p):
        try:
            json.dump(frame("us-gaap", "NetIncomeLoss", "USD", f"CY{y}"), open(p, "w")); report[f"NI_{y}"] = "ok"
        except Exception as e:
            report[f"NI_{y}"] = f"MISS {e}"
        time.sleep(0.12)
print("frames done", flush=True)

cand = {int(k): v for k, v in json.load(open(os.path.join(W04, "candidates.json"))).items()}
tickers = sorted({v["ticker"].replace("/", "-") for v in cand.values()})
t1 = calendar.timegm(time.strptime("2009-12-01", "%Y-%m-%d"))
t2 = calendar.timegm(time.strptime("2026-11-22", "%Y-%m-%d"))
ok = fail = skip = 0
for t in tickers:
    out = os.path.join(DATA, f"px_{t}.json")
    if os.path.exists(out) and os.path.getsize(out) > 50:
        skip += 1; continue
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{t}"
           f"?period1={t1}&period2={t2}&interval=1mo&events=div,split")
    try:
        raw = get(url)
        res = json.loads(raw)["chart"]["result"][0]
        ts = res["timestamp"]; q = res["indicators"]["quote"][0]
        adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose")
        bars = {}
        for i, tt in enumerate(ts):
            d = time.strftime("%Y-%m", time.gmtime(tt))
            c = q["close"][i]; h = q["high"][i]
            a = adj[i] if adj else c
            if c is None or a is None: continue
            bars[d] = [a, c, h if h is not None else c]
        if len(bars) < 12: raise ValueError("short")
        json.dump(bars, open(out, "w")); ok += 1
    except Exception as e:
        report[f"px_{t}"] = f"FAIL {e}"; fail += 1
    time.sleep(0.15)
print(f"tapes ok={ok} fail={fail} cached={skip}", flush=True)
json.dump(report, open(os.path.join(DATA, "fetch_report.json"), "w"), indent=1)
