#!/usr/bin/env python3
"""Pre-screen (non-price gates) for the V13 Wanger chassis + Yahoo tape fetch.
Gates per formation F=2015..2025 (all point-in-time, fiscal years <= F-1):
 sales>0 strictly increasing F-3->F-2->F-1; 3y sales growth > universe median;
 liab/assets (F-1) < universe median; operating income (F-1) > 0; shares present;
 split-adjusted EPS(F-1)>0, EPS(F-6)>0 and EPS CAGR>0 (PE gate needs price, later).
Fetches monthly Yahoo tapes {YYYY-MM:[adj,close,high]} for every CIK passing
>=1 formation, plus SPY."""
import json, os, time, urllib.request, calendar
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
W04 = os.path.expanduser("~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data")
MYFR = os.path.join(ROOT, "data", "frames")
DATA = os.path.join(ROOT, "data")
H = {"User-Agent": "AtlasGate v13 research research@atlasgate.example"}
YEARS = list(range(2009, 2026))

def loadj(p): return json.load(open(p)) if os.path.exists(p) else {}
def get(u, tries=3):
    for i in range(tries):
        try:
            r = urllib.request.Request(u, headers=H)
            return urllib.request.urlopen(r, timeout=90).read()
        except Exception:
            if i == tries - 1: raise
            time.sleep(2 * (i + 1))

tkp = os.path.join(DATA, "company_tickers_exchange.json")
if not os.path.exists(tkp):
    json.dump(json.loads(get("https://www.sec.gov/files/company_tickers_exchange.json")), open(tkp, "w"))
tk = json.load(open(tkp))
cik2ticker = {}
for row in tk["data"]:
    if row[2]: cik2ticker.setdefault(int(row[0]), row[2].replace("/", "-"))

def frame(name, y, kind):
    d = loadj(os.path.join(MYFR, f"{name}_{y}{kind}.json"))
    if not d: d = loadj(os.path.join(W04, "frames", f"{name}_{y}{kind}.json"))
    return {int(k): v for k, v in d.items()}

FR = {}
for nm, kd in [("Assets", "I"), ("Liabilities", "I"), ("Shares", "I"),
               ("NetIncomeLoss", "D"), ("OperatingIncomeLoss", "D")]:
    FR[nm] = {y: frame(nm, y, kd) for y in YEARS}
REV = {}
for y in YEARS:
    r = {}
    for nm in ["RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet", "Revenues"]:
        for k, v in frame(nm, y, "D").items(): r.setdefault(k, v)
    # prefer Revenues > SalesRevenueNet > RevContract (v12 order: Sales first then RevContract overwrote; use first-found priority Revenues/Sales/RevContract)
    REV[y] = r

# split factors: cumulative product of split-like YoY share ratios from year y to 2025
def cum_split(cik, y_from):
    f = 1.0
    prev = None
    for y in YEARS:
        s = FR["Shares"][y].get(cik)
        if s is None or s <= 0: continue
        if prev is not None:
            py, ps = prev
            r = s / ps if ps else 1.0
            if (r >= 1.6 or r <= 0.625) and py >= y_from:
                f *= r
        prev = (y, s)
    return f

def eps_adj(cik, y):
    ni = FR["NetIncomeLoss"][y].get(cik); sh = FR["Shares"][y].get(cik)
    if ni is None or not sh: return None
    cs = cum_split(cik, y)
    if cs <= 0: return None
    return ni / (sh * cs)

import statistics
prescreen = {}
cand_ciks = set()
for F in range(2015, 2026):
    rev1, rev2, rev3 = REV[F-1], REV[F-2], REV[F-3]
    liab, assets = FR["Liabilities"][F-1], FR["Assets"][F-1]
    la = [liab[c] / assets[c] for c in rev1 if c in liab and c in assets and assets[c] > 0]
    gr = [rev1[c] / rev3[c] - 1 for c in rev1 if c in rev3 and rev3[c] > 0]
    med_la = statistics.median(la) if la else 1.0
    med_gr = statistics.median(gr) if gr else 0.0
    out = []
    for c in rev1:
        if c not in cik2ticker: continue
        if c not in rev2 or c not in rev3: continue
        if not (rev1[c] > rev2[c] > rev3[c] > 0): continue
        if rev1[c] / rev3[c] - 1 <= med_gr: continue
        if c not in liab or c not in assets or assets[c] <= 0: continue
        if liab[c] / assets[c] > med_la: continue
        opinc = FR["OperatingIncomeLoss"][F-1].get(c)
        if opinc is None or opinc <= 0: continue
        if not FR["Shares"][F-1].get(c): continue
        e1, e6 = eps_adj(c, F-1), eps_adj(c, F-6)
        if e1 is None or e6 is None or e1 <= 0 or e6 <= 0: continue
        if (e1 / e6) ** (1 / 5) - 1 <= 0: continue
        out.append(c); cand_ciks.add(c)
    prescreen[F] = out
    print(F, "prescreen passers:", len(out), flush=True)
json.dump({"prescreen": {str(k): v for k, v in prescreen.items()},
           "cand_ciks": sorted(cand_ciks)}, open(os.path.join(DATA, "prescreen.json"), "w"), indent=1)
print("candidate CIKs:", len(cand_ciks), flush=True)

t1 = calendar.timegm(time.strptime("2009-12-01", "%Y-%m-%d"))
t2 = calendar.timegm(time.strptime("2026-11-22", "%Y-%m-%d"))
tickers = sorted({cik2ticker[c] for c in cand_ciks} | {"SPY"})
ok = fail = skip = 0; report = {}
for t in tickers:
    out = os.path.join(DATA, f"px_{t}.json")
    if os.path.exists(out) and os.path.getsize(out) > 50:
        skip += 1; continue
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{t}"
           f"?period1={t1}&period2={t2}&interval=1mo&events=div,split")
    try:
        res = json.loads(get(url))["chart"]["result"][0]
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
        report[t] = f"FAIL {e}"; fail += 1
    time.sleep(0.15)
print(f"tapes ok={ok} fail={fail} cached={skip}", flush=True)
json.dump(report, open(os.path.join(DATA, "fetch_report.json"), "w"), indent=1)
