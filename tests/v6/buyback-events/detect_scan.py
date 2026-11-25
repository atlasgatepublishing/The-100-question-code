#!/usr/bin/env python3
"""Phase 1 (support script): enumerate + download candidate 8-K texts.
Downloads, for every 8-K in 2016-11-21..2026-11-20 with Items 2.02/7.01/8.01
(or no items recorded), the primary document + exhibit-99-style documents.
Keeps the stripped text ONLY for filings mentioning repurchas*/buyback;
records every scanned accession so the pass is resumable and auditable."""
import html as htmlmod
import json, os, re, time, urllib.request

UA = {"User-Agent": "AtlasGateResearch terry-research@example.com"}
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "buyback-events-data")
TEXTS = os.path.join(CACHE, "texts")
os.makedirs(TEXTS, exist_ok=True)
START, END = "2016-11-21", "2026-11-20"
RELEVANT_ITEMS = {"2.02", "7.01", "8.01"}

CIKS = json.load(open(os.path.join(CACHE, "ciks.json")))
# Disney's pre-Mar-2019 filings live under the legacy registrant CIK 1001039
LEGACY = {"DIS": [(1001039, "2016-11-21", "2019-03-31")]}

def fetch(url, path=None, tries=3):
    if path and os.path.exists(path) and os.path.getsize(path) > 50:
        with open(path, "rb") as f:
            return f.read()
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                blob = r.read()
            if path:
                with open(path, "wb") as f:
                    f.write(blob)
            time.sleep(0.12)
            return blob
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"fetch failed {url}: {last}")

def fetch_json(url, path=None):
    return json.loads(fetch(url, path))

def all_filings(cik):
    base = fetch_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json",
                      os.path.join(CACHE, f"sub_{cik:010d}.json"))
    out = []
    def eat(block):
        items = block.get("items") or [""] * len(block["accessionNumber"])
        for i, acc in enumerate(block["accessionNumber"]):
            out.append({"accession": acc, "date": block["filingDate"][i],
                        "form": block["form"][i],
                        "primary": block["primaryDocument"][i],
                        "items": items[i] if i < len(items) else ""})
    eat(base["filings"]["recent"])
    for extra in base["filings"].get("files", []):
        if extra["filingTo"] < "2016-01-01":
            continue
        eat(fetch_json(f"https://data.sec.gov/submissions/{extra['name']}",
                       os.path.join(CACHE, extra["name"])))
    return out

def strip_html(raw):
    try:
        s = raw.decode("utf-8", errors="ignore")
    except Exception:
        s = str(raw)
    s = re.sub(r"(?is)<(script|style).*?</\1>", " ", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = htmlmod.unescape(s)
    return re.sub(r"\s+", " ", s)

DOCNAME = re.compile(r"(99|exhibit|press|release)", re.I)

def scan_filing(cik, f):
    acc_nodash = f["accession"].replace("-", "")
    base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}"
    idx = fetch_json(f"{base}/index.json",
                     os.path.join(CACHE, f"idx_{acc_nodash}.json"))
    names = {it["name"]: it.get("size", "") for it in idx["directory"]["item"]}
    docs = []
    if f["primary"] in names:
        docs.append(f["primary"])
    for name in names:
        if name == f["primary"]:
            continue
        low = name.lower()
        if not low.endswith((".htm", ".html", ".txt")):
            continue
        if DOCNAME.search(name):
            try:
                if names[name] and int(names[name]) > 3_000_000:
                    continue
            except ValueError:
                pass
            docs.append(name)
    texts = []
    for name in docs:
        try:
            raw = fetch(f"{base}/{name}")
        except Exception as e:
            print(f"    doc fail {f['accession']} {name}: {e}", flush=True)
            continue
        texts.append(strip_html(raw))
    return "\n".join(texts)

def main():
    log_path = os.path.join(CACHE, "scan_log.json")
    log = json.load(open(log_path)) if os.path.exists(log_path) else {}
    for ticker, cik in CIKS.items():
        sources = [(cik, START, END)] + LEGACY.get(ticker, [])
        for c, d0, d1 in sources:
            fl = all_filings(c)
            sel = []
            for f in fl:
                if f["form"] != "8-K" or not (d0 <= f["date"] <= d1):
                    continue
                items = {x.strip() for x in f["items"].split(",") if x.strip()}
                if items and not (items & RELEVANT_ITEMS):
                    continue
                sel.append(f)
            sel.sort(key=lambda f: f["date"])
            done = sum(1 for f in sel if f["accession"] in log)
            print(f"{ticker} (CIK {c}): {len(sel)} filings to scan, {done} already done", flush=True)
            hits = 0
            for f in sel:
                if f["accession"] in log:
                    continue
                try:
                    text = scan_filing(c, f)
                except Exception as e:
                    print(f"  FAIL {ticker} {f['accession']}: {e}", flush=True)
                    log[f["accession"]] = {"ticker": ticker, "date": f["date"], "error": str(e)}
                    continue
                low = text.lower()
                mention = ("repurchas" in low) or ("buyback" in low) or ("buy-back" in low)
                log[f["accession"]] = {"ticker": ticker, "date": f["date"],
                                       "items": f["items"], "mention": mention}
                if mention:
                    hits += 1
                    with open(os.path.join(TEXTS, f"{ticker}_{f['accession'].replace('-','')}.txt"), "w") as fh:
                        fh.write(text)
                if len(log) % 100 == 0:
                    json.dump(log, open(log_path, "w"))
            json.dump(log, open(log_path, "w"))
            print(f"{ticker} (CIK {c}): pass complete, {hits} new mention-filings", flush=True)
    json.dump(log, open(log_path, "w"))
    n_mention = sum(1 for v in log.values() if v.get("mention"))
    print(f"DONE. scanned={len(log)} mention={n_mention}", flush=True)

if __name__ == "__main__":
    main()
