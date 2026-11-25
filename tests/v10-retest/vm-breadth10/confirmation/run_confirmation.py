#!/usr/bin/env python3
"""
CONFIRMATION RUN (v10) — vm-breadth10 (Terry's confirmation rule, SPEC.md).

The DECADE cadence sweep flipped this strategy's verdict (originally the
steadier-but-poorer sibling of the champion: CONT $416.08 / VAL $259.73 at
quarterly; on the decade it never halted and posted money cadences at
weekly $452.04 (20/20), biweekly, monthly $563.94 (20/20), quarterly
$553.76 (19/20), semi-annual, annual vs SPY $367.80). No flipped verdict
is crowned until its money cadence is re-run on the OTHER roads.

This driver re-runs breadth-10, identical plumbing to the sweep
(vm_breadth10_v10.py copied into this folder, imported unmodified —
same scoring, same PIT EDGAR rules, same costs, same v9 protection
wrapper, same random-rank placebo twin design, seeds 1..20):

  Roads (monthly + quarterly; weekly as the third money cadence):
    LONG 2010-01-04 -> 2026-11-20   (SPY ref $822.94; champion $1,415.62)
    CONT 2019-01-02 -> 2026-11-20   (SPY ref $313.62; champion $544.47;
                                     quarterly original breadth-10 $416.08)
    VAL  2023-01-03 -> 2026-11-20   (SPY ref $187.77; champion $288.05;
                                     quarterly original breadth-10 $259.73)
  Fresh yearly folds 2017-2026 at monthly and quarterly: each calendar
  year standalone (first to last trading day of the year in the price
  book; 2026 ends 2026-11-20, end of data), fresh $100 start.
  20-seed placebos at each cadence on each confirmation road.

One clean shot, no tuning. Outputs ONLY into this folder:
  <road>-<cadence>.json per run, folds.json.
Usage: run_confirmation.py [roads|folds|weekly|all]
"""
import importlib.util
import json
import os
import random
import sys
import time
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


S = load_module("vm_breadth10_sweep",
                os.path.join(HERE, "vm_breadth10_v10.py"))
E = S.E
START_CASH = 100.0
SEEDS = list(range(1, 21))

ROADS = {
    "long": ("2010-01-04", "2026-11-20", 822.94, 1415.62),
    "cont": ("2019-01-02", "2026-11-20", 313.62, 544.47),
    "val": ("2023-01-03", "2026-11-20", 187.77, 288.05),
}
ORIGINAL_QUARTERLY = {"cont": 416.08, "val": 259.73}


def save(name, doc):
    with open(os.path.join(HERE, name), "w") as f:
        json.dump(doc, f, indent=1)
    print(f"  saved {name}", flush=True)


def run_one(pb, pit_eq, pit_sh, cadence, start, end, placebo_rng=None):
    sel = S.selection_dates(pb, cadence, start, end)
    r = S.run_v9(pb, pit_eq, pit_sh, start, end, sel,
                 placebo_rng=placebo_rng)
    return r, sel


def run_road_cadence(pb, pit_eq, pit_sh, road, cadence, with_placebos=True):
    start, end, spy_ref, champ_ref = ROADS[road]
    spy_final, spy_costs = E.spy_net(pb, start, end, START_CASH)
    r, sel = run_one(pb, pit_eq, pit_sh, cadence, start, end)
    diag = S.diagnostics(r["curve"])
    placebo_finals, beaten = [], None
    if with_placebos:
        for seed in SEEDS:
            pr, _ = run_one(pb, pit_eq, pit_sh, cadence, start, end,
                            placebo_rng=random.Random(seed))
            placebo_finals.append(round(pr["final"], 2))
        beaten = sum(1 for f in placebo_finals if f < r["final"])
    doc = {
        "slug": "vm-breadth10", "run_type": "confirmation",
        "road": road.upper(), "cadence": cadence,
        "window": [start, end], "start_cash": START_CASH,
        "final": round(r["final"], 2),
        "cagr_pct": S.cagr_pct(r["final"], start, end),
        "max_dd_pct": diag["max_dd_pct"], "max_dd_date": diag["max_dd_date"],
        "worst_close": diag["worst_close"],
        "worst_close_date": diag["worst_close_date"],
        "costs": round(r["costs"], 2), "orders": len(r["trades"]),
        "halts": r["halts"], "restart": r["restart"],
        "second_halt": r["second_halt"], "restarts": r["restarts"],
        "second_halt_info": r["second_halt_info"],
        "spy_final": round(spy_final, 2), "spy_costs": round(spy_costs, 2),
        "spy_final_reference": spy_ref,
        "beat_spy": round(r["final"], 2) > round(spy_final, 2),
        "champion_final_reference": champ_ref,
        "beat_champion": round(r["final"], 2) > champ_ref,
        "placebo_beaten": beaten,
        "placebo_note": "20 seeds (1..20), random-rank top-10 twins from "
                        "the same scored pool, same v9 wrapper (sweep design)",
        "placebo_finals": placebo_finals,
        "selection_dates_count": len(sel),
        "equity_curve": [[d, round(v, 2)] for d, v in r["curve"]],
    }
    if road in ORIGINAL_QUARTERLY and cadence == "quarterly":
        doc["original_published_final"] = ORIGINAL_QUARTERLY[road]
        doc["matches_original"] = abs(r["final"] - ORIGINAL_QUARTERLY[road]) < 0.02
    save(f"{road}-{cadence}.json", doc)
    print(f"ROAD {road.upper()} {cadence}: final=${r['final']:,.2f} "
          f"SPY=${spy_final:,.2f} (ref ${spy_ref}) champ=${champ_ref:,.2f} "
          f"CAGR={doc['cagr_pct']}% maxDD={diag['max_dd_pct']}% "
          f"costs=${r['costs']:,.2f} orders={len(r['trades'])} "
          f"halts={r['halts']} restart={r['restart']} "
          f"second_halt={r['second_halt']} placebo beaten {beaten}/20",
          flush=True)
    return doc


