#!/usr/bin/env python3
"""Chunked driver for run_pond.py (environment kills long processes;
each invocation builds/loads a pickle cache and runs ONE bounded chunk,
merging into ../results_pond.json).

Usage:
  chunk_runner.py build
  chunk_runner.py buffer <slot|set> <rules_csv> <roads_csv> <counts_csv>
  chunk_runner.py composite <rules_csv> <roads_csv> <counts_csv>
  chunk_runner.py twosleeve <rules_csv> <roads_csv> <counts_csv>
Counts csv uses grid labels: 1,2,3,5,8,10,15,20,30,ALL
"""
import json, os, random, sys, time
import run_pond as RP

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache.json")
OUT = os.path.join(HERE, "..", "results_pond.json")
SEEDS = RP.SEEDS

def build():
    t0 = time.time()
    _pb4, equity_rows, shares_rows = RP.V5.build_inputs()
    EQF = {t: RP.FastPIT(equity_rows[t]) for t in RP.UNIVERSE}
    SHF = {t: RP.FastPIT(shares_rows[t]) for t in RP.UNIVERSE}
    ciks = RP.E.get_ciks(); overrides = {"XOM": 34088}
    INCF, OCFF = {}, {}
    for t in RP.UNIVERSE:
        cik = overrides.get(t, ciks[t][0]); facts = RP.E.get_companyfacts(cik)
        INCF[t] = RP.FastPIT(RP.V9C.pit_series_income(facts))
        OCFF[t] = RP.FastPIT(RP.V9C.pit_series_ocf(facts))
        del facts
    fb = RP.build_book()
    didx = {t: {b["d"]: i for i, b in enumerate(fb.bars[t])} for t in RP.UNIVERSE}
    sel_by_road = {n: RP.E.quarter_selection_dates(fb, ws, we) for n, (ws, we) in RP.ROADS.items()}
    all_sel = sorted({d for v in sel_by_road.values() for d in v})
    champ_orders, comp_orders, val_orders, mom_orders = {}, {}, {}, {}
    for d in all_sel:
        sc = {}; scc = {}
        for t in RP.UNIVERSE:
            be = EQF[t].pit(d); so = SHF[t].pit(d)
            if be is None or so is None: continue
            b = fb.bar(t, d)
            if b is None: continue
            px = b["c"]
            if so[2] <= 0 or be[2] is None: continue
            mcap = so[2] * px
            if mcap <= 0: continue
            bl = fb.bars[t]; di = didx[t].get(d)
            if di is None or di < 253: continue
            mom = bl[di - 21]["c"] / bl[di - 252]["c"] - 1.0
            bm = be[2] / mcap
            sc[t] = (bm, mom)
            ni = INCF[t].pit(d); ocf = OCFF[t].pit(d)
            if ni is not None and ocf is not None:
                scc[t] = (bm, ni[2] / mcap, ocf[2] / mcap, mom)
        if len(sc) >= 5:
            vr = RP.E.percentile_ranks({t: v[0] for t, v in sc.items()})
            mr = RP.E.percentile_ranks({t: v[1] for t, v in sc.items()})
            comb = {t: (vr[t] + mr[t]) / 2.0 for t in sc}
            champ_orders[d] = (sorted(comb, key=lambda t: -comb[t]), sorted(sc))
            val_orders[d] = (sorted(sc, key=lambda t: -vr[t]), sorted(sc))
            mom_orders[d] = (sorted(sc, key=lambda t: -mr[t]), sorted(sc))
        if len(scc) >= 5:
            rb = RP.E.percentile_ranks({t: v[0] for t, v in scc.items()})
            re_ = RP.E.percentile_ranks({t: v[1] for t, v in scc.items()})
            rc = RP.E.percentile_ranks({t: v[2] for t, v in scc.items()})
            mr2 = RP.E.percentile_ranks({t: v[3] for t, v in scc.items()})
            vs = {t: (rb[t] + re_[t] + rc[t]) / 3.0 for t in scc}
            comb2 = {t: (vs[t] + mr2[t]) / 2.0 for t in scc}
            comp_orders[d] = (sorted(comb2, key=lambda t: -comb2[t]), sorted(scc))
    spy = {}
    for n, (ws, we) in RP.ROADS.items():
        s, _ = RP.E.spy_net(fb, ws, we, RP.START_CASH); spy[n] = round(s, 2)
    with open(CACHE, "w") as f:
        json.dump({"bars": fb.bars, "sel_by_road": sel_by_road, "champ": champ_orders,
                   "comp": comp_orders, "val": val_orders, "mom": mom_orders,
                   "spy": spy}, f)
    print(f"cache built ({time.time()-t0:.0f}s) champ_dates={len(champ_orders)} comp_dates={len(comp_orders)}", flush=True)

