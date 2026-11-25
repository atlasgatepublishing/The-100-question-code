"""Fetch EDGAR companyconcept share-count data (small payloads) for mapped CIKs.
dei EntityCommonStockSharesOutstanding for all; fallback concepts only where dei is thin."""
import json, pathlib, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = pathlib.Path(__file__).parent
DATA = HERE.parent / "data"
SECUA = {"User-Agent": "AtlasGatePublishing research contact@atlasgate.example"}
ciks = json.loads((DATA / "cik_map.json").read_text())

def fetch(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=SECUA)
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read()
        except Exception as e:
            if "404" in str(e) or i == tries - 1: raise
            time.sleep(2 * (i + 1))

def get(item):
    t, cik = item
    p = DATA / f"concept_{cik:010d}_dei.json"
    if p.exists() or (DATA / f"concept_{cik:010d}_dei.FAIL").exists(): return "ok"
    url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/dei/EntityCommonStockSharesOutstanding.json"
    try:
        tmp = p.with_suffix(".tmp"); tmp.write_bytes(fetch(url)); tmp.replace(p); return "ok"
    except Exception as e:
        try: (DATA / f"concept_{cik:010d}_dei.FAIL").write_text(str(e))
        except Exception: pass
        return "fail"

with ThreadPoolExecutor(max_workers=6) as ex:
    res = list(ex.map(get, sorted(ciks.items(), key=lambda kv: kv[1])))
print(f"dei ok={res.count('ok')} fail={res.count('fail')}", flush=True)

# fallback concepts where dei missing/thin
def nobs(cik):
    p = DATA / f"concept_{cik:010d}_dei.json"
    if not p.exists(): return 0
    try:
        d = json.loads(p.read_text())
        for u, v in (d.get("units") or {}).items():
            if "shares" in u: return len(v)
    except Exception: return 0
    return 0

thin = [(t, c) for t, c in ciks.items() if nobs(c) < 8]
print(f"thin dei: {len(thin)}", flush=True)
FALLBACKS = [("us-gaap", "CommonStockSharesIssued"), ("us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic")]
def get_fb(item):
    t, cik = item
    out = []
    for tax, tag in FALLBACKS:
        p = DATA / f"concept_{cik:010d}_{tag}.json"
        if p.exists() or (DATA / f"concept_{cik:010d}_{tag}.FAIL").exists(): out.append("ok"); continue
        url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/{tax}/{tag}.json"
        try:
            tmp = p.with_suffix(".tmp"); tmp.write_bytes(fetch(url)); tmp.replace(p); out.append("ok")
        except Exception as e:
            try: (DATA / f"concept_{cik:010d}_{tag}.FAIL").write_text(str(e))
            except Exception: pass
            out.append("fail")
    return out
with ThreadPoolExecutor(max_workers=6) as ex:
    list(ex.map(get_fb, thin))
print("DONE", flush=True)
