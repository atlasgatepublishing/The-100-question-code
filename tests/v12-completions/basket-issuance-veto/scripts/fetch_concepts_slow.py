"""Slow sequential EDGAR concept fetch v2: validates JSON, retries empty bodies, direct writes."""
import json, pathlib, time, urllib.request

HERE = pathlib.Path(__file__).parent
DATA = HERE.parent / "data"
SECUA = {"User-Agent": "AtlasGatePublishing research contact@atlasgate.example"}
ciks = json.loads((DATA / "cik_map.json").read_text())

def fetch_json(url, tries=5):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=SECUA)
            with urllib.request.urlopen(req, timeout=45) as r:
                body = r.read()
            d = json.loads(body)  # raises on empty/invalid
            if d.get("units"): return body
            last = "no-units"
        except Exception as e:
            last = repr(e)
            if "404" in str(e): raise
        time.sleep(4 * (i + 1))
    raise RuntimeError(last)

def get(cik, tax, tag, fname):
    p = DATA / fname
    if p.exists(): return "have"
    url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/{tax}/{tag}.json"
    try:
        p.write_bytes(fetch_json(url)); return "ok"
    except Exception as e:
        try: (DATA / (fname[:-5] + ".FAIL")).write_text(repr(e))
        except Exception: pass
        return "fail"

ok = fail = have = 0
items = sorted(ciks.items(), key=lambda kv: kv[1])
for t, cik in items:
    r = get(cik, "dei", "EntityCommonStockSharesOutstanding", f"concept_{cik:010d}_dei.json")
    if r == "ok": ok += 1
    elif r == "fail": fail += 1
    else: have += 1
    time.sleep(0.35)
print(f"dei ok={ok} fail={fail} have={have}", flush=True)

def nobs(cik):
    p = DATA / f"concept_{cik:010d}_dei.json"
    if not p.exists(): return 0
    try:
        d = json.loads(p.read_text())
        for u, v in (d.get("units") or {}).items():
            if "shares" in u: return len(v)
    except Exception: return 0
    return 0

thin = [(t, c) for t, c in items if nobs(c) < 8]
print(f"thin dei: {len(thin)}", flush=True)
for t, cik in thin:
    for tag in ["CommonStockSharesIssued", "WeightedAverageNumberOfSharesOutstandingBasic"]:
        get(cik, "us-gaap", tag, f"concept_{cik:010d}_{tag}.json")
        time.sleep(0.35)
print("DONE", flush=True)
