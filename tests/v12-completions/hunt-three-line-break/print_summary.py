#!/usr/bin/env python3
"""Compute everything and print a compact summary JSON to stdout (no curves)."""
import json, os, sys, random, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_tlb as R
import run_stages as S

out = {}
# SPY
dates, opens, closes = R.load_stock("SPY")
desired, nlines, nb, ns = R.tlb_desired(closes)
spy = {"n_lines": nlines, "buys": nb, "sells": ns, "roads": {}}
for road, (s, e) in R.ROADS.items():
    i0, i1 = R.idx_range(dates, s, e)
    ent = {}
    for rules, house in (("native", False), ("v9", True)):
        r = R.simulate(dates, opens, closes, desired, i0, i1, R.STK_COST, R.STK_FEE, house)
        pl = R.placebo_finals(dates, opens, closes, desired, i0, i1, R.STK_COST, R.STK_FEE, house)
        ent[rules] = {"final": r["final"], "dd": r["max_dd_pct"], "costs": r["costs"],
                      "orders": r["orders"], "halts": r["halts"], "inv": r["invested_pct"],
                      "beaten": sum(1 for x in pl if r["final"] > x),
                      "pl_med": round(statistics.median(pl), 2),
                      "pl_min": min(pl), "pl_max": max(pl),
                      "monthly": R.period_stats(r["equity_curve"])}
    ent["hold"] = R.buyhold(dates, closes, i0, i1, R.STK_COST, R.STK_FEE)
    spy["roads"][road] = ent
folds = {}
for y in range(2010, 2027):
    i0, i1 = R.idx_range(dates, f"{y}-01-01", f"{y}-12-31")
    if i0 is None: continue
    folds[str(y)] = [R.simulate(dates, opens, closes, desired, i0, i1, R.STK_COST, R.STK_FEE, h, light=True)["final"]
                     for h in (False, True)] + [R.buyhold(dates, closes, i0, i1, R.STK_COST, R.STK_FEE)]
spy["folds"] = folds
out["spy"] = spy
print("PART1 " + json.dumps(out), flush=True)

# POND
pond = {}
cache = {}
for sym in S.pond_syms():
    ld = R.load_stock(sym)
    if ld is None: continue
    d2, o2, c2 = ld
    des2, nl2, nb2, ns2 = R.tlb_desired(c2)
    cache[sym] = (d2, o2, c2, des2)
    ent = {"roads": {}}
    for road, (s, e) in R.ROADS.items():
        i0, i1 = R.idx_range(d2, s, e)
        if i0 is None: continue
        ent["roads"][road] = [R.simulate(d2, o2, c2, des2, i0, i1, R.STK_COST, R.STK_FEE, h, light=True)["final"]
                              for h in (False, True)] + [R.buyhold(d2, c2, i0, i1, R.STK_COST, R.STK_FEE)]
    pond[sym] = ent
agg = {"n": len(pond)}
for road in ("LONG", "DECADE", "CONT", "VAL"):
    for ri, rules in ((0, "native"), (1, "v9")):
        finals = [p["roads"][road][ri] for p in pond.values() if road in p["roads"]]
        holds = [p["roads"][road][2] for p in pond.values() if road in p["roads"]]
        beat = sum(1 for p in pond.values() if road in p["roads"] and p["roads"][road][ri] > p["roads"][road][2])
        agg[f"{road}_{rules}"] = {"median": round(statistics.median(finals), 2),
                                  "mean": round(statistics.mean(finals), 2),
                                  "best": max(finals), "worst": min(finals),
                                  "beat_hold": beat, "of": len(finals),
                                  "median_hold": round(statistics.median(holds), 2)}
ranked = sorted(pond.items(), key=lambda kv: kv[1]["roads"]["LONG"][0], reverse=True)
agg["top5_long_native"] = [(s, p["roads"]["LONG"][0], p["roads"]["LONG"][2]) for s, p in ranked[:5]]
agg["bot5_long_native"] = [(s, p["roads"]["LONG"][0], p["roads"]["LONG"][2]) for s, p in ranked[-5:]]
agg["per_name_long"] = {s: p["roads"]["LONG"] for s, p in pond.items()}
out2 = {"pond_agg": agg}
# pond pooled placebos
ppl = {}
for road in ("LONG", "VAL"):
    s, e = R.ROADS[road]
    for rules, house in (("native", False), ("v9", True)):
        reals = []; seed_means = []
        seed_lists = [[] for _ in range(20)]
        for sym, (d2, o2, c2, des2) in cache.items():
            i0, i1 = R.idx_range(d2, s, e)
            if i0 is None: continue
            reals.append(pond[sym]["roads"][road][0 if not house else 1])
            seg = des2[i0:i1 + 1]; L = len(seg)
            for sd in range(20):
                rng = random.Random(7700 + sd)
                k = rng.randrange(1, L) if L > 1 else 0
                full = list(des2[:i0]) + seg[k:] + seg[:k] + list(des2[i1 + 1:])
                seed_lists[sd].append(R.simulate(d2, o2, c2, full, i0, i1, R.STK_COST, R.STK_FEE, house, light=True)["final"])
        seed_means = [round(statistics.mean(x), 2) for x in seed_lists]
        ppl[f"{road}_{rules}"] = {"real_mean": round(statistics.mean(reals), 2),
                                  "pl_med": round(statistics.median(seed_means), 2),
                                  "pl_min": min(seed_means), "pl_max": max(seed_means),
                                  "beaten": sum(1 for x in seed_means if statistics.mean(reals) > x)}
