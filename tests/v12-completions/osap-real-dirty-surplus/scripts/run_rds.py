#!/usr/bin/env python3
"""RDS (Landsman et al. 2011) — Route B run per SPEC-FROZEN.md.
OSAP's own portfolio files (CC BY 4.0, Data-Release-2026.10), long-only top
sort bucket, program costs, native + v9-house (-15% floor) rulebooks,
roads LONG/DECADE/CONT/VAL + CONF (2000-2009, different-years window).
Placebo panel: OSAP PlaceboPortsFull top quintile (port 05), 114 signals.
"""
import json, os
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
SPY_PATH = "/home/hatch/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data/px_SPY.json"  # shareholder-yield copy is 0 bytes

COST_ANNUAL = 0.005  # 2 sides x 0.25% per re-formation, frozen in spec

CELLS = [
    # name, file, hold_months
    ("native_tercile_EW_hold12", "PredictorPortsFull.parquet", 12),
    ("holdper_1_tercile", "Alt_HoldPer_1.parquet", 1),
    ("holdper_3_tercile", "Alt_HoldPer_3.parquet", 3),
    ("holdper_6_tercile", "Alt_HoldPer_6.parquet", 6),
    ("holdper_12_tercile", "Alt_HoldPer_12.parquet", 12),
    ("quintile_VW_hold12", "Alt_Quintiles.parquet", 12),
    ("quintile_EW_hold12", "Alt_QuintilesEW.parquet", 12),
    ("decile_VW_hold12", "Alt_Deciles.parquet", 12),
    ("decile_EW_hold12", "Alt_DecilesEW.parquet", 12),
]
ROADS = {  # inclusive month ranges (data ends 2025-12)
    "LONG": ("2010-01", "2025-12"),
    "DECADE": ("2016-01", "2025-12"),
    "CONT": ("2019-01", "2025-12"),
    "VAL": ("2023-01", "2025-12"),
    "CONF_2000_2009": ("2000-01", "2009-12"),
    "FULLHIST": ("1973-07", "2025-12"),
}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPY_REF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}


def top_leg_series(fname, signal="RDS"):
    df = pd.read_parquet(os.path.join(DATA, fname))
    d = df[df.signalname == signal]
    ports = sorted(p for p in d.port.unique() if p != "LS")
    top = d[d.port == ports[-1]].copy()
    top["ym"] = pd.to_datetime(top.date).dt.strftime("%Y-%m")
    s = top.set_index("ym")["ret"].sort_index() / 100.0
    return s[~s.index.duplicated(keep="last")], int(top.Nlong.mean())


def run_series(rets, start, end, hold, house):
    """Compound $100 over months start..end. rets: monthly decimal series.
    Cost: (1-COST_ANNUAL) spread per re-formation -> monthly factor
    (1-COST_ANNUAL)**(1/hold). House: -15% DD from peak at month-end ->
    cash (0%) until next re-formation boundary (July for hold=12; every
    `hold` months elapsed otherwise)."""
    months = [m for m in rets.index if start <= m <= end]
    cf = (1 - COST_ANNUAL) ** (1.0 / hold)
    pot, peak, in_cash = 100.0, 100.0, False
    curve, cash_months = [], 0
    for i, m in enumerate(months):
        if in_cash:
            # re-entry check: July for annual forms, else boundary month
            if hold == 12:
                reenter = m.endswith("-07")
            else:
                reenter = (i % hold == 0)
            if reenter:
                in_cash = False
            else:
                cash_months += 1
                curve.append([m, round(pot, 4)])
                continue
        pot *= (1 + rets[m]) * cf
        peak = max(peak, pot)
        curve.append([m, round(pot, 4)])
        if house and pot <= 0.85 * peak:
            in_cash = True
    return curve, cash_months


def period_stats(curve, months_per_block=1):
    """Distribution stats from a monthly equity curve."""
    vals = [v for _, v in curve]
    rets = [vals[i] / vals[i - 1] - 1 for i in range(1, len(vals))]
    pos = sum(1 for r in rets if r > 0)
    # longest losing run + longest stretch between new highs (months)
    run = mx = 0
    for r in rets:
        run = run + 1 if r <= 0 else 0
        mx = max(mx, run)
    peak, since, mxu = -1, 0, 0
    for v in vals:
        if v >= peak:
            peak, since = v, 0
        else:
            since += 1
            mxu = max(mxu, since)
    return {
        "n_months": len(rets), "pct_positive": round(100 * pos / len(rets), 1) if rets else None,
        "median_month_pct": round(100 * float(np.median(rets)), 2) if rets else None,
        "mean_month_pct_secondary": round(100 * float(np.mean(rets)), 2) if rets else None,
        "best_month_pct": round(100 * max(rets), 2) if rets else None,
        "worst_month_pct": round(100 * min(rets), 2) if rets else None,
        "longest_losing_run_months": mx, "longest_underwater_months": mxu,
        "max_drawdown_pct": round(100 * min(vals[i] / max(vals[: i + 1]) - 1 for i in range(len(vals))), 2),
    }


