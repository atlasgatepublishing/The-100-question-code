#!/usr/bin/env python3
"""HUNT AUDIT (v12 lottery): direct tests, run 2026-11-22.
1) Stooq CSV endpoint for delisted OTC tickers (+ listed control).
2) Yahoo chart API (the program's own plumbing) for dead OTC tickers.
Records exactly what each source returns. No data is used for any run.
"""
import json, urllib.request, urllib.error

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}
out = {}

def get(url, nbytes=400):
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read()
            return {"status": r.status, "bytes": len(body),
                    "head": body[:nbytes].decode("utf-8", "replace")}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "error": str(e)}
    except Exception as e:
        return {"status": None, "error": repr(e)}

# --- Stooq: dead OTC tickers (Q-suffix bankruptcy names) + controls
stooq_syms = ["aapl.us", "lehmq.us", "bloaq.us", "shldq.us", "enrnq.us", "wamuq.us"]
out["stooq"] = {s: get(f"https://stooq.com/q/d/l/?s={s}&i=d") for s in stooq_syms}

# --- Yahoo chart API: dead OTC tickers, full-history request 2000->2026
import datetime
p1 = int(datetime.datetime(2000,1,1,tzinfo=datetime.timezone.utc).timestamp())
p2 = int(datetime.datetime(2026,11,22,tzinfo=datetime.timezone.utc).timestamp())
yahoo = {}
for sym in ["LEHMQ", "BLOAQ", "SHLDQ", "ENRNQ", "WAMUQ"]:
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
           f"?period1={p1}&period2={p2}&interval=1d")
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode())
        res = data.get("chart", {}).get("result")
        if res:
            ts = res[0].get("timestamp") or []
            yahoo[sym] = {"bars": len(ts),
                          "first": datetime.datetime.fromtimestamp(ts[0], datetime.timezone.utc).strftime("%Y-%m-%d") if ts else None,
                          "last": datetime.datetime.fromtimestamp(ts[-1], datetime.timezone.utc).strftime("%Y-%m-%d") if ts else None,
                          "exchange": res[0].get("meta", {}).get("exchangeName")}
        else:
            yahoo[sym] = {"bars": 0, "error": str(data.get("chart", {}).get("error"))}
    except Exception as e:
        yahoo[sym] = {"bars": None, "error": repr(e)}
out["yahoo_dead_otc"] = yahoo

print(json.dumps(out, indent=1))
with open("/home/hatch/workspace/stock-app/backtests/v12-completions/lottery/hunt/audit_results.json", "w") as f:
    json.dump(out, f, indent=1)
