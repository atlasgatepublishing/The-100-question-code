#!/usr/bin/env python3
"""V10 RETEST — residual-momentum CONFIRMATION RUN (Terry's confirmation
rule, SPEC.md): the DECADE sweep crowned WEEKLY ($589.98, 20/20) over the
native MONTHLY ($562.64, 18/20); a new money cadence is not crowned until
re-run on the other roads. This script re-runs WEEKLY and MONTHLY
(head-to-head) and QUARTERLY (original tempo) on:

  CONT  2019-01-02 -> 2026-11-20
  VAL   2023-01-03 -> 2026-11-20
  LONG  2010-01-04 -> 2026-11-20   (honesty check below)

plus fresh yearly folds at WEEKLY, 2010-2026.

Plumbing: IDENTICAL to the sweep (run_sweep.py in the parent folder) —
engine_v10.py (= engine_v9.py + date-keyed score memoization only),
fastpit.fast_pit_value (proven identical), lr_common bars_adj book over
the 31 needed tickers only (30-name UNIVERSE + SPY; the 1.7GB long-run
cache is never bulk-loaded), EDGAR chains via lr_common. The ONLY change
per run is the selection calendar (cadence_dates, copied verbatim from
run_sweep.py / w4lib). $100, program costs (0.10%/side + $0.01/sell),
v9 protections (plain -15% floor, 90-day sit-out, one restart, second
halt ends the run), point-in-time only. 20-seed placebos per road/cadence
via the engine's own placebo_block (random 5-name twins from the
identical scored pool, same mechanics).

INTEGRITY GATE (runs first; nothing counts unless it passes):
  - SPY in-plumbing vs SPEC references: CONT $313.62, VAL $187.77,
    LONG $822.94, DECADE $367.80.
  - Quarterly (original form) on CONT/VAL through THIS plumbing must
    reproduce the published $413.31 (16/20) / $277.43 (18/20) to the cent
    with all 40 placebo twin finals identical to ../integrity.json.
    (Those two runs double as the CONT/VAL quarterly confirmation roads.)
  - Weekly on DECADE through THIS plumbing must reproduce the sweep's
    $589.98 (20/20) with all 20 twin finals identical to
    ../cells/weekly.json.

LONG honesty: residual momentum needs 253 bars of price history before a
name can be scored (12-1 window + beta from 231 paired daily returns).
The pxfull payloads begin 2008-01-02 for 28/30 names (V 2008-03-19;
META has no bars before its 2012-05-18 IPO and is gate-excluded until it
accrues 253 bars — the engine's own gate, point-in-time). EDGAR chains
are the champion's PIT series (filed < asof, 548-day freshness), the
same chains the long-run-2010 construction used from 2010. So the
price/factor construction is honest at 2010-01-04. Caveat, printed in
CONFIRMATION.md: the pond itself is the Nov-2016 point-in-time top-30 —
the same pond the whole program uses for 2010 roads — so LONG carries
the program-wide universe-membership caveat, not a signal look-ahead.
The script records the scored-pool size at the first LONG selection
dates as evidence the gate, not hindsight, decides eligibility.
"""
import importlib.util
import json
import os
import sys
from datetime import date as _d

CONF = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(CONF)
BT = os.path.expanduser("~/workspace/stock-app/backtests")
sys.path.insert(0, os.path.join(BT, "long-run-2010"))
sys.path.insert(0, PARENT)
import lr_common as C  # noqa: E402


