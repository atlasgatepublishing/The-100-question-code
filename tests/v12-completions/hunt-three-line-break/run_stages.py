#!/usr/bin/env python3
"""Staged runner for run_tlb.py's engine (checkpointed partial JSONs).
Usage: python3 run_stages.py <stage>  — stages: spy, pond, ppl_long, ppl_val,
coins, cpl_full, cpl_recent, merge."""
import json, os, sys, random, statistics
import run_tlb as R

HERE = os.path.dirname(os.path.abspath(__file__))

def dump(name, obj):
    with open(os.path.join(HERE, name), "w") as f:
        json.dump(obj, f)
    print("wrote", name, flush=True)

def load(name):
    return json.load(open(os.path.join(HERE, name)))

def stage_spy():
    dates, opens, closes = R.load_stock("SPY")
    desired, nlines, nb, ns = R.tlb_desired(closes)
    spy = {"n_lines_full_series": nlines, "buy_signals": nb, "sell_signals": ns, "roads": {}}
    for road, (s, e) in R.ROADS.items():
        i0, i1 = R.idx_range(dates, s, e)
        ent = {}
        for rules, house in (("native", False), ("v9", True)):
            r = R.simulate(dates, opens, closes, desired, i0, i1, R.STK_COST, R.STK_FEE, house)
            pl = R.placebo_finals(dates, opens, closes, desired, i0, i1, R.STK_COST, R.STK_FEE, house)
            ent[rules] = {**{k: r[k] for k in ("final", "max_dd_pct", "costs", "orders", "halts", "invested_pct")},
                          "placebo_finals": pl,
                          "placebos_beaten": sum(1 for x in pl if r["final"] > x),
                          "period_stats_monthly": R.period_stats(r["equity_curve"]),
                          "equity_curve": r["equity_curve"], "trades": r["trades"]}
        ent["buyhold_own_plumbing"] = R.buyhold(dates, closes, i0, i1, R.STK_COST, R.STK_FEE)
        ent["spy_reference_program"] = R.SPYREF[road]
        ent["champion_vm"] = R.CHAMP[road]
        spy["roads"][road] = ent
    folds = {}
    for y in range(2010, 2027):
        i0, i1 = R.idx_range(dates, f"{y}-01-01", f"{y}-12-31")
        if i0 is None: continue
        folds[str(y)] = {rules: R.simulate(dates, opens, closes, desired, i0, i1, R.STK_COST, R.STK_FEE, house)["final"]
                         for rules, house in (("native", False), ("v9", True))}
        folds[str(y)]["buyhold"] = R.buyhold(dates, closes, i0, i1, R.STK_COST, R.STK_FEE)
    spy["year_folds"] = folds
    dump("stage_spy.json", spy)

def pond_syms():
    return sorted(fn[len("pxfull_"):-len(".json")] for fn in os.listdir(R.PXDIR)
                  if fn.startswith("pxfull_") and fn != "pxfull_SPY.json")

def stage_pond():
    pond = {}
    for sym in pond_syms():
        ld = R.load_stock(sym)
        if ld is None: continue
        d2, o2, c2 = ld
        des2, nl2, nb2, ns2 = R.tlb_desired(c2)
        ent = {"n_lines": nl2, "buy_signals": nb2, "sell_signals": ns2, "roads": {}}
        for road, (s, e) in R.ROADS.items():
            i0, i1 = R.idx_range(d2, s, e)
            if i0 is None: continue
            ent["roads"][road] = {
                rules: R.simulate(d2, o2, c2, des2, i0, i1, R.STK_COST, R.STK_FEE, house)["final"]
                for rules, house in (("native", False), ("v9", True))}
            ent["roads"][road]["buyhold"] = R.buyhold(d2, c2, i0, i1, R.STK_COST, R.STK_FEE)
        pond[sym] = ent
    dump("stage_pond.json", pond)

def stage_ppl(road):
    pond = load("stage_pond.json")
    s, e = R.ROADS[road]
    out = {}
    cache = {}
    for rules, house in (("native", False), ("v9", True)):
        reals = []; seed_finals = [[] for _ in range(20)]
        for sym in pond_syms():
            if sym not in pond: continue
            if sym not in cache:
                ld = R.load_stock(sym)
                if ld is None: continue
                d2, o2, c2 = ld
                des2, _, _, _ = R.tlb_desired(c2)
                cache[sym] = (d2, o2, c2, des2)
            d2, o2, c2, des2 = cache[sym]
            i0, i1 = R.idx_range(d2, s, e)
            if i0 is None: continue
            reals.append(pond[sym]["roads"][road][rules])
            seg = des2[i0:i1 + 1]; L = len(seg)
            for sd in range(20):
                rng = random.Random(7700 + sd)
                k = rng.randrange(1, L) if L > 1 else 0
                full = list(des2[:i0]) + seg[k:] + seg[:k] + list(des2[i1 + 1:])
                seed_finals[sd].append(R.simulate(d2, o2, c2, full, i0, i1, R.STK_COST, R.STK_FEE, house, light=True)["final"])
        out[f"{road}_{rules}"] = {"real_mean": round(statistics.mean(reals), 2) if reals else None,
                                  "placebo_means": [round(statistics.mean(x), 2) for x in seed_finals],
                                  "n_names": len(reals)}
    dump(f"stage_ppl_{road.lower()}.json", out)

def coin_universe():
    snap = json.load(open(os.path.join(R.CBASE, "snapshots.json")))
    u = set()
    for v in snap.values():
        for en in v["top20"]: u.add(en["symbol"])
    return sorted(u)

