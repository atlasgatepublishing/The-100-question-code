#!/usr/bin/env python3
"""Addendum step: build the full-frames universe and fetch price tapes for
non-price-gate passers.
- Universe: CIKs in dividend frames (dreman folder, 2009-2025) that also report
  AssetsCurrent and have a current ticker in SEC company_tickers_exchange.json.
- Non-price gates per formation F=2016..2025 (split-adjusted DPS/EPS):
  dividends paid all 7 yrs, >=3 DPS increases, no DPS decrease; EPS up >=4 of 7;
  shares>=5M; current ratio>=2; LTD/equity<=0.5; payout<=0.5.
- Fetch Yahoo monthly tapes for every CIK passing >=1 formation (not cached)."""
import json, os, time, urllib.request, calendar

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
W04 = os.path.expanduser("~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data")
DRE = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/catalog-aaii-dreman/data/frames")
MYFR = os.path.join(ROOT, "data", "frames")
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

# ticker mapping
tkp = os.path.join(ROOT, "data", "company_tickers_exchange.json")
if not os.path.exists(tkp):
    json.dump(json.loads(get("https://www.sec.gov/files/company_tickers_exchange.json")), open(tkp, "w"))
tk = json.load(open(tkp))
cik2ticker = {}
for row in tk["data"]:
    cik, name, ticker, exch = row[0], row[1], row[2], row[3]
    if ticker: cik2ticker.setdefault(int(cik), ticker.replace("/", "-"))

def frame(name, y, kind):
    d = loadj(os.path.join(MYFR, f"{name}_{y}{kind}.json"))
    if not d: d = loadj(os.path.join(W04, "frames", f"{name}_{y}{kind}.json"))
    return {int(k): v for k, v in d.items()}

FR = {}
for nm, kd in [("AssetsCurrent", "I"), ("LiabilitiesCurrent", "I"), ("StockholdersEquity", "I"),
               ("LongTermDebtCurrent", "I"), ("LongTermDebtNoncurrent", "I"), ("DebtCurrent", "I"),
               ("Shares", "I"), ("NetIncomeLoss", "D")]:
    FR[nm] = {y: frame(nm, y, kd) for y in YEARS}
DIV = {}
for y in YEARS:
    d1 = {int(k): v for k, v in loadj(os.path.join(DRE, f"PaymentsOfDividendsCommonStock_{y}D.json")).items()}
    d2 = {int(k): v for k, v in loadj(os.path.join(DRE, f"PaymentsOfDividends_{y}D.json")).items()}
    DIV[y] = d1 if d1 else d2

universe = set()
for y in YEARS:
    universe |= {c for c in DIV[y] if c in FR["AssetsCurrent"][y]}
universe = {c for c in universe if c in cik2ticker}
print("universe CIKs:", len(universe), flush=True)

def jumps(cik):
    s = FR["Shares"]; out = {}
    prev = None
    for y in YEARS:
        if cik in s[y]:
            if prev is not None and s[prev].get(cik):
                r = s[y][cik] / s[prev][cik]
                if r >= 1.6 or r <= 0.625: out[y] = r
            prev = y
    return out

def adj_series(cik, F, kind):
    """Per-share series for fiscal years F-7..F-1 restated to F-1 share units."""
    jm = jumps(cik)
    res = []
    for y in range(F - 7, F):
        if kind == "dps":
            dv = DIV[y].get(cik); sh = FR["Shares"][y].get(cik)
            v = dv / sh if dv and sh else None
        else:
            ni = FR["NetIncomeLoss"][y].get(cik); sh = FR["Shares"][y].get(cik)
            v = ni / sh if ni is not None and sh else None
        if v is None: return None
        J = 1.0
        for z, r in jm.items():
            if y < z <= F - 1: J *= r
        if J <= 0: return None
        res.append(v / J)
    return res

def nonprice_pass(cik, F):
    ds = adj_series(cik, F, "dps")
    if ds is None or any(v <= 0 for v in ds): return False
    inc = sum(1 for i in range(1, 7) if ds[i] > ds[i - 1])
    dec = any(ds[i] < ds[i - 1] for i in range(1, 7))
    if inc < 3 or dec: return False
    es = adj_series(cik, F, "eps")
    if es is None: return False
    if sum(1 for i in range(1, 7) if es[i] > es[i - 1]) < 4: return False
    sh = FR["Shares"][F - 1].get(cik)
    if not sh or sh < 5e6: return False
    ac = FR["AssetsCurrent"][F - 1].get(cik); lc = FR["LiabilitiesCurrent"][F - 1].get(cik)
    if not ac or not lc or ac / lc < 2.0: return False
    eqv = FR["StockholdersEquity"][F - 1].get(cik)
    if not eqv or eqv <= 0: return False
    debt = (FR["LongTermDebtNoncurrent"][F - 1].get(cik) or 0) + \
           (FR["LongTermDebtCurrent"][F - 1].get(cik) or 0) + (FR["DebtCurrent"][F - 1].get(cik) or 0)
    if debt / eqv > 0.5: return False
    ni = FR["NetIncomeLoss"][F - 1].get(cik)
    if not ni or ni <= 0 or DIV[F - 1][cik] / ni > 0.5: return False
    return True

passers = {}
need = set()
for F in range(2016, 2026):
    ps = [c for c in universe if nonprice_pass(c, F)]
    passers[F] = ps; need |= set(ps)
    print("nonprice passers", F, len(ps), flush=True)
json.dump({"passers": {str(F): v for F, v in passers.items()},
           "cik2ticker": {str(c): cik2ticker[c] for c in need}},
          open(os.path.join(ROOT, "data", "prescreen.json"), "w"), indent=1)

t1 = calendar.timegm(time.strptime("2009-12-01", "%Y-%m-%d"))
t2 = calendar.timegm(time.strptime("2026-11-22", "%Y-%m-%d"))
ok = fail = skip = 0
for cik in sorted(need):
    t = cik2ticker[cik]
    out = os.path.join(ROOT, "data", f"px_{t}.json")
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
            c = q["close"][i]; h = q["high"][i]; a = adj[i] if adj else c
            if c is None or a is None: continue
            bars[d] = [a, c, h if h is not None else c]
        if len(bars) < 12: raise ValueError("short")
        json.dump(bars, open(out, "w")); ok += 1
    except Exception as e:
        fail += 1; print("FAIL", t, e, flush=True)
    time.sleep(0.15)
print(f"tapes ok={ok} fail={fail} cached={skip} need={len(need)}", flush=True)
