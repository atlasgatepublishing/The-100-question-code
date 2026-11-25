#!/usr/bin/env python3
"""HOLDINGS-COUNT SWEEP — donchian-basket NATIVE form (full Turtle system).
Frozen rendering (SWEEP-SPEC.md, written before runs): the ONLY varied
parameter is the total concurrent UNITS cap (published native = 12).
Unit sizing (1% risk / 1N), 2N stops, 1/2N pyramiding, per-market cap 4,
group caps 6, loss rule, cash gross cap, costs, fills — all unchanged
(native_engine.py = v11 engine copy with total_cap parameterised).
ALL-ELIGIBLE = total_cap 10**9 (per-market/group caps still bind).
Grid: 1,2,3,5,8,10,15,20,30,ALL + off-grid native check cell 12.
Roads: DECADE/CONT/VAL + CONF_A/CONF_B (confirmation windows, all counts).
Placebos: 20 seeds, DECADE only (PEAD precedent), v11 placebo design.
Systems 1 and 2 both run. Output: native_results.json in this folder.
"""
import json, os, statistics, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import native_engine as T

HERE = os.path.dirname(os.path.abspath(__file__))
COUNTS = [1, 2, 3, 5, 8, 10, 15, 20, 30, None]  # None = ALL-ELIGIBLE
def _snap(a, b):
    days = [d for d in T.DATES if a <= d <= b]
    return days[0], days[-1]

WINDOWS = {"DECADE": ("2016-11-21", "2026-11-20"),
           "CONT": ("2019-01-02", "2026-11-20"),
           "VAL": ("2023-01-03", "2026-11-20"),
           "CONF_A": _snap("2017-01-01", "2020-12-31"),
           "CONF_B": _snap("2021-01-01", "2024-12-31")}

def cap_of(n):
    return 10**9 if n is None else n

def period_stats(curve):
    bym = {}
    for pt in curve:
        bym[pt["d"][:7]] = pt["eq"]
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
    out = {"form": "native-turtle", "native_count_total_units": 12,
           "counts_grid": ["ALL" if c is None else c for c in COUNTS],
           "systems": {}}
    # off-grid native reproduction check (cap 12)
    chk = {}
    for w, (a, b) in WINDOWS.items():
        if w.startswith("CONF"): continue
        chk[w] = {f"system{s}": T.run(a, b, s, total_cap=12)["final"] for s in (1, 2)}
    out["native_check_cap12"] = chk
    print("cap12 check:", chk, flush=True)
    for system in (1, 2):
        cells = {}
        for n in COUNTS:
            key = "ALL" if n is None else str(n)
            cell = {}
            for w, (a, b) in WINDOWS.items():
                r = T.run(a, b, system, total_cap=cap_of(n))
                cell[w] = {k: v for k, v in r.items() if k != "curve"}
                if w == "DECADE":
                    cell[w]["curve"] = r["curve"]
                    cell[w]["period_stats_monthly"] = period_stats(r["curve"])
            a, b = WINDOWS["DECADE"]
            twins = [T.run(a, b, system, placebo_seed=5500 + 31 * system + k,
                           total_cap=cap_of(n))["final"] for k in range(20)]
            real = cell["DECADE"]["final"]
            cell["placebos_decade"] = {"finals": twins,
                "beaten": sum(1 for t in twins if real > t),
                "median": round(statistics.median(twins), 2)}
            cells[key] = cell
            print(f"S{system} cap {key}: DECADE {cell['DECADE']['final']} "
                  f"CONT {cell['CONT']['final']} VAL {cell['VAL']['final']} "
                  f"plb {cell['placebos_decade']['beaten']}/20", flush=True)
        out["systems"][f"system{system}"] = cells
    json.dump(out, open(os.path.join(HERE, "native_results.json"), "w"), indent=1)
    print("saved native_results.json")

if __name__ == "__main__":
    main()
