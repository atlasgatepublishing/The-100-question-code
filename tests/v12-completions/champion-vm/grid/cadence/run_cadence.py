#!/usr/bin/env python3
"""CADENCE GRID — champion-vm (Value+Momentum, native count 5, house rules).
Second-Chance Protocol slice. DECADE 2016-11-21 -> 2026-11-20.
Reuses the holdings-champion-vm engine (read-only import) whose house
count-5 quarterly cell reproduces the champion DECADE $667.35 to the cent.
Cadence = re-rank / re-pick frequency (v10 uniform definition): AMP scores
(book-to-market from PIT EDGAR facts as of the cadence date + 12-1 momentum
to that date) are computed at each cadence date; trades happen only then.
Costs: 0.10%/side + $0.01/sell order. v9 house floor as in the parent engine.
Placebos: 20 seeds per cell, random 5-name draws from the same scored pool.
"""
import importlib.util, json, os, sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/holdings-champion-vm/run_sweep.py")

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

M = load("champ_engine", BASE)
START, END = "2016-11-21", "2026-11-20"
CONT = ("2019-01-02", "2026-11-20")
CADENCES = ["daily","weekly","biweekly","monthly","quarterly","semiannual","annual"]

def cadence_dates(pb, cad, start, end):
    days = [d for d in pb.dates if start <= d <= end]
    if cad == "daily": return days
    out, seen = [], set()
    for d in days:
        y, m = int(d[:4]), int(d[5:7])
        iso = date.fromisoformat(d).isocalendar()
        if cad == "weekly": k = (iso[0], iso[1])
        elif cad == "biweekly": k = (iso[0], iso[1] // 2)
        elif cad == "monthly": k = (y, m)
        elif cad == "quarterly":
            if m not in (1,4,7,10): continue
            k = (y, m)
        elif cad == "semiannual":
            if m not in (1,7): continue
            k = (y, m)
        elif cad == "annual":
            if m != 1: continue
            k = (y,)
        if k not in seen: seen.add(k); out.append(d)
    return out

def run_window(pb, pit_eq, pit_sh, universe, start, end, cadences):
    cells = {}
    for cad in cadences:
        sel = cadence_dates(pb, cad, start, end)
        dec = M.compute_decisions(pb, pit_eq, pit_sh, universe, sel)
        r = M.run_house(pb, dec, sel, start, end, 5)
        diag = M.diagnostics(r["curve"])
        pfin = []
        for seed in range(1, 21):
            pr = M.run_house(pb, dec, sel, start, end, 5, placebo_seed=seed)
            pfin.append(round(pr["final"], 2))
        beaten = sum(1 for v in pfin if r["final"] > v)
        cells[cad] = {"final": round(r["final"],2), "costs": round(r["costs"],2),
                      "orders": r["orders"], "halts": r["halts"],
                      "max_dd_pct": diag["max_dd_pct"],
                      "placebo_beaten": beaten, "placebo_finals": pfin,
                      "n_selection_dates": len(sel),
                      "curve": [[d, round(v,2)] for d,v in r["curve"]],
                      "period_stats": M.period_distribution(r["curve"], sel)}
        print(f"{start} {cad}: ${cells[cad]['final']} DD {diag['max_dd_pct']}% placebo {beaten}/20 sel {len(sel)}", flush=True)
    return cells

def main():
    pb, pit_eq, pit_sh, universe = M.build_fixed_inputs()
    out = {"family": "champion-vm", "label": "Champion Value+Momentum, native count 5, house (v9) rules",
           "window": [START, END], "native_cadence": "quarterly",
           "native_cadence_credited": {"final": 667.35, "source": "holdings-champion-vm/results.json house count-5 DECADE (published champion record)"},
           "spy_decade": 367.80, "cells": {}}
    out["cells"] = run_window(pb, pit_eq, pit_sh, universe, START, END, CADENCES)
    # confirmation: any non-native cadence beating native quarterly on DECADE
    nat = out["cells"]["quarterly"]["final"]
    live = [c for c in CADENCES if c != "quarterly" and out["cells"][c]["final"] > nat]
    out["confirmation"] = {}
    for cad in live:
        conf = run_window(pb, pit_eq, pit_sh, universe, CONT[0], CONT[1], [cad, "quarterly"])
        out["confirmation"][cad] = {"window": list(CONT), "cells": conf,
            "beats_native_on_CONT": conf[cad]["final"] > conf["quarterly"]["final"]}
        print(f"CONFIRM {cad} on CONT: {conf[cad]['final']} vs quarterly {conf['quarterly']['final']}", flush=True)
    with open(os.path.join(HERE, "cadence_results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("saved cadence_results.json")

if __name__ == "__main__":
    main()
