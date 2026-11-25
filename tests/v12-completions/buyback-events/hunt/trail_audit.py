import json, re, time, urllib.request, os

UA = {"User-Agent": "AtlasGate research research@example.com"}
OUT = "/home/hatch/workspace/stock-app/backtests/v12-completions/buyback-events/hunt/filings"
COMP = {  # zero-event or mixed announcers needing a 10-K trail audit
 "MSFT":"0000789019","MA":"0001141391","IBM":"0000051143","WFC":"0000072971",
 "UNH":"0000731766","MMM":"0000066740","KO":"0000021344","PG":"0000080424",
}
def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r: return r.read()

results = {}
for tk, cik in COMP.items():
    sub = json.loads(get(f"https://data.sec.gov/submissions/CIK{cik}.json"))
    rec = sub["filings"]["recent"]
    tens = []
    for form, acc, doc, fdate in zip(rec["form"], rec["accessionNumber"], rec["primaryDocument"], rec["filingDate"]):
        if form == "10-K" and "2017-01-01" <= fdate <= "2026-12-31":
            tens.append((fdate, acc.replace("-",""), doc))
    tens.sort()
    print(tk, "10-Ks:", [t[0] for t in tens])
    sents = {}
    for fdate, acc, doc in tens:
        path = os.path.join(OUT, f"{tk}_{fdate}_{doc}")
        if not os.path.exists(path):
            try:
                data = get(f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{doc}")
                open(path, "wb").write(data); time.sleep(0.15)
            except Exception as e:
                print("  fetch fail", tk, fdate, e); continue
        raw = open(path, encoding="utf-8", errors="ignore").read()
        txt = re.sub(r"<[^>]+>", " ", raw)
        txt = re.sub(r"\s+", " ", txt)
        for m in re.finditer(r"[^.]{0,220}?(authoriz\w+|approv\w+)[^.]{0,260}?\.", txt):
            s = m.group(0)
            if re.search(r"repurchas|buyback|buy back", s, re.I) and re.search(r"\$|million|billion|shares", s):
                key = re.sub(r"\s+", " ", s).strip()[:300]
                sents.setdefault(key, []).append(fdate)
    results[tk] = sents
    for s, ds in sents.items():
        print(f"  [{tk} 10-K filed {ds[0]}..{ds[-1]}] {s[:280]}")
    print()
json.dump({k: {s: v for s, v in d.items()} for k, d in results.items()},
          open(os.path.join(OUT, "..", "trail_audit.json"), "w"), indent=1)
