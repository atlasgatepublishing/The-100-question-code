import json, time, urllib.request, urllib.parse

UA = {"User-Agent": "AtlasGate research research@example.com"}
KNOWN = [
    ("MSFT","0000789019","2019-09-18","40 billion"),
    ("MSFT","0000789019","2021-09-14","60 billion"),
    ("MSFT","0000789019","2024-09-16","60 billion"),
    ("IBM","0000051143","2017-10-31","repurchase"),
    ("IBM","0000051143","2018-10-30","repurchase"),
    ("MA","0001141391","2023-12-05","repurchase"),
    ("MA","0001141391","2024-12-10","repurchase"),
    ("WFC","0000072971","2023-07-25","30 billion"),
    ("WFC","0000072971","2025-04-29","40 billion"),
]
def fts(q, cik, start, end):
    params = {"q": json.dumps(q), "ciks": cik, "dateRange": "custom",
              "startdt": start, "enddt": end}
    url = "https://efts.sec.gov/LATEST/search-index?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

from datetime import date, timedelta
out = []
for tk, cik, d, phrase in KNOWN:
    dt = date.fromisoformat(d)
    start = (dt - timedelta(days=3)).isoformat(); end = (dt + timedelta(days=14)).isoformat()
    try:
        res = fts("repurchase program", cik, start, end)
        hits = res["hits"]["hits"]
        rows = []
        for h in hits[:12]:
            s = h["_source"]
            rows.append({"form": s.get("form"), "file_date": s.get("file_date"),
                         "file": h["_id"], "items": s.get("items")})
        out.append({"ticker": tk, "announce": d, "window": [start, end],
                    "total_hits": res["hits"]["total"]["value"], "hits": rows})
        print(tk, d, "hits:", res["hits"]["total"]["value"])
        for r in rows: print("   ", r)
    except Exception as e:
        out.append({"ticker": tk, "announce": d, "error": str(e)})
        print(tk, d, "ERROR", e)
    time.sleep(0.4)
json.dump(out, open("/home/hatch/workspace/stock-app/backtests/v12-completions/buyback-events/hunt/fts_known10.json","w"), indent=1)
