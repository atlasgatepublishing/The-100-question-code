#!/usr/bin/env python3
"""CONFIRMATION RUN for leveraged-trend (v10 retest, Terry's confirmation
rule 2026-11-21 ~22:19).

The DECADE sweep flipped this family's verdict at the fast cadences:
daily (native, Gayed) $632.54, weekly $646.30, biweekly $622.94 — all
beat SPY's $367.80 on the decade, while the original monthly form
failed. No crown without cross-year confirmation: this script re-runs
all three SPY-beating cadences (daily = native; weekly = best cell;
biweekly = third money cadence) on LONG / CONT / VAL, plus fresh
yearly folds 2010-2026, using the strategy's own saved engine
(leveraged-trend-v10.py, copied into this folder; its CACHE path
points read-only at the parent folder's data/).

Placebos: NOT FEASIBLE on this chassis — single-asset SPY/UPRO binary
trend switch; there is no stock selection to randomize, no rank to
shuffle, and the original chassis carried no placebo/shift design.
placebo_beaten = null everywhere, documented, never invented.

Outputs (this folder only): long.json, cont.json, val.json, folds.json.
"""
import importlib.util, json, os

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "lev_conf", os.path.join(HERE, "leveraged-trend-v10.py"))
L = importlib.util.module_from_spec(spec)
spec.loader.exec_module(L)

CADENCES = ("daily", "weekly", "biweekly")
ROADS = {"long": ("2010-01-04", "2026-11-20"),
         "cont": ("2019-01-02", "2026-11-20"),
         "val": ("2023-01-03", "2026-11-20")}
PLACEBO_NOTE = ("n/a - infeasible on this chassis: single-asset SPY/UPRO "
                "binary trend switch, no selection/ranking to randomize, "
                "original chassis has no placebo/shift design. Not invented.")


def run(cad, s, e):
    L.set_cadence(cad)
    r = L.run_v9(s, e)
    curve = [(d, round(v, 4)) for d, v in r["curve"]]
    cagr, maxdd = L._cell_stats(curve, r["final"])
    return {
        "cadence": cad, "start": s, "end": e,
        "final": round(r["final"], 2), "cagr_pct": cagr,
        "max_dd_pct": maxdd, "costs": round(r["costs"], 2),
        "orders": r.get("orders", 0),
        "halts": (1 if r["halted"] else 0) + (1 if r["second_halt"] else 0),
        "restart": bool(r["restarts"]),
        "second_halt": bool(r["second_halt"]),
        "ep1_final": round(r["ep1_final"], 2),
        "ep1_halt": r["ep1_halt_info"], "restarts": r["restarts"],
        "second_halt_detail": r["second_halt"],
        "placebo_beaten": None, "placebo_twin_finals": [],
        "placebo_note": PLACEBO_NOTE,
        "curve": curve,
    }


def main():
    # ---- roads ----
    for road, (s, e) in ROADS.items():
        spy = round(L.spy_net(s, e)[0], 2)
        doc = {"slug": "leveraged-trend", "road": road.upper(),
               "start": s, "end": e, "spy_final": spy,
               "placebo_note": PLACEBO_NOTE, "runs": {}}
        for cad in CADENCES:
            r = run(cad, s, e)
            r["spy_final"] = spy
            r["beat_spy"] = r["final"] > spy
            doc["runs"][cad] = r
            print(road, cad, r["final"], "vs SPY", spy,
                  "halts", r["halts"], flush=True)
        with open(os.path.join(HERE, road + ".json"), "w") as f:
            json.dump(doc, f, indent=1)

    # ---- yearly folds 2010-2026, fresh $100 each ----
    CAL = L.CAL
    folds = {"slug": "leveraged-trend",
             "note": "Fresh $100 pot each calendar year, standalone, v9 "
                     "protections, program costs. 2026 is partial "
                     "(through 2026-11-20). SPY = same-year buy-hold net.",
             "placebo_note": PLACEBO_NOTE, "years": {}}
    for yr in range(2010, 2027):
        days = [d for d in CAL if d.startswith(str(yr))]
        s, e = days[0], days[-1]
        spy = round(L.spy_net(s, e)[0], 2)
        rec = {"start": s, "end": e, "spy_final": spy, "cadences": {}}
        for cad in CADENCES:
            r = run(cad, s, e)
            slim = {k: v for k, v in r.items() if k != "curve"}
            slim["curve"] = r["curve"]
            slim["beat_spy"] = r["final"] > spy
            slim["beat_100"] = r["final"] > 100.0
            rec["cadences"][cad] = slim
        folds["years"][str(yr)] = rec
        print("fold", yr,
              {c: rec["cadences"][c]["final"] for c in CADENCES},
              "SPY", spy, flush=True)
    with open(os.path.join(HERE, "folds.json"), "w") as f:
        json.dump(folds, f, indent=1)
    print("DONE CONFIRMATION")


if __name__ == "__main__":
    main()