out2["pond_pooled_placebos"] = ppl
print("PART2 " + json.dumps(out2), flush=True)

# COINS
coins = {}; excluded = {}; ccache = {}
for sym in S.coin_universe():
    if sym in R.COIN_NO_DATA:
        excluded[sym] = "NO-FREE-SERIES"; continue
    ld = R.load_coin(sym)
    if ld is None:
        excluded[sym] = "NO-FREE-SERIES"; continue
    d2, o2, c2 = ld
    des2, nl2, nb2, ns2 = R.tlb_desired(c2)
    ccache[sym] = (d2, o2, c2, des2)
    dead = d2[-1] < "2026-05-24"
    ent = {"first": d2[0], "last": d2[-1], "dead": dead, "windows": {}}
    for wname, (s, e) in (("FULL", ("2015-01-01", R.COIN_END)), ("RECENT", ("2023-01-01", R.COIN_END))):
        i0, i1 = R.idx_range(d2, s, e)
        if i0 is None or i1 - i0 < 30:
            ent["windows"][wname] = None; continue
        w = {}
        for rules, house in (("native", False), ("v9", True)):
            r = R.simulate(d2, o2, c2, des2, i0, i1, R.COIN_COST, 0.0, house)
            fin = r["final"]
            if dead and r["trades"] and r["trades"][-1][1] == "SELL-END":
                gross = r["trades"][-1][3]
                fin = round(fin - (gross - gross * R.COIN_COST), 2)
            w[rules] = {"final": fin, "dd": r["max_dd_pct"], "orders": r["orders"],
                        "halts": r["halts"], "inv": r["invested_pct"]}
            if sym in ("BTC", "ETH"):
                w[rules]["monthly"] = R.period_stats(r["equity_curve"])
        w["hold"] = 0.0 if dead else R.buyhold(d2, c2, i0, i1, R.COIN_COST, 0.0)
        ent["windows"][wname] = w
    coins[sym] = ent
cagg = {"ran": len(coins), "excluded": excluded,
        "dead": [s for s, e in coins.items() if e["dead"]],
        "btc_hold": {w: coins["BTC"]["windows"][w]["hold"] for w in ("FULL", "RECENT")}}
for wname in ("FULL", "RECENT"):
    for rules in ("native", "v9"):
        finals, ownwin, btcwin = [], 0, 0
        btch = cagg["btc_hold"][wname]
        for s2, e2 in coins.items():
            w = e2["windows"].get(wname)
            if not w: continue
            finals.append(w[rules]["final"])
            if w[rules]["final"] > w["hold"]: ownwin += 1
            if w[rules]["final"] > btch: btcwin += 1
        cagg[f"{wname}_{rules}"] = {"median": round(statistics.median(finals), 2),
                                    "mean": round(statistics.mean(finals), 2),
                                    "best": max(finals), "worst": min(finals),
                                    "beat_own": ownwin, "beat_btc": btcwin, "of": len(finals)}
cagg["btc"] = coins["BTC"]; cagg["eth"] = coins["ETH"]
fr = [(s, e["windows"]["FULL"]["native"]["final"], e["windows"]["FULL"]["hold"]) for s, e in coins.items() if e["windows"].get("FULL")]
fr.sort(key=lambda x: x[1], reverse=True)
cagg["top5_full_native"] = fr[:5]; cagg["bot5_full_native"] = fr[-5:]
cagg["per_coin_full"] = {s: [e["windows"]["FULL"]["native"]["final"], e["windows"]["FULL"]["v9"]["final"], e["windows"]["FULL"]["hold"]]
                         for s, e in coins.items() if e["windows"].get("FULL")}
cagg["per_coin_recent"] = {s: [e["windows"]["RECENT"]["native"]["final"], e["windows"]["RECENT"]["v9"]["final"], e["windows"]["RECENT"]["hold"]]
                           for s, e in coins.items() if e["windows"].get("RECENT")}
out3 = {"coin_agg": cagg}
cpl = {}
for wname, (s, e) in (("FULL", ("2015-01-01", R.COIN_END)), ("RECENT", ("2023-01-01", R.COIN_END))):
    for rules, house in (("native", False), ("v9", True)):
        reals = []; seed_lists = [[] for _ in range(20)]
        for sym, ent in coins.items():
            if not ent["windows"].get(wname): continue
            d2, o2, c2, des2 = ccache[sym]
            i0, i1 = R.idx_range(d2, s, e)
            reals.append(ent["windows"][wname][rules]["final"])
            seg = des2[i0:i1 + 1]; L = len(seg)
            for sd in range(20):
                rng = random.Random(9900 + sd)
                k = rng.randrange(1, L) if L > 1 else 0
                full = list(des2[:i0]) + seg[k:] + seg[:k] + list(des2[i1 + 1:])
                seed_lists[sd].append(R.simulate(d2, o2, c2, full, i0, i1, R.COIN_COST, 0.0, house, light=True)["final"])
        seed_means = [round(statistics.mean(x), 2) for x in seed_lists]
        cpl[f"{wname}_{rules}"] = {"real_mean": round(statistics.mean(reals), 2),
                                   "real_median": round(statistics.median(reals), 2),
                                   "pl_mean_med": round(statistics.median(seed_means), 2),
                                   "beaten": sum(1 for x in seed_means if statistics.mean(reals) > x)}
out3["coin_pooled_placebos"] = cpl
print("PART3 " + json.dumps(out3), flush=True)
print("SUMMARY COMPLETE", flush=True)
