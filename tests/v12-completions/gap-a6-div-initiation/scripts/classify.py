#!/usr/bin/env python3
"""Security-class fence — implements the CONSTRUCTION-SPEC's frozen
'common shares only' fence using Nasdaq Trader's exchange-published
security lists (nasdaqlisted.txt + otherlisted.txt, downloaded into
./data). The _w04 universe carries ONE ticker per CIK and for many
issuers that ticker is a preferred/depositary series, not the common
(e.g. Alphabet -> GOOGN, a mandatory-convertible-preferred depositary
share; Meta -> METAM). The frozen -/. ticker test cannot see these;
the exchange's own Security Name field can. Classification is by the
security's class as the exchange names it. No price or result was
consulted. Output: security_classes.json + census_events_common.json.
"""
import json, os, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
H = {"User-Agent": "Mozilla/5.0"}

def get(url, path):
    if not (os.path.exists(path) and os.path.getsize(path) > 1000):
        r = urllib.request.Request(url, headers=H)
        open(path, "wb").write(urllib.request.urlopen(r, timeout=60).read())
    return open(path, "rb").read().decode("utf-8", "replace")

def main():
    nas = get("https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt",
              os.path.join(DATA, "nasdaqlisted.txt"))
    oth = get("https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt",
              os.path.join(DATA, "otherlisted.txt"))
    secname, etf = {}, {}
    for line in nas.splitlines()[1:]:
        p = line.split("|")
        if len(p) < 8 or p[0] == "File Creation Time": continue
        secname[p[0]] = p[1]; etf[p[0]] = (p[6] == "Y")
    for line in oth.splitlines()[1:]:
        p = line.split("|")
        if len(p) < 8 or p[0] == "File Creation Time": continue
        # fields: ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot|Test Issue|NASDAQ Symbol
        secname[p[7]] = p[1]; etf[p[7]] = (p[4] == "Y")
        secname.setdefault(p[0], p[1]); etf.setdefault(p[0], p[4] == "Y")
    EXCL_WORDS = {"preferred", "preference", "units", "rights", "warrants"}
    def classify(t):
        n = secname.get(t)
        if n is None: return ("UNKNOWN-not-in-exchange-lists", None)
        if etf.get(t): return ("EXCLUDE-etf", n)
        words = {w.strip(".,").lower() for w in n.replace("-", " ").split()}
        if words & EXCL_WORDS: return ("EXCLUDE-noncommon-class", n)
        if "notes" in words or "note" in words: return ("EXCLUDE-notes", n)
        if "depositary" in words and "preferred" in n.lower(): return ("EXCLUDE-noncommon-class", n)
        if "depositary" in words and "american" not in words and "common" not in n.lower() \
           and "ordinary" not in n.lower():
            # bare 'Depositary Shares' of a domestic issuer = depositary shares
            # representing a preferred series (e.g. WAFDP); ADR commons are
            # named 'American Depositary Shares' and are kept.
            return ("EXCLUDE-depositary-unspecified", n)
        keep_markers = ("common stock", "ordinary shares", "capital stock",
                        "common shares", "beneficial interest", "common unit")
        if any(m in n.lower() for m in keep_markers) or "shares" in words:
            return ("COMMON", n)
        return ("UNKNOWN-unmatched-name", n)
    tapes = json.load(open(os.path.join(ROOT, "census_tapes.json")))
    classes = {}
    for t in sorted(tapes["universe"]):
        c, n = classify(t)
        classes[t] = {"class": c, "security_name": n}
    json.dump(classes, open(os.path.join(ROOT, "security_classes.json"), "w"), indent=1)
    cen = json.load(open(os.path.join(ROOT, "census_events.json")))
    kept, dropped = [], []
    for e in cen["events"]:
        e2 = {**e, "security_class": classes.get(e["ticker"], {}).get("class"),
              "security_name": classes.get(e["ticker"], {}).get("security_name")}
        (kept if e2["security_class"] == "COMMON" else dropped).append(e2)
    json.dump({"kept": kept, "dropped": dropped},
              open(os.path.join(ROOT, "census_events_common.json"), "w"), indent=1)
    from collections import Counter
    print("universe class counts:", Counter(v["class"] for v in classes.values()))
    print(f"events kept COMMON: {len(kept)}; dropped: {len(dropped)}")
    for e in dropped: print("  DROPPED:", e["ticker"], e["first_ex"], e["security_class"], "|", e["security_name"])
    for e in kept: print("  KEPT:", e["ticker"], e["first_ex"], e["kind"], "|", e["security_name"])

if __name__ == "__main__":
    main()
