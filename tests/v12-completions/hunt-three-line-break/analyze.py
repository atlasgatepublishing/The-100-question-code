#!/usr/bin/env python3
"""Extract aggregates for RESULTS.md from results.json (read-only analysis)."""
import json, os, statistics
HERE = os.path.dirname(os.path.abspath(__file__))
R = json.load(open(os.path.join(HERE, "results.json")))

spy = R["stocks"]["SPY"]
print("== SPY ==")
for road, ent in spy["roads"].items():
    for rules in ("native", "v9"):
        e = ent[rules]
        print(road, rules, "final", e["final"], "DD", e["max_dd_pct"], "costs", e["costs"],
              "orders", e["orders"], "halts", e["halts"], "inv%", e["invested_pct"],
              "placebos_beaten", e["placebos_beaten"], "/20",
              "pl_med", round(statistics.median(e["placebo_finals"]), 2),
              "pl_range", round(min(e["placebo_finals"]), 2), round(max(e["placebo_finals"]), 2))
    print("   buyhold_own", ent["buyhold_own_plumbing"], "spy_ref", ent["spy_reference_program"], "champ", ent["champion_vm"])
print("SPY monthly period stats:")
for road, ent in spy["roads"].items():
    for rules in ("native", "v9"):
        print(" ", road, rules, ent[rules]["period_stats_monthly"])
print("SPY year folds (native / v9 / buyhold):")
for y, f in spy["year_folds"].items():
    print(" ", y, f["native"], f["v9"], f["buyhold"])

pond = R["stocks"]["pond"]
print("\n== POND == n =", len(pond))
for road in ("LONG", "DECADE", "CONT", "VAL"):
    for rules in ("native", "v9"):
        finals = [p["roads"][road][rules] for p in pond.values() if road in p["roads"]]
        holds = [p["roads"][road]["buyhold"] for p in pond.values() if road in p["roads"]]
        beat = sum(1 for p in pond.values() if road in p["roads"] and p["roads"][road][rules] > p["roads"][road]["buyhold"])
        print(road, rules, "median", round(statistics.median(finals), 2), "mean", round(statistics.mean(finals), 2),
              "best", max(finals), "worst", min(finals), "beat_own_hold", f"{beat}/{len(finals)}",
              "median_hold", round(statistics.median(holds), 2))
print("pond pooled placebos:")
for k, v in R["stocks"]["pond_pooled_placebos"].items():
    beaten = sum(1 for x in v["placebo_means"] if v["real_mean"] > x)
    print(" ", k, "real_mean", v["real_mean"], "pl_means median", round(statistics.median(v["placebo_means"]), 2),
          "range", min(v["placebo_means"]), max(v["placebo_means"]), "seeds_beaten", f"{beaten}/20", "n", v["n_names"])
# best/worst pond names LONG native
ranked = sorted(pond.items(), key=lambda kv: kv[1]["roads"]["LONG"]["native"], reverse=True)
print("pond LONG native top5:", [(s, p["roads"]["LONG"]["native"], p["roads"]["LONG"]["buyhold"]) for s, p in ranked[:5]])
print("pond LONG native bot5:", [(s, p["roads"]["LONG"]["native"], p["roads"]["LONG"]["buyhold"]) for s, p in ranked[-5:]])

coins = R["coins"]["ran"]
print("\n== COINS == ran", len(coins), "excluded", len(R["coins"]["excluded"]), "btc_hold", R["coins"]["btc_hold"])
print("excluded:", R["coins"]["excluded"])
dead = [s for s, e in coins.items() if e["dead_series"]]
print("dead_series coins:", dead)
for wname in ("FULL", "RECENT"):
    for rules in ("native", "v9"):
        finals, holds, btcwin, ownwin = [], [], 0, 0
        btch = R["coins"]["btc_hold"][wname]
        for s, e in coins.items():
            w = e["windows"].get(wname)
            if not w: continue
            finals.append(w[rules]["final"]); holds.append(w["buyhold"])
            if btch is not None and w[rules]["final"] > btch: btcwin += 1
            if w[rules]["final"] > w["buyhold"]: ownwin += 1
        print(wname, rules, "median", round(statistics.median(finals), 2), "mean", round(statistics.mean(finals), 2),
              "best", max(finals), "worst", min(finals), "beat_own_hold", f"{ownwin}/{len(finals)}",
              "beat_BTC_hold", f"{btcwin}/{len(finals)}", "median_hold", round(statistics.median(holds), 2))
print("coin pooled placebos:")
for k, v in R["coins"]["pooled_placebos"].items():
    beaten = sum(1 for x in v["placebo_means"] if v["real_mean"] > x)
    print(" ", k, "real_mean", v["real_mean"], "real_median", v["real_median"],
          "pl_mean median", round(statistics.median(v["placebo_means"]), 2), "seeds_beaten", f"{beaten}/20", "n", v["n_coins"])
btc = coins.get("BTC")
if btc:
    print("BTC windows:")
    for wname, w in btc["windows"].items():
        if not w: continue
        for rules in ("native", "v9"):
            e = w[rules]
            print(" ", wname, rules, "final", e["final"], "DD", e["max_dd_pct"], "orders", e["orders"],
                  "halts", e["halts"], "inv%", e["invested_pct"], "hold", w["buyhold"])
            if "period_stats_monthly" in e: print("    monthly:", e["period_stats_monthly"])
eth = coins.get("ETH")
if eth:
    print("ETH windows:")
    for wname, w in eth["windows"].items():
        if not w: continue
        for rules in ("native", "v9"):
            e = w[rules]
            print(" ", wname, rules, "final", e["final"], "DD", e["max_dd_pct"], "orders", e["orders"], "hold", w["buyhold"])
# top/bottom coins FULL native
fr = [(s, e["windows"]["FULL"]["native"]["final"], e["windows"]["FULL"]["buyhold"]) for s, e in coins.items() if e["windows"].get("FULL")]
fr.sort(key=lambda x: x[1], reverse=True)
print("coins FULL native top5:", fr[:5])
print("coins FULL native bot5:", fr[-5:])
