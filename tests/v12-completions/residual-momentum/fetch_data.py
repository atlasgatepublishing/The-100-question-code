#!/usr/bin/env python3
"""Fetch (1) FF3 monthly factors from the Kenneth French library and
(2) daily adjclose tapes from Yahoo for every ticker that appears in the
point-in-time S&P 500 roster (data/sp500_hist.csv) at any date >= 2006-01-01,
plus SPY. Resumable: existing data/px_<T>.json files are kept.
Saves data/px_<T>.json = {"src":..., "bars":[[date, adjclose],...]}"""
import csv, io, json, os, time, urllib.request, zipfile
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data"); os.makedirs(DATA, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

# ---- FF3 monthly ----
ff_out = os.path.join(DATA, "ff3_monthly.csv")
if not os.path.exists(ff_out):
    url = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_CSV.zip"
    req = urllib.request.Request(url, headers=UA)
    raw = urllib.request.urlopen(req, timeout=120).read()
    zf = zipfile.ZipFile(io.BytesIO(raw))
    name = zf.namelist()[0]
    text = zf.read(name).decode()
    rows = []
    started = False
    for line in text.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 5 and parts[0].isdigit() and len(parts[0]) == 6:
            started = True
            rows.append(parts)
        elif started and (not line.strip() or not parts[0].isdigit()):
            if rows and not line.strip():
                break
    with open(ff_out, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["yyyymm", "mktrf", "smb", "hml", "rf"]); w.writerows(rows)
    print(f"ff3: {len(rows)} monthly rows -> {ff_out}", flush=True)
else:
    print("ff3: cached", flush=True)

# ---- roster tickers ----
snaps = []
with open(os.path.join(DATA, "sp500_hist.csv")) as f:
    for row in csv.DictReader(f):
        snaps.append((row["date"], [t.strip() for t in row["tickers"].split(",") if t.strip()]))
tickers = sorted({t for d, ts in snaps if d >= "2006-01-01" for t in ts} | {"SPY"})
print(f"roster tickers >=2006: {len(tickers)}", flush=True)

def yahoo_sym(t):
    return t.replace(".", "-")

def fetch(t):
    out = os.path.join(DATA, f"px_{t}.json")
    if os.path.exists(out) and os.path.getsize(out) > 100:
        return t, "cached"
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(yahoo_sym(t))}"
           f"?period1=1136073600&period2=1795600000&interval=1d&events=div,split")
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                payload = json.loads(r.read())
            res = payload["chart"]["result"][0]
            ts = res["timestamp"]; q = res["indicators"]["quote"][0]
            adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
            bars = []
            for i, tt in enumerate(ts):
                c = q["close"][i]
                if c is None:
                    continue
                a = adj[i] if adj and adj[i] else c
                bars.append([time.strftime("%Y-%m-%d", time.gmtime(tt)), round(float(a), 4)])
            if len(bars) < 50:
                return t, f"short({len(bars)})"
            with open(out, "w") as f:
                json.dump({"src": "yahoo", "bars": bars}, f)
            return t, f"ok({len(bars)})"
        except Exception as e:
            if attempt == 2:
                return t, f"FAIL {e}"
            time.sleep(2 * (attempt + 1))

results = {}
with ThreadPoolExecutor(max_workers=4) as ex:
    for t, status in ex.map(fetch, tickers):
        results[t] = status
ok = [t for t, s in results.items() if s.startswith(("ok", "cached"))]
bad = {t: s for t, s in results.items() if t not in ok}
print(f"fetched ok: {len(ok)} / {len(tickers)}; failed/short: {len(bad)}", flush=True)
with open(os.path.join(DATA, "fetch_report.json"), "w") as f:
    json.dump({"ok": len(ok), "total": len(tickers), "failed": bad}, f, indent=1)
print("failed tickers:", ", ".join(sorted(bad))[:2000], flush=True)
