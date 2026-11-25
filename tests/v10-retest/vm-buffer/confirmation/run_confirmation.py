#!/usr/bin/env python3
"""
CONFIRMATION RUN (v10) — vm-buffer (Terry's confirmation rule, SPEC.md).

The DECADE sweep flipped this strategy: originally strictly worse than the
champion on the champion's windows (CONT $379.76 / VAL $248.72 at quarterly,
integrity reproduced to the cent in the sweep), on the DECADE it posted
money cadences at daily $527.48 (20/20), weekly $623.28 (20/20), biweekly
$604.25 (20/20), monthly $579.72 (19/20), quarterly $473.50 (13/20) vs SPY
$367.80, ZERO halts at every cadence. No flipped verdict is crowned until
its money cadence is re-run on the OTHER roads.

This driver re-runs the buffer at WEEKLY (best money), MONTHLY and
QUARTERLY (native), identical plumbing to the sweep (run_v10.py imported
unmodified — same scoring, same FastPIT EDGAR rules, same pxfull prices,
same costs, same v9 protection wrapper, same buffer rule: signal /
selection / rebalance / buffer check ONLY on cadence dates, floor checked
daily, v9 restart lands on the next cadence date >= liquidation+90d;
same random-order placebo twin design, seeds 1..20):

  Roads:
    CONT 2019-01-02 -> 2026-11-20  (SPY ref $313.62; quarterly original $379.76)
    VAL  2023-01-03 -> 2026-11-20  (SPY ref $187.77; quarterly original $248.72)
  LONG 2010-01-04 -> 2026-11-20: NOT RUN — see CONFIRMATION.md. The
    universe is the fixed 30 names that were the largest US companies by
    market cap AS OF NOVEMBER 2016 (value-momentum-honest.py docstring);
    that list was not knowable in 2010 (it is selected with 2016
    information and includes post-2010 listings), so a 2010-start run on
    it would be survivorship/look-ahead flattered, not point-in-time
    honest. Documented limitation, not a failed confirmation.
  Fresh yearly folds 2017-2026 at WEEKLY: each calendar year standalone
    (first to last trading day of the year in the price book; 2026 ends
    2026-11-20, end of data), fresh $100 start.
  20-seed placebos at each cadence on each confirmation road (CONT/VAL).

One clean shot, no tuning. Outputs ONLY into this folder:
  <road>-<cadence>.json per run, folds.json.
Usage: run_confirmation.py
"""
import importlib.util
import json
import os
import random
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(HERE)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


S = load_module("vm_buffer_sweep", os.path.join(PARENT, "run_v10.py"))
E = S.E
START_CASH = 100.0
SEEDS = list(range(1, 21))
CADENCES = ["weekly", "monthly", "quarterly"]
ROADS = {
    "cont": ("2019-01-02", "2026-11-20", 313.62),
    "val": ("2023-01-03", "2026-11-20", 187.77),
}
ORIGINAL_QUARTERLY = {"cont": 379.76, "val": 248.72}


def save(name, doc):
    with open(os.path.join(HERE, name), "w") as f:
        json.dump(doc, f, indent=1)
    print(f"  saved {name}", flush=True)


