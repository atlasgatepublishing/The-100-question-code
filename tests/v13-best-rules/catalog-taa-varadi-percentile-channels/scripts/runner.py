#!/usr/bin/env python3
"""V13 best-rules runner — Varadi percentile channels.
Signal EXACTLY as published (v12 pctchan_factory states); sizing changed to
EQUAL weight among composite>=0.5 qualifiers; monthly; NO floor (native
rulebook). Benchmarks: SPY buy-hold, static equal-weight mix. 20-seed
placebos per road. Confirmation machinery pre-registered in spec."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import engine
from engine import (Panel, load_t2, load_etf_json, cadence_days, simulate,
                    period_stats, ROADS_2016, SPY_REF, CHAMP)
import numpy as np

OUT = os.path.dirname(HERE)

def etf_panel():
    p = Panel(load_t2("SPY"))
    ds, cs = load_t2("SPY"); p.series["SPY"] = cs[:]
    for s in ["QQQ", "IWM", "IEFA", "EEM", "VNQ", "DBC", "GLD", "TLT", "AGG", "SHY"]:
        p.add(s, load_t2(s))
    p.add("IEF", load_etf_json("IEF"))
    return p

_pct_cache = {}
def channel_states(p):
    U = ["SPY", "VNQ", "DBC", "AGG"]; LBS = [60, 120, 180, 252]
    key = id(p)
    if key not in _pct_cache:
        states = {}
        for s in U:
            arr = np.array([v if v is not None else np.nan for v in p.series[s]], dtype=float)
            st = {L: np.zeros(len(arr), dtype=int) for L in LBS}
            for L in LBS:
                pos = 0
                for j in range(len(arr)):
                    if j - L + 1 >= 0 and not np.isnan(arr[j]):
                        w = arr[j - L + 1:j + 1]
                        if not np.isnan(w).any():
                            hi = np.quantile(w, 0.75); lo = np.quantile(w, 0.25)
                            if arr[j] > hi: pos = 1
                            elif arr[j] < lo: pos = -1
                    st[L][j] = pos
            states[s] = st
        _pct_cache[key] = states
    return _pct_cache[key]

def best_factory(p):
    U = ["SPY", "VNQ", "DBC", "AGG"]; LBS = [60, 120, 180, 252]
    states = channel_states(p)
    def fn(i):
        keep = []
        for s in U:
            comp = sum(int(states[s][L][i]) for L in LBS) / 4
            if comp >= 0.5: keep.append(s)
        if not keep: return {"SHY": 1.0}
        return {s: 1.0 / len(keep) for s in keep}
    return fn

def spy_factory(p):
    return lambda i: {"SPY": 1.0}

def mix_factory(p):
    U = ["SPY", "VNQ", "DBC", "AGG"]
    return lambda i: {s: 0.25 for s in U}

def main():
    p = etf_panel()
    ridx = engine.road_indices(p, ROADS_2016)
    dec = cadence_days(p.dates, "monthly")
    out = {"family": "catalog-taa-varadi-percentile-channels", "program": "v13-best-rules",
           "roads": {}, "benchmarks": {}, "period_stats": {}, "curves": {}}
    for rname, idx in ridx.items():
        r = simulate(p, idx, dec, best_factory(p), rulebook="native")
        out["roads"][rname] = {k: r[k] for k in ("final", "max_dd_pct", "costs", "orders", "halts")}
        out["curves"][rname] = r["curve"]
        out["period_stats"][rname] = period_stats(r["curve"], p.dates, "monthly")
        engine._placebo_pool = (["SPY", "VNQ", "DBC", "AGG", "SHY"], 3)
        twins = []
        for seed in range(1, 21):
            t = simulate(p, idx, dec, best_factory(p), rulebook="native", placebo_seed=seed)
            twins.append(t["final"])
        out["roads"][rname]["placebo_finals"] = twins
        out["roads"][rname]["placebos_beaten"] = sum(1 for t in twins if r["final"] > t)
        for bname, fac in (("spy_buyhold", spy_factory), ("static_mix_eq", mix_factory)):
            b = simulate(p, idx, dec, fac(p), rulebook="native")
            out["benchmarks"].setdefault(rname, {})[bname] = {
                "final": b["final"], "max_dd_pct": b["max_dd_pct"]}
        print(rname, out["roads"][rname], out["benchmarks"][rname], flush=True)
    out["spy_ref_program"] = SPY_REF; out["champion_vm"] = CHAMP
    # Confirmation trigger check (bars frozen in BEST-RULES-SPEC.md)
    beats = [r for r in out["roads"] if out["roads"][r]["final"] > CHAMP[r]]
    out["roads_beating_champion"] = beats
    if beats:
        conf = {}
        for rname in beats:
            a, b = ROADS_2016[rname]
            # yearly folds
            folds = {}
            for y in range(a.year, b.year + 1):
                idx = [i for i, d in enumerate(p.dates)
                       if d.year == y and a <= d <= b]
                if len(idx) < 20: continue
                fr = simulate(p, idx, dec, best_factory(p), rulebook="native")
                fs = simulate(p, idx, dec, spy_factory(p), rulebook="native")
                folds[str(y)] = {"strategy": fr["final"], "spy": fs["final"]}
            # half windows
            idx = ridx[rname]; mid = idx[len(idx) // 2]
            halves = {}
            for hn, hidx in (("H1", idx[:len(idx)//2]), ("H2", idx[len(idx)//2:])):
                hr = simulate(p, hidx, dec, best_factory(p), rulebook="native")
                hs = simulate(p, hidx, dec, spy_factory(p), rulebook="native")
                halves[hn] = {"strategy": hr["final"], "spy": hs["final"]}
            conf[rname] = {"yearly_folds": folds, "halves": halves}
        out["confirmation"] = conf
    with open(os.path.join(OUT, "results.json"), "w") as fh:
        json.dump(out, fh, indent=1)
    print("DONE beats_champion:", beats)

if __name__ == "__main__":
    main()
