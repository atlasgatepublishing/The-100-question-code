#!/usr/bin/env python3
"""V13 Best-Rules run for catalog-taa-vitral-multiasset-momentum.

My rules (BEST-RULES-SPEC.md, frozen before this script): single 12-month
return ranking over the 10-asset risk-on pond, top-3 equal weight, per-slot
absolute filter (12m return > 0) with defensive cascade IEF-if-rising else
SHY. Monthly, no floor, program costs. Published (v12-constructed) Vitral
form re-run in the same engine/data as comparator. Benchmarks: SPY buy-hold,
static equal-weight 10, 60/40 SPY/IEF. Placebos: 20 seeds random rotation.
"""
import json, math, os, sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import engine
from engine import (Panel, load_t2, load_etf_json, cadence_days, simulate,
                    period_stats, ROADS_2016, SPY_REF, CHAMP)
import numpy as np

OUT = os.path.dirname(HERE)

RISK_ON = ["SPY", "QQQ", "IWM", "IEFA", "EEM", "VNQ", "DBC", "GLD", "TLT", "AGG"]
SHELF = RISK_ON + ["IEF", "SHY"]


def etf_panel():
    p = Panel(load_t2("SPY"))
    for s in ["QQQ", "IWM", "IEFA", "EEM", "VNQ", "DBC", "GLD", "TLT", "AGG", "SHY"]:
        p.add(s, load_t2(s))
    ds, cs = load_t2("SPY")
    p.series["SPY"] = cs[:]
    p.add("IEF", load_etf_json("IEF"))
    return p


# ---- published-form machinery (copied from the v12 runner, unchanged) ----
_corr_cache = {}

def corr_matrix(p, i, syms, n=126):
    key = (p.dates[i].year, p.dates[i].month, tuple(syms))
    if key in _corr_cache:
        return _corr_cache[key]
    if i - n < 0:
        return None
    arr = []
    for s in syms:
        w = p.series[s][i - n:i + 1]
        if any(v is None for v in w):
            return None
        arr.append([w[k + 1] / w[k] - 1 for k in range(n)])
    m = np.corrcoef(np.array(arr))
    _corr_cache[key] = m
    return m


def vitral_factory(p, count=5):
    U = RISK_ON
    def score(i):
        m = corr_matrix(p, i, U)
        if m is None:
            return None
        sig = {s: [] for s in U}
        for s in U:
            for n in (63, 126, 252):
                r = p.ret(s, i, n)
                if r is None:
                    return None
                sig[s].append(r)
                v = p.vol(s, i, n)
                sig[s].append(r / (v * math.sqrt(n)) if v else 0.0)
            for n in (50, 100, 200):
                sma = p.sma(s, i, n)
                c = p.close(s, i)
                if sma is None:
                    return None
                sig[s].append(1.0 if c > sma else 0.0)
        ranks = {s: [] for s in U}
        for k in range(9):
            vals = sorted((sig[s][k], s) for s in U)
            for pos, (_, s) in enumerate(vals):
                ranks[s].append(pos / (len(U) - 1))
        out = {}
        for a, s in enumerate(U):
            avgc = sum(m[a][b] for b in range(len(U)) if b != a) / (len(U) - 1)
            out[s] = (sum(ranks[s]) / 9) / (1 + max(avgc, 0))
        return out
    def fn(i):
        sc = score(i)
        if sc is None:
            return {}
        top = sorted(sc, key=sc.get, reverse=True)[:count]
        w = {}
        for s in top:
            if p.ret(s, i, 252) is not None and p.ret(s, i, 252) < 0:
                ro = max(["IEF", "SHY"], key=lambda x: (p.ret(x, i, 63) or -9))
                if (p.ret(ro, i, 63) or -9) < 0:
                    ro = "SHY"
                w[ro] = w.get(ro, 0.0) + 1.0 / count
            else:
                w[s] = w.get(s, 0.0) + 1.0 / count
        return w
    return fn


# ---- MY RULES ----
def simple_factory(p, count=3):
    def fn(i):
        scored = []
        for s in RISK_ON:
            r = p.ret(s, i, 252)
            if r is None:
                return {}
            scored.append((r, s))
        scored.sort(reverse=True)
        # defensive cascade decided once per decision date
        rief = p.ret("IEF", i, 252)
        refuge = "IEF" if (rief is not None and rief > 0) else "SHY"
        w = {}
        for r, s in scored[:count]:
            tgt = s if r > 0 else refuge
            w[tgt] = w.get(tgt, 0.0) + 1.0 / count
        return w
    return fn


def spy_factory(p):
    return lambda i: {"SPY": 1.0}

