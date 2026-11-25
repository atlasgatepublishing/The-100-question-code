#!/usr/bin/env python3
"""
THE GREAT RETEST (v10) — CONFIRMATION RUN: GAP A-1 SAME-MONTH SEASONALITY,
SEMI-ANNUAL cadence (Terry's CONFIRMATION RULE, SPEC.md 2026-11-21 ~22:19).

Why this run exists: in the parent sweep (../results.json) A-1 already OWNS
ITS GROUND at native monthly (decade monthly $591.60, 20/20), but the
SEMI-ANNUAL cell printed $760.50 (19/20) — the biggest final on the row — on
a degraded sampling (it only ever samples the January and July rankings).
A new best tempo is not crowned until it is re-run on the other roads. This
script is that re-run, one clean shot, frozen spec, no tuning.

Plumbing: IDENTICAL to the parent sweep — this file imports the sweep
script (../gap-a1-seasonality-v10.py) as a module and uses its engine,
cadence decision-date generator, v9 episode wrapper, costs and placebo
design unchanged. Data: read-only shared cache
backtests/v7/gap-a1-seasonality/data/ (31 Yahoo adjclose payloads,
2008->2026), loaded one ticker at a time (narrow loading per the memory
rule; the 1.7GB long-run cache is never touched).

Steps, in order:
  1. INTEGRITY GATE — original form (monthly decisions, plain $85 floor,
     NO restart, the v7 engine as published) on CONT and VAL must
     reproduce CONT $406.91 (costs $39.79, 840 orders, 19/20) and
     VAL $278.12 (costs $18.25, 417 orders, 18/20) to the cent, and SPY
     buy-and-hold in this plumbing must reproduce CONT $313.62 /
     VAL $187.77. No confirmation number counts if the gate fails.
  2. CONFIRMATION ROADS — CONT (2019-01-02->2026-11-20) and VAL
     (2023-01-03->2026-11-20), each at SEMI-ANNUAL and at MONTHLY
     (native, head-to-head), v9 protections, $100, program costs,
     point-in-time only, 20-seed random-rank placebos per road/cadence.
  3. FRESH YEARLY FOLDS — fresh $100 per calendar year at SEMI-ANNUAL
     (v9 protections), 2017..2026 (2026 ends 2026-11-20), vs SPY net in
     the same plumbing. 2017 is the first fold year the task specifies;
     the eligible pool is 29/30 names in 2017 (META reaches the
     >=6-observation rule in 2018/2019 depending on month) and 30/30
     from Jan 2019 — stated, never patched.
  4. LONG ROAD — there is NO honest 2010 LONG road for A-1 and none is
     run: the signal needs >=6 same-month returns from the prior 10
     years; the data begins 2008-01, so a 2010 decision has ZERO
     eligible names (verified in this run and recorded in
     confirmation_summary.json). CONT/VAL + folds carry the verdict.

Outputs (this folder only): integrity.json, CONT_monthly.json,
CONT_semiannual.json, VAL_monthly.json, VAL_semiannual.json, folds.json,
confirmation_summary.json. CONFIRMATION.md is written from those files.
Simulation only. No broker orders were placed.
"""
import importlib.util
import json
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
SWEEP = os.path.join(HERE, "..", "gap-a1-seasonality-v10.py")

_spec = importlib.util.spec_from_file_location("a1_sweep", SWEEP)
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)

PLACEBO_SEEDS = list(range(1, 21))
ROADS = [("CONT", "2019-01-02", "2026-11-20", 406.91, 313.62),
         ("VAL", "2023-01-03", "2026-11-20", 278.12, 187.77)]
CADENCES = ["semiannual", "monthly"]


def dump(name, doc):
    with open(os.path.join(HERE, name), "w") as f:
        json.dump(doc, f, indent=1)
    print(f"saved {name}", flush=True)


