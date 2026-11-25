"""Sequential EDGAR concept fetch (SEC fair-access friendly), cache-resuming, atomic writes."""
import json, pathlib, time, urllib.request

HERE = pathlib.Path(__file__).parent
DATA = HERE.parent / "data"
SECUA = {"User-Agent": "AtlasGatePublishing research contact@atlasgate.example"}
ciks = json.loads((DATA / "cik_map.json").read_text())

def fetch(url, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=SECUA)
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read()
        except Exception as e:
            if "404" in str(e) or i == tries - 1: raise
            time.sleep(3 * (i + 1))

def save(p, data):
    tmp = p.with_suffix(".tmp"); tmp.write_bytes(data); tmp.replace(p)

def get_dei(cik):
    p = DATA / f"concept_{cik:010d}_dei.json"
    if p.exists(): return "have"
    url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/dei/EntityCommonStockSharesOutstanding.json"
    try:
        save(p, fetch(url)); return "ok"
    except Exception as e:
        try: (DATA / f"concept_{cik:010d}_dei.FAIL").write_text(repr(e))
        except Exception: pass
        return "fail"

ok = fail = have = 0
for t, cik in sorted(ciks.items(), key=lambda kv: kv[1]):
    r = get_dei(cik)
    if r == "ok": ok += 1
    elif r == "fail": fail += 1
    else: have += 1
    time.sleep(0.12)
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

thin = [(t, c) for t, c in ciks.items() if nobs(c) < 8]
print(f"thin dei: {len(thin)}", flush=True)
for t, cik in thin:
    for tax, tag in [("us-gaap", "CommonStockSharesIssued"), ("us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic")]:
        p = DATA / f"concept_{cik:010d}_{tag}.json"
        if p.exists(): continue
        url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/{tax}/{tag}.json"
        try: save(p, fetch(url))
        except Exception as e:
            try: (DATA / f"concept_{cik:010d}_{tag}.FAIL").write_text(repr(e))
            except Exception: pass
        time.sleep(0.12)
print("DONE", flush=True)
