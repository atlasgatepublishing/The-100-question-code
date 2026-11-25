#!/usr/bin/env python3
"""V13 Best Rules — RDS exclusion-broad form, per BEST-RULES-SPEC.md (frozen
before this run). Route B chassis inherited from v12: OSAP's own portfolio
files (CC BY 4.0, Data-Release-2026.10), delisting-inclusive, PIT as
constructed. My-rules form: exclude lowest sort bucket, hold all remaining
buckets equal-weight; annual (12-mo) chassis; NO floor; costs 0.50%/yr
(2 sides x 0.25% per June re-formation) as monthly factor 0.995^(1/12).
Placebos: all 114 OSAP placebo signals under the identical generic rule,
plus a fixed 20-seed draw (seeds 1..20). $100 pots.
"""
import json, os
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
VDATA = "/home/hatch/workspace/stock-app/backtests/v12-completions/osap-real-dirty-surplus/data"
SPY_PATH = "/home/hatch/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data/px_SPY.json"
COST_M = 0.995 ** (1.0 / 12)  # 0.50% per annual re-formation, spread monthly

ROADS = {
    "LONG": ("2010-01", "2025-12"),
    "DECADE": ("2016-01", "2025-12"),
    "CONT": ("2019-01", "2025-12"),
    "VAL": ("2023-01", "2025-12"),
    "CONF_2000_2009": ("2000-01", "2009-12"),
    "FULLHIST": ("1973-07", "2025-12"),
}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPY_REF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
# Published form (v12 record, native tercile EW hold12, same costs) — comparison only
PUBLISHED = {"LONG": 307.88, "DECADE": 184.25, "CONT": 173.11, "VAL": 120.32,
             "CONF_2000_2009": 276.89, "FULLHIST": 43775.23}


def exclusion_series(df, signal):
    """Equal average of all non-LS buckets except the lowest bucket."""
    d = df[df.signalname == signal]
    ports = sorted(p for p in d.port.unique() if p != "LS")
    keep = ports[1:]
    piv = d[d.port.isin(keep)].pivot_table(index="date", columns="port", values="ret")
    s = piv.mean(axis=1) / 100.0
    s.index = pd.to_datetime(s.index).strftime("%Y-%m")
    nheld = float(d[d.port.isin(keep)].groupby("date")["Nlong"].sum().mean())
    return s[~s.index.duplicated(keep="last")].sort_index(), keep, nheld


def run_series(rets, start, end):
    months = [m for m in rets.index if start <= m <= end]
    pot, curve = 100.0, []
    for m in months:
        pot *= (1 + rets[m]) * COST_M
        curve.append([m, round(pot, 4)])
    return curve


def period_stats(curve):
    vals = [v for _, v in curve]
    rets = [vals[i] / vals[i - 1] - 1 for i in range(1, len(vals))]
    if not rets:
        return {}
    pos = sum(1 for r in rets if r > 0)
    run = mx = 0
    for r in rets:
        run = run + 1 if r <= 0 else 0
        mx = max(mx, run)
    peak, since, mxu = -1.0, 0, 0
    for v in vals:
        if v >= peak:
            peak, since = v, 0
        else:
            since += 1
            mxu = max(mxu, since)
    return {
        "n_months": len(rets), "pct_positive": round(100 * pos / len(rets), 1),
        "median_month_pct": round(100 * float(np.median(rets)), 2),
        "mean_month_pct_secondary": round(100 * float(np.mean(rets)), 2),
        "best_month_pct": round(100 * max(rets), 2),
        "worst_month_pct": round(100 * min(rets), 2),
        "longest_losing_run_months": mx, "longest_underwater_months": mxu,
        "max_drawdown_pct": round(100 * min(vals[i] / max(vals[: i + 1]) - 1 for i in range(len(vals))), 2),
    }


def annual_blocks(curve):
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
        "years": [[lbl, round(100 * r, 2)] for lbl, r in blocks],
    }


def spy_curve(start, end):
    rows = json.load(open(SPY_PATH))
    px = {r[0]: r[1] for r in rows}
    prev = [m for m in sorted(px) if m < start]
    if not prev:
        return None
    base = px[prev[-1]]
    months = [m for m in sorted(px) if start <= m <= end]
    return [[m, round(100 * px[m] / base, 4)] for m in months]


