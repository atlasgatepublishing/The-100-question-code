#!/usr/bin/env python3
"""Benchmark ONLY (not a second shot at my rules): the v12 published/
constructed form — all 48 E-type CN cells (4 debt-price series x spans
{41,91,205} x REV/MOM x bands 75/25,90/10), daily, always-in long/short SPY,
cost 0.10% per unit position change — recomputed on the v13 roads with the
same SPY/yield data as run_best.py, so RESULTS.md can print my-rules vs
published-form on identical windows. Representative = the v12 pre-registered
median cell AAA|cn41|mom|90; grid median and fenced best also reported.
Simulation only."""
import csv, json, os
import numpy as np
import run_best as rb

FAM = rb.FAM
SERIES_FILES = {"TB3": "DGS3MO", "TN10": "DGS10", "AAA": "DAAA", "BAA": "DBAA"}
V12DATA = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/"
                             "catalog-aronson-cn-extremes-debt/data")

def load_series(dates, fname):
    obs = {}
    for row in csv.DictReader(open(os.path.join(V12DATA, fname + ".csv"))):
        try: obs[row["observation_date"]] = float(row[fname])
        except Exception: pass
    s = np.full(len(dates), np.nan); last = np.nan
    for i, d in enumerate(dates):
        if d in obs: last = obs[d]
        s[i] = last
    return np.where((s > 0) & ~np.isnan(s), 100.0 / s, np.nan)

def e_positions(series, span, hi, mode):
    s = rb.lma4(rb.cn(series, span))
    pos = np.zeros(len(series)); cur = 0.0
    for i in range(len(series)):
        v = s[i]
        if not np.isnan(v):
            if v >= hi: cur = -1.0 if mode == "rev" else 1.0
            elif v <= 100 - hi: cur = 1.0 if mode == "rev" else -1.0
        pos[i] = cur
    return pos

def main():
    dates, C = rb.fetch_spy()
    ser = {k: load_series(dates, v) for k, v in SERIES_FILES.items()}
    cells = {}
    for nm, sv in ser.items():
        for sp in (41, 91, 205):
            for m in ("rev", "mom"):
                for hi in (75, 90):
                    cells[f"{nm}|cn{sp}|{m}|{hi}"] = e_positions(sv, sp, hi, m)
    out = {"note": "published/constructed v12 form recomputed on v13 roads, same data basis as run_best.py",
           "roads": {}}
    for rname, (a, b) in rb.ROADS.items():
        finals = {}
        rep = None
        for cname, pos in cells.items():
            r = rb.run(pos, dates, C, a, b)
            finals[cname] = r["final"]
            if cname == "AAA|cn41|mom|90": rep = r
        order = sorted(finals, key=finals.get)
        med = order[len(order) // 2]
        out["roads"][rname] = {"representative_cell_AAA_cn41_mom_90": rep,
                               "grid_median_cell": med, "grid_median_final": finals[med],
                               "best_cell_fenced": order[-1], "best_final_fenced": finals[order[-1]],
                               "n_cells": len(finals)}
        print(rname, "rep", rep["final"], "median", med, finals[med],
              "best(fenced)", order[-1], finals[order[-1]], flush=True)
    json.dump(out, open(os.path.join(FAM, "published_benchmark.json"), "w"), indent=1)
    print("DONE")

if __name__ == "__main__":
    main()
