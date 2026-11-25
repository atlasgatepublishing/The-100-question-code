#!/usr/bin/env python3
"""
Trail audit PASS 3b — in-memory version. The sandbox filesystem began
refusing writes inside hunt/filings/ after ~230 cached filings
(Errno 1 on new files, silent zero-byte writes), so this pass downloads
each 10-K via curl straight into memory, extracts, and keeps only the
sentences. Companies: those pass 2 could not finish (fetch failures)
plus XOM/WMT/V re-extraction with the broader net. Filing window
2017-01-01 so late-2016/2017 authorizations are seen.
"""
import json, re, subprocess, time, urllib.request

UA = {"User-Agent": "AtlasGate research research@example.com"}
CIKS = json.load(open("/home/hatch/workspace/stock-app/backtests/v6/buyback-events/buyback-events-data/ciks.json"))
import sys
TODO = sys.argv[1:] or ["DIS", "GE", "XOM", "WMT", "HD", "BAC", "CVX",
                         "PFE", "VZ", "T", "NFLX", "INTC", "CSCO", "PEP", "V"]


def get_json(url):
    last = None
    for _ in range(2):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except Exception as e:
            last = e
            time.sleep(5)
    raise last


def get_doc(url):
    for _ in range(2):
        p = subprocess.run(["curl", "-s", "--max-time", "45", "-A",
                            "AtlasGate research research@example.com", url],
                           capture_output=True, timeout=60)
        if len(p.stdout) > 20000:
            return p.stdout.decode("utf-8", "ignore")
        time.sleep(5)
    return None


results = {}
for tk in TODO:
    cik = str(CIKS[tk]).zfill(10)
    sub = get_json(f"https://data.sec.gov/submissions/CIK{cik}.json")
    blocks = [sub["filings"]["recent"]]
    for f in sub["filings"].get("files", []):
        blocks.append(get_json("https://data.sec.gov/submissions/" + f["name"]))
        time.sleep(0.3)
    seen, tens = set(), []
    for rec in blocks:
        for form, acc, doc, fdate in zip(rec["form"], rec["accessionNumber"],
                                         rec["primaryDocument"], rec["filingDate"]):
            if form == "10-K" and "2017-01-01" <= fdate <= "2026-12-31" and acc not in seen:
                seen.add(acc)
                tens.append((fdate, acc.replace("-", ""), doc))
    tens.sort()
    sents, fails = {}, 0
    for fdate, acc, doc in tens:
        print(f"  .. {tk} {fdate}", flush=True)
        raw = get_doc(f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{doc}")
        time.sleep(0.4)
        if raw is None:
            print("  fetch fail", tk, fdate, flush=True)
            fails += 1
            continue
        txt = re.sub(r"<[^>]+>", " ", raw)
        txt = re.sub(r"\s+", " ", txt)
        for s in re.split(r"(?<=[.;])\s+", txt):
            if len(s) > 700 or not re.search(r"repurchas", s, re.I):
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
out = "/home/hatch/workspace/stock-app/backtests/v12-completions/buyback-events/hunt/trail_audit3_" + "_".join(TODO) + ".json"
json.dump(results, open(out, "w"), indent=1)
print("DONE", out)
