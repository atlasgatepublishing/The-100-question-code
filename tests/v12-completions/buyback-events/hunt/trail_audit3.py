#!/usr/bin/env python3
"""
Trail audit PASS 3 — completes the companies pass 2 could not finish
(mass EDGAR fetch failures) plus XOM/WMT re-extraction with a broader
net, and V's remaining years.

Broader extraction than passes 1-2 (whose verb filter missed
'announced a program' wording at XOM): sentence-split first (fast),
keep any sentence that mentions a repurchase program/authorization AND
an amount or share count. Filing window widened to 2017-01-01 so
late-2016/2017 authorizations narrated in FY2016/FY2017 10-Ks are seen.
Slower fetch rate (0.5s) + one retry — pass 2 died on fetch errors.
"""
import json, re, time, urllib.request, os

UA = {"User-Agent": "AtlasGate research research@example.com"}
OUT = "/home/hatch/workspace/stock-app/backtests/v12-completions/buyback-events/hunt/filings"
CIKS = json.load(open("/home/hatch/workspace/stock-app/backtests/v6/buyback-events/buyback-events-data/ciks.json"))
TODO = ["DIS", "GE", "XOM", "WMT", "HD", "BAC", "CVX", "PFE", "VZ", "T",
        "NFLX", "INTC", "CSCO", "PEP", "V"]


def get(url, binary=False):
    last = None
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            return data if binary else json.loads(data)
        except Exception as e:
            last = e
            time.sleep(5)
    raise last


results = {}
for tk in TODO:
    cik = str(CIKS[tk]).zfill(10)
    sub = get(f"https://data.sec.gov/submissions/CIK{cik}.json")
    blocks = [sub["filings"]["recent"]]
    for f in sub["filings"].get("files", []):
        blocks.append(get("https://data.sec.gov/submissions/" + f["name"]))
        time.sleep(0.3)
    seen, tens = set(), []
    for rec in blocks:
        for form, acc, doc, fdate in zip(rec["form"], rec["accessionNumber"],
                                         rec["primaryDocument"], rec["filingDate"]):
            if form == "10-K" and "2017-01-01" <= fdate <= "2026-12-31" and acc not in seen:
                seen.add(acc)
                tens.append((fdate, acc.replace("-", ""), doc))
    tens.sort()
    sents = {}
    fails = 0
    for fdate, acc, doc in tens:
        path = os.path.join(OUT, f"{tk}_{fdate}_{doc}")
        if not os.path.exists(path) or os.path.getsize(path) < 20000:
            try:
                import subprocess
                url = (f"https://www.sec.gov/Archives/edgar/data/"
                       f"{int(cik)}/{acc}/{doc}")
                p = subprocess.run(
                    ["curl", "-s", "-A", "AtlasGate research research@example.com",
                     url], capture_output=True, timeout=90)
                if len(p.stdout) < 20000:
                    raise IOError(f"short download: {len(p.stdout)} bytes")
                tmp = path + ".tmp"
                open(tmp, "wb").write(p.stdout)
                os.replace(tmp, path)
                time.sleep(0.5)
            except Exception as e:
                print("  fetch fail", tk, fdate, e, flush=True)
                fails += 1
                continue
        raw = open(path, encoding="utf-8", errors="ignore").read()
        txt = re.sub(r"<[^>]+>", " ", raw)
        txt = re.sub(r"\s+", " ", txt)
        for s in re.split(r"(?<=[.;])\s+", txt):
            if len(s) > 700:
                continue
            if not re.search(r"repurchas", s, re.I):
                continue
            if not re.search(r"program|authoriz", s, re.I):
                continue
            if not re.search(r"\$\s?\d|million shares|billion", s):
                continue
            sents.setdefault(s.strip()[:340], []).append(fdate)
    results[tk] = sents
    print(f"{tk}: 10-Ks={len(tens)} fails={fails} sentences={len(sents)}", flush=True)
    for s, ds in sents.items():
        print(f"  [{ds[0]}..{ds[-1]}] {s[:300]}", flush=True)
    print(flush=True)
json.dump(results, open(os.path.join(OUT, "..", "trail_audit3.json"), "w"), indent=1)
print("DONE")