def load_cache():
    with open(CACHE) as f: raw = json.load(f)
    raw["fb"] = RP.FastBook(raw.pop("bars"))
    # JSON turns order tuples into lists — run_* index them, lists are fine
    return raw

def merge(path_keys, value):
    data = {}
    if os.path.exists(OUT):
        data = json.load(open(OUT))
    node = data
    for k in path_keys[:-1]:
        node = node.setdefault(k, {})
    node[path_keys[-1]] = value
    with open(OUT, "w") as f: json.dump(data, f, indent=1)

def parse_counts(csv):
    return [("ALL" if x == "ALL" else int(x)) for x in csv.split(",")]

def run_plain_chunk(fam_keys, orders, picker, rules_list, roads, counts, C):
    fb = C["fb"]
    for rname in roads:
        ws, we = RP.ROADS[rname]; sel = C["sel_by_road"][rname]
        cells = {}
        if os.path.exists(OUT):
            try:
                node = json.load(open(OUT))
                for k in fam_keys: node = node[k]
                cells = node[rname]["cells"]
            except Exception: cells = {}
        for cnt in counts:
            RP.CUR[0] = cnt
            for rules in rules_list:
                r = RP.run_rules(fb, orders, sel, ws, we, picker, rules)
                twins = []
                for seed in SEEDS:
                    prng = random.Random(seed)
                    twins.append(round(RP.run_rules(fb, orders, sel, ws, we, picker, rules, rng=prng)["final"], 2))
                st = RP.cell_stats(r); st["placebo_finals"] = twins
                st["placebos_beaten"] = sum(1 for x in twins if st["final"] > x)
                cells[f"{cnt}|{rules}"] = st
                print(f"{fam_keys} {rname} n={cnt} {rules}: ${st['final']} beat {st['placebos_beaten']}/20", flush=True)
        merge(fam_keys + [rname], {"window": [ws, we], "spy": C["spy"][rname], "cells": cells})

def main():
    a = sys.argv[1]
    if a == "build":
        build(); return
    C = load_cache()
    if a == "buffer":
        form = sys.argv[2]; rules = sys.argv[3].split(","); roads = sys.argv[4].split(","); counts = parse_counts(sys.argv[5])
        run_plain_chunk(["vm-buffer", form], C["champ"], RP.make_buffer(form), rules, roads, counts, C)
    elif a == "composite":
        rules = sys.argv[2].split(","); roads = sys.argv[3].split(","); counts = parse_counts(sys.argv[4])
        run_plain_chunk(["vm-composite"], C["comp"], RP.pick_plain, rules, roads, counts, C)
    elif a == "twosleeve":
        rules = sys.argv[2].split(","); roads = sys.argv[3].split(","); counts = parse_counts(sys.argv[4])
        fb = C["fb"]
        for rname in roads:
            ws, we = RP.ROADS[rname]; sel = C["sel_by_road"][rname]
            cells = {}
            if os.path.exists(OUT):
                try:
                    node = json.load(open(OUT))["vm-twosleeve-house"]
                    cells = node[rname]["cells"]
                except Exception: cells = {}
            for k in counts:
                for rule in rules:
                    r = RP.ts_rules(fb, C["val"], C["mom"], sel, ws, we, k, rule)
                    twins = []
                    for seed in SEEDS:
                        prng = random.Random(seed)
                        twins.append(round(RP.ts_rules(fb, C["val"], C["mom"], sel, ws, we, k, rule, rng=prng)["final"], 2))
                    st = RP.cell_stats(r); st["placebo_finals"] = twins
                    st["placebos_beaten"] = sum(1 for x in twins if st["final"] > x)
                    cells[f"{k}|{rule}"] = st
                    print(f"twosleeve {rname} k={k} {rule}: ${st['final']} beat {st['placebos_beaten']}/20", flush=True)
            merge(["vm-twosleeve-house", rname], {"window": [ws, we], "spy": C["spy"][rname], "cells": cells})
    print("chunk done", flush=True)

if __name__ == "__main__":
    main()
