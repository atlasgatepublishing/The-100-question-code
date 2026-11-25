"""Stage 1: fence universe + Yahoo ex-date split census (factor >= 2, 2010-2026).
Universe: v11 _w04 candidates.json (658 CIK-keyed tickers, read-only) + v10 pond
(cache filenames in v10 gap-a7 folder, read-only). Raw Yahoo JSON cached locally.
"""
import json, os, re, time, glob
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache"); os.makedirs(CACHE, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}

cand = json.load(open(os.path.expanduser(
    "~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data/candidates.json")))
universe = {}  # ticker -> cik (int or None)
for cik, v in cand.items():
    t = (v.get("ticker") or "").strip().upper()
    if re.fullmatch(r"[A-Z]{1,6}([.-][A-Z])?", t or ""):
        universe[t] = int(cik)
pond = [os.path.basename(p)[7:-5] for p in glob.glob(os.path.expanduser(
    "~/workspace/stock-app/backtests/v10-retest/gap-a7-split-drift/cache/pxlong_*.json"))]
for t in pond:
    universe.setdefault(t.upper(), None)
print(f"universe: {len(universe)} tickers ({len(pond)} pond)")

# CIK fill for pond names from SEC master ticker file
need = [t for t, c in universe.items() if c is None]
if need:
    try:
        r = requests.get("https://www.sec.gov/files/company_tickers.json",
                         headers={"User-Agent": "AtlasGate Research research@atlasgate.example"}, timeout=30)
        m = {v["ticker"].upper(): v["cik_str"] for v in r.json().values()}
        for t in need:
            if t in m: universe[t] = int(m[t])
    except Exception as e:
        print("cik fill failed:", e)
json.dump(universe, open(os.path.join(HERE, "data", "universe.json"), "w"), indent=0)

events, fails = [], []
for i, t in enumerate(sorted(universe)):
    safe = t.replace("/", "-")
    path = os.path.join(CACHE, f"yh_{safe}.json")
    raw = None
    if os.path.exists(path):
        try: raw = json.load(open(path))
        except Exception: raw = None
    if raw is None:
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(t, safe='')}"
               f"?period1=1262304000&period2=1796000000&interval=1d&events=div,splits")
        for attempt in range(3):
            try:
                r = requests.get(url, headers=UA, timeout=25)
                if r.status_code == 200 and r.json().get("chart", {}).get("result"):
                    raw = r.json(); json.dump(raw, open(path, "w")); break
                time.sleep(1.5 * (attempt + 1))
            except Exception:
                time.sleep(1.5 * (attempt + 1))
        time.sleep(0.12)
    if not raw:
        fails.append(t); continue
    try:
        res = raw["chart"]["result"][0]
        sp = (res.get("events") or {}).get("splits") or {}
        for _, s in sp.items():
            f = s["numerator"] / s["denominator"]
            if f >= 2.0:
                from datetime import datetime, timezone
                d = datetime.fromtimestamp(s["date"], tz=timezone.utc).date().isoformat()
                if "2010-01-01" <= d <= "2026-11-20":
                    events.append({"ticker": t, "cik": universe[t], "ex_date": d,
                                   "factor": round(f, 4), "split_text": s.get("splitFactor")})
    except Exception:
        fails.append(t)
    if i % 100 == 0: print(f"{i}/{len(universe)} events={len(events)} fails={len(fails)}", flush=True)

events.sort(key=lambda e: (e["ex_date"], e["ticker"]))
json.dump({"events": events, "fetch_failures": fails, "universe_size": len(universe)},
          open(os.path.join(HERE, "data", "exdate_census.json"), "w"), indent=1)
from collections import Counter
print("DONE events:", len(events), "failures:", len(fails))
print("per year:", dict(sorted(Counter(e["ex_date"][:4] for e in events).items())))
