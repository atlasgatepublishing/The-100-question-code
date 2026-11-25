"""Fetch point-in-time quarterly diluted EPS from SEC EDGAR XBRL companyconcept API.
For each ticker with a cached Yahoo price file in the v3/v4 shared caches (read-only),
pull EarningsPerShareDiluted facts, keep ~quarter-length facts, dedupe by period-end
keeping the EARLIEST filed date (filing-date discipline). Saved to ./eps_cache/.
"""
import json, os, time, urllib.request, glob

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "eps_cache"); os.makedirs(OUT, exist_ok=True)
CACHES = ["/home/hatch/workspace/stock-app/backtests/v3/pead-cache",
          "/home/hatch/workspace/stock-app/backtests/v4/pead-small-cache"]

tickers = set()
for c in CACHES:
    for f in glob.glob(os.path.join(c, "px_*.json")):
        t = os.path.basename(f)[3:-5]
        if t != "SPY": tickers.add(t)
tickers = sorted(tickers)

cik = {}
for c in CACHES[:1]:
    d = json.load(open(os.path.join(c, "company_tickers.json")))
    for v in d.values():
        cik[v["ticker"]] = v["cik_str"]

UA = {"User-Agent": "AtlasGatePublishing research contact@example.com"}
ok, fail = [], []
for t in tickers:
    dst = os.path.join(OUT, f"eps_{t}.json")
    if os.path.exists(dst): ok.append(t); continue
    c = cik.get(t)
    if not c: fail.append((t, "no cik")); continue
    url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{c:010d}/us-gaap/EarningsPerShareDiluted.json"
    try:
        req = urllib.request.Request(url, headers=UA)
        raw = json.load(urllib.request.urlopen(req, timeout=30))
        units = raw.get("units", {}).get("USD/shares", [])
        facts = []
        from datetime import date
        for u in units:
            try:
                s = date.fromisoformat(u["start"]); e = date.fromisoformat(u["end"])
            except Exception: continue
            dur = (e - s).days
            if 80 <= dur <= 100 and u.get("form") in ("10-Q", "10-K", "10-Q/A", "10-K/A"):
                facts.append({"end": u["end"], "filed": u["filed"], "val": u["val"], "form": u["form"]})
        # dedupe by period end: earliest filed wins
        by_end = {}
        for f in facts:
            if f["end"] not in by_end or f["filed"] < by_end[f["end"]]["filed"]:
                by_end[f["end"]] = f
        facts = sorted(by_end.values(), key=lambda x: x["end"])
        json.dump({"ticker": t, "cik": c, "facts": facts}, open(dst, "w"))
        ok.append(t)
    except Exception as ex:
        fail.append((t, str(ex)[:80]))
    time.sleep(0.15)
print("tickers", len(tickers), "ok", len(ok), "fail", fail)
