#!/usr/bin/env python3
"""V10 CONFIRMATION RUN — N-3 QUARTER-END WINDOW-DRESSING REBOUND
(novel-x3-window-dressing), MONTHLY and QUARTERLY cadences only.

Terry's CONFIRMATION RULE (SPEC.md, 2026-11-21 ~22:19): the sweep's
PROVISIONAL money cadences (monthly $392.34 / quarterly $375.31 on the
DECADE, SPY $367.80) are not crowned until re-run on the OTHER roads —
LONG, CONT, VAL — plus fresh yearly folds. This script does exactly
that, one clean shot, no tuning.

Engine: the sweep's own code, loaded UNMODIFIED from ../sweep.py (a
byte-identical copy sits beside this script as sweep.py, md5
9a8571c57886689771c3e085add50af2). Only the window globals START/END
are set per run — the cadence treatment is identical to the sweep:
entries never gated (the event itself), cadence governs the exit
rhythm (scheduled day-5 exit executes on the first cadence date
on/after it) and the v9 floor checks. $100 start, program costs,
point-in-time, v9 protections (plain -15% floor, 90-day cash sit,
episode-2 floor, second halt ends the run).

Roads: LONG 2010-01-04->2026-11-20, CONT 2019-01-02->2026-11-20,
VAL 2023-01-03->2026-11-20. SPY buy-hold finals computed in-plumbing
via the champion engine's spy_net (driver.py's method) and checked
against the published $822.94 / $313.62 / $187.77.

Placebos: the design's own twin design (uniform 5 names from the same
quarter's rankable set, seeds 1..20, same cadence + v9 wrapper) on
every road x cadence cell.

Folds: fresh calendar-year runs 2017-2026 at MONTHLY cadence, fresh
$100 each, ranked picker; SPY same-year final in-plumbing.

Artifact assessment (per road x cadence): for every traded event we
also record the SCHEDULED-exit (day-5) basket/SPY gross — the pure
5-day rebound — beside the actual (cadence) exit figures the engine
already logs, plus the exit delay in trading days and whether the
actual exit landed after the NEXT event's entry date (the documented
slow-cadence slip). If the actual-exit excess is positive while the
scheduled-exit excess is not, the edge is the longer hold, not the
5-day rebound.
"""
import importlib.util, json, os, statistics, time
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(HERE)

spec = importlib.util.spec_from_file_location(
    "x3sweep", os.path.join(PARENT, "sweep.py"))
S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)
M = S.M; E = S.E; BX = S.BX; CAL = S.CAL; BARS = S.BARS
PB = E.PriceBook(BARS)

ROADS = {"LONG": ("2010-01-04", "2026-11-20", 822.94),
         "CONT": ("2019-01-02", "2026-11-20", 313.62),
         "VAL": ("2023-01-03", "2026-11-20", 187.77)}
CADENCES = ["monthly", "quarterly"]

def spy_net(start, end):
    v, _ = E.spy_net(PB, start, end, 100.0)
    return round(v, 2)

def run(start, end, cadence, picker):
    S.START, S.END = start, end
    return S.run_v9_cad(cadence, picker)

def artifact_stats(events):
    """events: engine event_log of episode 1 (same basis as sweep)."""
    traded = [ev for ev in events if ev.get("basket_gross_pct") is not None]
    rows = []
    cal_idx = {d: i for i, d in enumerate(CAL)}
    Ls = sorted(ev["L"] for ev in events)
    for ev in traded:
        picks = ev["picks"]
        rels, ok = [], True
        for t in picks:
            a = BX.close_on_or_before(t, ev["L"])
            b = BX.close_on_or_before(t, ev["exit_scheduled"])
            if a and b: rels.append(b / a)
            else: ok = False
        bg5 = (sum(rels) / len(rels) - 1) * 100 if rels else None
        s0 = BX.close_on_or_before("SPY", ev["L"])
        s5 = BX.close_on_or_before("SPY", ev["exit_scheduled"])
        sg5 = (s5 / s0 - 1) * 100 if s0 and s5 else None
        exc5 = (bg5 - sg5) if (bg5 is not None and sg5 is not None) else None
        nxt = [L for L in Ls if L > ev["L"]]
        rows.append({
            "L": ev["L"], "exit_scheduled": ev["exit_scheduled"],
            "exit_actual": ev["exit_actual"],
            "delay_trading_days": (cal_idx.get(ev["exit_actual"], 0)
                                   - cal_idx.get(ev["exit_scheduled"], 0)),
            "exit_after_next_entry": bool(nxt and ev["exit_actual"] > nxt[0]),
            "excess_gross_actual_pct": ev["excess_gross_pct"],
            "excess_net_actual_pct": ev["excess_net_pct"],
            "excess_gross_scheduled5_pct": (round(exc5, 2)
                                            if exc5 is not None else None),
            "excess_net_scheduled5_pct": (round(exc5 - 0.21, 2)
                                          if exc5 is not None else None)})
    def mean(key):
        vals = [r[key] for r in rows if r.get(key) is not None]
        return round(statistics.mean(vals), 3) if vals else None
    return {
        "n_events_traded": len(rows),
        "mean_delay_trading_days": mean("delay_trading_days"),
        "n_exits_after_next_entry": sum(1 for r in rows
                                        if r["exit_after_next_entry"]),
        "mean_excess_net_actual_pct": mean("excess_net_actual_pct"),
        "mean_excess_net_scheduled5_pct": mean("excess_net_scheduled5_pct"),
        "events_beat_spy_actual": sum(1 for r in rows
                                      if (r["excess_gross_actual_pct"] or -9) > 0),
        "events_beat_spy_scheduled5": sum(
            1 for r in rows
            if (r["excess_gross_scheduled5_pct"] or -9) > 0),
        "per_event": rows}

