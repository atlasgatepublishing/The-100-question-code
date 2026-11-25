#!/usr/bin/env python3
"""HOLDINGS-COUNT SWEEP — canslim-oneil-judgment JUDGMENT-CONSTRUCTED form (v12 folder).
Count mapping (frozen, PEAD precedent): breakout candidates on a day are
ranked by RS and taken until slots fill — a ranked queue competing for
slots — so count N = max concurrent positions, slice = equity/N,
implemented by setting the source module's MAX_POS = N and
POS_FRAC = 1/N per run. Every other frozen rule is untouched (C/A gates,
RS>=80, M state machine, base/pivot entries, 7.5% stop, +22.5% profit,
8-week rule, program $85 floor ending the road). ALL-ELIGIBLE = no slot
cap at the native 20% slice (cash is the only limit), as in PEAD.
Placebos: the source module's entry-matched design, 20 seeds per cell
per road. VALIDATION: N=5 must reproduce the source results.json finals
(LONG $102.15, DECADE/CONT/VAL $100.00).
"""
import importlib.util, json, os, statistics, time

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/canslim-oneil-judgment/run_judgment.py")
spec = importlib.util.spec_from_file_location("canslim_judg", SRC)
M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)

COUNTS = [1, 2, 3, 5, "NATIVE6", 8, 10, 15, 20, 30, None]
ROADS = M.ROADS
CONF = {"CONF_A": ("2020-01-01", "2023-12-31"), "CONF_B": ("2024-01-01", "2026-11-20")}

def period_stats(curve):
    bym = {}
    for d, v in curve: bym[d[:7]] = v
    keys = sorted(bym); rets = []; prev = 100.0
    for k in keys:
        rets.append(bym[k] / prev - 1); prev = bym[k]
    if not rets: return None
    prof = sum(1 for r in rets if r > 0)
    worst_run = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; worst_run = max(worst_run, cur)
    peak, since, longest = 100.0, 0, 0
    for k in keys:
        if bym[k] >= peak: peak = bym[k]; longest = max(longest, since); since = 0
        else: since += 1
    longest = max(longest, since)
    return {"period": "calendar month", "n_periods": len(rets),
            "pct_profitable": round(100 * prof / len(rets), 1),
            "median_pct": round(statistics.median(rets) * 100, 2),
            "mean_pct_secondary_average": round(statistics.mean(rets) * 100, 2),
            "best_pct": round(max(rets) * 100, 2), "worst_pct": round(min(rets) * 100, 2),
            "longest_losing_run_periods": worst_run,
            "longest_stretch_between_new_highs_periods": longest}

def main():
    t0 = time.time()
    series_by, funds, failures = {}, {}, []
    for t in M.lr.POOL:
        bars = M.load_bars(t)
        if not bars or len(bars) < 300:
            failures.append((t, "no/short price cache")); continue
        facts = M.load_facts_for(t)
        if facts is None:
            failures.append((t, "no facts cache")); continue
        series_by[t] = M.Series(bars)
        funds[t] = M.Fund(facts)
    spy = series_by.get("SPY")
    if spy is None:
        spy = M.Series(M.load_bars("SPY")); series_by["SPY"] = spy
    master = spy.dates
    print(f"universe: {len(series_by)} names ({round(time.time()-t0)}s)", flush=True)
    rs = M.compute_rs({t: s for t, s in series_by.items() if t != "SPY"}, master)
    mstates = M.market_states(spy)
    cands = {}
    for t, s in series_by.items():
        if t == "SPY": continue
        cands[t] = M.breakout_candidates(s)
    print("candidates:", sum(len(v) for v in cands.values()), f"({round(time.time()-t0)}s)", flush=True)
    src = json.load(open(os.path.expanduser(
        "~/workspace/stock-app/backtests/v12-completions/canslim-oneil-judgment/results.json")))
    out = {"family": "canslim-oneil-judgment", "form": "judgment_constructed_v12", "native_count": 6,
           "counts_grid": ["ALL" if c is None else c for c in COUNTS], "cells": {}}
    def run_cell(n, start, end, with_placebos):
        if n is None:
            M.MAX_POS = 10 ** 9; M.POS_FRAC = 0.20; M.PILOT_FRAC = 0.10
        elif n == "NATIVE6":
            M.MAX_POS = 6; M.POS_FRAC = 0.20; M.PILOT_FRAC = 0.10
        else:
            M.MAX_POS = n; M.POS_FRAC = 1.0 / n; M.PILOT_FRAC = 0.5 / n
        days = [d for d in master if d <= end]
        r = M.simulate(days, series_by, rs, mstates, cands, funds, start, end)
        cell = {"final": r["final"], "costs": r["costs"], "orders": r["orders"],
                "halted": r["halted"], "max_dd_pct": r["max_dd_pct"],
                "n_entries": len(r["entries"]), "entries": r["entries"],
                "curve": r["curve"]}
        if with_placebos:
            pfin = []
            for seed in range(20):
                pr = M.simulate(days, series_by, rs, mstates, cands, funds, start, end,
                                placebo_seed=seed, real_entries=r["entries"])
                pfin.append(pr["final"])
            cell["placebo_finals"] = pfin
            cell["placebo_beaten"] = sum(1 for x in pfin if r["final"] > x)
        return cell
    # validation at NATIVE6 (exact original sizing)
    val = {}
    for w in ("LONG", "DECADE"):
        a, b = ROADS[w]
        c = run_cell("NATIVE6", a, b, False)
        val[w] = {"sweep_final": c["final"], "source_final": src["roads"][w]["final"],
                  "match": c["final"] == src["roads"][w]["final"]}
    out["validation_native6"] = val
    print("VALIDATION judgment native6:", val, flush=True)
    for n in COUNTS:
        key = "ALL" if n is None else str(n)
        cell = {}
        for w, (a, b) in {**ROADS, **CONF}.items():
            c = run_cell(n, a, b, True)
            cell[w] = {k: v for k, v in c.items() if k != "curve"}
            if w == "LONG": cell[w]["curve"] = c["curve"]
        out["cells"][key] = cell
        print(f"judgment n={key}: " + " ".join(f"{w} {cell[w]['final']}(e{cell[w]['n_entries']},p{cell[w]['placebo_beaten']})" for w in ROADS) +
              f" ({round(time.time()-t0)}s)", flush=True)
    finals = {k: c["LONG"]["final"] for k, c in out["cells"].items()}
    best = max(finals, key=finals.get)
    out["best_LONG"] = best
    for k in {best, "NATIVE6"}:
        out["cells"][k]["LONG"]["period_stats_monthly"] = period_stats(out["cells"][k]["LONG"]["curve"])
    for c in out["cells"].values(): c["LONG"].pop("curve", None)
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("judgment canslim sweep done", round(time.time() - t0), "s", flush=True)

if __name__ == "__main__":
    main()
