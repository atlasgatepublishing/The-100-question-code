#!/usr/bin/env python3
"""
CONFIRMATION RUN — gap-a4-distress, MONTHLY cadence only.
THE GREAT RETEST (v10), CONFIRMATION RULE (SPEC.md, Terry 2026-11-21 ~22:19):
the sweep crowned a NEW money cadence (monthly, DECADE $593.62, 20/20) for a
strategy whose original verdict was NOT PROMOTED (driven by VAL at quarterly:
$154.25 < SPY $187.77, 2/20). A changed verdict / new crown does not enter the
SCOREBOARD until the money cadence is re-run on the OTHER roads — LONG, CONT,
VAL — plus fresh yearly folds, and the cross-year record is printed.

This script reuses the sweep's own plumbing VERBATIM (run_v10.py in the
parent folder, imported read-only): same engine (engine_original_v9.py byte
copy), same fast helpers, same cadence-date generator, same v9 protection
wrapper (run_v9_cad: plain -15% floor from episode start, no ladder, one
restart after 90 days at the next monthly decision point, second halt ends),
same costs, $100 start, point-in-time only, 20 placebo seeds (1..20) per road.

Steps:
  1) INTEGRITY GATE — reproduce the sweep's DECADE monthly cell through this
     plumbing: final $593.62, 20/20, and all 20 twin finals identical to
     cells/monthly.json. If the final does not reproduce, the script writes
     decade_monthly_repro.json + GATE_FAILED.txt and stops.
  2) MONTHLY on CONT (2019-01-02->2026-11-20) and VAL (2023-01-03->2026-11-20),
     same Nov-2016 pond, full-range prices (identical source to the sweep).
  3) MONTHLY on LONG (2010-01-04->2026-11-20). The strategy's own pond is the
     point-in-time top-30 AS OF NOV 2016 — running that pond from 2010 would
     be look-ahead (the pond is selected with 2016 knowledge). So LONG uses
     the long-run-2010 convention exactly as the champion's LONG did: the
     pond is REBUILT point-in-time at the road's start (2010-01-04) with
     lr_common.build_pond's method; the saved build is read from
     backtests/long-run-2010/results_champion.json (pond_build.pond, the
     champion's own 2010 pond). Facts for those 30 names are loaded NARROWLY
     (one file per name) from the read-only v7 long-hold EDGAR cache
     (backtests/v7/long-hold/data/facts_*.json — the cache lr_common itself
     documents as its fundamentals source), prices from the same cache's
     pxfull_*.json. The 1.7GB long-run cache is NOT bulk-loaded.
     Documented universe differences vs the Nov-2016 pond: GOOG (2010 pond)
     vs GOOGL (2016 pond) — same issuer, different share class line in the
     price cache; HPQ/GS/COP/OXY/ORCL/C/SLB in, META/BRK-B/V/MA/UNH/HD/
     NFLX/DIS/MMM/KO out (2010 sizes). Visa and Berkshire remain unscorable
     in spirit: they are simply not in the 2010 top-30.
  4) Fresh yearly folds at monthly, fresh $100 per year, every year the
     Nov-2016-pond data honestly covers: 2016 stub (2016-11-21->12-31,
     partial), 2017-2025 full calendar years, 2026 partial
     (2026-01-01->2026-11-20). Scored vs SPY (same window, program
     convention) and vs the $100 start. No placebos on folds (SPEC
     confirmation rule scores folds vs SPY / start).

Outputs (this folder only): decade_monthly_repro.json, road_long.json,
road_cont.json, road_val.json, folds.json, summary.json, run.log (stdout).
"""
import gc
import importlib.util
import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(HERE)
BT = os.path.join(HERE, "..", "..", "..")
LH_DATA = os.path.join(PARENT, "..", "..", "v7", "long-hold", "data")
LR_DIR = os.path.join(PARENT, "..", "..", "long-run-2010")

spec = importlib.util.spec_from_file_location(
    "run_v10", os.path.join(PARENT, "run_v10.py"))
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)
O = R.O
E = R.E

START_CASH = 100.0
PLACEBO_SEEDS = list(range(1, 21))
END = "2026-11-20"
DECADE = ("2016-11-21", END)
LONG = ("2010-01-04", END)
CONT = ("2019-01-02", END)
VAL = ("2023-01-03", END)