def static_factory(p):
    return lambda i: {s: 1.0 / len(RISK_ON) for s in RISK_ON}

def mix6040_factory(p):
    return lambda i: {"SPY": 0.6, "IEF": 0.4}


def days_between_highs(curve):
    peak = -1.0
    since = 0
    longest = 0
    for _, e in curve:
        if e >= peak:
            peak = e
            longest = max(longest, since)
            since = 0
        else:
            since += 1
    return max(longest, since)


def run_on(p, idx, dec, factory, rulebook="native", placebo_seed=None):
    return simulate(p, idx, dec, factory(p), rulebook=rulebook,
                    placebo_seed=placebo_seed)


def main():
    p = etf_panel()
    ridx = engine.road_indices(p, ROADS_2016)
    dec = cadence_days(p.dates, "monthly")
    out = {"family": "catalog-taa-vitral-multiasset-momentum",
           "program": "v13-best-rules", "roads": {}, "curves": {},
           "period_stats": {}, "benchmarks": {}, "confirmation": None}

    forms = {
        "mine": (simple_factory, (SHELF, 3)),
        "published": (vitral_factory, (RISK_ON, 5)),
    }
    benches = {"spy_buyhold": spy_factory, "static_ew10": static_factory,
               "mix_60_40": mix6040_factory}

    for rname, idx in ridx.items():
        out["benchmarks"][rname] = {}
        for bname, bf in benches.items():
            r = run_on(p, idx, dec, bf)
            out["benchmarks"][rname][bname] = {
                "final": r["final"], "max_dd_pct": r["max_dd_pct"],
                "costs": r["costs"], "orders": r["orders"]}
        for fname, (factory, pool) in forms.items():
            r = run_on(p, idx, dec, factory)
            entry = {"final": r["final"], "max_dd_pct": r["max_dd_pct"],
                     "costs": r["costs"], "orders": r["orders"],
                     "halts": r["halts"]}
            engine._placebo_pool = pool
            twins = []
            for seed in range(1, 21):
                t = run_on(p, idx, dec, factory, placebo_seed=seed)
                twins.append(t["final"])
            entry["placebo_finals"] = twins
            entry["placebos_beaten"] = sum(1 for t in twins if r["final"] > t)
            out["roads"][f"{rname}|{fname}"] = entry
            out["curves"][f"{rname}|{fname}"] = r["curve"]
            ps = period_stats(r["curve"], p.dates, "monthly")
            ps["longest_below_high_days"] = days_between_highs(r["curve"])
            out["period_stats"][f"{rname}|{fname}"] = ps
            print(rname, fname, entry["final"], "DD", entry["max_dd_pct"],
                  "placebos", entry["placebos_beaten"], "/20", flush=True)

    # ---- Terry's confirmation rule: only if a road beats champion V+M ----
    triggered = [rn for rn in ridx
                 if out["roads"][f"{rn}|mine"]["final"] > CHAMP[rn]]
    if triggered:
        conf = {}
        for rn in triggered:
            idx = ridx[rn]
            folds = {}
            for yr in range(2017, 2026):
                fidx = [i for i in idx if p.dates[i].year == yr]
                if len(fidx) < 20:
                    continue
                mine = run_on(p, fidx, dec, simple_factory)["final"]
                spy = run_on(p, fidx, dec, spy_factory)["final"]
                folds[str(yr)] = {"mine": mine, "spy": spy, "beat_spy": mine > spy}
            mid = idx[len(idx) // 2]
            halves = {}
            for hn, hidx in (("first", [i for i in idx if i < mid]),
                             ("second", [i for i in idx if i >= mid])):
                mine = run_on(p, hidx, dec, simple_factory)["final"]
                spy = run_on(p, hidx, dec, spy_factory)["final"]
                halves[hn] = {"mine": mine, "spy": spy, "beat_spy": mine > spy}
            folds_won = sum(1 for f in folds.values() if f["beat_spy"])
            conf[rn] = {"yearly_folds": folds, "half_windows": halves,
                        "folds_beat_spy": folds_won, "folds_total": len(folds),
                        "both_halves_beat_spy": all(h["beat_spy"] for h in halves.values()),
                        "confirmed": folds_won > len(folds) / 2 and all(
                            h["beat_spy"] for h in halves.values())}
        out["confirmation"] = conf
        print("CONFIRMATION TRIGGERED:", json.dumps(conf, indent=1), flush=True)
    else:
        print("No road beat the champion; confirmation not triggered.", flush=True)

    with open(os.path.join(OUT, "results.json"), "w") as fh:
        json.dump(out, fh, indent=1)
    print("WROTE results.json")


if __name__ == "__main__":
    main()