def main():
    t0 = time.time()
    _pb4, equity_rows, shares_rows = S.V5.build_inputs()
    S.EQF = {t: S.FastPIT(equity_rows[t]) for t in S.UNIVERSE}
    S.SHF = {t: S.FastPIT(shares_rows[t]) for t in S.UNIVERSE}
    fb = S.build_sweep_book()
    S.verify_fast_pit(equity_rows, shares_rows, fb)
    didx_map = {t: {b["d"]: i for i, b in enumerate(fb.bars[t])}
                for t in S.UNIVERSE}
    days = [d for d in fb.dates if "2017-01-01" <= d <= "2026-11-20"]
    score_cache = {}
    for d in days:
        score_cache[d] = S.compute_scores(fb, d, didx_map)
    print(f"scores computed for {len(days)} days ({time.time()-t0:.0f}s)",
          flush=True)

    # ---------- roads ----------
    for cad in CADENCES:
        for road, (start, end, spy_ref) in ROADS.items():
            spy_final, spy_costs = E.spy_net(fb, start, end, START_CASH)
            clist = S.cadence_dates(fb, cad, start, end)
            r = S.run_v9(fb, score_cache, clist, start, end, START_CASH)
            placebo_finals = []
            for seed in SEEDS:
                pr = S.run_v9(fb, score_cache, clist, start, end,
                              START_CASH, placebo_rng=random.Random(seed))
                placebo_finals.append(
                    {"seed": seed, "final": round(pr["final"], 2),
                     "halts": len(pr["halt_events"]),
                     "second_halt": pr["second_halt"] is not None})
            beaten = sum(1 for p in placebo_finals if p["final"] < r["final"])
            doc = {
                "slug": "vm-buffer", "run_type": "confirmation",
                "road": road.upper(), "cadence": cad,
                "window": [start, end], "start_cash": START_CASH,
                "final": round(r["final"], 2),
                "cagr_pct": S.cagr(r["final"], start, end),
                "max_dd_pct": S.curve_stats(r["curve"], r["final"]),
                "costs": round(r["costs"], 2),
                "orders": len(r["trades"]),
                "halts": len(r["halt_events"]),
                "halt_events": r["halt_events"],
                "restarts": r["restarts"],
                "restart": bool(r["restarts"]),
                "second_halt": r["second_halt"],
                "spy_final": round(spy_final, 2),
                "spy_final_reference": spy_ref,
                "beat_spy": round(r["final"], 2) > round(spy_final, 2),
                "placebo_beaten": beaten,
                "placebo_note": "20 seeds (1..20), identical buffer "
                                "mechanics on random pool orderings, same "
                                "cadence and v9 protections (sweep design).",
                "placebo_finals": placebo_finals,
                "selection_dates": clist,
                "equity_curve": [[d, round(v, 4)] for d, v in r["curve"]],
            }
            if cad == "quarterly":
                doc["original_published_final"] = ORIGINAL_QUARTERLY[road]
                doc["matches_original"] = (
                    abs(r["final"] - ORIGINAL_QUARTERLY[road]) < 0.02)
            save(f"{road}-{cad}.json", doc)
            print(f"ROAD {road.upper()} {cad}: final=${r['final']:,.2f} "
                  f"SPY=${spy_final:,.2f} (ref ${spy_ref}) "
                  f"CAGR={doc['cagr_pct']}% maxDD={doc['max_dd_pct']}% "
                  f"costs=${r['costs']:,.2f} orders={len(r['trades'])} "
                  f"halts={len(r['halt_events'])} placebo {beaten}/20 "
                  f"({time.time()-t0:.0f}s)", flush=True)

    # ---------- folds: weekly, 2017-2026 ----------
    folds = []
    for year in range(2017, 2027):
        ydays = [d for d in fb.dates if d[:4] == str(year)]
        s, e = ydays[0], ydays[-1]
        spy_final, _ = E.spy_net(fb, s, e, START_CASH)
        clist = S.cadence_dates(fb, "weekly", s, e)
        r = S.run_v9(fb, score_cache, clist, s, e, START_CASH)
        fold = {
            "year": year, "cadence": "weekly", "window": [s, e],
            "start_cash": START_CASH,
            "final": round(r["final"], 2),
            "cagr_pct": S.cagr(r["final"], s, e),
            "max_dd_pct": S.curve_stats(r["curve"], r["final"]),
            "costs": round(r["costs"], 2),
            "orders": len(r["trades"]),
            "halts": len(r["halt_events"]),
            "halt_events": r["halt_events"],
            "restarts": r["restarts"],
            "second_halt": r["second_halt"],
            "spy_final": round(spy_final, 2),
            "beat_spy": round(r["final"], 2) > round(spy_final, 2),
            "beat_100": round(r["final"], 2) > 100.0,
            "selection_dates": clist,
            "equity_curve": [[d, round(v, 4)] for d, v in r["curve"]],
        }
        folds.append(fold)
        print(f"FOLD {year} weekly: final=${r['final']:,.2f} "
              f"vs SPY ${spy_final:,.2f} beat_spy={fold['beat_spy']} "
              f"beat_100={fold['beat_100']} halts={len(r['halt_events'])}",
              flush=True)
    save("folds.json", {
        "slug": "vm-buffer", "run_type": "confirmation folds",
        "cadence": "weekly",
        "note": "Each calendar year 2017-2026 standalone, fresh $100 "
                "start, program costs, v9 protections, identical "
                "plumbing (sweep pxfull prices + FastPIT EDGAR). Window "
                "= first to last trading day of the year in the price "
                "book; 2026 fold ends 2026-11-20 (end of data). SPY = "
                "same-year buy-hold net (program convention, own "
                "plumbing). No placebos on folds (placebos run per "
                "cadence per confirmation road, per task).",
        "record": {
            "vs_spy": [sum(1 for f in folds if f["beat_spy"]), len(folds)],
            "vs_100": [sum(1 for f in folds if f["beat_100"]), len(folds)],
        },
        "folds": folds})
    print(f"DONE in {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
