#!/usr/bin/env python3
"""
V13 BEST-RULES — VM-BREADTH10 (Value+Momentum top-10 wing).
Simulation only. Spec frozen in BEST-RULES-SPEC.md BEFORE this run.

MY RULES: champion signal unchanged (PIT EDGAR book-to-market + 12-1
momentum, percentile ranks averaged, quarterly re-pick, next-open
execution, equal weight, honest top-30 pond PIT at each road start,
program costs 0.10%/side + $0.01/sell) with exactly one change from the
house published form:
  - NO floor / stop / ladder (diversification at count 10 IS the
    protection; the -15% chassis is removed per spec reasoning)
Holdings count = 10 (definitional for this family).

Chassis: v12 holdings-champion-vm/run_sweep.py imported read-only.
INTEGRITY GATE: house count-5 must reproduce the published champion
finals (LONG $1,415.62 / DECADE $667.35 / CONT $544.47 / VAL $288.05)
before any v13 number is taken. Same-chassis count-10 house-floor twin
prints as the published-form reference (floor priced, not asserted).

CONFIRMATION (pre-registered in the spec): if my rules beat the
published champion V+M on any road -> fresh-$100 calendar-year folds
2017..2026 + DECADE half-windows, my full rule set (count 10, no floor)
head-to-head vs the published champion house form (count 5 + floor
chassis). Confirmed requires >=6/10 folds AND >=1/2 halves.
"""
import importlib.util
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SWEEP_PATH = os.path.expanduser(
    "~/workspace/stock-app/backtests/v12-completions/holdings-champion-vm/run_sweep.py")
TOP2_PATH = os.path.expanduser(
    "~/workspace/stock-app/backtests/v13-best-rules/value-momentum/results.json")
END = "2026-11-20"
SEEDS = list(range(1, 21))
MY_COUNT = 10


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


S = load_module("vm_sweep", SWEEP_PATH)


