"""V13 pead-lite data build (writes ONLY into ./data_cache/).

1) Prices: Yahoo chart API, 2009-01-01 -> 2026-11-21, for the v11 lite universe
   (tickers with cached prices in the v3+v4 shared caches, read-only) + SPY.
   Stores timestamp/open/close/adjclose arrays as pxe_<T>.json.
2) Earnings-release dates: SEC EDGAR submissions API (declared UA, polite rate).
   For each ticker's CIK (from the v11 eps_cache), walk the recent block plus all
   additional filing-history files; keep 8-K / 8-K/A filings whose items contain
   '2.02'. Stores ev8k_<T>.json = sorted list of filing dates.
"""
import json, os, time, urllib.request, glob, sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data_cache"); os.makedirs(OUT, exist_ok=True)
V3 = "/home/hatch/workspace/stock-app/backtests/v3/pead-cache"
V4 = "/home/hatch/workspace/stock-app/backtests/v4/pead-small-cache"
EPS = "/home/hatch/workspace/stock-app/backtests/v11-native-rules/pead-lite/eps_cache"

tickers = sorted({os.path.basename(f)[3:-5] for c in (V3, V4)
                  for f in glob.glob(os.path.join(c, "px_*.json"))} - {"SPY"})
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AtlasGate research"}
UA_SEC = {"User-Agent": "AtlasGatePublishing research contact@example.com"}

def get(url, ua, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=ua)
            return json.load(urllib.request.urlopen(req, timeout=40))
        except Exception as e:
            if i == tries - 1: raise
            time.sleep(2.0 * (i + 1))

# --- prices ---
P1 = 1230768000   # 2009-01-01 UTC
P2 = 1795564800   # 2026-11-22 UTC
ok, fail = [], []
for t in tickers + ["SPY"]:
    dst = os.path.join(OUT, f"pxe_{t}.json")
    if os.path.exists(dst): ok.append(t); continue
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{t}"
           f"?period1={P1}&period2={P2}&interval=1d&events=div,split")
    try:
        d = get(url, UA)["chart"]["result"][0]
        q = d["indicators"]["quote"][0]
        adj = d["indicators"]["adjclose"][0]["adjclose"]
        rows = {"timestamp": d["timestamp"], "open": q["open"], "close": q["close"], "adjclose": adj}
        json.dump(rows, open(dst, "w")); ok.append(t)
    except Exception as e:
        fail.append((t, str(e)[:70]))
    time.sleep(0.25)
print("prices ok", len(ok), "fail", fail, flush=True)

# --- 8-K Item 2.02 filing dates ---
ok2, fail2 = [], []
for t in tickers:
    dst = os.path.join(OUT, f"ev8k_{t}.json")
    if os.path.exists(dst): ok2.append(t); continue
    ep = os.path.join(EPS, f"eps_{t}.json")
    if not os.path.exists(ep): fail2.append((t, "no eps cache")); continue
    cik = json.load(open(ep))["cik"]
    try:
        sub = get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", UA_SEC)
        dates = set()
        def scan(block):
            forms = block.get("form", []); fds = block.get("filingDate", []); items = block.get("items", [])
            for i, fm in enumerate(forms):
                if fm in ("8-K", "8-K/A") and i < len(items) and "2.02" in items[i]:
                    dates.add(fds[i])
        scan(sub["filings"]["recent"])
        for extra in sub["filings"].get("files", []):
            d2 = get(f"https://data.sec.gov/submissions/{extra['name']}", UA_SEC)
            scan(d2)
            time.sleep(0.12)
        json.dump(sorted(dates), open(dst, "w")); ok2.append(t)
    except Exception as e:
        fail2.append((t, str(e)[:70]))
    time.sleep(0.12)
print("8k ok", len(ok2), "fail", fail2, flush=True)
