#!/usr/bin/env python3
"""Phase 1b: parallel scanner (8 workers, global ~7 req/s limiter, inside
SEC fair-access). Same scope/rules as detect_scan.py; doc set trimmed:
exhibit-99-style docs always; the primary document only when the filing
carries Item 8.01/7.01 or no exhibit-style doc exists. Resumable via
scan_log.json; reconstructs log entries for texts saved by the serial pass."""
import html as htmlmod
import json, os, re, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

UA = {"User-Agent": "AtlasGateResearch terry-research@example.com"}
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "buyback-events-data")
TEXTS = os.path.join(CACHE, "texts")
os.makedirs(TEXTS, exist_ok=True)
START, END = "2016-11-21", "2026-11-20"
RELEVANT_ITEMS = None  # v3: no items filter — announcements hide under 5.02/9.01-only filings
CIKS = json.load(open(os.path.join(CACHE, "ciks.json")))
LEGACY = {"DIS": [(1001039, "2016-11-21", "2019-03-31")]}

_rate_lock = threading.Lock()
_last_req = [0.0]

def rate_wait():
    with _rate_lock:
        now = time.time()
        wait = _last_req[0] + 0.13 - now
        if wait > 0:
            time.sleep(wait)
        _last_req[0] = time.time()

def fetch(url, path=None, tries=3):
    if path and os.path.exists(path) and os.path.getsize(path) > 50:
        with open(path, "rb") as f:
            return f.read()
    last = None
    for i in range(tries):
        try:
            rate_wait()
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                blob = r.read()
            if path:
                with open(path, "wb") as f:
                    f.write(blob)
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
    s = raw.decode("utf-8", errors="ignore")
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
    exhibits = []
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
            exhibits.append(name)
    items = {x.strip() for x in f["items"].split(",") if x.strip()}
    docs = list(exhibits)
    if (items & {"8.01", "7.01"}) or not exhibits:
        if f["primary"] in names:
            docs.append(f["primary"])
    texts = []
    for name in docs:
        try:
            texts.append(strip_html(fetch(f"{base}/{name}")))
        except Exception:
            continue
    return "\n".join(texts)

def main():
    log_path = os.path.join(CACHE, "scan_log.json")
    log = json.load(open(log_path)) if os.path.exists(log_path) else {}
    # reconstruct entries for texts saved by the serial pass but not logged
    all_by_acc = {}
    for ticker, cik in CIKS.items():
        for c, _, _ in [(cik, 0, 0)] + LEGACY.get(ticker, []):
            for f in all_filings(c):
                all_by_acc[f["accession"]] = (ticker, f)
    rebuilt = 0
    nodash_map = {acc.replace("-", ""): (acc, t, f)
                  for acc, (t, f) in all_by_acc.items()}
    for fn in os.listdir(TEXTS):
        if not fn.endswith(".txt"):
            continue
        ticker, acc_nodash = fn[:-4].rsplit("_", 1)
        hit = nodash_map.get(acc_nodash)
        if hit:
            acc, t, f = hit
            if acc not in log:
                log[acc] = {"ticker": t, "date": f["date"],
                            "items": f["items"], "mention": True}
                rebuilt += 1
    print(f"log: {len(log)} entries ({rebuilt} rebuilt from saved texts)", flush=True)

    jobs = []  # (ticker, cik, filing)
    for ticker, cik in CIKS.items():
        for c, d0, d1 in [(cik, START, END)] + LEGACY.get(ticker, []):
            for f in all_filings(c):
                if f["form"] != "8-K" or not (d0 <= f["date"] <= d1):
                    continue
                items = {x.strip() for x in f["items"].split(",") if x.strip()}
                if RELEVANT_ITEMS and items and not (items & RELEVANT_ITEMS):
                    continue
                if f["accession"] in log:
                    continue
                jobs.append((ticker, c, f))
    print(f"jobs: {len(jobs)} filings to scan", flush=True)

    lock = threading.Lock()
    state = {"done": 0, "mention": 0}

    def work(job):
        ticker, c, f = job
        try:
            text = scan_filing(c, f)
            low = text.lower()
            mention = ("repurchas" in low) or ("buyback" in low) or ("buy-back" in low)
            entry = {"ticker": ticker, "date": f["date"],
                     "items": f["items"], "mention": mention}
            if mention:
                path = os.path.join(
                    TEXTS, f"{ticker}_{f['accession'].replace('-', '')}.txt")
                with open(path, "w") as fh:
                    fh.write(text)
        except Exception as e:
            entry = {"ticker": ticker, "date": f["date"], "error": str(e)}
            mention = False
        with lock:
            log[f["accession"]] = entry
            state["done"] += 1
            state["mention"] += 1 if entry.get("mention") else 0
            if state["done"] % 150 == 0:
                json.dump(log, open(log_path, "w"))
                print(f"  {state['done']}/{len(jobs)} done, "
                      f"{state['mention']} mentions", flush=True)

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(work, jobs))
    json.dump(log, open(log_path, "w"))
    n_mention = sum(1 for v in log.values() if v.get("mention"))
    n_err = sum(1 for v in log.values() if v.get("error"))
    print(f"DONE. scanned={len(log)} mention={n_mention} errors={n_err}", flush=True)

if __name__ == "__main__":
    main()