CHAMPION = {"LONG": 1415.62, "CONT": 544.47, "VAL": 288.05}
SPEC_SPY = {"LONG": 822.94, "CONT": 313.62, "VAL": 187.77, "DECADE": 367.80}


def road_run(pb, data, spy_me, window, tag):
    """One monthly road: ranked run + SPY + 20 placebo twins (v9 wrapper)."""
    ws, we = window
    sel_dates = R.cadence_dates(pb, "monthly", ws, we)
    r = R.run_v9_cad(pb, data, spy_me, sel_dates, ws, we)
    st = R.curve_stats(r["curve"])
    spy_final, _ = E.spy_net(pb, ws, we, START_CASH)
    scurve = R.spy_curve(pb, ws, we)
    sst = R.curve_stats(scurve)
    twin_finals = []
    for seed in PLACEBO_SEEDS:
        rng = random.Random(seed)
        rp = R.run_v9_cad(pb, data, spy_me, sel_dates, ws, we,
                          placebo_rng=rng)
        twin_finals.append(round(rp["final"], 2))
    beaten = sum(1 for v in twin_finals if r["final"] > v)
    out = {
        "road": tag, "cadence": "monthly", "start": ws, "end": we,
        "final": round(r["final"], 2),
        "cagr_pct": R.cagr(r["final"], ws, we),
        "max_dd_pct": st["max_dd_pct"],
        "worst_close": st["worst_close"],
        "worst_close_date": st["worst_close_date"],
        "costs": round(r["costs"], 2), "orders": r["orders"],
        "halts": (1 if r["ep1_halted"] else 0) + (1 if r["ep2_halted"] else 0),
        "restart": bool(r["restart"]), "second_halt": bool(r["ep2_halted"]),
        "status": r["status"], "halts_detail": R.halts_list(r),
        "spy_final": round(spy_final, 2),
        "spy_max_dd_pct": sst["max_dd_pct"],
        "spy_worst_close": sst["worst_close"],
        "champion_ref_final": CHAMPION.get(tag),
        "spec_spy_ref": SPEC_SPY.get(tag),
        "placebo_beaten": beaten,
        "placebo_twin_finals": twin_finals,
        "equity_curve": [[d, round(v, 4)] for d, v in r["curve"]],
        "spy_equity_curve": [[d, round(v, 4)] for d, v in scurve],
    }
    print(f"ROAD {tag}: final=${r['final']:,.2f} CAGR={out['cagr_pct']}% "
          f"maxDD={st['max_dd_pct']}% halts={out['halts']} "
          f"restart={out['restart']} costs=${r['costs']:,.2f} "
          f"orders={r['orders']} | SPY=${spy_final:,.2f} "
          f"(maxDD {sst['max_dd_pct']}%) | placebo {beaten}/20", flush=True)
    return out


def save(name, obj):
    with open(os.path.join(HERE, name), "w") as f:
        json.dump(obj, f, indent=1)


