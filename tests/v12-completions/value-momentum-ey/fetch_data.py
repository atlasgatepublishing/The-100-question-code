#!/usr/bin/env python3
"""v12 value-momentum-ey data fetch (see CONSTRUCTION-SPEC.md).
- Tradable seed: SEC company_tickers_exchange.json (cached in data/) mapped
  from data/seed_universe.json; keep NYSE/Nasdaq/TXSE; drop preferred/unit/
  warrant tickers (contains -P, ends -W/-WT/-U/-R).
- EDGAR companyconcept (as-filed, filed dates) for the 5 chain concepts,
  one JSON per CIK in data/concepts_<cik>.json.
- Yahoo chart daily bars 2008-01-01..2026-11-22 per ticker in
  data/pxfull_<ticker>.json (+ SPY). Same source/method as house engine.
"""
import json, os, re, time, urllib.request, urllib.parse, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
os.makedirs(DATA, exist_ok=True)
SEC_H = {"User-Agent": "AtlasGate v12 research research@atlasgate.example"}
YH_H = {"User-Agent": "Mozilla/5.0"}

CONCEPTS = [
    ("us-gaap", "NetIncomeLoss"),
    ("us-gaap", "ProfitLoss"),
    ("dei", "EntityCommonStockSharesOutstanding"),
    ("us-gaap", "CommonStockSharesOutstanding"),
    ("us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic"),
]

def get(url, headers, tries=3):
    for i in range(tries):
        try:
            r = urllib.request.Request(url, headers=headers)
            return urllib.request.urlopen(r, timeout=90).read()
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))

def tradable_seed():
    seed = json.load(open(os.path.join(DATA, "seed_universe.json")))
    out = {}
    dropped = []
    for cik, info in seed.items():
        t = info["ticker"]
        if info["exchange"] not in ("NYSE", "Nasdaq", "TXSE"):
            dropped.append((t, "exchange:" + str(info["exchange"])))
            continue
        if "-P" in t or re.search(r"-(W|WT|U|R)$", t):
            dropped.append((t, "security-type"))
            continue
        out[int(cik)] = info
    json.dump({"tradable": {str(k): v for k, v in out.items()},
               "dropped": dropped},
              open(os.path.join(DATA, "tradable_universe.json"), "w"), indent=1)
    return out, dropped

def fetch_concepts(seed):
    ok = fail = 0
    for cik in sorted(seed):
        p = os.path.join(DATA, f"concepts_{cik:010d}.json")
        if os.path.exists(p) and os.path.getsize(p) > 50:
            ok += 1
            continue
        bundle = {}
        try:
            for tax, concept in CONCEPTS:
                u = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/{tax}/{concept}.json"
                try:
                    bundle[f"{tax}:{concept}"] = json.loads(get(u, SEC_H))
                except Exception as e:
                    bundle[f"{tax}:{concept}"] = {"error": str(e)}
                time.sleep(0.11)
            json.dump(bundle, open(p, "w"))
            ok += 1
        except Exception as e:
            fail += 1
            print("CONCEPT FAIL", cik, e, flush=True)
        if ok % 100 == 0:
            print(f"concepts {ok} done", flush=True)
    print(f"concepts done ok={ok} fail={fail}", flush=True)

def fetch_prices(seed):
    p1 = int(datetime.datetime(2008, 1, 1, tzinfo=datetime.timezone.utc).timestamp())
    p2 = int(datetime.datetime(2026, 11, 22, tzinfo=datetime.timezone.utc).timestamp())
    tickers = sorted({v["ticker"] for v in seed.values()}) + ["SPY"]
    ok = fail = 0
    fails = []
    for t in tickers:
        p = os.path.join(DATA, f"pxfull_{t}.json")
        if os.path.exists(p) and os.path.getsize(p) > 1000:
            ok += 1
            continue
        u = ("https://query1.finance.yahoo.com/v8/finance/chart/%s"
             "?period1=%d&period2=%d&interval=1d&events=div,split"
             % (urllib.parse.quote(t), p1, p2))
        try:
            blob = get(u, YH_H)
            d = json.loads(blob)
            if not d["chart"]["result"]:
                raise ValueError("empty result")
            open(p, "wb").write(blob)
            ok += 1
        except Exception as e:
            fail += 1
            fails.append({"ticker": t, "error": str(e)})
        if (ok + fail) % 100 == 0:
            print(f"prices {ok + fail} done", flush=True)
        time.sleep(0.15)
    json.dump(fails, open(os.path.join(DATA, "price_failures.json"), "w"), indent=1)
    print(f"prices done ok={ok} fail={fail}", flush=True)

if __name__ == "__main__":
    seed, dropped = tradable_seed()
    print(f"tradable seed: {len(seed)} CIKs, dropped {len(dropped)}", flush=True)
    fetch_concepts(seed)
    fetch_prices(seed)
    print("ALL FETCH DONE", flush=True)
