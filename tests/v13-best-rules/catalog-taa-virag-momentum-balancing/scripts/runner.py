#!/usr/bin/env python3
"""V13 best-rules runner — Virag MBB. Spec frozen in BEST-RULES-SPEC.md
(md5 4d0e58e0d080c255b392bcff7a5dfaec) before this run.
Forms: best (composite 3/6/12 avg-return rank, top-4 EW, abs filter>0 -> SHY,
monthly, NO floor), published (single 12m rank, same chassis), static EW10
control, SPY buy-hold. 20-seed placebos for best form. Confirmation
(yearly folds + half-windows vs SPY) auto-runs only if a road beats V+M."""
import json, os, sys
from datetime import date
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine
from engine import (Panel, load_t2, cadence_days, simulate, period_stats,
                    ROADS_2016, SPY_REF, CHAMP)

OUT = os.path.expanduser("~/workspace/stock-app/backtests/v13-best-rules/catalog-taa-virag-momentum-balancing")
U = ["SPY", "QQQ", "IWM", "IEFA", "EEM", "VNQ", "DBC", "GLD", "AGG", "TLT"]

def build_panel():
    p = Panel(load_t2("SPY"))
    ds, cs = load_t2("SPY"); p.series["SPY"] = cs[:]
    for s in U[1:] + ["SHY"]:
        p.add(s, load_t2(s))
    return p

def best_factory(p, count=4):
    def fn(i):
        scored = []
        for s in U:
            rs = [p.ret(s, i, n) for n in (63, 126, 252)]
            if any(r is None for r in rs): return {}
            scored.append((sum(rs) / 3.0, s))
        scored.sort(reverse=True)
        w = {}
        for r, s in scored[:count]:
            tgt = s if r > 0 else "SHY"
            w[tgt] = w.get(tgt, 0.0) + 1.0 / count
        return w
    return fn

def published_factory(p, count=4):
    def fn(i):
        scored = [(p.ret(s, i, 252), s) for s in U]
        if any(r is None for r, _ in scored): return {}
        scored.sort(reverse=True)
        w = {}
        for r, s in scored[:count]:
            tgt = s if r > 0 else "SHY"
            w[tgt] = w.get(tgt, 0.0) + 1.0 / count
        return w
    return fn

def static_factory(p):
    def fn(i):
        if p.ret("SPY", i, 252) is None: return {}
        return {s: 0.1 for s in U}
    return fn

def spy_factory(p):
    def fn(i):
        return {"SPY": 1.0}
    return fn

def main():
    p = build_panel()
    dec = cadence_days(p.dates, "monthly")
    ridx = engine.road_indices(p, ROADS_2016)
    out = {"family": "catalog-taa-virag-momentum-balancing", "program": "v13-best-rules",
           "spec_md5": "4d0e58e0d080c255b392bcff7a5dfaec", "roads": {}, "curves": {},
           "period_stats": {}, "confirmations": {}}
    forms = {"best": best_factory, "published": published_factory,
             "static_ew10": static_factory, "spy_buyhold": spy_factory}
    for rname, idx in ridx.items():
        entry = {}
        for fname, fac in forms.items():
            r = simulate(p, idx, dec, fac(p), rulebook="native")
            entry[fname] = {k: r[k] for k in ("final", "max_dd_pct", "costs", "orders", "halts")}
            if fname in ("best", "published"):
                out["curves"][f"{rname}|{fname}"] = r["curve"]
                out["period_stats"][f"{rname}|{fname}"] = period_stats(r["curve"], p.dates, "monthly")
        # placebos for best form
        engine._placebo_pool = (U, 4)
        twins = []
        for seed in range(1, 21):
            t = simulate(p, idx, dec, best_factory(p), rulebook="native", placebo_seed=seed)
            twins.append(t["final"])
        entry["best_placebo_finals"] = twins
        entry["best_placebos_beaten"] = sum(1 for t in twins if entry["best"]["final"] > t)
        out["roads"][rname] = entry
        print(rname, {k: v["final"] for k, v in entry.items() if isinstance(v, dict)},
              "placebos_beaten", entry["best_placebos_beaten"], flush=True)
        # confirmation if best beats champion on this road
        if entry["best"]["final"] > CHAMP[rname]:
            a, b = ROADS_2016[rname]
            conf = {"yearly_folds": {}, "half_windows": {}}
            years = sorted({d.year for d in p.dates if a <= d <= b})
            wins = 0; folds = 0; strat_meds = []; spy_meds = []
            for y in years:
                fidx = [i for i, d in enumerate(p.dates) if d.year == y and a <= d <= b]
                if len(fidx) < 60: continue
                sf = simulate(p, fidx, dec, best_factory(p), rulebook="native")["final"]
                pf = simulate(p, fidx, dec, spy_factory(p), rulebook="native")["final"]
                conf["yearly_folds"][str(y)] = {"strategy": sf, "spy": pf}
                folds += 1; wins += 1 if sf > pf else 0
                strat_meds.append(sf); spy_meds.append(pf)
            sm = sorted(strat_meds)[len(strat_meds)//2] if strat_meds else 0
            pm = sorted(spy_meds)[len(spy_meds)//2] if spy_meds else 0
            conf["yearly_majority_beats_spy"] = bool(folds and wins * 2 > folds)
            conf["yearly_median"] = {"strategy": sm, "spy": pm, "strategy_wins": sm > pm}
            mid = date.fromordinal((a.toordinal() + b.toordinal()) // 2)
            hw_ok = True
            for hn, (ha, hb) in {"first": (a, mid), "second": (mid, b)}.items():
                hidx = [i for i, d in enumerate(p.dates) if ha <= d <= hb]
                sf = simulate(p, hidx, dec, best_factory(p), rulebook="native")["final"]
                pf = simulate(p, hidx, dec, spy_factory(p), rulebook="native")["final"]
                conf["half_windows"][hn] = {"strategy": sf, "spy": pf}
                hw_ok = hw_ok and sf > pf
            conf["half_windows_both_beat_spy"] = bool(hw_ok)
            conf["passed"] = bool(conf["yearly_majority_beats_spy"] and conf["yearly_median"]["strategy_wins"] and hw_ok)
            out["confirmations"][rname] = conf
            print("CONFIRMATION", rname, conf, flush=True)
    with open(os.path.join(OUT, "results.json"), "w") as fh:
        json.dump(out, fh, indent=1)
    print("DONE")

if __name__ == "__main__":
    main()
