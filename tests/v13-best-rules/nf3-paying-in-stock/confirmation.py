#!/usr/bin/env python3
"""
V13 N-F3 CONFIRMATION — yearly folds on different years (PROGRAM.md
confirmation rule, triggered because the v13 form beat champions on
DECADE/CONT/VAL). Fresh $100 pot each calendar year, MY rules
(semiannual, count 5, no floor), vs SPY and 20 placebos per fold, plus
the published quarterly count-5 fold finals from the v12 confirmation
file as the published-form comparator. Simulation only.
"""
import importlib.util
import json
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "v13", os.path.join(HERE, "run_v13.py"))
v13 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v13)
C = v13.C


def folds_for_pond(pond, years, caches, pb):
    out = []
    for yr in years:
        start, end = f"{yr}-01-01", f"{yr}-12-31"
        days_all = [d for d in pb.dates if start <= d <= end]
        if len(days_all) < 50:
            continue
        sel = v13.cadence_dates(days_all, "semiannual")
        sel_set = set(sel)
        scores = {}
        for d in sel:
            sc = {}
            for t in pond:
                v, _st = caches[t].get(d)
                if v is not None:
                    sc[t] = v
            scores[d] = sc
        win = v13.Window(pb, pond, start, end)
        idx = list(range(len(win.days)))
        r = v13.run_pot_slice(win, idx, sel_set, scores, 5, 100.0,
                              float("-inf"), None)
        spy, _ = C.champ.spy_net(pb, start, end, 100.0)
        pf = []
        for seed in range(1, 21):
            rng = random.Random(seed)
            pr = v13.run_pot_slice(win, idx, sel_set, scores, 5, 100.0,
                                   float("-inf"), rng)
            pf.append(round(pr["final"], 2))
        beaten = sum(1 for x in pf if r["final"] > x)
        sf = sorted(pf)
        fold = {"year": yr, "final": round(r["final"], 2),
                "spy_final": round(spy, 2), "placebo_beaten": beaten,
                "placebo_median": round((sf[9] + sf[10]) / 2.0, 2),
                "placebo_finals": pf, "costs": round(r["costs"], 2),
                "orders": r["orders"],
                "max_dd_pct": v13.curve_diagnostics(r["curve"])["max_drawdown_pct"]}
        out.append(fold)
        print(f"  {yr}: v13=${fold['final']} SPY=${fold['spy_final']} "
              f"placebo {beaten}/20 med=${fold['placebo_median']}",
              flush=True)
    return out


def main():
    pub = json.load(open(os.path.expanduser(
        "~/workspace/stock-app/backtests/v12-completions/holdings-nf3/"
        "confirmation_folds.json")))
    pub5 = {}
    for f in pub["folds"]:
        pub5[f["year"]] = f["counts"]["5"]["final"]

    result = {"form": "v13 semiannual count5 no-floor, fresh $100/year",
              "folds": []}
    print("pond 2016 folds 2017-2026...", flush=True)
    caches = v13.load_caches(v13.UNIVERSE)
    pb = v13.build_book(v13.UNIVERSE)
    for f in folds_for_pond(v13.UNIVERSE, range(2017, 2027), caches, pb):
        f["pond"] = "pond2016"
        f["published_quarterly_count5_final"] = pub5.get(f["year"])
        result["folds"].append(f)
    print("pond 2012 folds 2013-2016...", flush=True)
    caches = v13.load_caches(v13.LONG_POND)
    pb = v13.build_book(v13.LONG_POND)
    for f in folds_for_pond(v13.LONG_POND, range(2013, 2017), caches, pb):
        f["pond"] = "pond2012"
        f["published_quarterly_count5_final"] = pub5.get(f["year"])
        result["folds"].append(f)

    folds = result["folds"]
    result["summary"] = {
        "n_folds": len(folds),
        "folds_beating_spy": sum(1 for f in folds if f["final"] > f["spy_final"]),
        "folds_beating_placebo_median": sum(
            1 for f in folds if f["final"] > f["placebo_median"]),
        "folds_beating_published_quarterly": sum(
            1 for f in folds
            if f["published_quarterly_count5_final"] is not None
            and f["final"] > f["published_quarterly_count5_final"]),
        "fold_finals_total": round(sum(f["final"] for f in folds), 2),
        "published_fold_finals_total": round(sum(
            f["published_quarterly_count5_final"] for f in folds
            if f["published_quarterly_count5_final"] is not None), 2),
    }
    with open(os.path.join(HERE, "confirmation_folds.json"), "w") as fh:
        json.dump(result, fh, indent=1, default=str)
    print(json.dumps(result["summary"], indent=1), flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
