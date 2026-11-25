#!/usr/bin/env python3
"""V13 best-rules run: Glenn Quint Switching, simplified one-asset gate.
Spec: BEST-RULES-SPEC.md (frozen before this run).
Monthly chassis: signal at month-end close, rebalance at that close,
cost 0.10% of traded value. NO floor. Data read-only from the v12 folder.
"""
import json, os, sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
FOLDER = os.path.dirname(HERE)
V12 = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/catalog-taa-glenn-quint-switching")
DATA = os.path.join(V12, "data")
COST = 0.001
END = "2026-11-20"
ROADS = {"LONG": "2010-01-01", "DECADE": "2016-01-01", "CONT": "2019-01-01", "VAL": "2023-01-01"}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
RISK = ["SPY", "QQQ", "EFA", "EEM", "TLT"]
HOLDABLE = RISK + ["IEF"]

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
ME_POS = {d: i for i, d in enumerate(ME.index)}

def ret_k(i, t, k=3):
    if i < k: return np.nan
    return ME[t].iloc[i] / ME[t].iloc[i-k] - 1

def weights_v13(i):
    """Best rules: rank five by 3m return; hold winner if its own 3m > 0, else IEF."""
    if i < 3: return {}
    r = {t: ret_k(i, t) for t in RISK}
    best = max(r, key=r.get)
    return {best: 1.0} if r[best] > 0 else {"IEF": 1.0}

def weights_published(i):
    if i < 3: return {}
    r = {t: ret_k(i, t) for t in RISK}
    if any(x <= 0 for x in r.values()): return {"IEF": 1.0}
    return {max(r, key=r.get): 1.0}

def simulate(start, end, wfun, placebo_seed=None):
    start = pd.Timestamp(start); end = pd.Timestamp(end)
    pos = np.where((DAYS >= start) & (DAYS <= end))[0]
    rng = np.random.default_rng(placebo_seed) if placebo_seed is not None else None
    shares = {}; cash = 100.0
    dates, vals = [], []
    wcache = {}
    for p in pos:
        row = PXV[p]; d = DAYS[p]
        def equity():
            return cash + sum(s * row[COL[t]] for t, s in shares.items() if not np.isnan(row[COL[t]]))
        if p in REBAL_POS or p == pos[0]:
            md = ME.index[ME.index <= d][-1]; mi = ME_POS[md]
            if mi not in wcache: wcache[mi] = wfun(mi)
            w = dict(wcache[mi])
            if w:
                eq = equity()
                if rng is not None:
                    inv = sum(v for t, v in w.items() if t != "BIL")
                    k = sum(1 for v in w.values() if v > 0.01)
                    picks = list(rng.choice(HOLDABLE, size=min(k, len(HOLDABLE)), replace=False))
                    w = {t: inv / len(picks) for t in picks}
                    if inv < 0.999: w["BIL"] = 1 - inv
                target = {t: eq * v for t, v in w.items()}
                traded = 0.0; new = {}
                for t in set(target) | set(shares):
                    cur = shares.get(t, 0.0) * row[COL[t]]
                    traded += abs(target.get(t, 0.0) - cur)
                    if target.get(t, 0.0) > 0: new[t] = target[t] / row[COL[t]]
                scale = (eq - COST * traded) / eq if eq > 0 else 0
                shares = {t: s * scale for t, s in new.items()}; cash = 0.0
        dates.append(d); vals.append(equity())
    return pd.Series(vals, index=pd.DatetimeIndex(dates))

def static_mix(start, end):
    return simulate(start, end, lambda i: {t: 0.2 for t in RISK} if i >= 0 else {})

def spy_road(start, end):
    days = DAYS[(DAYS >= pd.Timestamp(start)) & (DAYS <= pd.Timestamp(end))]
    s = PX["SPY"].loc[days]
    return 100.0 * s / s.iloc[0]

