#!/usr/bin/env python3
"""Finisher for the v10 dividend-growth sweep: computes ONLY the
semiannual and annual DECADE cells (the main sweep.py process was
killed by the host three times mid-run; daily..quarterly cells are
already saved in cells/). Lean memory: EDGAR facts are dropped after
the eligibility pools for these two cadences' 32 selection dates are
built. Engine mechanics are sweep.py's, imported unmodified."""
import importlib.util, gc, json, os, random
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("sweep", os.path.join(HERE, "sweep.py"))
S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)
E = S.E
import bisect

def main():
    ciks = E.get_ciks()
    facts_by_t, filed_idx = {}, {}
    for t in S.UNIVERSE:
        cik = 34088 if t == "XOM" else ciks[t][0]
        facts_by_t[t] = E.get_companyfacts(cik)
        filed_idx[t] = sorted({e[2] for c in
            ("CommonStockDividendsPerShareDeclared",
             "CommonStockDividendsPerShareCashPaid")
            for e in S.dps_entries(facts_by_t[t], c)})
    raw_bars, divs, splits = S.load_raw_market()
    raw_pb = E.PriceBook(raw_bars)
    todo = {}
    for cad in ("semiannual", "annual"):
        if os.path.exists(os.path.join(HERE, "cells", f"{cad}.json")):
            print(f"{cad}: already saved, skip", flush=True)
            continue
        sels = S.cadence_dates(raw_pb.dates, cad, S.DEC_START, S.DEC_END)
        todo[cad] = sels
    elig_cache = {}
    pools_by_cad = {}
    for cad, sels in todo.items():
        pools = {}
        for d in sels:
            ranked = []
            for t in S.UNIVERSE:
                key = (t, bisect.bisect_left(filed_idx[t], d))
                if key not in elig_cache:
                    elig_cache[key] = S.eligibility(facts_by_t[t], d,
                                                    splits.get(t, []))
                res = elig_cache[key]
                if res is not None:
                    ranked.append((t, res[0]))
            ranked.sort(key=lambda kv: (-kv[1], kv[0]))
            pools[d] = ranked
        pools_by_cad[cad] = pools
        print(f"{cad}: pools built for {len(sels)} dates", flush=True)
    del facts_by_t, elig_cache, filed_idx
    gc.collect()
    for cad, sels in todo.items():
        pools = pools_by_cad[cad]
        r = S.run_pot_div(raw_pb, divs, pools, S.DEC_START, S.DEC_END,
                          label=f"DEC {cad}", sel_dates=sels)
        st = S.cell_stats(r, S.DEC_START, S.DEC_END)
        placebo_finals = []
        for seed in S.PLACEBO_SEEDS:
            rng = random.Random(seed)
            pr = S.run_pot_div(raw_pb, divs, pools, S.DEC_START, S.DEC_END,
                               placebo_rng=rng, label=f"PLB {cad} {seed}",
                               sel_dates=sels)
            placebo_finals.append(round(pr["final"], 2))
        beaten = sum(1 for f in placebo_finals if f < r["final"])
        cell = dict(st)
        cell["placebo_finals"] = placebo_finals
        cell["placebo_beaten"] = beaten
        cell["n_selection_dates"] = len(sels)
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump(cell, f, indent=1)
        print(f"{cad}: final=${st['final']:,.2f} CAGR={st['cagr_pct']}% "
              f"maxDD={st['max_dd_pct']}% costs=${st['costs']:,.2f} "
              f"orders={st['orders']} divs=${st['dividends_credited']:,.2f} "
              f"placebo beaten {beaten}/20", flush=True)
    print("FINISHER DONE", flush=True)

if __name__ == "__main__":
    main()
