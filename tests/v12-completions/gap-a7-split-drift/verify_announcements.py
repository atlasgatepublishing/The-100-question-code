"""Stage 2: verify each ex-date event's ANNOUNCEMENT date on EDGAR.
For each event: EDGAR submissions for the CIK -> 8-K/8-K-A filings in
[ex_date-150d, ex_date) -> scan filing docs (primary + exhibits) in date order
for a forward-split announcement whose stated ratio matches the Yahoo factor.
Announcement date = filing date of earliest matching filing. Frozen per spec.
"""
import json, os, re, time
import requests
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
FCACHE = os.path.join(HERE, "cache", "filings"); os.makedirs(FCACHE, exist_ok=True)
H_SEC = {"User-Agent": "AtlasGate Research research@atlasgate.example", "Accept-Encoding": "gzip"}
H_WEB = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}

WORDS = {"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,"eight":8,"nine":9,
         "ten":10,"eleven":11,"twelve":12,"fifteen":15,"twenty":20,"twenty-five":25,"fifty":50,"one-hundred":100}

def stated_factors(text):
    """All forward-split factors stated in a paragraph (reverse excluded by caller)."""
    out = []
    t = text.lower()
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*[-–]?\s*for\s*[-–]?\s*(\d+(?:\.\d+)?)", t):
        a, b = float(m.group(1)), float(m.group(2))
        if b: out.append(a / b)
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*[-–]?\s*for\s*[-–]?\s*one\b", t):
        out.append(float(m.group(1)))
    for w, n in WORDS.items():
        if re.search(rf"\b{w}\s*[-–]?\s*for\s*[-–]?\s*one\b", t): out.append(float(n))
        if re.search(rf"\b{w}\s*[-–]?\s*for\s*[-–]?\s*two\b", t): out.append(n / 2)
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)", t):
        a, b = float(m.group(1)), float(m.group(2))
        if b and a > b: out.append(a / b)
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*%\s*stock dividend", t):
        out.append(1 + float(m.group(1)) / 100)
    return out

def announcement_factor(html, target):
    """Return stated factor if this doc announces a forward split matching target.
    Sentence-window scan (3-sentence windows) — robust to stripped HTML layout."""
    txt = re.sub(r"<[^>]+>", " ", html)
    txt = re.sub(r"&#\d+;|&[a-z]+;", " ", txt)
    txt = re.sub(r"\s+", " ", txt)
    sents = re.split(r"(?<=[.!?])\s+", txt)
    for i, s in enumerate(sents):
        if "split" not in s.lower(): continue
        win = " ".join(sents[max(0, i - 1): i + 2])
        wl = win.lower()
        if "reverse" in wl: continue
        if not any(k in wl for k in ("announc", "approv", "declar", "effect", "board of directors")): continue
        for f in stated_factors(win):
            if abs(f - target) < 0.02 and f >= 2.0:
                return f
    return None

def get(url, headers, timeout=30, binary=False):
    for a in range(3):
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
            if r.status_code == 200: return r
            if r.status_code in (403, 404): return None
        except Exception: pass
        time.sleep(1.0 * (a + 1))
    return None

MEMO = {}
def submissions(cik):
    if cik in MEMO: return MEMO[cik]
    path = os.path.join(FCACHE, f"sub_{cik}.json")
    if os.path.exists(path):
        try:
            d = json.load(open(path)); MEMO[cik] = d; return d
        except Exception: pass
    r = get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", H_SEC)
    if r is None: return None
    try: json.dump(r.json(), open(path, "w"))
    except Exception: pass
    MEMO[cik] = r.json(); return MEMO[cik]

def filing_docs(cik, acc):
    accn = acc.replace("-", "")
    if accn in MEMO: return MEMO[accn]
    path = os.path.join(FCACHE, f"idx_{accn}.json")
    if os.path.exists(path):
        try:
            d = json.load(open(path)); MEMO[accn] = d; return d
        except Exception: pass
    r = get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn}/index.json", H_SEC)
    if r is None: return None
    try: json.dump(r.json(), open(path, "w"))
    except Exception: pass
    MEMO[accn] = r.json(); return MEMO[accn]

