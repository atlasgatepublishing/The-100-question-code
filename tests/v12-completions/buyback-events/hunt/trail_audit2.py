import json, re, time, urllib.request, os
UA = {"User-Agent": "AtlasGate research research@example.com"}
OUT = "/home/hatch/workspace/stock-app/backtests/v12-completions/buyback-events/hunt/filings"
CIKS = json.load(open("/home/hatch/workspace/stock-app/backtests/v6/buyback-events/buyback-events-data/ciks.json"))
DONE = {"MSFT","MA","IBM","WFC","UNH","MMM","KO","PG"}
def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r: return r.read()
results = {}
for tk, cik in CIKS.items():
    if tk in DONE: continue
    cik = str(cik).zfill(10)
    try:
        sub = json.loads(get(f"https://data.sec.gov/submissions/CIK{cik}.json"))
    except Exception as e:
        print(tk, "sub fail", e); continue
    blocks = [sub["filings"]["recent"]] + [json.loads(get("https://data.sec.gov/submissions/" + f["name"])) for f in sub["filings"].get("files", [])]
    seen=set(); tens=[]
    for rec in blocks:
        for form, acc, doc, fdate in zip(rec["form"], rec["accessionNumber"], rec["primaryDocument"], rec["filingDate"]):
            if form == "10-K" and "2018-06-01" <= fdate <= "2026-12-31" and acc not in seen:
                seen.add(acc); tens.append((fdate, acc.replace("-",""), doc))
    tens.sort()
    sents = {}
    for fdate, acc, doc in tens:
        path = os.path.join(OUT, f"{tk}_{fdate}_{doc}")
        if not os.path.exists(path):
            try:
                open(path,"wb").write(get(f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{doc}")); time.sleep(0.12)
            except Exception as e:
                print("  fetch fail", tk, fdate, e); continue
        raw = open(path, encoding="utf-8", errors="ignore").read()
        txt = re.sub(r"<[^>]+>", " ", raw); txt = re.sub(r"\s+", " ", txt)
        for m in re.finditer(r"[^.]{0,220}?(authoriz\w+|approv\w+)[^.]{0,260}?\.", txt):
            s = m.group(0)
            if re.search(r"repurchas|buyback|buy back", s, re.I) and re.search(r"\$|million|billion|shares", s):
                sents.setdefault(re.sub(r"\s+"," ",s).strip()[:300], []).append(fdate)
    results[tk] = sents
    print(tk, "10-Ks:", len(tens))
    for s, ds in sents.items(): print(f"  [{ds[0]}..{ds[-1]}] {s[:270]}")
    print(flush=True)
json.dump(results, open("/home/hatch/workspace/stock-app/backtests/v12-completions/buyback-events/hunt/trail_audit2.json","w"), indent=1)
print("DONE")