def main():
    t0 = time.time()
    summary = {}
    for road, (start, end, spy_pub) in ROADS.items():
        spy = spy_net(start, end)
        assert spy == spy_pub, f"SPY mismatch {road}: {spy} != {spy_pub}"
        print(f"{road} SPY verified ${spy}", flush=True)
        for cad in CADENCES:
            r = run(start, end, cad, M.ranked_picker)
            twins = []
            for seed in range(1, 21):
                pr = run(start, end, cad, M.make_placebo_picker(seed))
                twins.append({"seed": seed, "final": pr["final"],
                              "costs": pr["costs"], "orders": pr["orders"],
                              "halt_dates": pr["halts"]})
            beaten = sum(1 for t in twins if t["final"] < r["final"])
            art = artifact_stats(r["events"])
            cell = {
                "slug": "novel-x3-window-dressing", "run": "confirmation",
                "road": road, "window": [start, end], "cadence": cad,
                "cadence_class": "event-driven",
                "cadence_treatment": "identical to sweep: entries never gated; cadence governs exit rhythm + floor checks",
                "start_pot": 100.0, "final": r["final"],
                "cagr_pct": r["cagr_pct"], "max_dd_pct": r["max_dd_pct"],
                "costs": r["costs"], "orders": r["orders"],
                "halts": len(r["halts"]),
                "halt_records": [{"signal_date": h} for h in r["halts"]],
                "restart": r["restart"], "restart_record": r["restart_info"],
                "second_halt": r["second_halt"],
                "spy_final": spy, "beats_spy": r["final"] > spy,
                "placebo_beaten": beaten, "placebo_twins": twins,
                "placebo_note": "Design's own placebo: uniform 5 names from the same quarter's rankable set, seeds 1..20, same cadence + v9 wrapper",
                "n_events": r["event_stats"]["n_events"],
                "event_stats": r["event_stats"],
                "artifact": {k: v for k, v in art.items() if k != "per_event"},
                "events": r["events"], "artifact_per_event": art["per_event"],
                "equity_curve": r["curve"]}
            fn = os.path.join(HERE, f"{road.lower()}-{cad}.json")
            json.dump(cell, open(fn, "w"), indent=1)
            summary[f"{road}-{cad}"] = {
                "final": r["final"], "spy": spy, "placebo_beaten": beaten,
                "events": r["event_stats"]["n_events"],
                "mean_net_excess": r["event_stats"]["mean_excess_net_pct"],
                "artifact": cell["artifact"]}
            print(road, cad, "final", r["final"], "SPY", spy, "placebo",
                  beaten, "/20 events", r["event_stats"]["n_events"],
                  "meanNetExcess", r["event_stats"]["mean_excess_net_pct"],
                  "sched5Net", art["mean_excess_net_scheduled5_pct"],
                  "afterNext", art["n_exits_after_next_entry"],
                  f"({time.time()-t0:.0f}s)", flush=True)

    folds = {}
    for y in range(2017, 2027):
        days = [d for d in CAL if d[:4] == str(y)]
        s, e = days[0], days[-1]
        spy = spy_net(s, e)
        r = run(s, e, "monthly", M.ranked_picker)
        folds[str(y)] = {
            "year": y, "window": [s, e], "cadence": "monthly",
            "start_pot": 100.0, "final": r["final"],
            "cagr_pct": r["cagr_pct"], "max_dd_pct": r["max_dd_pct"],
            "costs": r["costs"], "orders": r["orders"],
            "halts": len(r["halts"]),
            "halt_records": [{"signal_date": h} for h in r["halts"]],
            "restart": r["restart"], "restart_record": r["restart_info"],
            "second_halt": r["second_halt"], "spy_final": spy,
            "beats_spy": r["final"] > spy, "beats_100": r["final"] > 100.0,
            "n_events": r["event_stats"]["n_events"],
            "event_stats": r["event_stats"], "events": r["events"],
            "equity_curve": r["curve"]}
        print("fold", y, "final", r["final"], "SPY", spy,
              "events", r["event_stats"]["n_events"],
              f"({time.time()-t0:.0f}s)", flush=True)
    json.dump({"slug": "novel-x3-window-dressing", "run": "confirmation",
               "cadence": "monthly", "folds": folds},
              open(os.path.join(HERE, "folds.json"), "w"), indent=1)
    json.dump(summary, open(os.path.join(HERE, "summary.json"), "w"), indent=1)
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
