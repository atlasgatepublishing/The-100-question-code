#!/usr/bin/env python3
"""Staged runner for run_wyckoff (exec wall-clock limits force staging;
logic lives entirely in run_wyckoff.py / JUDGMENT-SPEC.md).
Modes: scan0 | scan1 | real | placebo_<ROAD> | merge"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_wyckoff as rw

HERE = os.path.dirname(os.path.abspath(__file__))

class Light:
    """Series subset simulate() needs (no candidate-scan arrays)."""
    def __init__(self, bars):
        self.bars = bars
        self.dates = [b["d"] for b in bars]
        self.idx = {b["d"]: i for i, b in enumerate(bars)}
        self.c = [b["c"] for b in bars]
        self.v = [b["v"] for b in bars]
        n = len(bars)
        pv = [0.0] * (n + 1)
        for i in range(n):
            pv[i + 1] = pv[i] + self.v[i]
        self.avg50v = [None] * n
        for i in range(n):
            if i >= 50:
                self.avg50v[i] = (pv[i] - pv[i - 50]) / 50

def load_full(tickers):
    out = {}
    for t in tickers:
        bars = rw.load_bars(t)
        if bars and len(bars) >= 400:
            out[t] = rw.Series(bars)
    return out

def load_light(tickers):
    out = {}
    for t in tickers:
        bars = rw.load_bars(t)
        if bars and len(bars) >= 400:
            out[t] = Light(bars)
    return out

def mode_scan(half):
    tickers = rw.lr.POOL[half::2]
    full = load_full(tickers + (["SPY"] if "SPY" not in tickers else []))
    spy = full.get("SPY") or rw.Series(rw.load_bars("SPY"))
    cands = {}
    used = {}
    for t, s in full.items():
        if t == "SPY":
            continue
        cd = {}
        for i in range(len(s.bars)):
            c = rw.find_candidate(s, spy, i)
            if c is not None:
                key = (t, c["sos_idx"])
                if used.get(key):
                    continue
                used[key] = True
                cd[s.bars[i]["d"]] = {"range_high": c["range_high"],
                                     "range_low": c["range_low"],
                                     "stop": c["stop"], "target": c["target"],
                                     "t7_margin": c["t7_margin"]}
        if cd:
            cands[t] = cd
        print(t, len(cd), flush=True)
    with open(os.path.join(HERE, f"cands_part{half}.json"), "w") as f:
        json.dump(cands, f)
    print("scan done", half, sum(len(v) for v in cands.values()), flush=True)

def merged_cands():
    cands = {}
    for half in (0, 1):
        with open(os.path.join(HERE, f"cands_part{half}.json")) as f:
            cands.update(json.load(f))
    return cands

def mode_real():
    cands = merged_cands()
    tickers = sorted(cands.keys())
    full = load_full(tickers + ["SPY"])
    spy = full["SPY"]
    results = {"label": "JUDGMENT-CONSTRUCTED: our frozen reconstruction of "
                        "the author's documented decision-making; not the "
                        "author's own trading.",
               "universe_size": len(rw.lr.POOL), "roads": {}}
    for name, (start, end) in rw.ROADS.items():
        days = [d for d in spy.dates if d <= end]
        r = rw.simulate(days, full, cands, start, end, spy)
        spy_days = [d for d in spy.dates if start <= d <= end]
        s0 = spy.c[spy.idx[spy_days[0]]]
        s1 = spy.c[spy.idx[spy_days[-1]]]
        spy_final = round(100 * (s1 / s0) * (1 - 0.001) - 0.01 * (s1 / s0), 2)
        results["roads"][name] = {
            "start": start, "end": end, "final": r["final"],
            "costs": r["costs"], "orders": r["orders"], "halted": r["halted"],
            "max_dd_pct": r["max_dd_pct"], "n_entries": len(r["entries"]),
            "spy_final_same_chassis": spy_final,
            "curve": r["curve"],
            "entries": r["entries"],
            "trades": [[d, t, sd, round(px, 4), round(v, 2), w]
                       for d, t, sd, px, v, w in r["trades"]]}
        print(name, r["final"], "entries", len(r["entries"]), flush=True)
    with open(os.path.join(HERE, "real.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("real done", flush=True)

def mode_placebo(road):
    with open(os.path.join(HERE, "real.json")) as f:
        real = json.load(f)
    # entries saved as [date, stop_frac, target_frac]
    entries = [(e[0], e[1], e[2]) for e in real["roads"][road]["entries"]]
    light = load_light(list(rw.lr.POOL) + ["SPY"])
    spy = light["SPY"]
    start, end = rw.ROADS[road]
    days = [d for d in spy.dates if d <= end]
    finals = []
    for seed in range(20):
        pr = rw.simulate(days, light, {}, start, end, spy,
                         placebo_seed=seed, real_entries=entries)
        finals.append(pr["final"])
        print(road, seed, pr["final"], flush=True)
    with open(os.path.join(HERE, f"placebo_{road}.json"), "w") as f:
        json.dump({"road": road, "placebo_finals": finals}, f)
    print("placebo done", road, flush=True)

def mode_merge():
    with open(os.path.join(HERE, "real.json")) as f:
        res = json.load(f)
    for road in rw.ROADS:
        with open(os.path.join(HERE, f"placebo_{road}.json")) as f:
            p = json.load(f)
        r = res["roads"][road]
        r["placebo_finals"] = p["placebo_finals"]
        r["placebo_beaten"] = sum(1 for x in p["placebo_finals"]
                                  if r["final"] > x)
        del r["entries"]
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(res, f, indent=1)
    print("merged", flush=True)

if __name__ == "__main__":
    mode = sys.argv[1]
    if mode.startswith("scan"):
        mode_scan(int(mode[-1]))
    elif mode == "real":
        mode_real()
    elif mode.startswith("placebo_"):
        mode_placebo(mode.split("_", 1)[1])
    elif mode == "merge":
        mode_merge()