def main():
    t0 = time.time()
    R.install_fast_helpers()
    summary = {"slug": "gap-a4-distress", "confirmation_cadence": "monthly"}

    # ============ Phase 1: Nov-2016 pond (DECADE gate, CONT, VAL, folds)
    data = R.load_facts()
    bars = R.load_bars_full()
    pb = R.FastPriceBook(bars)
    spy_me = O.month_end_closes(bars["SPY"])
    O.SELECTION_CACHE.clear()
    print(f"phase1 data loaded {time.time()-t0:.0f}s", flush=True)

    # ---- 1) INTEGRITY GATE: reproduce DECADE monthly $593.62 / 20/20
    dec = road_run(pb, data, spy_me, DECADE, "DECADE")
    with open(os.path.join(PARENT, "cells", "monthly.json")) as f:
        ref = json.load(f)
    gate = {
        "expected_final": ref["final"],
        "reproduced_final": dec["final"],
        "final_match": dec["final"] == ref["final"],
        "expected_placebo_beaten": ref["placebo_beaten"],
        "reproduced_placebo_beaten": dec["placebo_beaten"],
        "expected_twin_finals": ref["placebo_twin_finals"],
        "reproduced_twin_finals": dec["placebo_twin_finals"],
        "twin_finals_match": dec["placebo_twin_finals"] ==
                             ref["placebo_twin_finals"],
        "expected_costs": ref["costs"], "reproduced_costs": dec["costs"],
        "expected_orders": ref["orders"], "reproduced_orders": dec["orders"],
        "expected_max_dd_pct": ref["max_dd_pct"],
        "reproduced_max_dd_pct": dec["max_dd_pct"],
        "spy_final": dec["spy_final"], "spec_spy_ref": SPEC_SPY["DECADE"],
    }
    gate["passed"] = (gate["final_match"] and gate["twin_finals_match"]
                      and dec["placebo_beaten"] == 20)
    save("decade_monthly_repro.json", {**dec, "integrity_gate": gate})
    print(f"GATE: final match={gate['final_match']} twins match="
          f"{gate['twin_finals_match']} passed={gate['passed']} "
          f"({time.time()-t0:.0f}s)", flush=True)
    if not gate["passed"]:
        save("GATE_FAILED.txt", gate)
        print("INTEGRITY GATE FAILED — stopping, per instructions.",
              flush=True)
        return 2
    summary["decade_monthly_gate"] = gate

    # ---- 2) CONT + VAL at monthly
    cont = road_run(pb, data, spy_me, CONT, "CONT")
    save("road_cont.json", cont)
    val = road_run(pb, data, spy_me, VAL, "VAL")
    save("road_val.json", val)
    summary["roads"] = {"CONT": {k: v for k, v in cont.items()
                                 if "curve" not in k},
                        "VAL": {k: v for k, v in val.items()
                                if "curve" not in k}}
    print(f"CONT/VAL done {time.time()-t0:.0f}s", flush=True)

    # ---- 4) yearly folds at monthly (fresh $100/year)
    folds = []
    fold_windows = [("2016 stub (partial, from decade start)",
                     "2016-11-21", "2016-12-31")]
    for y in range(2017, 2026):
        fold_windows.append((str(y), f"{y}-01-01", f"{y}-12-31"))
    fold_windows.append(("2026 (partial, to 2026-11-20)",
                         "2026-01-01", END))
    for label, fs, fe in fold_windows:
        sel_dates = R.cadence_dates(pb, "monthly", fs, fe)
        r = R.run_v9_cad(pb, data, spy_me, sel_dates, fs, fe)
        st = R.curve_stats(r["curve"])
        spy_final, _ = E.spy_net(pb, fs, fe, START_CASH)
        row = {"label": label, "start": fs, "end": fe,
               "final": round(r["final"], 2),
               "return_pct": round(r["final"] / START_CASH * 100 - 100, 2),
               "cagr_pct": R.cagr(r["final"], fs, fe),
               "max_dd_pct": st["max_dd_pct"],
               "worst_close": st["worst_close"],
               "costs": round(r["costs"], 2), "orders": r["orders"],
               "halts": (1 if r["ep1_halted"] else 0) +
                        (1 if r["ep2_halted"] else 0),
               "restart": bool(r["restart"]),
               "second_halt": bool(r["ep2_halted"]),
               "status": r["status"], "halts_detail": R.halts_list(r),
               "spy_final": round(spy_final, 2),
               "spy_return_pct": round(spy_final / START_CASH * 100 - 100, 2),
               "beat_spy": r["final"] > spy_final,
               "beat_start_100": r["final"] > START_CASH,
               "equity_curve": [[d, round(v, 4)] for d, v in r["curve"]]}
        folds.append(row)
        print(f"FOLD {label}: final=${r['final']:,.2f} "
              f"({row['return_pct']:+.2f}%) vs SPY ${spy_final:,.2f} "
              f"beat_spy={row['beat_spy']} maxDD={st['max_dd_pct']}% "
              f"halts={row['halts']}", flush=True)
    full_years = [f for f in folds if f["label"].isdigit()]
    save("folds.json", {
        "cadence": "monthly", "fresh_start_per_fold": START_CASH,
        "folds": folds,
        "full_year_record_vs_spy":
            f"{sum(1 for f in full_years if f['beat_spy'])}/"
            f"{len(full_years)} full calendar years (2017-2025)",
        "all_folds_record_vs_spy":
            f"{sum(1 for f in folds if f['beat_spy'])}/{len(folds)} "
            f"incl. partial 2016 stub and partial 2026",
        "folds_beating_start":
            f"{sum(1 for f in folds if f['beat_start_100'])}/{len(folds)}",
    })
    summary["folds_record"] = {
        "full_years_vs_spy":
            f"{sum(1 for f in full_years if f['beat_spy'])}/{len(full_years)}",
        "all_vs_spy": f"{sum(1 for f in folds if f['beat_spy'])}/{len(folds)}",
    }
    print(f"folds done {time.time()-t0:.0f}s", flush=True)

    # free phase-1 memory before the LONG phase (shared RAM is tight)
    del data, bars, pb, spy_me
    O.SELECTION_CACHE.clear()
    gc.collect()

    # ============ Phase 2: LONG on the point-in-time 2010 pond
    with open(os.path.join(LR_DIR, "results_champion.json")) as f:
        pond2010 = json.load(f)["pond_build"]["pond"]
    print(f"LONG pond (2010 PIT top-30, champion's build): {pond2010}",
          flush=True)
    ciks = E.get_ciks()
    overrides = {"XOM": 34088, "GOOG": 1288776}

    def facts_for(cik):
        fn = f"facts_{cik:010d}.json"
        for d in (LH_DATA, os.path.join(LR_DIR, "data"),
                  os.path.join(BT, "v4", "data")):
            p = os.path.join(d, fn)
            if os.path.exists(p) and os.path.getsize(p) > 100:
                with open(p, "rb") as fh:
                    blob = fh.read()
                if blob[:2] == b"\x1f\x8b":
                    import gzip
                    blob = gzip.decompress(blob)
                return json.loads(blob)
        raise FileNotFoundError(fn)

    equity_rows, shares_rows, concepts = {}, {}, {}
    for t in pond2010:
        cik = overrides.get(t, ciks[t][0])
        facts = facts_for(cik)
        eq = (E.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
              E.pit_series(facts, "us-gaap",
                           "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                           prio=1))
        so = (E.pit_series(facts, "dei",
                           "EntityCommonStockSharesOutstanding", prio=3) +
              E.pit_series(facts, "us-gaap",
                           "CommonStockSharesOutstanding", prio=2) +
              E.pit_series(facts, "us-gaap",
                           "WeightedAverageNumberOfSharesOutstandingBasic",
                           prio=1))
        equity_rows[t], shares_rows[t] = eq, so
        concepts[t] = O.build_concept_rows(facts, eq)
        del facts
    data_long = {"equity": equity_rows, "shares": shares_rows,
                 "concepts": concepts}
    bars_long = {}
    for t in pond2010 + ["SPY"]:
        path = os.path.join(LH_DATA, f"pxfull_{t}.json")
        if not os.path.exists(path):
            path = os.path.join(LR_DIR, "data", f"pxfull_{t}.json")
        with open(path, "rb") as fh:
            bars_long[t] = R.bars_from_payload(json.loads(fh.read()))
    pb_long = R.FastPriceBook(bars_long)
    spy_me_long = O.month_end_closes(bars_long["SPY"])
    # switch the engine's universe to the 2010 pond (compute_selection
    # iterates the engine module's UNIVERSE global)
    O.UNIVERSE = pond2010
    O.SELECTION_CACHE.clear()
    print(f"LONG data loaded {time.time()-t0:.0f}s", flush=True)

    long = road_run(pb_long, data_long, spy_me_long, LONG, "LONG")
    long["pond"] = pond2010
    long["pond_source"] = ("point-in-time top-30 at 2010-01-04, champion's "
                           "own long-run build (long-run-2010/"
                           "results_champion.json pond_build) — the "
                           "strategy's Nov-2016 pond cannot honestly "
                           "start in 2010 (look-ahead)")
    long["universe_note"] = ("GOOG in the 2010 pond vs GOOGL in the "
                             "Nov-2016 pond (same issuer, share-class line "
                             "in the price cache); facts read narrowly "
                             "from v7/long-hold/data/facts_*.json")
    save("road_long.json", long)
    summary["roads"]["LONG"] = {k: v for k, v in long.items()
                                if "curve" not in k}
    save("summary.json", summary)
    print(f"DONE {time.time()-t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