def yearly_vs_spy(curve, scurve):
    """Calendar-year returns of pot vs SPY (Dec-to-Dec), share of years pot > SPY."""
    def yrs(c):
        d = {m: v for m, v in c}
        out = {}
        for y in range(2000, 2026):
            a, b = f"{y-1}-12", f"{y}-12"
            if a in d and b in d:
                out[y] = d[b] / d[a] - 1
        return out
    a, b = yrs(curve), yrs(scurve or [])
    common = sorted(set(a) & set(b))
    if not common:
        return None
    wins = sum(1 for y in common if a[y] > b[y])
    return {"years": len(common), "years_beating_spy": wins,
            "per_year": [[y, round(100 * a[y], 2), round(100 * b[y], 2)] for y in common]}


def main():
    pred = pd.read_parquet(os.path.join(VDATA, "PredictorPortsFull.parquet"))
    rds, keep, nheld = exclusion_series(pred, "RDS")
    print("RDS exclusion buckets kept:", keep, "mean held names:", round(nheld))

    pl = pd.read_parquet(os.path.join(VDATA, "PlaceboPortsFull.parquet"))
    placebo_series = {}
    for sig in sorted(pl.signalname.unique()):
        try:
            s, _, _ = exclusion_series(pl, sig)
            if len(s) > 100:
                placebo_series[sig] = s
        except Exception:
            pass
    print("placebo signals usable:", len(placebo_series))
    sig_list = sorted(placebo_series)
    seeded = []
    for seed in range(1, 21):
        rng = np.random.default_rng(seed)
        seeded.append(sig_list[int(rng.integers(0, len(sig_list)))])
    print("20-seed placebo draw:", seeded)

    out = {"family": "osap-real-dirty-surplus", "program": "v13-best-rules",
           "form": "EXCLUSION-BROAD: exclude bottom tercile, hold middle+top terciles EW, annual June, no floor",
           "buckets_kept": keep, "mean_held_names": round(nheld, 1),
           "cost_convention": "0.50% per annual re-formation (2x0.25%), monthly factor 0.995^(1/12)",
           "champions": CHAMP, "spy_program_ref": SPY_REF, "published_form_v12": PUBLISHED,
           "seeded_placebos": seeded, "roads": {}}

    for road, (a, b) in ROADS.items():
        curve = run_series(rds, a, b)
        final = curve[-1][1]
        sc = spy_curve(a, b)
        spy_final = sc[-1][1] if sc else None
        pfin = {}
        for sig, ps in placebo_series.items():
            pc = run_series(ps, a, b)
            if pc:
                pfin[sig] = pc[-1][1]
        beaten = sum(1 for v in pfin.values() if final > v)
        seed_beaten = sum(1 for s in seeded if s in pfin and final > pfin[s])
        entry = {
            "final": final, "max_drawdown_pct": period_stats(curve)["max_drawdown_pct"],
            "spy_exact_final": spy_final, "published_form_final": PUBLISHED.get(road),
            "champion_final": CHAMP.get(road),
            "placebos_beaten": f"{beaten}/{len(pfin)}",
            "placebo_median_final": round(float(np.median(list(pfin.values()))), 2) if pfin else None,
            "seeded_placebos_beaten_of_20": seed_beaten,
            "monthly_stats": period_stats(curve),
            "annual_blocks": annual_blocks(curve),
            "yearly_vs_spy": yearly_vs_spy(curve, sc),
            "curve": curve, "spy_curve": sc,
        }
        # half-windows (frozen confirmation bar 2)
        months = [m for m, _ in curve]
        mid = months[len(months) // 2]
        halves = {}
        for lbl, (ha, hb) in {"first_half": (a, months[len(months) // 2 - 1]),
                              "second_half": (mid, b)}.items():
            hc = run_series(rds, ha, hb)
            hs = spy_curve(ha, hb)
            halves[lbl] = {"window": [ha, hb], "final": hc[-1][1] if hc else None,
                           "spy_exact_final": hs[-1][1] if hs else None}
        entry["half_windows"] = halves
        out["roads"][road] = entry
        print(road, "final", final, "maxDD", entry["max_drawdown_pct"], "SPYexact", spy_final,
              "placebos", entry["placebos_beaten"], "seeded", seed_beaten, "/20", flush=True)

    with open(os.path.join(ROOT, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("saved results.json")


if __name__ == "__main__":
    main()