def stage_coins():
    coins = {}; excluded = {}
    for sym in coin_universe():
        if sym in R.COIN_NO_DATA:
            excluded[sym] = "NO-FREE-SERIES (v4 registry: no usable free daily series)"
            continue
        ld = R.load_coin(sym)
        if ld is None:
            excluded[sym] = "NO-FREE-SERIES (cache missing or <30 usable bars)"
            continue
        d2, o2, c2 = ld
        des2, nl2, nb2, ns2 = R.tlb_desired(c2)
        dead = d2[-1] < "2026-05-24"
        ent = {"first": d2[0], "last": d2[-1], "bars": len(d2), "n_lines": nl2,
               "buy_signals": nb2, "sell_signals": ns2, "dead_series": dead, "windows": {}}
        for wname, (s, e) in (("FULL", ("2015-01-01", R.COIN_END)), ("RECENT", ("2023-01-01", R.COIN_END))):
            i0, i1 = R.idx_range(d2, s, e)
            if i0 is None or i1 - i0 < 30:
                ent["windows"][wname] = None; continue
            w = {}
            for rules, house in (("native", False), ("v9", True)):
                r = R.simulate(d2, o2, c2, des2, i0, i1, R.COIN_COST, 0.0, house)
                w[rules] = {k: r[k] for k in ("final", "max_dd_pct", "costs", "orders", "halts", "invested_pct")}
                w[rules]["trades"] = r["trades"]
                if sym in ("BTC", "ETH"):
                    w[rules]["equity_curve"] = r["equity_curve"]
                    w[rules]["period_stats_monthly"] = R.period_stats(r["equity_curve"])
            if dead:
                for rules in ("native", "v9"):
                    tr = w[rules]["trades"]
                    if tr and tr[-1][1] == "SELL-END":
                        gross = tr[-1][3]
                        net = gross - gross * R.COIN_COST
                        w[rules]["final"] = round(w[rules]["final"] - net, 2)
                        w[rules]["dead_zero_applied"] = True
            w["buyhold"] = 0.0 if dead else R.buyhold(d2, c2, i0, i1, R.COIN_COST, 0.0)
            ent["windows"][wname] = w
        coins[sym] = ent
    dump("stage_coins.json", {"ran": coins, "excluded": excluded, "universe_size": len(coin_universe())})

def stage_cpl(wname):
    coins = load("stage_coins.json")["ran"]
    s, e = ("2015-01-01", R.COIN_END) if wname == "FULL" else ("2023-01-01", R.COIN_END)
    out = {}
    cache = {}
    for rules, house in (("native", False), ("v9", True)):
        reals = []; seed_lists = [[] for _ in range(20)]
        for sym, ent in coins.items():
            if not ent["windows"].get(wname): continue
            if sym not in cache:
                ld = R.load_coin(sym); d2, o2, c2 = ld
                des2, _, _, _ = R.tlb_desired(c2)
                cache[sym] = (d2, o2, c2, des2)
            d2, o2, c2, des2 = cache[sym]
            i0, i1 = R.idx_range(d2, s, e)
            reals.append(ent["windows"][wname][rules]["final"])
            seg = des2[i0:i1 + 1]; L = len(seg)
            for sd in range(20):
                rng = random.Random(9900 + sd)
                k = rng.randrange(1, L) if L > 1 else 0
                full = list(des2[:i0]) + seg[k:] + seg[:k] + list(des2[i1 + 1:])
                seed_lists[sd].append(R.simulate(d2, o2, c2, full, i0, i1, R.COIN_COST, 0.0, house, light=True)["final"])
        out[f"{wname}_{rules}"] = {"real_mean": round(statistics.mean(reals), 2) if reals else None,
                                   "real_median": round(statistics.median(reals), 2) if reals else None,
                                   "placebo_means": [round(statistics.mean(x), 2) for x in seed_lists],
                                   "n_coins": len(reals)}
    dump(f"stage_cpl_{wname.lower()}.json", out)

def stage_merge():
    out = {"family": "hunt-three-line-break", "disposition": "HUNT-FOUND (deep-hunt-nonus)",
           "form": "Three-Line Break, Nison 1994 published rules frozen literally; at-close execution; sizing CONSTRUCTED program standard",
           "stock_costs": "0.10%/side + $0.01 sell fee", "coin_costs": "0.60%/side (stated rate; band 0.40-0.80)",
           "champions": R.CHAMP, "spy_reference": R.SPYREF, "stocks": {}, "coins": {}}
    out["stocks"]["SPY"] = load("stage_spy.json")
    out["stocks"]["pond"] = load("stage_pond.json")
    ppl = {}
    ppl.update(load("stage_ppl_long.json")); ppl.update(load("stage_ppl_val.json"))
    out["stocks"]["pond_pooled_placebos"] = ppl
    cj = load("stage_coins.json")
    out["coins"]["universe_size"] = cj["universe_size"]
    out["coins"]["ran"] = cj["ran"]
    out["coins"]["excluded"] = cj["excluded"]
    btc = cj["ran"].get("BTC", {}).get("windows", {})
    out["coins"]["btc_hold"] = {w: (btc[w]["buyhold"] if btc.get(w) else None) for w in ("FULL", "RECENT")}
    cpl = {}
    cpl.update(load("stage_cpl_full.json")); cpl.update(load("stage_cpl_recent.json"))
    out["coins"]["pooled_placebos"] = cpl
    dump("results.json", out)

if __name__ == "__main__":
    st = sys.argv[1]
    {"spy": stage_spy, "pond": stage_pond, "coins": stage_coins, "merge": stage_merge,
     "ppl_long": lambda: stage_ppl("LONG"), "ppl_val": lambda: stage_ppl("VAL"),
     "cpl_full": lambda: stage_cpl("FULL"), "cpl_recent": lambda: stage_cpl("RECENT")}[st]()
    print("stage", st, "complete", flush=True)