def road_doc(pb, mrets_by, road, start, end, cadence):
    r = M.run_pot_v9(pb, mrets_by, start, end, cadence,
                     label=f"{road} {cadence} RANKED")
    finals = []
    for seed in PLACEBO_SEEDS:
        rng = random.Random(seed)
        pr = M.run_pot_v9(pb, mrets_by, start, end, cadence,
                          placebo_rng=rng,
                          label=f"{road} {cadence} PLACEBO {seed}")
        finals.append(round(pr["final"], 2))
    beats = sum(1 for v in finals if r["final"] > v)
    spy, spy_costs = M.spy_net(pb, start, end)
    doc = {"slug": "gap-a1-seasonality", "run": "confirmation",
           "road": road, "cadence": cadence, "window": [start, end],
           "start_cash": 100.0,
           "protection": "v9: plain -15% floor; first halt -> liquidate "
                         "next open, 90-day sit-out, restart at next "
                         "cadence decision date, ep2 floor -15% from "
                         "restart balance; second halt ends run",
           "final": round(r["final"], 2),
           "cagr_pct": M.cagr(r["final"], start, end),
           "max_dd_pct": M.max_dd(r["curve"]),
           "costs": round(r["costs"], 2), "orders": r["orders"],
           "halts": r["halts"], "halt_dates": r["halt_dates"],
           "restart": r["restart"], "second_halt": bool(r["ep2_halted"]),
           "status": r["status"],
           "spy_final_plumbing": round(spy, 2),
           "spy_costs_plumbing": round(spy_costs, 2),
           "placebo_beaten": beats, "placebo_finals": finals,
           "equity_curve": [[d, round(v, 4)] for d, v in r["curve"]]}
    print(f"{road} {cadence}: final=${r['final']:.2f} "
          f"CAGR={doc['cagr_pct']} maxDD={doc['max_dd_pct']} "
          f"costs=${r['costs']:.2f} orders={r['orders']} "
          f"halts={r['halts']} status={r['status']} "
          f"SPY=${spy:.2f} placebo beats={beats}/20", flush=True)
    return doc