def load_mod(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


M = load_mod("engine_v10", os.path.join(PARENT, "engine_v10.py"))
M.SCORES_CACHE = {}
from fastpit import fast_pit_value  # noqa: E402
M.E.pit_value = fast_pit_value
E = M.E
ORIG_QSD = E.quarter_selection_dates

ROADS = {"LONG": ("2010-01-04", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"),
         "VAL": ("2023-01-03", "2026-11-20"),
         "DECADE": ("2016-11-21", "2026-11-20")}
SPY_REF = {"LONG": 822.94, "CONT": 313.62, "VAL": 187.77, "DECADE": 367.80}
CADENCES = ["weekly", "monthly", "quarterly"]


def cadence_dates(pb, start, end, cad):
    """Uniform operational cadence — verbatim from run_sweep.py."""
    days = [d for d in pb.dates if start <= d <= end]
    if cad == "daily":
        return days
    out, seen = [], set()
    for d in days:
        dt = _d.fromisoformat(d)
        if cad == "weekly":
            key = ("W", dt.isocalendar()[0], dt.isocalendar()[1])
        elif cad == "biweekly":
            monday = dt.toordinal() - dt.weekday()
            if (monday // 7) % 2 != 0:
                continue
            key = ("B", monday)
        elif cad == "monthly":
            key = ("M", d[:4], d[5:7])
        elif cad == "quarterly":
            if d[5:7] not in ("01", "04", "07", "10"):
                continue
            key = ("Q", d[:4], d[5:7])
        elif cad == "semiannual":
            if d[5:7] not in ("01", "07"):
                continue
            key = ("S", d[:4], d[5:7])
        elif cad == "annual":
            key = ("A", d[:4])
        else:
            raise ValueError(cad)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def build_book():
    bars = {}
    for t in M.UNIVERSE + ["SPY"]:
        bars[t] = C.bars_adj(C.yahoo_payload(t))
    pb = M.FastBook(bars)
    eq, so = {}, {}
    for t in M.UNIVERSE:
        facts = C.load_facts(C.cik_for(t))
        eq[t] = C.equity_chain(facts)
        so[t] = C.shares_chain(facts)
    return pb, eq, so


def curve_diag(curve):
    peak, maxdd = -1.0, 0.0
    worst, worst_d = None, None
    for d, v in curve:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak * 100.0
            if dd > maxdd:
                maxdd = dd
        if worst is None or v < worst:
            worst, worst_d = v, d
    return round(maxdd, 2), (round(worst, 2) if worst is not None else None), worst_d


def run_one(pb, eq, so, start, end, cad, placebos=True, label=""):
    E.quarter_selection_dates = lambda b, s, e: cadence_dates(b, s, e, cad)
    try:
        r = M.run_pot_resmom(pb, eq, so, start, end, 100.0, 85.0, M.LADDER,
                             label=label, quiet=True)
        pl = None
        if placebos:
            pl = M.placebo_block(pb, eq, so, start, end, r["final"], label)
    finally:
        E.quarter_selection_dates = ORIG_QSD
    maxdd, worst, worst_d = curve_diag(r["curve"])
    cg, _ = C.cagr(r["final"], 100.0, start, end)
    halts = len(r.get("restarts") or []) + (1 if r.get("second_halt") else 0)
    out = {"cadence": cad, "start": start, "end": end,
           "final": round(r["final"], 2), "cagr_pct": cg,
           "max_dd_pct": maxdd, "worst_close": worst,
           "worst_close_date": worst_d,
           "costs": round(r["costs"], 2), "orders": len(r["trades"]),
           "halts": halts, "restarts": r.get("restarts") or [],
           "restart": bool(r.get("restarts")),
           "second_halt": r.get("second_halt"),
           "curve": [[d, round(v, 4)] for d, v in r["curve"]]}
    if pl is not None:
        out.update({"placebo_beaten": pl["seeds_beaten"],
                    "placebo_median": pl["median"],
                    "placebo_best": pl["best"], "placebo_worst": pl["worst"],
                    "placebo_twins": [{"seed": row["seed"],
                                       "final": row["final"],
                                       "costs": row["costs"],
                                       "orders": row["orders"],
                                       "restarts": row["restarts"],
                                       "second_halt": row["second_halt"]}
                                      for row in pl["rows"]]})
    print("RUN", label, out["final"], "beats",
          out.get("placebo_beaten"), "costs", out["costs"],
          "orders", out["orders"], "halts", halts, flush=True)
    return out


def save(name, obj):
    with open(os.path.join(CONF, name), "w") as f:
        json.dump(obj, f, indent=1, default=str)


def main():
    pb, eq, so = build_book()
    M.SPY_RET = M.spy_daily_returns(pb)

    # ---------- SPY verification ----------
    spy = {}
    for tag, (s, e) in ROADS.items():
        v, _ = E.spy_net(pb, s, e, 100.0)
        spy[tag] = round(v, 2)
        print("SPY", tag, spy[tag], "ref", SPY_REF[tag],
              "match", abs(v - SPY_REF[tag]) < 0.011, flush=True)

    # ---------- LONG honesty diagnostic ----------
    first_bars = {t: pb.bars[t][0]["d"] for t in M.UNIVERSE + ["SPY"]}
    print("FIRST BARS", json.dumps(first_bars), flush=True)

    # ---------- INTEGRITY: quarterly CONT/VAL (double as road runs) ----
    pub = json.load(open(os.path.join(PARENT, "integrity.json")))
    integrity = {"spy_in_plumbing": spy, "spy_ref": SPY_REF,
                 "spy_match": {t: abs(spy[t] - SPY_REF[t]) < 0.011
                               for t in SPY_REF},
                 "first_bar_dates": first_bars, "windows": {}}
    road_runs = {}
    for tag in ("CONT", "VAL"):
        s, e = ROADS[tag]
        cell = run_one(pb, eq, so, s, e, "quarterly",
                       label=f"INTEG {tag} quarterly")
        cell["spy_final"] = spy[tag]
        twins = [t["final"] for t in cell["placebo_twins"]]
        pw = pub["windows"][tag]
        ok = (abs(cell["final"] - pw["published_final"]) < 0.011 and
              cell["placebo_beaten"] == pw["published_placebo_beaten"] and
              twins == pw["twin_finals"])
        integrity["windows"][tag] = {
            "published_final": pw["published_final"],
            "reproduced_final": cell["final"],
            "published_placebo_beaten": pw["published_placebo_beaten"],
            "reproduced_placebo_beaten": cell["placebo_beaten"],
            "twins_match_published": twins == pw["twin_finals"],
            "match": ok}
        print("INTEG", tag, cell["final"], "match", ok, flush=True)
        road_runs[(tag, "quarterly")] = cell
        save(f"{tag}-quarterly.json", cell)

    # ---------- INTEGRITY: decade weekly vs the sweep cell -------------
    dec = run_one(pb, eq, so, *ROADS["DECADE"], "weekly",
                  label="INTEG DECADE weekly")
    sweep_cell = json.load(open(os.path.join(PARENT, "cells", "weekly.json")))
    dec_twins = [t["final"] for t in dec["placebo_twins"]]
    sweep_twins = [t["final"] for t in sweep_cell["placebo_twins"]]
    dec_ok = (abs(dec["final"] - sweep_cell["final"]) < 0.011 and
              dec["placebo_beaten"] == sweep_cell["placebo_beaten"] and
              dec_twins == sweep_twins)
    integrity["decade_weekly"] = {
        "sweep_final": sweep_cell["final"], "reproduced_final": dec["final"],
        "sweep_placebo_beaten": sweep_cell["placebo_beaten"],
        "reproduced_placebo_beaten": dec["placebo_beaten"],
        "twins_match_sweep": dec_twins == sweep_twins, "match": dec_ok}
    print("INTEG DECADE weekly", dec["final"], "match", dec_ok, flush=True)
    save("decade-weekly-check.json", dec)

    integrity["status"] = ("reproduced" if
                           all(integrity["spy_match"].values()) and
                           all(w["match"] for w in
                               integrity["windows"].values()) and dec_ok
                           else "FAILED")
    save("integrity.json", integrity)
    print("INTEGRITY STATUS:", integrity["status"], flush=True)
    if integrity["status"] != "reproduced":
        raise SystemExit("INTEGRITY FAILED — confirmation numbers do not count")

    # ---------- LONG pool-size evidence at the first selection dates ---
    E.quarter_selection_dates = lambda b, s, e: cadence_dates(
        b, s, e, "weekly")
    try:
        r0 = M.run_pot_resmom(pb, eq, so, "2010-01-04", "2010-03-31",
                              100.0, 85.0, M.LADDER, label="LONG-PROBE",
                              quiet=True, record_pools=True)
    finally:
        E.quarter_selection_dates = ORIG_QSD
    pool_evidence = [{"date": d, "pool_size": len(pool)}
                     for d, pool, _ in (r0["pools"] if r0 else [])]
    print("LONG POOL EVIDENCE", json.dumps(pool_evidence), flush=True)
    integrity["long_pool_evidence_first_quarter_2010"] = pool_evidence
    save("integrity.json", integrity)

    # ---------- Confirmation roads --------------------------------------
    for tag in ("LONG", "CONT", "VAL"):
        s, e = ROADS[tag]
        for cad in CADENCES:
            if (tag, cad) in road_runs:
                continue
            cell = run_one(pb, eq, so, s, e, cad, label=f"{tag} {cad}")
            cell["spy_final"] = spy[tag]
            road_runs[(tag, cad)] = cell
            save(f"{tag}-{cad}.json", cell)

    # ---------- Fresh yearly folds at WEEKLY ---------------------------
    folds = []
    for y in range(2010, 2027):
        fs = f"{y}-01-01"
        fe = "2026-11-20" if y == 2026 else f"{y}-12-31"
        cell = run_one(pb, eq, so, fs, fe, "weekly", placebos=False,
                       label=f"FOLD {y} weekly")
        fspy, _ = E.spy_net(pb, fs, fe, 100.0)
        cell["spy_final"] = round(fspy, 2)
        cell["beat_spy"] = cell["final"] > fspy
        cell["year"] = y
        folds.append(cell)
        print("FOLD", y, cell["final"], "vs SPY", round(fspy, 2),
              "beat", cell["beat_spy"], flush=True)
    wins = sum(1 for f in folds if f["beat_spy"])
    above = sum(1 for f in folds if f["final"] > 100.0)
    comp = 100.0
    for f in folds:
        comp *= f["final"] / 100.0
    folds_doc = {"cadence": "weekly", "folds": folds,
                 "record_vs_spy": f"{wins}/{len(folds)}",
                 "folds_above_start": above,
                 "compounded_final": round(comp, 2)}
    save("folds.json", folds_doc)
    print("FOLDS DONE", folds_doc["record_vs_spy"], "above", above,
          "compounded", folds_doc["compounded_final"], flush=True)

    summary = {"slug": "residual-momentum",
               "candidate_cadence": "weekly",
               "integrity_status": integrity["status"],
               "spy": spy,
               "long_pool_evidence": pool_evidence,
               "roads": {f"{tag}-{cad}": {k: v for k, v in cell.items()
                                          if k not in ("curve",
                                                       "placebo_twins")}
                         for (tag, cad), cell in road_runs.items()},
               "folds_record_vs_spy": folds_doc["record_vs_spy"],
               "folds_above_start": above,
               "folds_compounded_final": folds_doc["compounded_final"]}
    save("confirmation_summary.json", summary)
    print("CONFIRMATION DONE", flush=True)


if __name__ == "__main__":
    main()
