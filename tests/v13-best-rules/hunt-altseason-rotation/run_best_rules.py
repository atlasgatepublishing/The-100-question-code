#!/usr/bin/env python3
"""V13 BEST RULES — hunt-altseason-rotation, BEST-RULES-SPEC.md exact.
Gauge: published Altcoin Season Index on the FULL PIT eligible set (CMC monthly
snapshot top-20 excl. BTC/stables/wrapped, v4 record). Portfolio: 5 largest
eligible by snapshot rank, equal-weight. ONE binary line: index >= 50 -> 100%
top-5 alt basket; index < 50 or not computable -> 100% BTC. Monthly rebalance
(1st). Costs 0.60%/side turnover-charged. NO floor. Death rule: series ended ->
last close 30 days, then ZERO. Placebos: 20 seeds, line ~ U[40,60].
Static reference: 50/50 BTC/top-5 basket, monthly rebalanced, no index."""
import bisect, json, os, random, sys
from datetime import date as _date, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *

HERE = os.path.expanduser("~/workspace/stock-app/backtests/v13-best-rules/hunt-altseason-rotation")
V4 = os.path.expanduser("~/workspace/stock-app/backtests/v4")
STABLE_IDS = {825, 3408, 4943, 8536, 4642, 27620, 42046}
STABLE_SYMS = {"USDT", "USDC", "DAI", "BUSD", "UST", "USDE", "USD1", "WBTC"}
BTC = 1
TOPN = 5

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
    return out  # snapshot order = market-cap rank order

def compute_index(d, el):
    b = ret90(BTC, d)
    if b is None or not el: return None, 0
    vals = [v for v in (ret90(c, d) for c in el) if v is not None]
    if not vals: return None, 0
    return 100 * sum(1 for v in vals if v > b) / len(vals), len(vals)

all_dates = [d for d in P[BTC][0] if "2016-10-01" <= d <= "2026-11-20"]

def run(line=50.0, static5050=False, start="2017-01-01", end="2026-11-20"):
    dates = [d for d in all_dates if start <= d <= end]
    hold = {}; cash = START; curve = []; idx_log = []; trades_cost = 0.0; switches = 0
    prev_state = None
    for d in dates:
        val = cash + sum(u * (px(c, d) or 0.0) for c, u in hold.items())
        if d[8:10] == "01":
            el = eligible(d)
            basket = el[:TOPN]
            idx, n = compute_index(d, el)
            idx_log.append({"d": d, "index": None if idx is None else round(idx, 1), "n": n,
                            "basket": basket})
            if static5050:
                targets = {BTC: 0.5}
                for c in basket: targets[c] = 0.5 / len(basket) if basket else 0
                if not basket: targets = {BTC: 1.0}
                state = "static"
            elif idx is not None and idx >= line and basket:
                targets = {c: 1.0 / len(basket) for c in basket}
                state = "ALT"
            else:
                targets = {BTC: 1.0}
                state = "BTC"
            if prev_state is not None and state != prev_state and not static5050: switches += 1
            prev_state = state
            cur = {}
            for c, u in hold.items():
                p = px(c, d); cur[c] = (u * p / val) if (p and val > 0) else 0.0
            traded = sum(abs(targets.get(c, 0.0) - cur.get(c, 0.0)) for c in set(cur) | set(targets))
            cost_amt = val * traded * CRY_COST
            trades_cost += cost_amt; val -= cost_amt
            hold = {}
            for c, w in targets.items():
                p = px(c, d)
                if p and p > 0 and w > 0: hold[c] = (w * val) / p
            cash = val - sum(u * (px(c, d) or 0.0) for c, u in hold.items())
            val = cash + sum(u * (px(c, d) or 0.0) for c, u in hold.items())
        curve.append({"d": d, "eq": round(val, 4)})
    return {"final": curve[-1]["eq"], "curve": curve, "maxdd": maxdd(curve),
            "costs": round(trades_cost, 2), "switches": switches, "index_log": idx_log}

out = {"family": "hunt-altseason-rotation", "program": "v13-best-rules",
       "spec": "Binary majority line 50; gauge on full eligible top-20 PIT set; portfolio = 5 largest eligible by snapshot rank, EW; monthly; 0.60%/side; NO floor.",
       "published_best_v12_native": {"FULL": 777.56, "DESIGN": 319.93, "VALIDATION": 240.98}}
for wname, (s, e) in {"FULL": ("2017-01-01", "2026-11-20"), "DESIGN": ("2017-01-01", "2022-12-31"),
                      "VALIDATION": ("2023-01-01", "2026-11-20")}.items():
    nat = run(start=s, end=e); stat = run(start=s, end=e, static5050=True)
    wb = [{"d": d, "o": c, "c": c} for d, c in zip(P[BTC][0], P[BTC][1]) if s <= d <= e]
    out[wname] = {"best_rules": nat, "static_5050_top5": {"final": stat["final"], "maxdd": stat["maxdd"], "costs": stat["costs"]},
                  "btc_buyhold": round(buyhold_close(wb), 2),
                  "periods_monthly": period_stats(nat["curve"], "monthly")}
    print(wname, "best", nat["final"], "dd", nat["maxdd"], "static", stat["final"], "btchold", out[wname]["btc_buyhold"],
          "switches", nat["switches"], "costs", nat["costs"], flush=True)
pls = {}
for wname, (s, e) in {"FULL": ("2017-01-01", "2026-11-20"), "VALIDATION": ("2023-01-01", "2026-11-20")}.items():
    finals = []
    for sd in range(1, 21):
        rng = random.Random(sd)
        line = rng.uniform(40, 60)
        finals.append(run(line=line, start=s, end=e)["final"])
    pls[wname] = {"finals": [round(f, 2) for f in finals],
                  "beaten": sum(1 for f in finals if out[wname]["best_rules"]["final"] > f)}
out["placebos"] = pls
json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
print("placebos beaten:", {k: v["beaten"] for k, v in pls.items()})