def main():
    t0 = time.time()
    # v13 top-2 reference (sibling folder, read-only, printed as grading bar)
    top2 = {}
    try:
        with open(TOP2_PATH) as f:
            t2 = json.load(f)
        for rn, rd in t2["roads"].items():
            top2[rn] = {"final": rd["my_rules"]["final"],
                        "max_dd_pct": rd["my_rules"]["max_dd_pct"]}
    except Exception as ex:
        print(f"WARN: top-2 reference unavailable: {ex}", flush=True)

    results = {
        "program": "v13-best-rules",
        "family": "vm-breadth10 (Value+Momentum, top-10 wing)",
        "spec": "BEST-RULES-SPEC.md (frozen before run)",
        "my_rules": {"count": MY_COUNT, "floor": None,
                     "cadence": "quarterly", "weighting": "equal",
                     "costs": "0.10%/side + $0.01 per sell order",
                     "start_cash": 100.0},
        "published_form_breadth10": {
            "count": 10, "rules": "house (-15% floor chassis), quarterly",
            "record_finals": {"LONG_monthly": 1728.69, "LONG_quarterly": 1819.82,
                              "CONT": 416.08, "VAL": 259.73, "DECADE_quarterly": 553.76}},
        "published_champion_vm": {"count": 5, "rules": "house (-15% floor chassis)",
                                  "finals": {"LONG": 1415.62, "DECADE": 667.35,
                                             "CONT": 544.47, "VAL": 288.05}},
        "v13_top2_reference": top2,
        "spy_reference": {"LONG": 822.94, "DECADE": 367.80,
                          "CONT": 313.62, "VAL": 187.77},
        "integrity": {}, "roads": {}, "confirmation": None,
    }

    # ---------------- inputs (v12 chassis builders, read-only caches)
    pb, pit_eq, pit_sh, universe = S.build_fixed_inputs()
    all_sel = S.quarter_dates(pb, "2016-11-21", END)
    dec_fixed = S.compute_decisions(pb, pit_eq, pit_sh, universe, all_sel)

    pbL, pit_eqL, pit_shL, pondL, pond_info = S.build_long_inputs()
    selL_all = S.quarter_dates(pbL, "2010-01-04", END)
    dec_long = S.compute_decisions(pbL, pit_eqL, pit_shL, pondL, selL_all)
    results["long_pond"] = pondL

    road_specs = [
        ("DECADE", pb, dec_fixed, "2016-11-21", END),
        ("CONT", pb, dec_fixed, "2019-01-02", END),
        ("VAL", pb, dec_fixed, "2023-01-03", END),
        ("LONG", pbL, dec_long, "2010-01-04", END),
    ]

    # ---------------- integrity gate: house count-5 = published champion
    expect = {"DECADE": 667.35, "CONT": 544.47, "VAL": 288.05, "LONG": 1415.62}
    champ_runs = {}
    for name, pbx, decx, s, e in road_specs:
        sel = S.quarter_dates(pbx, s, e)
        r = S.run_house(pbx, decx, sel, s, e, 5)
        ok = abs(round(r["final"], 2) - expect[name]) < 0.02
        results["integrity"][name] = {"expected_house_count5": expect[name],
                                      "reproduced": round(r["final"], 2),
                                      "match": ok}
        print(f"INTEGRITY {name} house-5: ${r['final']:,.2f} expected "
              f"${expect[name]} match={ok}", flush=True)
        assert ok, f"integrity failed on {name}"
        champ_runs[name] = (pbx, decx, sel, s, e, r)

    # ---------------- my-rules run + references per road
    beat_any = False
    for name, pbx, decx, s, e in road_specs:
        sel = S.quarter_dates(pbx, s, e)
        spy = S.spy_final(pbx, s, e)
        r = S.run_native(pbx, decx, sel, s, e, MY_COUNT)
        diag = S.diagnostics(r["curve"])
        pfinals = []
        for seed in SEEDS:
            pr = S.run_native(pbx, decx, sel, s, e, MY_COUNT, placebo_seed=seed)
            pfinals.append(round(pr["final"], 2))
        beaten = sum(1 for f in pfinals if f < r["final"])
        dist = S.period_distribution([(d, v) for d, v in r["curve"]], sel)
        # published breadth-10 house form on this chassis (count 10 + floor)
        rh10 = S.run_house(pbx, decx, sel, s, e, 10)
        hdiag = S.diagnostics(rh10["curve"])
        hdist = S.period_distribution([(d, v) for d, v in rh10["curve"]], sel)
        # published champion (house count 5) diagnostics + distribution
        pr5 = champ_runs[name][5]
        cdiag = S.diagnostics(pr5["curve"])
        cdist = S.period_distribution([(d, v) for d, v in pr5["curve"]], sel)
        beat = round(r["final"], 2) > expect[name]
        beat_any = beat_any or beat
        results["roads"][name] = {
            "window": [s, e], "spy_final": spy,
            "my_rules": {"final": round(r["final"], 2),
                         "costs": round(r["costs"], 2), "orders": r["orders"],
                         "max_dd_pct": diag["max_dd_pct"],
                         "max_dd_date": diag["max_dd_date"],
                         "worst_close": diag["worst_close"],
                         "worst_close_date": diag["worst_close_date"],
                         "placebo_beaten": beaten,
                         "placebo_finals": pfinals,
                         "beats_published_champion": beat,
                         "beats_published_breadth10_house_twin":
                             round(r["final"], 2) > round(rh10["final"], 2),
                         "period_distribution": dist,
                         "curve": [[d, round(v, 4)] for d, v in r["curve"]]},
            "published_breadth10_house10": {
                "final": round(rh10["final"], 2), "costs": round(rh10["costs"], 2),
                "orders": rh10["orders"], "halts": rh10["halts"],
                "max_dd_pct": hdiag["max_dd_pct"], "max_dd_date": hdiag["max_dd_date"],
                "period_distribution": hdist,
                "curve": [[d, round(v, 4)] for d, v in rh10["curve"]]},
            "published_champion_house5": {
                "final": round(pr5["final"], 2), "costs": round(pr5["costs"], 2),
                "orders": pr5["orders"], "halts": pr5["halts"],
                "max_dd_pct": cdiag["max_dd_pct"], "max_dd_date": cdiag["max_dd_date"],
                "period_distribution": cdist,
                "curve": [[d, round(v, 4)] for d, v in pr5["curve"]]},
        }
        print(f"{name} MY-RULES count10/nofloor: ${r['final']:,.2f} "
              f"(breadth10-house ${rh10['final']:,.2f}, champion ${expect[name]:,.2f}, "
              f"SPY ${spy:,.2f}) placebos {beaten}/20 maxDD {diag['max_dd_pct']}% "
              f"orders={r['orders']} costs=${r['costs']:,.2f}", flush=True)

    # ---------------- confirmation (Terry's rule, pre-registered)
    if beat_any:
        folds = {}
        for yr in range(2017, 2027):
            s = f"{yr}-01-01"
            e = END if yr == 2026 else f"{yr}-12-31"
            sel = S.quarter_dates(pb, s, e)
            rc = S.run_native(pb, dec_fixed, sel, s, e, MY_COUNT)
            rp = S.run_house(pb, dec_fixed, sel, s, e, 5)
            folds[str(yr)] = {"my_rules_final": round(rc["final"], 2),
                              "published_final": round(rp["final"], 2),
                              "my_rules_max_dd_pct": S.diagnostics(rc["curve"])["max_dd_pct"],
                              "my_rules_win": rc["final"] > rp["final"]}
        halves = {}
        for hn, (s, e) in {"H1_2016-2021": ("2016-11-21", "2021-12-31"),
                           "H2_2022-2026": ("2022-01-01", END)}.items():
            sel = S.quarter_dates(pb, s, e)
            rc = S.run_native(pb, dec_fixed, sel, s, e, MY_COUNT)
            rp = S.run_house(pb, dec_fixed, sel, s, e, 5)
            halves[hn] = {"my_rules_final": round(rc["final"], 2),
                          "published_final": round(rp["final"], 2),
                          "my_rules_max_dd_pct": S.diagnostics(rc["curve"])["max_dd_pct"],
                          "my_rules_win": rc["final"] > rp["final"]}
        wins = sum(1 for v in folds.values() if v["my_rules_win"])
        hwins = sum(1 for v in halves.values() if v["my_rules_win"])
        results["confirmation"] = {
            "design": "fresh-$100 calendar-year folds 2017-2026 + DECADE "
                      "half-windows; my full rule set vs published champion "
                      "house form (count 5 + floor chassis)",
            "year_folds": folds, "fold_wins": f"{wins}/10",
            "half_windows": halves, "half_wins": f"{hwins}/2",
            "confirmed": wins >= 6 and hwins >= 1}
        print(f"CONFIRMATION: folds {wins}/10 halves {hwins}/2 "
              f"confirmed={results['confirmation']['confirmed']}", flush=True)

    results["elapsed_sec"] = round(time.time() - t0, 1)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("DONE", results["elapsed_sec"], flush=True)


if __name__ == "__main__":
    main()