def verify(ev):
    cik, ex, target = ev["cik"], ev["ex_date"], ev["factor"]
    if not cik: return None, "no_cik"
    sub = submissions(cik)
    if not sub: return None, "no_submissions"
    exd = date.fromisoformat(ex); lo = exd - timedelta(days=150)
    # merge recent + archived history files (recent alone does not reach 2010s)
    rows = []
    def eat(rec):
        for form, fdate, acc, doc in zip(rec["form"], rec["filingDate"], rec["accessionNumber"], rec["primaryDocument"]):
            rows.append((form, fdate, acc, doc))
    eat(sub["filings"]["recent"])
    for fmeta in sub["filings"].get("files", []):
        if fmeta["filingTo"] < lo.isoformat() or fmeta["filingFrom"] > ex: continue
        hp = os.path.join(FCACHE, "hist_" + fmeta["name"])
        if fmeta["name"] in MEMO:
            eat(MEMO[fmeta["name"]]); continue
        if os.path.exists(hp):
            try:
                d = json.load(open(hp)); MEMO[fmeta["name"]] = d; eat(d); continue
            except Exception: pass
        r = get(f"https://data.sec.gov/submissions/{fmeta['name']}", H_SEC)
        if r is None: continue
        try: json.dump(r.json(), open(hp, "w"))
        except Exception: pass
        MEMO[fmeta["name"]] = r.json(); eat(MEMO[fmeta["name"]])
    rec = {"form": [r[0] for r in rows], "filingDate": [r[1] for r in rows],
           "accessionNumber": [r[2] for r in rows], "primaryDocument": [r[3] for r in rows]}
    cands = []
    for form, fdate, acc, doc in zip(rec["form"], rec["filingDate"], rec["accessionNumber"], rec["primaryDocument"]):
        if form in ("8-K", "8-K/A") and lo.isoformat() <= fdate < ex:
            cands.append((fdate, acc, doc))
    cands.sort()
    for fdate, acc, primary in cands:
        accn = acc.replace("-", "")
        # fast path: the filing's full-submission .txt contains every document
        tkey = f"{accn}_fulltxt"
        html = MEMO.get(tkey)
        if html is None:
            r = get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn}/{accn}.txt", H_SEC, timeout=40)
            if r is not None:
                html = r.text[:6_000_000]; MEMO[tkey] = html; time.sleep(0.11)
        if html:
            f = announcement_factor(html, target)
            if f: return {"announced": fdate, "accession": acc, "doc": f"{accn}.txt", "stated_factor": f}, "verified"
            continue
        idx = filing_docs(cik, acc)
        docs = []
        if idx:
            for it in idx["directory"]["item"]:
                n = it["name"].lower()
                if n.endswith((".htm", ".html", ".txt")) and n != "index.json":
                    docs.append(it["name"])
            docs.sort(key=lambda n: (0 if n == primary else 1 if "ex99" in n.replace("-", "").replace("_", "") or "ex-99" in n else 2, n))
        elif primary: docs = [primary]
        for dn in docs[:6]:
            key = f"{accn}_{dn}".replace("/", "_")
            path = os.path.join(FCACHE, key)
            if key in MEMO:
                html = MEMO[key]
            elif os.path.exists(path):
                html = open(path, errors="ignore").read(); MEMO[key] = html
            else:
                r = get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn}/{dn}", H_SEC, timeout=40)
                if r is None: continue
                html = r.text[:3_000_000]; MEMO[key] = html
                try: open(path, "w", errors="ignore").write(html)
                except Exception: pass
                time.sleep(0.11)
            f = announcement_factor(html, target)
            if f: return {"announced": fdate, "accession": acc, "doc": dn, "stated_factor": f}, "verified"
    return None, f"no_match_in_{len(cands)}_filings"

def main():
    census = json.load(open(os.path.join(HERE, "data", "exdate_census.json")))
    out, done = [], {}
    vpath = os.path.join(HERE, "data", "verified_events.json")
    if os.path.exists(vpath):
        try:
            prev = json.load(open(vpath))
            done = {e["ticker"] + e["ex_date"]: e for e in prev}
        except Exception: done = {}
    todo = []
    for ev in census["events"]:
        k = ev["ticker"] + ev["ex_date"]
        if k in done: out.append(done[k])
        else: todo.append(ev)
    def work(ev):
        res, status = verify(ev)
        rec = dict(ev); rec["verify_status"] = status
        if res: rec.update(res)
        print(f"REC|{ev['ticker']}|{ev['ex_date']}|{ev['factor']}|{status}|{rec.get('announced','')}|{rec.get('accession','')}|{rec.get('doc','')}|{rec.get('stated_factor','')}", flush=True)
        return rec
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=4) as ex_:
        out.extend(ex_.map(work, todo))
    from collections import Counter
    print("DONE", Counter(e["verify_status"].split("_in_")[0] for e in out))

if __name__ == "__main__":
    main()
