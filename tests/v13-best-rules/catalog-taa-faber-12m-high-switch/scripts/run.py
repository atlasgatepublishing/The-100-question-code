#!/usr/bin/env python3
"""V13 Best Rules — Faber 12-month-high switch.
Spec: BEST-RULES-SPEC.md (frozen before this run).
Signal (monthly, month-end close): sleeve holds asset if month-end close
>= 0.95 * max daily close over trailing 252 trading days (incl. current);
else sleeve parks in BIL. Five equal 20% sleeves: SPY EFA DBC VNQ GLD.
Cost 0.10% of traded value. $100 pots. Point-in-time only.
Placebos (20 seeds): random-ticker (v12 convention) + random-timing
(per-sleeve coin flip matched to that sleeve's realised on-frequency).
"""
import json, os
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
FOLDER = os.path.dirname(HERE)
DATA = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/catalog-taa-faber-12m-high-switch/data")
COST = 0.001
END = "2026-11-20"
ROADS = {"LONG": "2010-01-01", "DECADE": "2016-01-01", "CONT": "2019-01-01", "VAL": "2023-01-01"}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
ASSETS = ["SPY", "EFA", "DBC", "VNQ", "GLD"]
HOLDABLE = ASSETS + ["IEF", "BIL"]

def load():
    out = {}
    for t in set(ASSETS + ["IEF", "BIL"]):
        df = pd.read_csv(os.path.join(DATA, t + ".csv"), parse_dates=["date"])
        out[t] = df.set_index("date")["adjclose"]
    return pd.DataFrame(out).sort_index()

PX = load()
DAYS = PX.index
_grp = PX.index.to_series().groupby([PX.index.year, PX.index.month])
ME_DATES = [pd.Timestamp(x) for x in _grp.max().values]
ME_SET = set(ME_DATES)
PXV = PX.values
COL = {t: j for j, t in enumerate(PX.columns)}
DAY_POS = {d: i for i, d in enumerate(DAYS)}

def signal_at(d):
    """dict asset->True/False at month-end date d, point-in-time."""
    p = DAY_POS[d]
    if p < 251:
        return None
    out = {}
    for t in ASSETS:
        window = PXV[p - 251:p + 1, COL[t]]
        window = window[~np.isnan(window)]
        if len(window) < 200:
            return None
        out[t] = bool(PXV[p, COL[t]] >= 0.95 * window.max())
    return out

SIGNALS = {}
for d in ME_DATES:
    s = signal_at(d)
    if s is not None:
        SIGNALS[d] = s

def weights_from_signal(sig):
    w = {}
    for t in ASSETS:
        tgt = t if sig[t] else "BIL"
        w[tgt] = w.get(tgt, 0.0) + 0.2
    return w

def simulate(start, end, mode="signal", seed=None):
    start = pd.Timestamp(start); end = pd.Timestamp(end)
    pos = np.where((DAYS >= start) & (DAYS <= end))[0]
    rng = np.random.default_rng(seed) if seed is not None else None
    # matched on-frequency per sleeve for random-timing placebo (this road)
    onfreq = None
    if mode == "randtime":
        months = [d for d in ME_DATES if start <= d <= end and d in SIGNALS]
        onfreq = {t: float(np.mean([SIGNALS[d][t] for d in months])) if months else 0.5 for t in ASSETS}
    shares = {}; cash = 100.0
    dates, vals = [], []
    static_done = False
    for p in pos:
        row = PXV[p]; d = DAYS[p]
        def equity():
            return cash + sum(s * row[COL[t]] for t, s in shares.items() if not np.isnan(row[COL[t]]))
        is_rebal = (d in ME_SET) or (p == pos[0])
        if mode == "static":
            is_rebal = (p == pos[0])
        if is_rebal:
            w = None
            if mode == "signal":
                md = [x for x in ME_DATES if x <= d and x in SIGNALS]
                if md:
                    w = weights_from_signal(SIGNALS[md[-1]])
            elif mode == "static":
                if not static_done:
                    w = {t: 0.2 for t in ASSETS}; static_done = True
            elif mode == "randtime":
                md = [x for x in ME_DATES if x <= d and x in SIGNALS]
                if md:
                    sig = {t: bool(rng.random() < onfreq[t]) for t in ASSETS}
                    w = weights_from_signal(sig)
            elif mode == "randticker":
                md = [x for x in ME_DATES if x <= d and x in SIGNALS]
                if md:
                    base = weights_from_signal(SIGNALS[md[-1]])
                    inv = sum(v for t, v in base.items() if t != "BIL")
                    k = sum(1 for v in base.values() if v > 0.01)
                    pool = [t for t in HOLDABLE if t != "BIL"]
                    picks = list(rng.choice(pool, size=min(k, len(pool)), replace=False))
                    w = {t: inv / len(picks) for t in picks}
                    if inv < 0.999:
                        w["BIL"] = 1 - inv
            if w:
                eq = equity()
                target = {t: eq * v for t, v in w.items()}
                traded = sum(abs(target.get(t, 0.0) - shares.get(t, 0.0) * row[COL[t]])
                             for t in set(target) | set(shares))
                scale = (eq - COST * traded) / eq if eq > 0 else 0
                shares = {t: (target[t] / row[COL[t]]) * scale for t in target if target[t] > 0}
                cash = 0.0
        dates.append(d); vals.append(equity())
    return pd.Series(vals, index=pd.DatetimeIndex(dates))

