#!/usr/bin/env python3
"""V13 best-rules runner — catalog-taa-us-crossasset-momentum.
Rules frozen in BEST-RULES-SPEC.md before this run:
11 risky ETFs; for each asset, cross-score = mean 12m return of the OTHER 10;
hold if cross-score > 0, equal weight; none qualify -> SHY. Monthly, no floor.
Placebos: 20 seeds, same risky count per decision, random names."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine
from engine import (Panel, load_t2, load_etf_json, cadence_days, simulate,
                    period_stats, ROADS_2016, SPY_REF, CHAMP)
from datetime import date

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RISKY = ["SPY", "QQQ", "IWM", "IEFA", "EEM", "VNQ", "DBC", "GLD", "TLT", "AGG", "IEF"]

def build_panel():
    p = Panel(load_t2("SPY"))
    ds, cs = load_t2("SPY"); p.series["SPY"] = cs[:]
    for s in RISKY + ["SHY"]:
        if s in ("SPY", "IEF"): continue
        p.add(s, load_t2(s))
    p.add("IEF", load_etf_json("IEF"))
    return p

def cross_factory(p):
    def fn(i):
        rets = {}
        for s in RISKY:
            r = p.ret(s, i, 252)
            if r is None: return {"SHY": 1.0}
            rets[s] = r
        tot = sum(rets.values())
        picks = []
        for s in RISKY:
            cross = (tot - rets[s]) / (len(RISKY) - 1)
            if cross > 0: picks.append(s)
        if not picks: return {"SHY": 1.0}
        return {s: 1.0 / len(picks) for s in picks}
    return fn

def static_factory():
    return lambda i: {s: 1.0 / len(RISKY) for s in RISKY}

def spy_factory():
    return lambda i: {"SPY": 1.0}

def main():
    p = build_panel()
    ridx = engine.road_indices(p, ROADS_2016)
    dec = cadence_days(p.dates, "monthly")
    out = {"family": "catalog-taa-us-crossasset-momentum", "program": "v13-best-rules",
           "roads": {}, "benchmarks": {}, "curves": {}, "period_stats": {}}
    log = []
    for rname, idx in ridx.items():
        r = simulate(p, idx, dec, cross_factory(p), rulebook="native")
        out["roads"][rname] = {k: r[k] for k in ("final", "max_dd_pct", "costs", "orders", "halts")}
        out["curves"][rname] = r["curve"]
        out["period_stats"][rname] = period_stats(r["curve"], p.dates, "monthly")
        twins = []
        for seed in range(1, 21):
            t = simulate(p, idx, dec, cross_factory(p), rulebook="native", placebo_seed=seed)
            twins.append(t["final"])
        out["roads"][rname]["placebo_finals"] = twins
        out["roads"][rname]["placebos_beaten"] = sum(1 for t in twins if r["final"] > t)
        # benchmarks, same machinery/costs, monthly cadence (single initial buy in practice)
        for bname, fac in (("spy_buyhold", spy_factory()), ("static_mix", static_factory())):
            b = simulate(p, idx, dec, fac, rulebook="native")
            out["benchmarks"][f"{rname}|{bname}"] = {k: b[k] for k in ("final", "max_dd_pct", "costs", "orders")}
        log.append(f"{rname}: final={r['final']} dd={r['max_dd_pct']} costs={r['costs']} "
                   f"orders={r['orders']} placebos_beaten={out['roads'][rname]['placebos_beaten']}/20 "
                   f"spy={out['benchmarks'][rname+'|spy_buyhold']['final']} "
                   f"static={out['benchmarks'][rname+'|static_mix']['final']}")
        print(log[-1], flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as fh:
        json.dump(out, fh, indent=1)
    with open(os.path.join(HERE, "run.log"), "w") as fh:
        fh.write("\n".join(log) + "\n")
    # confirmation trigger check (bars frozen in spec)
    trig = [r for r in out["roads"] if out["roads"][r]["final"] > CHAMP[r]]
    print("CHAMPION-TRIGGERS:", trig, flush=True)
    with open(os.path.join(HERE, "run.log"), "a") as fh:
        fh.write(f"CHAMPION-TRIGGERS: {trig}\n")

if __name__ == "__main__":
    main()
