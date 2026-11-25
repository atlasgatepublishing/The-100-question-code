#!/usr/bin/env python3
"""
LAZY PRICES — era signal build for the long run.

Builds whole-document 10-K cosine similarities for the 2010 pond from
EDGAR filings dated 2007-01-01 -> 2026-11-20, using the gap-a5 engine's
own frozen method (its doc_text / token rule / cosine / consecutive-
filing chaining, imported verbatim). Fetching from 2007 is the analog
of gap-a5 fetching from 2016: the first in-window signals must rest on
real prior-year documents. Differences from gap-a5's build, plumbing
only: (1) the pond is the 2010 point-in-time top-30 with era CIKs;
(2) submission history files are fetched WITHOUT gap-a5's 2015 cutoff
(era filings live in the old history files); (3) vector caches are
reused read-only from gap-a5's data/vecs when the same CIK+accession
was already tokenized there; new work lands in this test's data/lazy/.
"""
import gzip
import json
import os
import sys
import time
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lr_common as C  # noqa: E402

lazy = C.load_module("lazy_lr", os.path.join(
    C.V7, "gap-a5-lazy-prices", "lazy-prices.py"))
GAP5_VECS = os.path.join(C.V7, "gap-a5-lazy-prices", "data", "vecs")
LZ = os.path.join(C.MYDATA, "lazy")
DOCS = os.path.join(LZ, "docs")
VECS = os.path.join(LZ, "vecs")
for d in (LZ, DOCS, VECS):
    os.makedirs(d, exist_ok=True)
FETCH_FROM, FETCH_TO = "2007-01-01", "2026-11-20"

with open(os.path.join(C.BT, "v7", "long-hold",
                       "universe-build-long.json")) as f:
    POND = json.load(f)["universe"]
print(f"pond ({len(POND)}): {POND}", flush=True)


def get_filing_index(cik):
    """All filings for a CIK: recent + EVERY history file (no cutoff)."""
    path = os.path.join(LZ, f"submissions_{cik:010d}.json")
    blob = C.fetch_cached(
        f"https://data.sec.gov/submissions/CIK{cik:010d}.json", path)
    j = json.loads(blob)
    blocks = [j["filings"]["recent"]]
    for extra in j["filings"].get("files", []):
        p2 = os.path.join(LZ, f"submissions_{cik:010d}_{extra['name']}")
        b2 = C.fetch_cached(
            f"https://data.sec.gov/submissions/{extra['name']}", p2)
        blocks.append(json.loads(b2))
    rows = []
    for blk in blocks:
        n = len(blk["form"])
        for i in range(n):
            rows.append({
                "form": blk["form"][i],
                "accession": blk["accessionNumber"][i],
                "filing_date": blk["filingDate"][i],
                "acceptance": blk["acceptanceDateTime"][i],
                "primary_doc": blk["primaryDocument"][i],
                "period": blk.get("reportDate", [""] * n)[i],
            })
    return rows


def get_vector(cik, filing):
    """Term-frequency Counter for one filing (gap-a5 method verbatim);
    cache order: this test's vecs, then gap-a5's vecs (read-only)."""
    acc = filing["accession"]
    fname = f"vec_{cik:010d}_{acc}.json.gz"
    vpath = os.path.join(VECS, fname)
    if os.path.exists(vpath) and os.path.getsize(vpath) > 100:
        with gzip.open(vpath, "rt") as f:
            return Counter(json.load(f))
    gpath = os.path.join(GAP5_VECS, fname)
    if os.path.exists(gpath) and os.path.getsize(gpath) > 100:
        with gzip.open(gpath, "rt") as f:
            return Counter(json.load(f))
    dpath = os.path.join(DOCS, f"{cik:010d}_{acc}_{filing['primary_doc']}")
    url = (f"https://www.sec.gov/Archives/edgar/data/{cik}/"
           f"{acc.replace('-', '')}/{filing['primary_doc']}")
    blob = C.fetch_cached(url, dpath)
    counts = Counter(lazy.TOKEN_RE.findall(lazy.doc_text(blob).lower()))
    with gzip.open(vpath, "wt") as f:
        json.dump(dict(counts), f)
    return counts


def main():
    signals, census = {}, {}
    for t in POND:
        cik = C.cik_for(t)
        rows = get_filing_index(cik)
        k10 = [r for r in rows if r["form"] == "10-K"
               and FETCH_FROM <= r["filing_date"] <= FETCH_TO]
        ka = [r for r in rows if r["form"] == "10-K/A"
              and FETCH_FROM <= r["filing_date"] <= FETCH_TO]
        k10.sort(key=lambda r: r["acceptance"])
        sigs, prev, total_tokens, failed = [], None, 0, []
        for r in k10:
            try:
                vec = get_vector(cik, r)
            except Exception as e:  # noqa
                failed.append((r["accession"], r["filing_date"], str(e)))
                continue
            total_tokens += sum(vec.values())
            if prev is not None:
                sim = lazy.cosine(prev, vec)
                if sim is not None:
                    sigs.append((r["acceptance"][:10], round(sim, 6),
                                 r["accession"]))
            prev = vec
        signals[t] = sigs
        census[t] = {"cik": cik, "n_10k": len(k10),
                     "n_10ka_excluded": len(ka),
                     "n_similarities": len(sigs),
                     "total_tokens": total_tokens,
                     "first_filing": k10[0]["filing_date"] if k10 else None,
                     "last_filing": k10[-1]["filing_date"] if k10 else None,
                     "first_similarity": sigs[0][0] if sigs else None,
                     "fetch_failures": failed}
        print(f"{t}: CIK {cik} 10-Ks={len(k10)} (A excluded={len(ka)}) "
              f"similarities={len(sigs)} tokens={total_tokens:,} "
              f"failures={len(failed)}", flush=True)
    with open(os.path.join(LZ, "similarities_era.json"), "w") as f:
        json.dump({"signals": signals, "census": census}, f, indent=1)
    print("DONE signals built", flush=True)


if __name__ == "__main__":
    main()
