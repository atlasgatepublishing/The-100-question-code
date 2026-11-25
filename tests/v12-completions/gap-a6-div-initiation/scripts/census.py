#!/usr/bin/env python3
"""Census builder — gap-a6-div-initiation v12.
Universe: _w04 broad candidates (EDGAR frames top-600 by assets, year-ends
2016-2025) intersect NYSE/Nasdaq, common shares only (no '-' or '.'), with a
cached _w04 price file. Per ticker: Nasdaq dividend-history tape (cached).
Event = first-ever regular cash dividend, or resumption after >=5y silence,
with first ex-date in 2016-11-21..2026-11-20, a further dividend within
15 months (regular-program confirmation), declaration date from the tape.
Point-in-time membership: eligible from first frame year the name appears
(event first-ex must be >= Jan 1 of the year after? No: frame is year-end;
eligible for events with ex-date after that year-end date, i.e. ex >=
(year+1)-01-01 when first frame year = year... frames are CY year-end
snapshots; a name in CY2016 frame was a top filer at 2016-12-31, so events
from 2017-01-01 on. For the DECADE window start 2016-11-21 we additionally
allow names in the CY2016 frame for events on/after 2016-11-21 (the frame
is the closest PIT snapshot; stated in census output).
"""
import json, os, time, urllib.request, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data"); os.makedirs(DATA, exist_ok=True)
W04 = os.path.expanduser("~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data")
H = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)", "Accept": "application/json"}

def fetch(url, path, tries=3):
    if os.path.exists(path) and os.path.getsize(path) > 50:
        return open(path, "rb").read()
    last = None
    for i in range(tries):
        try:
            r = urllib.request.Request(url, headers=H)
            b = urllib.request.urlopen(r, timeout=40).read()
            open(path, "wb").write(b); return b
        except Exception as e:
            last = e; time.sleep(2 * (i + 1))
    raise RuntimeError(f"{url}: {last}")

def pdate(s):
    if not s or s == "N/A": return None
    try: return dt.datetime.strptime(s, "%m/%d/%Y").date().isoformat()
    except Exception: return None

def main():
    cand = json.load(open(os.path.join(W04, "candidates.json")))
    px = {f[3:-5] for f in os.listdir(W04) if f.startswith("px_")}
    uni = {}
    for cik, v in cand.items():
        t = v["ticker"]
        if t in px and v.get("exchange") in ("NYSE", "Nasdaq") and "-" not in t and "." not in t:
            first_year = min(int(y) for y in v["years"])
            uni.setdefault(t, {"name": v["name"], "exchange": v["exchange"], "first_frame_year": first_year})
    tickers = sorted(uni)
    print(f"universe: {len(tickers)}", flush=True)
    tapes, fails = {}, []
    for i, t in enumerate(tickers):
        path = os.path.join(DATA, f"nasdaq_{t}.json")
        try:
            j = json.loads(fetch(f"https://api.nasdaq.com/api/quote/{t}/dividends?assetclass=stocks", path))
            rows = ((j.get("data") or {}).get("dividends") or {}).get("rows") or []
            out = []
            for r in rows:
                ex = pdate(r.get("exOrEffDate"))
                if not ex: continue
                amt = r.get("amount", "").replace("$", "").replace(",", "")
                try: amt = float(amt)
                except Exception: amt = None
                out.append({"ex": ex, "decl": pdate(r.get("declarationDate")),
                            "amt": amt, "type": r.get("type")})
            out.sort(key=lambda r: r["ex"])
            tapes[t] = out
        except Exception as e:
            fails.append({"ticker": t, "error": str(e)})
        if i % 50 == 0: print(f"  {i}/{len(tickers)}", flush=True)
        time.sleep(0.12)
    json.dump({"universe": uni, "tapes": tapes, "failures": fails},
              open(os.path.join(ROOT, "census_tapes.json"), "w"))
    # Event detection
    W0, W1 = "2016-11-21", "2026-11-20"
    events = []
    for t, rows in tapes.items():
        cash = [r for r in rows if (r["type"] or "").lower().startswith("cash")]
        if not cash: continue
        elig_from = f"{uni[t]['first_frame_year']}-11-21" if uni[t]['first_frame_year'] == 2016 else f"{uni[t]['first_frame_year']+1}-01-01"
        for k, r in enumerate(cash):
            kind = None
            if k == 0: kind = "first-ever"
            else:
                gap = (dt.date.fromisoformat(r["ex"]) - dt.date.fromisoformat(cash[k-1]["ex"])).days / 365.25
                if gap >= 5.0: kind = f"resumption (gap {gap:.2f}y)"
            if not kind: continue
            if not (W0 <= r["ex"] <= W1): continue
            if r["ex"] < elig_from: continue
            nxt = [x for x in cash if x["ex"] > r["ex"] and (dt.date.fromisoformat(x["ex"]) - dt.date.fromisoformat(r["ex"])).days <= 457]
            if not nxt:
                events.append({"ticker": t, "kind": kind, "first_ex": r["ex"], "decl": r["decl"],
                               "amt": r["amt"], "status": "EXCLUDED-no-second-dividend-within-15m"})
                continue
            events.append({"ticker": t, "kind": kind, "first_ex": r["ex"], "decl": r["decl"],
                           "amt": r["amt"], "status": "QUALIFYING", "n_prior_divs": k,
                           "prior_ex": cash[k-1]["ex"] if k else None})
    events.sort(key=lambda e: (e["first_ex"], e["ticker"]))
    json.dump({"universe_size": len(tickers), "events": events},
              open(os.path.join(ROOT, "census_events.json"), "w"), indent=1)
    q = [e for e in events if e["status"] == "QUALIFYING"]
    print(f"tapes ok: {len(tapes)}, failures: {len(fails)}")
    print(f"events found: {len(events)}, qualifying: {len(q)}")
    for e in events: print(" ", e)

if __name__ == "__main__":
    main()