def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else "all"
    t0 = time.time()
    equity_rows, shares_rows = S.build_fundamentals()
    pit_eq = {t: S.PitIndex(equity_rows[t]) for t in S.UNIVERSE}
    pit_sh = {t: S.PitIndex(shares_rows[t]) for t in S.UNIVERSE}
    pb = S.build_pricebook_full()
    print(f"inputs loaded in {time.time() - t0:.0f}s", flush=True)

    if phase in ("roads", "all"):
        for cadence in ("monthly", "quarterly"):
            for road in ("long", "cont", "val"):
                run_road_cadence(pb, pit_eq, pit_sh, road, cadence)
        print(f"roads phase done in {time.time() - t0:.0f}s", flush=True)

    if phase in ("weekly", "all"):
        for road in ("long", "cont", "val"):
            run_road_cadence(pb, pit_eq, pit_sh, road, "weekly")
        print(f"weekly phase done in {time.time() - t0:.0f}s", flush=True)

    if phase in ("folds", "all"):
        folds = []
        for cadence in ("monthly", "quarterly"):
            for year in range(2017, 2027):
                days = [d for d in pb.dates if d[:4] == str(year)]
                s, e = days[0], days[-1]
                spy_final, _ = E.spy_net(pb, s, e, START_CASH)
                r, sel = run_one(pb, pit_eq, pit_sh, cadence, s, e)
                diag = S.diagnostics(r["curve"])
                fold = {
                    "year": year, "cadence": cadence, "window": [s, e],
                    "start_cash": START_CASH,
                    "final": round(r["final"], 2),
                    "cagr_pct": S.cagr_pct(r["final"], s, e),
                    "max_dd_pct": diag["max_dd_pct"],
                    "max_dd_date": diag["max_dd_date"],
                    "costs": round(r["costs"], 2),
                    "orders": len(r["trades"]),
                    "halts": r["halts"], "restart": r["restart"],
                    "second_halt": r["second_halt"],
                    "restarts": r["restarts"],
                    "second_halt_info": r["second_halt_info"],
                    "spy_final": round(spy_final, 2),
                    "beat_spy": round(r["final"], 2) > round(spy_final, 2),
                    "beat_100": round(r["final"], 2) > 100.0,
                    "selection_dates_count": len(sel),
                    "equity_curve": [[d, round(v, 2)] for d, v in r["curve"]],
                }
                folds.append(fold)
                print(f"FOLD {year} {cadence}: final=${r['final']:,.2f} "
                      f"vs SPY ${spy_final:,.2f} "
                      f"beat_spy={fold['beat_spy']} beat_100={fold['beat_100']} "
                      f"halts={r['halts']}", flush=True)
        rec = {}
        for cadence in ("monthly", "quarterly"):
            cf = [f for f in folds if f["cadence"] == cadence]
            rec[cadence] = {
                "vs_spy": [sum(1 for f in cf if f["beat_spy"]), len(cf)],
                "vs_100": [sum(1 for f in cf if f["beat_100"]), len(cf)],
            }
        save("folds.json", {
            "slug": "vm-breadth10", "run_type": "confirmation folds",
            "note": "Each calendar year standalone, fresh $100 start, "
                    "program costs, v9 protections, identical plumbing. "
                    "Window = first to last trading day of the year in the "
                    "price book; 2026 fold ends 2026-11-20 (end of data). "
                    "SPY = same-year buy-hold net (program convention).",
            "record": rec, "folds": folds})
        print(f"folds phase done in {time.time() - t0:.0f}s", flush=True)

    print(f"DONE phase={phase} in {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