def stats(ec):
    dd = float((ec / ec.cummax() - 1).min())
    m = ec.resample("M").last(); mr = m.pct_change().dropna()
    streak = cur = 0
    for x in mr:
        cur = cur + 1 if x < 0 else 0; streak = max(streak, cur)
    last_high = 0; maxgap = 0; cm = m.cummax()
    for j in range(len(m)):
        if m.iloc[j] >= cm.iloc[j] - 1e-12: last_high = j
        maxgap = max(maxgap, j - last_high)
    return {"final": round(float(ec.iloc[-1]), 2), "max_dd_pct": round(100 * dd, 1),
            "months": int(len(mr)), "share_pos": round(float((mr > 0).mean()), 3) if len(mr) else None,
            "median_month_pct": round(100 * float(mr.median()), 2) if len(mr) else None,
            "avg_month_pct": round(100 * float(mr.mean()), 2) if len(mr) else None,
            "best_month_pct": round(100 * float(mr.max()), 2) if len(mr) else None,
            "worst_month_pct": round(100 * float(mr.min()), 2) if len(mr) else None,
            "longest_losing_streak_months": int(streak),
            "longest_below_high_months": int(maxgap)}

def main():
    out = {"family": "catalog-taa-glenn-quint-switching", "program": "v13-best-rules",
           "roads": {}, "confirmation": {}}
    for road, st in ROADS.items():
        ec = simulate(st, END, weights_v13)
        s = stats(ec)
        pub = stats(simulate(st, END, weights_published))
        spy = spy_road(st, END)
        mix = stats(static_mix(st, END))
        beaten = 0; pfin = []
        for seed in range(20):
            pec = simulate(st, END, weights_v13, placebo_seed=seed)
            pfin.append(round(float(pec.iloc[-1]), 2))
            if s["final"] > float(pec.iloc[-1]): beaten += 1
        out["roads"][road] = {"best_rules": s, "published_filtered_recomputed": pub,
                              "spy_final": round(float(spy.iloc[-1]), 2),
                              "static_mix": mix, "placebos_beaten": beaten,
                              "placebo_finals": sorted(pfin),
                              "champion_vm": CHAMP[road],
                              "curve": {str(d.date()): round(float(v), 4) for d, v in ec.items()}}
        print(road, "best", s["final"], "dd", s["max_dd_pct"], "pub", pub["final"],
              "spy", round(float(spy.iloc[-1]), 2), "mix", mix["final"], "placebos", beaten, flush=True)
    # Confirmation (frozen bars) only for roads beating the champion
    for road, st in ROADS.items():
        if out["roads"][road]["best_rules"]["final"] > CHAMP[road]:
            conf = {}
            for nm, (a, b) in {"fold_2010_2018": ("2010-01-01", "2018-12-31"),
                               "fold_2019_2026": ("2019-01-01", "2026-11-20")}.items():
                conf[nm] = {"final": stats(simulate(a, b, weights_v13))["final"],
                            "spy_final": round(float(spy_road(a, b).iloc[-1]), 2)}
            days = DAYS[(DAYS >= pd.Timestamp(st)) & (DAYS <= pd.Timestamp(END))]
            mid = days[len(days) // 2]
            for nm, (a, b) in {"half_1": (st, str(mid.date())), "half_2": (str(mid.date()), END)}.items():
                conf[nm] = {"final": stats(simulate(a, b, weights_v13))["final"],
                            "spy_final": round(float(spy_road(a, b).iloc[-1]), 2)}
            conf["placebos_beaten"] = out["roads"][road]["placebos_beaten"]
            conf["passed"] = all(conf[k]["final"] > conf[k]["spy_final"] for k in
                                 ("fold_2010_2018", "fold_2019_2026", "half_1", "half_2")) \
                             and conf["placebos_beaten"] >= 18
            out["confirmation"][road] = conf
    with open(os.path.join(FOLDER, "results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("done")

if __name__ == "__main__":
    main()
