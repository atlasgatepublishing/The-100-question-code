#!/usr/bin/env python3
"""Harvest price tapes already cached elsewhere in the program (read-only
sources) into this folder's data/ in this family's format, for roster
tickers not yet fetched. Sources: any px_<T>.json in {"src","bars"} format
and any pxfull_<T>.json raw Yahoo payloads under ~/workspace/stock-app.
Prefers the tape with the most bars. Never overwrites an existing file."""
import csv, glob, json, os, time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
BASE = os.path.expanduser("~/workspace/stock-app")

snaps = []
with open(os.path.join(DATA, "sp500_hist.csv")) as f:
    for row in csv.DictReader(f):
        snaps.append((row["date"], [t.strip() for t in row["tickers"].split(",") if t.strip()]))
need = {t for d, ts in snaps if d >= "2006-01-01" for t in ts} | {"SPY"}
have = {fn[3:-5] for fn in os.listdir(DATA) if fn.startswith("px_") and fn.endswith(".json")}
missing = sorted(need - have)
print(f"need {len(need)}, have {len(have)}, missing {len(missing)}", flush=True)

def from_payload(payload):
    res = payload["chart"]["result"][0]
    ts = res["timestamp"]; q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        c = q["close"][i]
        if c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        bars.append([time.strftime("%Y-%m-%d", time.gmtime(t)), round(float(a), 4)])
    return bars

best = {}  # ticker -> (nbars, bars, srcpath)
for pat in [BASE + "/backtests/**/px_*.json", BASE + "/backtests/**/pxfull_*.json"]:
    for p in glob.glob(pat, recursive=True):
        if p.startswith(HERE):
            continue
        fn = os.path.basename(p)
        t = fn[3:-5] if fn.startswith("px_") else fn[7:-5]
        if t not in missing:
            continue
        try:
            j = json.load(open(p))
            if isinstance(j, dict) and "bars" in j:
                bars = j["bars"]
            elif isinstance(j, dict) and "chart" in j:
                bars = from_payload(j)
            else:
                continue
            if len(bars) > 50 and (t not in best or len(bars) > best[t][0]):
                best[t] = (len(bars), bars, p)
        except Exception:
            continue

n = 0
for t, (nb, bars, p) in best.items():
    out = os.path.join(DATA, f"px_{t}.json")
    if os.path.exists(out):
        continue
    with open(out, "w") as f:
        json.dump({"src": "harvest:" + p.replace(BASE, "~"), "bars": bars}, f)
    n += 1
print(f"harvested {n} tapes", flush=True)
have2 = {fn[3:-5] for fn in os.listdir(DATA) if fn.startswith("px_") and fn.endswith(".json")}
print(f"coverage now {len(have2 & need)}/{len(need)}; still missing {len(need - have2)}", flush=True)
