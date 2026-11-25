#!/usr/bin/env python3
"""Second-Chance grid for Slice-7 families. Usage: grid.py <slug> <key>
Cells: cadence (rebalance every 1/3/6/12 months) x rulebook (native/house)
on DECADE + CONT; holdings counts (selection families) monthly x rulebook
on DECADE + CONT, with 10-seed random-twin placebo medians on native cells.
Crypto: NOT-APPLICABLE for all Slice-7 families (asset-class ETF rotation
incl. Treasury/macro sleeves; no coin form of the published universes) —
recorded in RESULTS.md, not forced."""
import sys, os, json, random
sys.path.insert(0, "/tmp/slice7")
import pandas as pd
from engine import simulate, period_stats, ROADS
import families as F
from pragmatic import make_pragmatic

BASE = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions")
GROADS = ("DECADE", "CONT")

def cell(fn, road, house, reb=1):
    st, en = ROADS[road]
    eq, info = simulate(st, en, fn, house=house, rebalance_months=reb)
    return round(info["final"], 2)

def run(slug, key):
    folder = os.path.join(BASE, slug, "grid"); os.makedirs(folder, exist_ok=True)
    out = {"roads": list(GROADS), "cadence_cells": {}, "holdings_cells": {}}
    if key in ("mama", "papa", "tacbond"):
        scores = {"mama": F.mama_scores, "papa": F.papa_scores, "tacbond": F.tb_scores}[key]
        native_n = 3
        if key == "tacbond":
            def mk(n):
                def fn(date, rng=None):
                    s = scores(date); bil = F.ret_months("BIL", date, 6)
                    if not s or bil is None: return {}
                    top = sorted(s, key=s.get, reverse=True)[:n]
                    return {t: 1.0 / n for t in top if s[t] > 0 and s[t] > bil}
                return fn
            def mkp(n):
                def fn(date, rng=None):
                    s = scores(date); bil = F.ret_months("BIL", date, 6)
                    if not s or bil is None: return {}
                    picks = rng.sample(sorted(s), min(n, len(s)))
                    return {t: 1.0 / n for t in picks if s[t] > 0 and s[t] > bil}
                return fn
        else:
            def mk(n):
                return F.make_topn(scores, n)
            def mkp(n):
                return F.make_topn_placebo(scores, n)
        nat = mk(native_n)
        for reb, lab in ((1, "monthly"), (3, "quarterly"), (6, "semiannual"), (12, "annual")):
            for form, hf in (("native", False), ("house", True)):
                out["cadence_cells"][f"{lab}|{form}"] = {r: cell(nat, r, hf, reb) for r in GROADS}
        for n in (1, 2, 3, 5, 8, 99):
            lab = "ALL" if n == 99 else str(n)
            fn = mk(10**6) if n == 99 else mk(n)
            row = {}
            for form, hf in (("native", False), ("house", True)):
                row[form] = {r: cell(fn, r, hf, 1) for r in GROADS}
            if n != 99:
                pfn = mkp(n); med = {}
                for r in GROADS:
                    fs = []
                    for seed in range(10):
                        rng = random.Random(5000 + seed)
                        st, en = ROADS[r]
                        eq, info = simulate(st, en, pfn, house=False, rng=rng)
                        fs.append(info["final"])
                    fs.sort(); med[r] = round(fs[5], 2)
                row["placebo_median_10seed"] = med
            out["holdings_cells"][lab] = row
    elif key == "pragmatic":
        def factory():
            p = make_pragmatic()
            from engine import month_ends
            for d in month_ends("2009-01-01", "2009-12-31"): p(d, None)
            return p
        for form, hf in (("native", False), ("house", True)):
            out["cadence_cells"][f"quarterly-tranched|{form}"] = {r: cell(factory(), r, hf, 1) for r in GROADS}
        out["holdings_cells"] = {"note": "NOT-APPLICABLE — fixed 2-of-3 selection per tranche is the published form; holdings dimension is the tranche structure itself (see untranched variant in RESULTS)."}
    else:
        fn = {"movement": F.movement, "spycomp": F.spycomp, "bondcomp": F.bondcomp, "bondui1": F.bondui1}[key]
        for reb, lab in ((1, "monthly"), (3, "quarterly"), (6, "semiannual"), (12, "annual")):
            for form, hf in (("native", False), ("house", True)):
                out["cadence_cells"][f"{lab}|{form}"] = {r: cell(fn, r, hf, reb) for r in GROADS}
        out["holdings_cells"] = {"note": "NOT-APPLICABLE — fixed published allocations (no ranked top-N selection)."}
    json.dump(out, open(os.path.join(folder, "results.json"), "w"), indent=1)
    print("GRID WROTE", slug, flush=True)

if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2])
