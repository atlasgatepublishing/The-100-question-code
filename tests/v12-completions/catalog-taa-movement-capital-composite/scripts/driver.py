#!/usr/bin/env python3
"""Main-run driver for Slice-7 families. Usage: driver.py <slug> <family-key>"""
import sys, os, json, random
sys.path.insert(0, "/tmp/slice7")
import pandas as pd
from engine import simulate, period_stats, month_ends, ROADS
import families as F
from pragmatic import make_pragmatic

BASE = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions")

STATELESS = {
    "mama": (F.mama, "random", F.mama_placebo),
    "papa": (F.papa, "random", F.papa_placebo),
    "tacbond": (F.tacbond, "random", F.tacbond_placebo),
    "movement": (F.movement, "shuffle", None),
    "spycomp": (F.spycomp, "shuffle", None),
    "bondcomp": (F.bondcomp, "shuffle", None),
    "bondui1": (F.bondui1, "shuffle", None),
}

def decisions_of(fn):
    mes = month_ends("2009-01-01", "2026-11-20")
    return {d: fn(d, None) for d in mes}

def run_family(slug, key):
    folder = os.path.join(BASE, slug)
    os.makedirs(os.path.join(folder, "data"), exist_ok=True)
    if key == "pragmatic":
        def factory():
            p = make_pragmatic()
            for d in month_ends("2009-01-01", "2009-12-31"): p(d, None)
            return p
        native_factory = factory
        placebo_kind = "shuffle"
        dec = decisions_of(factory())
    else:
        fn, placebo_kind, pfn = STATELESS[key]
        native_factory = lambda fn=fn: fn
        dec = decisions_of(fn) if placebo_kind == "shuffle" else None
    out = {}
    for road, (st, en) in ROADS.items():
        res = {}
        for form, hf in (("native", False), ("house", True)):
            eq, info = simulate(st, en, native_factory(), house=hf)
            res[form] = {"final": round(info["final"], 2), "halts": info["halts"], "periods": period_stats(eq)}
            if road == "CONT":
                res[form]["curve"] = {str(k.date()): round(float(v), 4) for k, v in eq.items()}
        finals = []
        for seed in range(20):
            rng = random.Random(1000 + seed)
            if placebo_kind == "random":
                pfn = STATELESS[key][2]
                eq, info = simulate(st, en, pfn, house=False, rng=rng)
            else:
                keys = list(dec.keys()); vals = [dec[k] for k in keys]
                rng.shuffle(vals)
                mp = dict(zip(keys, vals))
                eq, info = simulate(st, en, lambda d, rng=None, mp=mp: mp.get(d, {}), house=False)
            finals.append(round(info["final"], 2))
        finals.sort()
        res["placebo"] = {"median": finals[10], "p90": finals[17], "max": finals[-1], "min": finals[0],
                          "native_beats_of_20": int(sum(1 for f in finals if res["native"]["final"] > f))}
        out[road] = res
        print(slug, road, "native", res["native"]["final"], "house", res["house"]["final"],
              "placebo_med", res["placebo"]["median"], "beats", res["placebo"]["native_beats_of_20"], flush=True)
    json.dump(out, open(os.path.join(folder, "results.json"), "w"), indent=1)
    print("WROTE", slug)

if __name__ == "__main__":
    run_family(sys.argv[1], sys.argv[2])
