#!/usr/bin/env python3
"""Supplementary area runs for leveraged-trend (v10 W8): the LONG / CONT /
VAL windows from the original brief, at the two cadences that matter -
monthly (the original engine's form) and daily (Gayed's published form) -
under v9 protection, using the in-folder engine leveraged-trend-v10.py.
Writes area-runs.json (with full curves) beside this script.
"""
import importlib.util, json, os

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "lev_v10", os.path.join(HERE, "leveraged-trend-v10.py"))
L = importlib.util.module_from_spec(spec)
spec.loader.exec_module(L)

WINDOWS = {"LONG": ("2010-01-04", "2026-11-20"),
           "CONT": ("2019-01-02", "2026-11-20"),
           "VAL": ("2023-01-03", "2026-11-20")}

out = {"windows": {}, "spy": {}}
for cad in ("monthly", "daily"):
    L.set_cadence(cad)
    for wname, (s, e) in WINDOWS.items():
        r = L.run_v9(s, e)
        curve = [(d, round(v, 4)) for d, v in r["curve"]]
        cagr, maxdd = L._cell_stats(curve, r["final"])
        out["windows"][f"{wname}_{cad}"] = {
            "cadence": cad, "start": s, "end": e,
            "final": round(r["final"], 2), "cagr_pct": cagr,
            "max_dd_pct": maxdd, "costs": round(r["costs"], 2),
            "orders": r.get("orders", 0),
            "halts": (1 if r["halted"] else 0) + (1 if r["second_halt"] else 0),
            "restart": bool(r["restarts"]),
            "second_halt": bool(r["second_halt"]),
            "ep1_final": round(r["ep1_final"], 2),
            "ep1_halt": r["ep1_halt_info"], "restarts": r["restarts"],
            "second_halt_detail": r["second_halt"], "curve": curve}
        print(cad, wname, out["windows"][f"{wname}_{cad}"]["final"], flush=True)
    for wname, (s, e) in WINDOWS.items():
        out["spy"][wname] = round(L.spy_net(s, e)[0], 2)
print("SPY", out["spy"])
with open(os.path.join(HERE, "area-runs.json"), "w") as f:
    json.dump(out, f, indent=1)
print("DONE")
