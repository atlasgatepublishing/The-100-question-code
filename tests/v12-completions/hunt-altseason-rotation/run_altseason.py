#!/usr/bin/env python3
"""Altseason Index rotation — SPEC-FROZEN exact (CONSTRUCTED allocation on published zones).
Monthly rebalance on the 1st; most recent Sunday CMC snapshot <= prior day from the v4 PIT
file; eligible = snapshot top-20 excl. BTC, stablecoins, wrapped BTC, and coins with no price
series in the v4 registry. Index = 100 x share of eligible coins with full 90d history whose
90d return > BTC's 90d return. >=75 -> 100% EW alt basket; <=25 -> 100% BTC; else 50/50.
Costs 0.60%/side on every position change (turnover-charged). Death rule: price series ended
-> last close for 30 days, then ZERO. NATIVE no floor; V9 -15% plain floor on daily closes
(exit all to cash, run stops). Placebos: 20 seeds, zone thresholds shifted in pairs.
(This is the optimized bisect version that produced results.json; an earlier linear-scan
draft timed out and was replaced before any results were taken from it.)"""
import bisect, json, os, random, sys
from datetime import date as _date, timedelta
sys.path.insert(0, "/tmp/hunt1")
from common import *

HERE = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/hunt-altseason-rotation")
V4 = os.path.expanduser("~/workspace/stock-app/backtests/v4")
STABLE_IDS = {825, 3408, 4943, 8536, 4642, 27620, 42046}  # USDT USDC DAI BUSD UST USDe USD1 per v4 registry ids (spec)
STABLE_SYMS = {"USDT", "USDC", "DAI", "BUSD", "UST", "USDE", "USD1", "WBTC"}
BTC = 1

reg = json.load(open(os.path.join(V4, "crypto-basket-pit-results.json")))["registry"]
P = {}
for cid_s, info in reg.items():
    cid = int(cid_s)
    if info["source"] == "excluded": continue
    kind, name = info["source"].split(":", 1)
    fn = {"yahoo": f"y_{name}.json", "binance": f"b_{name}.json", "kraken": f"k_{name}.json"}[kind]
    p = os.path.join(V4, "crypto-basket-pit-data", fn)
    if not os.path.exists(p): continue
    rows = sorted(json.load(open(p)), key=lambda r: r["d"])
    P[cid] = ([r["d"] for r in rows], [r["c"] for r in rows], {r["d"]: r["c"] for r in rows})

def px(cid, d):
    dates, closes, m = P[cid]
    if d in m: return m[d]
    i = bisect.bisect_right(dates, d) - 1
    if i < 0: return None
    if d > dates[-1]:
        gap = (_date.fromisoformat(d) - _date.fromisoformat(dates[-1])).days
        return closes[-1] if gap <= 30 else 0.0
    return closes[i]

def ret90(cid, d):
    dates, closes, m = P[cid]
    d0 = (_date.fromisoformat(d) - timedelta(days=90)).strftime("%Y-%m-%d")
    if dates[0] > d0: return None
    p0 = px(cid, d0); p1 = px(cid, d)
    if not p0 or p1 is None: return None
    return p1 / p0 - 1

snaps = json.load(open(os.path.join(V4, "crypto-basket-pit-data", "snapshots.json")))
snap_dates = sorted(snaps.keys())
def eligible(d):
    i = bisect.bisect_left(snap_dates, d) - 1
    if i < 0: return []
    out = []
    for t in snaps[snap_dates[i]]["top20"]:
        cid = t["cmc_id"]
        if cid == BTC or cid in STABLE_IDS or t["symbol"] in STABLE_SYMS: continue
        if cid not in P: continue
        out.append(cid)
    return out

def compute_index(d, el):
    b = ret90(BTC, d)
    if b is None or not el: return None, 0
    vals = [v for v in (ret90(c, d) for c in el) if v is not None]
    if not vals: return None, 0
    return 100 * sum(1 for v in vals if v > b) / len(vals), len(vals)