def spy_road(start, end):
    days = DAYS[(DAYS >= pd.Timestamp(start)) & (DAYS <= pd.Timestamp(end))]
    s = PX["SPY"].loc[days]
    return 100.0 * s / s.iloc[0]

def stats(ec):
    dd = float((ec / ec.cummax() - 1).min())
    m = ec.resample("M").last()
    mr = m.pct_change().dropna()
    streak = cur = 0
    for x in mr:
        cur = cur + 1 if x < 0 else 0; streak = max(streak, cur)
    last_high = 0; maxgap = 0; cm = m.cummax()
    for j in range(len(m)):
        if m.iloc[j] >= cm.iloc[j] - 1e-12: last_high = j
        maxgap = max(maxgap, j - last_high)
    return {"final": round(float(ec.iloc[-1]), 2), "max_dd_pct": round(100 * dd, 1),
            "months": int(len(mr)),
            "share_pos": round(float((mr > 0).mean()), 3) if len(mr) else None,
            "median_month_pct": round(100 * float(mr.median()), 2) if len(mr) else None,
            "avg_month_pct": round(100 * float(mr.mean()), 2) if len(mr) else None,
            "best_month_pct": round(100 * float(mr.max()), 2) if len(mr) else None,
            "worst_month_pct": round(100 * float(mr.min()), 2) if len(mr) else None,
            "longest_losing_streak_months": int(streak),
            "longest_below_high_months": int(maxgap)}

def main():
    out = {"family": "catalog-taa-faber-12m-high-switch", "variant": "v13-best-rules",
           "roads": {}, "confirmation": None}
    beaten_champ = []
    for road, st in ROADS.items():
        ec = simulate(st, END, "signal")
        s = stats(ec)
        spy = spy_road(st, END); ss = stats(spy)
        static = simulate(st, END, "static"); stt = stats(static)
        rt_beaten = 0; rk_beaten = 0; rt_finals = []; rk_finals = []
        for seed in range(20):
            f1 = float(simulate(st, END, "randtime", seed).iloc[-1]); rt_finals.append(round(f1, 2))
            if s["final"] > f1: rt_beaten += 1
            f2 = float(simulate(st, END, "randticker", seed).iloc[-1]); rk_finals.append(round(f2, 2))
            if s["final"] > f2: rk_beaten += 1
        out["roads"][road] = {"mine": s, "spy": {"final": ss["final"], "max_dd_pct": ss["max_dd_pct"]},
                              "static_mix": {"final": stt["final"], "max_dd_pct": stt["max_dd_pct"]},
                              "random_timing_beaten": rt_beaten, "random_timing_finals": rt_finals,
                              "random_ticker_beaten": rk_beaten, "random_ticker_finals": rk_finals,
                              "champion_vm": CHAMP[road],
                              "curve": {str(d.date()): round(float(v), 4) for d, v in ec.items()}}
        if s["final"] > CHAMP[road]:
            beaten_champ.append(road)
        print(road, s, "spy", ss["final"], "static", stt["final"], "RT", rt_beaten, "RK", rk_beaten, flush=True)
    if beaten_champ:
        conf = {}
        for road in beaten_champ:
            st = pd.Timestamp(ROADS[road]); en = pd.Timestamp(END)
            mid = st + (en - st) / 2
            conf[road] = {}
            for nm, (a, b) in {"fold_2010_2018": ("2010-01-01", "2018-12-31"),
                               "fold_2019_2026": ("2019-01-01", END),
                               "half1": (str(st.date()), str(mid.date())),
                               "half2": (str(mid.date()), END)}.items():
                ec = simulate(a, b, "signal"); s = stats(ec)
                spy = spy_road(a, b)
                conf[road][nm] = {"final": s["final"], "max_dd_pct": s["max_dd_pct"],
                                  "spy_final": round(float(spy.iloc[-1]), 2)}
        out["confirmation"] = conf
    with open(os.path.join(FOLDER, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE", {r: out["roads"][r]["mine"]["final"] for r in ROADS}, "champ_beaten:", beaten_champ)

if __name__ == "__main__":
    main()
