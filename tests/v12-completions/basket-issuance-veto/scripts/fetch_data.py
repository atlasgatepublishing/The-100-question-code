"""Fetch data for basket-issuance-veto v12 CONSTRUCTED run (threaded, cache-resuming).
Universe: PIT S&P500 lifecycles (shared read-only sibling file).
Prices+splits: Yahoo chart API per ticker. Issuance: SEC EDGAR companyfacts per CIK."""
import csv, json, pathlib, time, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor

HERE = pathlib.Path(__file__).parent
DATA = HERE.parent / "data"; DATA.mkdir(exist_ok=True)
LIFE = pathlib.Path.home() / "workspace/stock-app/backtests/v12-completions/gap-a10-div-capture/data/sp500_ticker_start_end.csv"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
SECUA = {"User-Agent": "AtlasGatePublishing research contact@atlasgate.example"}

def norm(t): return t.replace(".", "").replace("-", "").upper()

tickers = set()
for row in csv.DictReader(open(LIFE)):
    s, e = row["start_date"], row["end_date"] or "9999-12-31"
    if e >= "2008-06-01" and s <= "2026-11-21":
        tickers.add(row["ticker"])
tickers = sorted(tickers)
print(f"universe tickers: {len(tickers)}", flush=True)

ct_path = DATA / "company_tickers.json"
if not ct_path.exists():
    req = urllib.request.Request("https://www.sec.gov/files/company_tickers.json", headers=SECUA)
    ct_path.write_bytes(urllib.request.urlopen(req, timeout=60).read())
ct = json.loads(ct_path.read_text())
cikmap = {}
for v in ct.values():
    cikmap.setdefault(norm(v["ticker"]), v["cik_str"])
cikmap[norm("XOM")] = 34088

P1, P2 = 1230768000, 1795305600
def fetch(url, headers, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception as e:
            if "404" in str(e) or i == tries - 1: raise
            time.sleep(2 * (i + 1))

def get_px(t):
    p = DATA / f"px_{t}.json"
    if p.exists(): return "ok"
    url = (f"https://query2.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(t)}"
           f"?period1={P1}&period2={P2}&interval=1d&events=div,split")
    try:
        p.write_bytes(fetch(url, UA)); return "ok"
    except Exception as e:
        (DATA / f"px_{t}.FAIL").write_text(str(e)); return "fail"

with ThreadPoolExecutor(max_workers=6) as ex:
    res = list(ex.map(get_px, tickers))
print(f"prices ok={res.count('ok')} fail={res.count('fail')}", flush=True)

ciks = {}
for t in tickers:
    c = cikmap.get(norm(t))
    if c: ciks[t] = c
print(f"mapped tickers: {len(ciks)} / {len(tickers)}", flush=True)
(DATA / "cik_map.json").write_text(json.dumps(ciks, indent=0))

def get_facts(item):
    t, cik = item
    p = DATA / f"facts_{cik:010d}.json"
    if p.exists(): return "ok"
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
    try:
        p.write_bytes(fetch(url, SECUA)); return "ok"
    except Exception as e:
        (DATA / f"facts_{cik:010d}.FAIL").write_text(str(e)); return "fail"

with ThreadPoolExecutor(max_workers=4) as ex:
    res = list(ex.map(get_facts, sorted(ciks.items(), key=lambda kv: kv[1])))
print(f"facts ok={res.count('ok')} fail={res.count('fail')}", flush=True)
print("DONE", flush=True)