all_dates = [d for d in P[BTC][0] if "2016-10-01" <= d <= "2026-11-20"]

def run(alt_line=75.0, btc_line=25.0, house=False, static5050=False, start="2017-01-01", end="2026-11-20"):
    dates = [d for d in all_dates if start <= d <= end]
    hold = {}; cash = START; curve = []; halted = False; idx_log = []
    for d in dates:
        val = cash + sum(u * (px(c, d) or 0.0) for c, u in hold.items())
        if d[8:10] == "01" and not halted:
            el = eligible(d)
            idx, n = compute_index(d, el)
            idx_log.append({"d": d, "index": None if idx is None else round(idx, 1), "n": n})
            if static5050:
                targets = {BTC: 0.5}
                for c in el: targets[c] = 0.5 / len(el) if el else 0
                if not el: targets = {BTC: 1.0}
            elif idx is None: targets = {BTC: 1.0}
            elif idx >= alt_line: targets = {c: 1.0 / len(el) for c in el} if el else {BTC: 1.0}
            elif idx <= btc_line: targets = {BTC: 1.0}
            else:
                targets = {BTC: 0.5}
                for c in el: targets[c] = 0.5 / len(el)
            cur = {}
            for c, u in hold.items():
                p = px(c, d); cur[c] = (u * p / val) if (p and val > 0) else 0.0
            traded = sum(abs(targets.get(c, 0.0) - cur.get(c, 0.0)) for c in set(cur) | set(targets))
            val -= val * traded * CRY_COST
            hold = {}
            for c, w in targets.items():
                p = px(c, d)
                if p and p > 0 and w > 0: hold[c] = (w * val) / p
            cash = val - sum(u * (px(c, d) or 0.0) for c, u in hold.items())
            val = cash + sum(u * (px(c, d) or 0.0) for c, u in hold.items())
        curve.append({"d": d, "eq": round(val, 4)})
        if house and not halted and val <= 85.0:
            halted = True; hold = {}; cash = val
            rest = dates[dates.index(d)+1:]
            curve += [{"d": rd, "eq": round(val, 4)} for rd in rest]
            break
    return {"final": curve[-1]["eq"], "curve": curve, "maxdd": maxdd(curve), "halted": halted, "index_log": idx_log}

out = {"family": "hunt-altseason-rotation",
       "holdings_grid": "NOT-APPLICABLE — allocation/rotation system, no ranked top-N count to vary (spec (c))"}
for wname, (s, e) in {"FULL": ("2017-01-01", "2026-11-20"), "DESIGN": ("2017-01-01", "2022-12-31"), "VALIDATION": ("2023-01-01", "2026-11-20")}.items():
    nat = run(start=s, end=e); hou = run(start=s, end=e, house=True); stat = run(start=s, end=e, static5050=True)
    wb = [{"d": d, "o": c, "c": c} for d, c in zip(P[BTC][0], P[BTC][1]) if s <= d <= e]
    out[wname] = {"native": nat, "house_v9": hou, "static_5050": {"final": stat["final"], "maxdd": stat["maxdd"]},
                  "btc_buyhold": round(buyhold_close(wb), 2), "periods_monthly": period_stats(nat["curve"], "monthly")}
    print(wname, "native", nat["final"], "house", hou["final"], "static", stat["final"], "btchold", out[wname]["btc_buyhold"], flush=True)
pls = {}
for wname, (s, e) in {"FULL": ("2017-01-01", "2026-11-20"), "VALIDATION": ("2023-01-01", "2026-11-20")}.items():
    finals = []
    for sd in range(1, 21):
        rng = random.Random(sd)
        a = rng.uniform(65, 85); b = rng.uniform(15, 35)
        if b >= a: b = a - 10
        finals.append(run(alt_line=a, btc_line=b, start=s, end=e)["final"])
    pls[wname] = {"finals": [round(f, 2) for f in finals], "beaten": sum(1 for f in finals if out[wname]["native"]["final"] > f)}
out["placebos"] = pls
json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
print("placebos beaten:", {k: v["beaten"] for k, v in pls.items()})
