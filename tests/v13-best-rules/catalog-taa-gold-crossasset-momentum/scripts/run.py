#!/usr/bin/env python3
"""V13 Best Rules — catalog-taa-gold-crossasset-momentum.
Published construction exactly (monthly: GLD+IEF 12m both > 0 -> 100% GLD,
else BIL), chassis per BEST-RULES-SPEC.md: monthly cadence, binary sizing,
NO floor. Data read-only from the v12 folder. Cost 0.10%/side. $100 pots.
"""
import json, os
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
FOLDER = os.path.dirname(HERE)
DATA = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/catalog-taa-gold-crossasset-momentum/data")
COST = 0.001
END = "2026-11-20"
ROADS = {"LONG": "2010-01-01", "DECADE": "2016-01-01", "CONT": "2019-01-01", "VAL": "2023-01-01"}
CHAMP = {"LONG": 1415.62, "CONT": 544.47, "VAL": 288.05, "DECADE": 667.35}
SPY_REF = {"LONG": 822.94, "CONT": 313.62, "VAL": 187.77, "DECADE": 367.80}

def load_prices():
    out = {}
    for fn in os.listdir(DATA):
        if fn.endswith(".csv") and fn[:-4].isupper() and len(fn) <= 8:
            hdr = pd.read_csv(os.path.join(DATA, fn), nrows=0).columns
            if "adjclose" in hdr:
                df = pd.read_csv(os.path.join(DATA, fn), parse_dates=["date"])
                out[fn[:-4]] = df.set_index("date")["adjclose"]
    return pd.DataFrame(out).sort_index()

PX = load_prices()
_grp = PX.index.to_series().groupby([PX.index.year, PX.index.month])
ME = PX.loc[_grp.max().values]
DAYS = PX.index
PXV = PX.values
COL = {t: j for j, t in enumerate(PX.columns)}
REBAL_POS = set(PX.index.get_indexer(ME.index))
BIL_C = COL["BIL"]
ME_IDX = {d: i for i, d in enumerate(ME.index)}

def ret12(i, t):
    if i < 12: return np.nan
    return ME[t].iloc[i] / ME[t].iloc[i-12] - 1

def target_w(i):
    if i < 12: return {}
    if ret12(i, "GLD") > 0 and ret12(i, "IEF") > 0: return {"GLD": 1.0}
    return {"BIL": 1.0}

def simulate(start, end, placebo_seed=None):
    start = pd.Timestamp(start); end = pd.Timestamp(end)
    pos = np.where((DAYS >= start) & (DAYS <= end))[0]
    rng = np.random.default_rng(placebo_seed) if placebo_seed is not None else None
    shares = {}; cash = 100.0
    dates, vals = [], []
    for p in pos:
        row = PXV[p]; d = DAYS[p]
        def equity():
            return cash + sum(s * row[COL[t]] for t, s in shares.items() if not np.isnan(row[COL[t]]))
        if (p in REBAL_POS) or (p == pos[0]):
            mi = ME_IDX[ME.index[ME.index <= d][-1]]
            w = target_w(mi)
            if w:
                if rng is not None:
                    inv = sum(v for t, v in w.items() if t != "BIL")
                    k = sum(1 for v in w.values() if v > 0.01)
                    pool = ["GLD"]  # holdable universe ex-BIL: GLD only -> degenerate by construction
                    picks = list(rng.choice(pool, size=min(k, len(pool)), replace=False))
                    w = {t: inv / len(picks) for t in picks}
                    if inv < 0.999: w["BIL"] = 1 - inv
                eq = equity()
                target_val = {t: eq * v for t, v in w.items()}
                traded = 0.0; new_shares = {}
                for t in set(target_val) | set(shares):
                    cur = shares.get(t, 0.0) * row[COL[t]]
                    traded += abs(target_val.get(t, 0.0) - cur)
                    if target_val.get(t, 0.0) > 0: new_shares[t] = target_val[t] / row[COL[t]]
                scale = (eq - COST * traded) / eq if eq > 0 else 0
                shares = {t: s * scale for t, s in new_shares.items()}; cash = 0.0
        dates.append(d); vals.append(equity())
    return pd.Series(vals, index=pd.DatetimeIndex(dates))

