"""V13 activist-13D harvest.
1) Extend the v11 EDGAR census (read-only input) backward 2010-2018 with the identical
   query (efts, form SC 13D, phrase "beneficial ownership", monthly windows).
2) Intent-phrase passes: for each frozen phrase in BEST-RULES-SPEC.md, harvest the set of
   accession numbers whose filing full text contains the phrase (form SC 13D through 2024,
   SCHEDULE 13D + SC 13D for 2025-2026), monthly windows 2010-2026.
Checkpointed; safe to re-run. Writes ONLY in this folder."""
import os, json, re, time
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
V11 = os.path.expanduser("~/workspace/stock-app/backtests/v11-native-rules/activist-13d")
H = {"User-Agent": "Atlas Gate Publishing research@example.com", "Accept-Encoding": "gzip, deflate", "Host": "efts.sec.gov"}
PHRASES = ["strategic alternatives", "maximize shareholder value", "maximize stockholder value",
           "undervalued", "board representation", "nominate"]

def query_month(q, form, year, month):
    start = f"{year}-{month:02d}-01"
    end = f"{year + (month == 12)}-{(month % 12) + 1:02d}-01"
    out = []
    frm = 0
    while True:
        d = None
        for attempt in range(4):
            try:
                r = requests.get("https://efts.sec.gov/LATEST/search-index",
                                 params={"q": q, "forms": form, "dateRange": "custom",
                                         "startdt": start, "enddt": end, "from": frm, "size": 100},
                                 headers=H, timeout=40)
                dj = r.json()
                if "hits" in dj: d = dj; break
            except Exception:
                pass
            time.sleep(2 + attempt * 2)
        if d is None: return out, False
        hits = d["hits"]["hits"]
        out.extend(hits)
        total = d["hits"]["total"]["value"]
        frm += 100
        if frm >= min(total, 10000) or not hits: break
        time.sleep(0.12)
    return out, True

def extend_census():
    base = json.load(open(os.path.join(V11, "census.json")))
    out_path = os.path.join(HERE, "my_census.json")
    seen = json.load(open(out_path)) if os.path.exists(out_path) else dict(base)
    prog_path = os.path.join(HERE, "extend_progress.json")
    done = set(json.load(open(prog_path))) if os.path.exists(prog_path) else set()
    for year in range(2010, 2019):
        for month in range(1, 13):
            key = f"{year}-{month:02d}"
            if key in done: continue
            hits, ok = query_month('"beneficial ownership"', "SC 13D", year, month)
            if not ok:
                print("FAILED month", key, flush=True); continue
            for h in hits:
                s = h["_source"]
                if s["form"] != "SC 13D": continue
                adsh = s["adsh"]
                if adsh in seen: continue
                names = s.get("display_names") or []
                subj = names[0] if names else ""
                m = re.search(r"\(([A-Z][A-Z.\-]{0,9})\)\s+\(CIK", subj)
                seen[adsh] = {"adsh": adsh, "file_date": s["file_date"], "subject": subj,
                              "ticker": m.group(1) if m else None, "cik": (s.get("ciks") or [None])[0]}
            done.add(key)
            json.dump(seen, open(out_path, "w")); json.dump(sorted(done), open(prog_path, "w"))
            print("census extended through", key, len(seen), flush=True)
    return seen

def intent_passes(phrases=None):
    phrases = phrases or PHRASES
    tag = phrases[0].replace(" ", "_") if len(phrases) == 1 else "all"
    out_path = os.path.join(HERE, f"intent_{tag}.json")
    intent = json.load(open(out_path)) if os.path.exists(out_path) else {}
    prog_path = os.path.join(HERE, f"intent_progress_{tag}.json")
    done = set(json.load(open(prog_path))) if os.path.exists(prog_path) else set()
    for phrase in phrases:
        for year in range(2010, 2027):
            forms = ["SC 13D"] if year <= 2024 else ["SCHEDULE 13D", "SC 13D"]
            for form in forms:
                for month in range(1, 13):
                    key = f"{phrase}|{form}|{year}-{month:02d}"
                    if key in done: continue
                    hits, ok = query_month(f'"{phrase}"', form, year, month)
                    if not ok:
                        print("FAILED", key, flush=True); continue
                    for h in hits:
                        s = h["_source"]
                        if s["form"] != form: continue
                        intent.setdefault(s["adsh"], [])
                        if phrase not in intent[s["adsh"]]: intent[s["adsh"]].append(phrase)
                    done.add(key)
                    if month % 6 == 0:
                        json.dump(intent, open(out_path, "w")); json.dump(sorted(done), open(prog_path, "w"))
                    print("intent through", key, len(intent), flush=True)
        json.dump(intent, open(out_path, "w")); json.dump(sorted(done), open(prog_path, "w"))
    return intent

if __name__ == "__main__":
    import sys
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("all", "census"): extend_census()
    if which in ("all", "intent"): intent_passes()
    if which.startswith("phrase:"): intent_passes([which[len("phrase:"):]])
    print("DONE", which, flush=True)