def main():
    # ---- narrow loading: one cached payload at a time
    bars = {}
    for t in M.UNIVERSE + ["SPY"]:
        bars[t] = M.get_prices(t)
    pb = M.PriceBook(bars)
    mrets_by = {t: M.monthly_returns(bars[t]) for t in M.UNIVERSE}
    print(f"loaded {len(bars)} tickers; dates {pb.dates[0]}..{pb.dates[-1]}",
          flush=True)

    # ---- LONG-road honesty check: eligible names at 2010 decision months
    long_check = {}
    for y, mo in [(2010, 1), (2010, 7), (2013, 1), (2014, 7), (2017, 1)]:
        n = sum(1 for t in M.UNIVERSE
                if M.seasonal_signal(mrets_by[t], y, mo)[0] is not None)
        long_check[f"{y}-{mo:02d}"] = n
    print(f"LONG honesty check, eligible names by decision month: "
          f"{long_check}", flush=True)

    # ---------------- 1. INTEGRITY GATE (original form, no restart)
    integrity = {"original_finals": {"CONT": 406.91, "VAL": 278.12,
                                     "CONT_costs": 39.79, "VAL_costs": 18.25,
                                     "CONT_orders": 840, "VAL_orders": 417,
                                     "CONT_placebo_beaten": 19,
                                     "VAL_placebo_beaten": 18,
                                     "CONT_spy": 313.62, "VAL_spy": 187.77},
                 "reproduced_finals": {}}
    for wname, ws, we, _pub, _spy_pub in ROADS:
        sel = M.decision_dates(pb, ws, we, "monthly")
        r = M.run_pot(pb, mrets_by, ws, we, sel,
                      label=wname + " INTEGRITY")
        finals = []
        for seed in PLACEBO_SEEDS:
            rng = random.Random(seed)
            pr = M.run_pot(pb, mrets_by, ws, we, sel, placebo_rng=rng,
                           label=f"{wname} INTEGRITY PLACEBO {seed}")
            finals.append(round(pr["final"], 2))
        beats = sum(1 for v in finals if r["final"] > v)
        spy, spy_costs = M.spy_net(pb, ws, we)
        integrity["reproduced_finals"][wname] = round(r["final"], 2)
        integrity["reproduced_finals"][wname + "_costs"] = round(r["costs"], 2)
        integrity["reproduced_finals"][wname + "_orders"] = len(r["trades"])
        integrity["reproduced_finals"][wname + "_placebo_beaten"] = beats
        integrity["reproduced_finals"][wname + "_placebo_finals"] = finals
        integrity["reproduced_finals"][wname + "_spy"] = round(spy, 2)
        integrity["reproduced_finals"][wname + "_spy_costs"] = round(spy_costs, 2)
        integrity["reproduced_finals"][wname + "_curve"] = [
            [d, round(v, 4)] for d, v in r["curve"]]
        print(f"INTEGRITY {wname}: final=${r['final']:.2f} "
              f"costs=${r['costs']:.2f} orders={len(r['trades'])} "
              f"beats={beats}/20 SPY=${spy:.2f}", flush=True)
    rf = integrity["reproduced_finals"]
    ok = (rf["CONT"] == 406.91 and rf["VAL"] == 278.12 and
          rf["CONT_costs"] == 39.79 and rf["VAL_costs"] == 18.25 and
          rf["CONT_orders"] == 840 and rf["VAL_orders"] == 417 and
          rf["CONT_placebo_beaten"] == 19 and rf["VAL_placebo_beaten"] == 18
          and rf["CONT_spy"] == 313.62 and rf["VAL_spy"] == 187.77)
    integrity["status"] = "reproduced" if ok else "FAILED"
    print(f"INTEGRITY STATUS: {integrity['status']}", flush=True)
    dump("integrity.json", integrity)
    if not ok:
        print("GATE FAILED — confirmation numbers do not count; stopping.",
              flush=True)
        return

    # ---------------- 2. CONFIRMATION ROADS
    roads = {}
    for road, ws, we, _pub, _spy_pub in ROADS:
        for cadence in CADENCES:
            doc = road_doc(pb, mrets_by, road, ws, we, cadence)
            roads[f"{road}_{cadence}"] = doc
            dump(f"{road}_{cadence}.json", doc)

    # ---------------- 3. FRESH YEARLY FOLDS at SEMI-ANNUAL (v9)
    folds = []
    for y in range(2017, 2027):
        ws = f"{y}-01-01"
        we = "2026-11-20" if y == 2026 else f"{y}-12-31"
        r = M.run_pot_v9(pb, mrets_by, ws, we, "semiannual",
                         label=f"FOLD {y} semiannual")
        spy, spy_costs = M.spy_net(pb, ws, we)
        pool_jan = sum(1 for t in M.UNIVERSE
                       if M.seasonal_signal(mrets_by[t], y, 1)[0] is not None)
        folds.append({"year": y, "window": [ws, we], "cadence": "semiannual",
                      "start_cash": 100.0,
                      "final": round(r["final"], 2),
                      "return_pct": round((r["final"] / 100.0 - 1) * 100, 2),
                      "cagr_pct": M.cagr(r["final"], ws, we),
                      "max_dd_pct": M.max_dd(r["curve"]),
                      "costs": round(r["costs"], 2), "orders": r["orders"],
                      "halts": r["halts"], "halt_dates": r["halt_dates"],
                      "restart": r["restart"],
                      "second_halt": bool(r["ep2_halted"]),
                      "status": r["status"],
                      "spy_final_plumbing": round(spy, 2),
                      "spy_return_pct": round((spy / 100.0 - 1) * 100, 2),
                      "beat_spy": r["final"] > spy,
                      "eligible_pool_january": pool_jan,
                      "equity_curve": [[d, round(v, 4)]
                                       for d, v in r["curve"]]})
        f = folds[-1]
        print(f"FOLD {y}: final=${f['final']:.2f} vs SPY "
              f"${f['spy_final_plumbing']:.2f} beat={f['beat_spy']} "
              f"halts={f['halts']} status={f['status']} "
              f"pool_jan={pool_jan}", flush=True)
    wins = sum(1 for f in folds if f["beat_spy"])
    comp = spy_comp = 100.0
    for f in folds:
        comp *= 1 + f["return_pct"] / 100.0
        spy_comp *= 1 + f["spy_return_pct"] / 100.0
    folds_doc = {"slug": "gap-a1-seasonality", "run": "confirmation folds",
                 "cadence": "semiannual", "protection": "v9 (as roads)",
                 "note": "Fresh $100 per calendar year; 2026 fold ends "
                         "2026-11-20. Fold windows follow the original v7 "
                         "convention (Jan 1 -> Dec 31). Semi-annual "
                         "decisions sample the January and July rankings "
                         "only. Eligible pool is 29/30 in Jan 2017-2018 "
                         "(META short of the >=6-observation rule) and "
                         "30/30 from Jan 2019 — stated, never patched.",
                 "folds": folds,
                 "record_vs_spy": f"{wins} wins, {len(folds) - wins} losses",
                 "fold_compounded_final": round(comp, 2),
                 "spy_fold_compounded_final": round(spy_comp, 2)}
    dump("folds.json", folds_doc)

    # ---------------- summary
    summary = {"slug": "gap-a1-seasonality",
               "run": "v10 CONFIRMATION — semiannual cadence",
               "integrity_status": integrity["status"],
               "long_road": {"status": "NOT RUN — no honest 2010 LONG road",
                             "reason": "Signal needs >=6 same-month returns "
                                       "from the prior 10 years; price data "
                                       "begins 2008-01, so 2010 decisions "
                                       "have zero eligible names.",
                             "eligible_names_by_decision_month": long_check},
               "roads": {k: {kk: v[kk] for kk in
                             ("road", "cadence", "window", "final",
                              "cagr_pct", "max_dd_pct", "costs", "orders",
                              "halts", "halt_dates", "restart",
                              "second_halt", "status", "spy_final_plumbing",
                              "placebo_beaten", "placebo_finals")}
                         for k, v in roads.items()},
               "folds_record_vs_spy": folds_doc["record_vs_spy"],
               "folds_compounded": folds_doc["fold_compounded_final"],
               "spy_folds_compounded": folds_doc["spy_fold_compounded_final"]}
    dump("confirmation_summary.json", summary)
    print("DONE CONFIRMATION", flush=True)


if __name__ == "__main__":
    main()