def bh(ticker, start, end):
    days = DAYS[(DAYS >= pd.Timestamp(start)) & (DAYS <= pd.Timestamp(end))]
    s = PX[ticker].loc[days]
    return 100.0 * s / s.iloc[0]

def static_mix(start, end):
    days = DAYS[(DAYS >= pd.Timestamp(start)) & (DAYS <= pd.Timestamp(end))]
    g = PX["GLD"].loc[days]; f = PX["IEF"].loc[days]
    return 50.0 * g / g.iloc[0] + 50.0 * f / f.iloc[0]

def dist_stats(ec, freq):
    m = ec.resample(freq).last()
    mr = m.pct_change().dropna()
    streak = cur = 0
    for x in mr:
        cur = cur + 1 if x < 0 else 0; streak = max(streak, cur)
    last_high = 0; maxgap = 0
    cm = m.cummax()
    for j in range(len(m)):
        if m.iloc[j] >= cm.iloc[j] - 1e-12: last_high = j
        maxgap = max(maxgap, j - last_high)
    return {"periods": int(len(mr)),
            "median_period_pct": round(100 * float(mr.median()), 2) if len(mr) else None,
            "share_positive": round(float((mr > 0).mean()), 3) if len(mr) else None,
            "best_period_pct": round(100 * float(mr.max()), 2) if len(mr) else None,
            "worst_period_pct": round(100 * float(mr.min()), 2) if len(mr) else None,
            "avg_period_pct_secondary": round(100 * float(mr.mean()), 2) if len(mr) else None,
            "longest_losing_streak": int(streak),
            "longest_below_high_periods": int(maxgap)}

def road_stats(ec):
    dd = float((ec / ec.cummax() - 1).min())
    return {"final": round(float(ec.iloc[-1]), 2), "max_dd_pct": round(100 * dd, 1),
            "monthly": dist_stats(ec, "M"), "yearly": dist_stats(ec, "A")}

def main():
    out = {"family": "catalog-taa-gold-crossasset-momentum", "program": "v13-best-rules",
           "spec": "BEST-RULES-SPEC.md", "roads": {}, "curves": {}}
    for road, st in ROADS.items():
        ec = simulate(st, END)
        s = road_stats(ec)
        benches = {}
        for name, curve in (("spy_bh", bh("SPY", st, END)), ("gld_bh", bh("GLD", st, END)),
                            ("static_50gld_50ief", static_mix(st, END))):
            benches[name] = {"final": round(float(curve.iloc[-1]), 2),
                             "max_dd_pct": round(100 * float((curve / curve.cummax() - 1).min()), 1)}
        beaten = 0
        raw_final = float(ec.iloc[-1])
        for seed in range(20):
            pec = simulate(st, END, placebo_seed=seed)
            if raw_final > float(pec.iloc[-1]) + 1e-9: beaten += 1
        out["roads"][road] = {"strategy": s, "benchmarks": benches,
                              "champion_vm": CHAMP[road], "spy_program_ref": SPY_REF[road],
                              "placebos_beaten_of_20": beaten,
                              "placebo_note": "degenerate by construction: holdable universe ex-BIL is GLD only, draws replicate the strategy"}
        out["curves"][road] = {str(d.date()): round(float(v), 4) for d, v in ec.items()}
        print(road, s["final"], "DD", s["max_dd_pct"], "SPY", benches["spy_bh"]["final"],
              "GLD", benches["gld_bh"]["final"], "MIX", benches["static_50gld_50ief"]["final"],
              "placebo", beaten)
    # confirmation folds run regardless for the record (no road is expected to trigger)
    folds = {}
    for nm, (a, b) in {"fold_2010_2018": ("2010-01-01", "2018-12-31"),
                       "fold_2019_2026": ("2019-01-01", "2026-11-20")}.items():
        ec = simulate(a, b)
        folds[nm] = {"final": round(float(ec.iloc[-1]), 2),
                     "max_dd_pct": round(100 * float((ec / ec.cummax() - 1).min()), 1),
                     "spy_final": round(float(bh("SPY", a, b).iloc[-1]), 2),
                     "gld_final": round(float(bh("GLD", a, b).iloc[-1]), 2)}
    out["folds"] = folds
    print("folds", folds)
    with open(os.path.join(FOLDER, "results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("done")

if __name__ == "__main__":
    main()