def annual_blocks(curve):
    """Native tempo: July-June holding-year returns from monthly curve."""
    d = {m: v for m, v in curve}
    blocks = []
    for y in range(1973, 2026):
        a, b = f"{y}-06", f"{y + 1}-06"
        if a in d and b in d:
            blocks.append((f"{y}Jul-{y+1}Jun", d[b] / d[a] - 1))
    if not blocks:
        return None
    rs = [r for _, r in blocks]
    pos = sum(1 for r in rs if r > 0)
    run = mx = 0
    for r in rs:
        run = run + 1 if r <= 0 else 0
        mx = max(mx, run)
    return {
        "n_years": len(rs), "pct_positive": round(100 * pos / len(rs), 1),
        "median_year_pct": round(100 * float(np.median(rs)), 2),
        "mean_year_pct_secondary": round(100 * float(np.mean(rs)), 2),
        "best_year": [blocks[int(np.argmax(rs))][0], round(100 * max(rs), 2)],
        "worst_year": [blocks[int(np.argmin(rs))][0], round(100 * min(rs), 2)],
        "longest_losing_run_years": mx,
    }


def spy_road(start, end):
    rows = json.load(open(SPY_PATH))
    px = {r[0]: r[1] for r in rows}
    prev = [m for m in sorted(px) if m < start]
    if not prev or end not in px:
        return None
    return round(100 * px[end] / px[prev[-1]], 2)


def main():
    # placebo panel: top quintile (port 05) of every placebo signal, OP file
    pl = pd.read_parquet(os.path.join(DATA, "PlaceboPortsFull.parquet"))
    pl["ym"] = pd.to_datetime(pl.date).dt.strftime("%Y-%m")
    placebo_series = {}
    for sig, g in pl[pl.port == "05"].groupby("signalname"):
        s = g.set_index("ym")["ret"].sort_index() / 100.0
        placebo_series[sig] = s[~s.index.duplicated(keep="last")]

    out = {"family": "osap-real-dirty-surplus", "route": "B (OSAP portfolio files)",
           "cost_convention": "0.50% per re-formation (2 sides x 0.25%), spread monthly as (0.995)^(1/hold)",
           "cells": {}, "spy_exact": {r: spy_road(*ROADS[r]) for r in ROADS},
           "champions": CHAMP, "spy_program_ref": SPY_REF}

    for name, fname, hold in CELLS:
        s, nlong = top_leg_series(fname)
        out["cells"][name] = {"file": fname, "hold_months": hold, "mean_Nlong": nlong, "roads": {}}
        for road, (a, b) in ROADS.items():
            for house in (False, True):
                curve, cash_m = run_series(s, a, b, hold, house)
                final = curve[-1][1] if curve else None
                # placebos under identical road/rulebook, hold=12 quintile chassis
                beaten, tot, pfin = 0, 0, []
                for sig, ps in placebo_series.items():
                    pc, _ = run_series(ps, a, b, 12, house)
                    if pc:
                        tot += 1
                        pfin.append(pc[-1][1])
                        if final is not None and final > pc[-1][1]:
                            beaten += 1
                key = f"{road}_{'house' if house else 'native'}"
                out["cells"][name]["roads"][key] = {
                    "final": final, "cash_months": cash_m,
                    "placebos_beaten": f"{beaten}/{tot}",
                    "placebo_median_final": round(float(np.median(pfin)), 2) if pfin else None,
                    "monthly_stats": period_stats(curve),
                    "curve": curve,
                }
        # native-tempo annual blocks on FULLHIST native
        fh = out["cells"][name]["roads"]["FULLHIST_native"]["curve"]
        out["cells"][name]["annual_blocks_FULLHIST_native"] = annual_blocks(fh)
        print(name, {r: out["cells"][name]["roads"][f"{r}_native"]["final"] for r in ("LONG", "DECADE", "CONT", "VAL")}, flush=True)

    with open(os.path.join(ROOT, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("saved results.json; SPY exact:", out["spy_exact"])


if __name__ == "__main__":
    main()
