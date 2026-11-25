#!/usr/bin/env python3
"""Difficulty Ribbon Compression — frozen construction (SPEC-FROZEN.md).
Ribbon = SMAs of daily BTC difficulty at 9,14,25,40,60,90,128,200 days;
compression = stdev(SMAs)/mean(SMAs). DRC-BUY-ZONE (CONSTRUCTED switch):
long exactly while compression < 0.05. Costs 0.60%/side, price = CoinMetrics
PriceUSD. NATIVE no floor; V9 = -15% plain floor, daily-close check, run stops.
Difficulty: blockchain.com Charts API (protocol data, never restated).
Windows: FULL / DESIGN / VALIDATION per spec. Bar = BTC buy-hold net of
one buy + one sell at 0.60%. Placebos: 20 seeds threshold U[0.03,0.08];
plus inverted control (long while compression >= 0.05), reported once."""
import json, os, statistics, sys, urllib.request
sys.path.insert(0, "/tmp/hs2")
from common import period_stats, max_dd, END

HERE = os.path.dirname(os.path.abspath(__file__))
COST = 0.006

def fetch_all():
    dp = os.path.join(HERE, "difficulty.json"); pp = os.path.join(HERE, "cm_price.json")
    if not os.path.exists(dp):
        # NOTE (bug found & fixed during run, documented): timespan=all returns
        # ~4-day SAMPLED points, which corrupts the ribbon. 2-year chunks return
        # true daily points; difficulty is fetched in chunks and merged.
        import time as _t2
        merged = {}
        for y0 in range(2009, 2027, 2):
            start_ts = int(_t2.mktime(_t2.strptime(f"{y0}-01-01", "%Y-%m-%d")))
            u = f"https://api.blockchain.info/charts/difficulty?timespan=2years&start={start_ts}&format=json"
            j = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=90).read())
            for v in j["values"]: merged[v["x"]] = v["y"]
        blob = json.dumps({"values": [{"x": k, "y": merged[k]} for k in sorted(merged)]}).encode()
        open(dp, "wb").write(blob)
    if not os.path.exists(pp):
        rows = {}; url = ("https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
                          "?assets=btc&metrics=PriceUSD&frequency=1d&page_size=10000&start_time=2010-01-01")
        while url:
            j = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=90).read())
            for r in j["data"]: rows[r["time"][:10]] = float(r["PriceUSD"])
            url = j.get("next_page_url")
        json.dump(rows, open(pp, "w"))
    diff = json.load(open(dp))["values"]
    dmap = {}
    import time as _t
    for v in diff: dmap[_t.strftime("%Y-%m-%d", _t.gmtime(v["x"]))] = v["y"]
    price = json.load(open(pp))
    dates = sorted(d for d in price if d in dmap)
    return dates, [price[d] for d in dates], [dmap[d] for d in dates]

def run_state(dates, prices, state, start, end, floor=False):
    idx = [i for i, d in enumerate(dates) if start <= d <= end]
    if not idx: return None
    eq = 100.0; curve = []; prev = 0; ep = 100.0; dead = False; trades = 0
    for k, i in enumerate(idx):
        if k > 0 and prev == 1: eq *= prices[i] / prices[idx[k-1]]
        des = 0 if dead else state[i]
        if des != prev:
            eq *= (1 - COST)
            if des == 0: trades += 1
            prev = des
        if floor and prev == 1 and eq < 0.85 * ep:
            eq *= (1 - COST); prev = 0; trades += 1; dead = True
        curve.append((dates[i], round(eq, 4)))
    if prev == 1:
        eq *= (1 - COST); curve[-1] = (curve[-1][0], round(eq, 4))
    return {"final": round(eq, 2), "curve": curve, "trades": trades}

def bh(dates, prices, start, end):
    idx = [i for i, d in enumerate(dates) if start <= d <= end]
    fin = 100 * (1 - COST) * prices[idx[-1]] / prices[idx[0]] * (1 - COST)
    curve = [(dates[i], round(100 * (1 - COST) * prices[i] / prices[idx[0]], 4)) for i in idx]
    curve[-1] = (curve[-1][0], round(fin, 4))
    return {"final": round(fin, 2), "curve": curve}

def main():
    dates, prices, diffs = fetch_all()
    W = [9, 14, 25, 40, 60, 90, 128, 200]
    smas = []
    for w in W:
        s = [None]*len(diffs); run = 0.0
        for i, v in enumerate(diffs):
            run += v
            if i >= w: run -= diffs[i-w]
            if i >= w-1: s[i] = run/w
        smas.append(s)
    comp = [None]*len(diffs)
    for i in range(len(diffs)):
        vals = [s[i] for s in smas]
        if all(v is not None for v in vals):
            m = statistics.mean(vals)
            comp[i] = statistics.pstdev(vals)/m if m else None
    first = next(dates[i] for i in range(len(dates)) if comp[i] is not None)
    res = {"family": "hunt-difficulty-ribbon", "first_computable": first,
           "windows": {"FULL": (first, END), "DESIGN": (first, "2022-12-31"), "VALIDATION": ("2023-01-01", END)}}
    def state_for(thr, invert=False):
        st = []
        for i in range(len(dates)):
            if comp[i] is None: st.append(0)
            else: st.append((1 if comp[i] >= thr else 0) if invert else (1 if comp[i] < thr else 0))
        return st
    st = state_for(0.05)
    curves = {}
    for wname, (s, e) in res["windows"].items():
        nat = run_state(dates, prices, st, s, e, floor=False)
        v9 = run_state(dates, prices, st, s, e, floor=True)
        b = bh(dates, prices, s, e)
        inv = run_state(dates, prices, state_for(0.05, invert=True), s, e, floor=False)
        res[wname] = {"native_final": nat["final"], "v9_final": v9["final"], "buyhold_final": b["final"],
                      "inverted_final": inv["final"], "trades": nat["trades"], "maxdd_pct": max_dd(nat["curve"]),
                      "days_long": sum(1 for i, d in enumerate(dates) if s <= d <= e and st[i] == 1),
                      "periods_monthly_native": period_stats(nat["curve"], "monthly")}
        curves[wname] = nat["curve"]
    res["curves"] = curves
    import random
    pl = {}
    for wname in ["FULL", "VALIDATION"]:
        s, e = res["windows"][wname]; finals = []
        for seed in range(1, 21):
            rng = random.Random(seed * 5 + len(wname))
            thr = rng.uniform(0.03, 0.08)
            finals.append(run_state(dates, prices, state_for(thr), s, e, floor=False)["final"])
        pl[wname] = {"median": round(statistics.median(finals), 2),
                     "n_beaten_by_native": sum(1 for f in finals if res[wname]["native_final"] > f), "finals": finals}
    res["placebos"] = pl
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print({w: res[w] for w in ["FULL", "DESIGN", "VALIDATION"]}); print(pl)

if __name__ == "__main__": main()
