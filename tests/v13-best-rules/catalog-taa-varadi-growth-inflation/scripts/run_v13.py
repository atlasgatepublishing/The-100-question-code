#!/usr/bin/env python3
"""V13 Best-Rules runner — Varadi growth-inflation.
Spec: BEST-RULES-SPEC.md (frozen 2026-11-22T20:06Z before this run).
Published signal EXACTLY as v12 (200d SPY trend; SIEI ratio vs own 200d; regime map).
Chassis: MONTHLY decisions, sizing 75% regime sector / 25% SPY core, NO floor.
Placebos: 20 seeds, random sector from {XLK,XLE,XLP,XLU} at 75% + SPY 25%, same cadence/costs.
Benchmarks beside: SPY buy-and-hold; static EW mix of the 4 holdable sectors (monthly rebalance).
Costs: 0.10%/side + $0.01/sell order (engine standard). $100 pots."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine
from engine import (Panel, load_sector, cadence_days, simulate, period_stats,
                    ROADS, SPY_REF, CHAMP)

OUT = os.path.expanduser("~/workspace/stock-app/backtests/v13-best-rules/catalog-taa-varadi-growth-inflation")
SECTORS4 = ["XLK", "XLE", "XLP", "XLU"]
PUBLISHED = {"LONG": 404.19, "DECADE": 225.06, "CONT": 241.36, "VAL": 161.68}

POS = ["XLE", "XLF", "XLI", "XLB"]; NEG = ["XLP", "XLV", "XLU"]
REGIME_MAP = {("u", "u"): "XLE", ("u", "d"): "XLK", ("d", "u"): "XLP", ("d", "d"): "XLU"}

def siei_ratio(p, i):
    pos = [p.close(s, i) for s in POS]; neg = [p.close(s, i) for s in NEG]
    if any(v is None for v in pos + neg): return None
    return (sum(pos) / len(pos)) / (sum(neg) / len(neg))

def gi_factory(p):
    def fn(i):
        r = siei_ratio(p, i)
        if r is None: return {}
        vals = [siei_ratio(p, j) for j in range(i - 199, i + 1)]
        if any(v is None for v in vals): return {}
        infl_up = r > sum(vals) / 200
        sma = p.sma("SPY", i, 200); c = p.close("SPY", i)
        g = "u" if (sma is not None and c is not None and c > sma) else "d"
        return {REGIME_MAP[(g, "u" if infl_up else "d")]: 1.0}
    return fn

def my_factory(p):
    base = gi_factory(p)
    def fn(i):
        t = base(i)
        if not t: return {}
        sec = next(iter(t))
        if sec == "SPY": return {"SPY": 1.0}
        return {sec: 0.75, "SPY": 0.25}
    return fn

def placebo_target(rng, signal_fn, i):
    pick = rng.choice(SECTORS4)
    return {pick: 0.75, "SPY": 0.25}
engine.placebo_target = placebo_target
engine._placebo_pool = (SECTORS4, 1)

def build_panel():
    p = Panel(load_sector("SPY"))
    ds, cs = load_sector("SPY"); p.series["SPY"] = cs[:]
    for s in ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]:
        p.add(s, load_sector(s))
    return p

def main():
    p = build_panel()
    dec_monthly = cadence_days(p.dates, "monthly")
    ridx = engine.road_indices(p, ROADS)
    out = {"family": "catalog-taa-varadi-growth-inflation", "program": "v13-best-rules",
           "spec_frozen": "2026-11-22T20:06Z", "roads": {}, "curves": {}, "period_stats": {},
           "benchmarks": {}, "published_native": PUBLISHED, "spy_ref": SPY_REF, "champ_vm": CHAMP}
    for rname, idx in ridx.items():
        r = simulate(p, idx, dec_monthly, my_factory(p), rulebook="native")
        entry = {k: r[k] for k in ("final", "max_dd_pct", "costs", "orders", "halts")}
        out["curves"][rname] = r["curve"]
        out["period_stats"][rname] = period_stats(r["curve"], p.dates, "monthly")
        # benchmarks
        spy = simulate(p, idx, {idx[0]}, lambda i: {"SPY": 1.0}, rulebook="native")
        mix = simulate(p, idx, dec_monthly, lambda i: {s: 0.25 for s in SECTORS4}, rulebook="native")
        out["benchmarks"][rname] = {
            "spy_buyhold": {"final": spy["final"], "max_dd_pct": spy["max_dd_pct"], "costs": spy["costs"]},
            "static_mix_ew4": {"final": mix["final"], "max_dd_pct": mix["max_dd_pct"], "costs": mix["costs"]}}
        # placebos (native rulebook = my chassis has no floor)
        twins = []
        for seed in range(1, 21):
            t = simulate(p, idx, dec_monthly, my_factory(p), rulebook="native", placebo_seed=seed)
            twins.append(t["final"])
        entry["placebo_finals"] = twins
        entry["placebos_beaten"] = sum(1 for t in twins if r["final"] > t)
        out["roads"][rname] = entry
        print(rname, entry["final"], "DD", entry["max_dd_pct"], "placebos", entry["placebos_beaten"],
              "| SPYbh", spy["final"], "| mix", mix["final"], flush=True)
    with open(os.path.join(OUT, "results.json"), "w") as fh:
        json.dump(out, fh, indent=1)
    print("DONE")

if __name__ == "__main__":
    main()
