#!/usr/bin/env python3
"""V13 best-rules run for catalog-taa-keller-eaa. See BEST-RULES-SPEC.md (frozen first).
Arms: best (faithful EAA formula, wS=1, 15-asset universe, TopN=5, CP, monthly, no floor),
lite (NEW CONSTRUCTION ablation: z=r only, equal-weight), published_off / published_def
(7-asset rerun for comparator), static 60/40 SPY/BND, SPY buy-hold.
Costs 0.10% of traded value per rebalance. Point-in-time month-end signals only."""
import json, math, os, sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
FOLDER = os.path.dirname(HERE)
DATA = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/catalog-taa-keller-eaa/data")
COST = 0.001
END = "2026-11-20"
ROADS = {"LONG": "2010-01-01", "DECADE": "2016-01-01", "CONT": "2019-01-01", "VAL": "2023-01-01"}
CHAMP = {"LONG": 1415.62, "CONT": 544.47, "VAL": 288.05, "DECADE": 667.35}
U7 = ["SPY", "VEA", "VWO", "GSG", "VNQ", "BND", "SHY"]
U15 = ["SPY", "QQQ", "IWM", "VEA", "VWO", "EWJ", "VNQ", "GSG", "GLD",
       "BND", "TLT", "TIP", "LQD", "HYG", "SHY"]

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
MRET = ME.pct_change()
DAYS = PX.index
PXV = PX.values
COL = {t: j for j, t in enumerate(PX.columns)}
REBAL_POS = set(PX.index.get_indexer(ME.index))
BIL_C = COL["BIL"]

def ret_k(i, t, k):
    if i < k: return np.nan
    return ME[t].iloc[i] / ME[t].iloc[i-k] - 1

def eaa_weights(i, U, ws, lite=False):
    if i < 12: return {}
    rets = MRET[U].iloc[i-11:i+1]
    idx = rets.mean(axis=1)
    sc = {}
    for t in U:
        r = (ret_k(i, t, 1) + ret_k(i, t, 3) + ret_k(i, t, 6) + ret_k(i, t, 12)) / 22.0
        if lite:
            z = r if r > 0 else 0.0
        else:
            v = rets[t].std()  # wV=0 -> term is 1, computed for fidelity
            c = np.corrcoef(rets[t].values, idx.values)[0, 1] if rets[t].std() > 0 else 1.0
            z = (r * math.sqrt(max(1 - c, 0.0))) ** ws if r > 0 else 0.0
        sc[t] = (r, z)
    topn = 1 + math.ceil(math.sqrt(len(U)))
    top = sorted(U, key=lambda t: -sc[t][1])[:topn]
    cp = sum(1 for t in U if sc[t][0] <= 0) / len(U)
    if lite:
        pos = [t for t in top if sc[t][1] > 0]
        if not pos: return {"IEF": 1.0}
        w = {t: (1 - cp) / len(pos) for t in pos}
    else:
        tot = sum(sc[t][1] for t in top)
        if tot <= 0: return {"IEF": 1.0}
        w = {t: (1 - cp) * sc[t][1] / tot for t in top if sc[t][1] > 0}
    if cp > 0: w["IEF"] = w.get("IEF", 0) + cp
    return w

ARMS = {
    "best":          (lambda i: eaa_weights(i, U15, 1.0), U15 + ["IEF"]),
    "lite":          (lambda i: eaa_weights(i, U15, 1.0, lite=True), U15 + ["IEF"]),
    "published_off": (lambda i: eaa_weights(i, U7, 2.0), U7 + ["IEF"]),
    "published_def": (lambda i: eaa_weights(i, U7, 1.0), U7 + ["IEF"]),
    "static_60_40":  (lambda i: {"SPY": 0.6, "BND": 0.4}, ["SPY", "BND"]),
}

def simulate(arm, start, end, placebo_seed=None):
    FN, HOLDABLE = ARMS[arm]
    start = pd.Timestamp(start); end = pd.Timestamp(end)
    pos = np.where((DAYS >= start) & (DAYS <= end))[0]
    rng = np.random.default_rng(placebo_seed) if placebo_seed is not None else None
    shares = {}; cash = 100.0; cd = []; cv = []
    wcache = {}
    for p in pos:
        row = PXV[p]; d = DAYS[p]
        def equity():
            return cash + sum(s * row[COL[t]] for t, s in shares.items() if not np.isnan(row[COL[t]]))
        if p in REBAL_POS or p == pos[0]:
            mi = ME.index.get_indexer([ME.index[ME.index <= d][-1]])[0]
            if mi not in wcache: wcache[mi] = FN(mi)
            w = wcache[mi]
            if w:
                eq = equity()
                if rng is not None:
                    inv = sum(v for t, v in w.items() if t != "BIL")
                    k = sum(1 for v in w.values() if v > 0.01)
                    pool = [t for t in HOLDABLE if t != "BIL"]
                    picks = list(rng.choice(pool, size=min(k, len(pool)), replace=False))
                    w = {t: inv / len(picks) for t in picks}
                    if inv < 0.999: w["BIL"] = 1 - inv
                target_val = {t: eq * v for t, v in w.items()}
                traded = 0.0; new_shares = {}
                for t in set(target_val) | set(shares):
                    cur = shares.get(t, 0.0) * row[COL[t]]
                    traded += abs(target_val.get(t, 0.0) - cur)
                    if target_val.get(t, 0.0) > 0: new_shares[t] = target_val[t] / row[COL[t]]
                scale = (eq - COST * traded) / eq if eq > 0 else 0
                shares = {t: s * scale for t, s in new_shares.items()}; cash = 0.0
        cd.append(d); cv.append(equity())
    return pd.Series(cv, index=pd.DatetimeIndex(cd))

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
            "longest_losing_streak_months": int(streak), "longest_below_high_months": int(maxgap)}

def main():
    out = {"family": "catalog-taa-keller-eaa", "program": "v13-best-rules",
           "spec": "BEST-RULES-SPEC.md", "arms": {}, "champions_vm": CHAMP}
    for arm in ARMS:
        out["arms"][arm] = {}
        for road, st in ROADS.items():
            ec = simulate(arm, st, END)
            s = stats(ec)
            spy = spy_road(st, END)
            entry = {"stats": s, "spy_final": round(float(spy.iloc[-1]), 2)}
            if arm in ("best", "lite"):
                beaten = 0
                for seed in range(20):
                    pec = simulate(arm, st, END, placebo_seed=seed)
                    if s["final"] > float(pec.iloc[-1]): beaten += 1
                entry["placebos_beaten"] = beaten
            if road == "LONG":
                entry["curve"] = {str(d.date()): round(float(v), 4) for d, v in ec.items()}
            out["arms"][arm][road] = entry
            print(arm, road, s["final"], s["max_dd_pct"], entry.get("placebos_beaten"), flush=True)
    # confirmation folds for best arm (printed regardless; binding only if a road beats champion)
    folds = {}
    for nm, (a, b) in {"fold_2010_2018": ("2010-01-01", "2018-12-31"),
                       "fold_2019_2026": ("2019-01-01", "2026-11-20"),
                       "half_LONG_a": ("2010-01-01", "2018-06-29"),
                       "half_LONG_b": ("2018-07-02", "2026-11-20")}.items():
        ec = simulate("best", a, b); s = stats(ec); spy = spy_road(a, b)
        folds[nm] = {"final": s["final"], "max_dd_pct": s["max_dd_pct"],
                     "spy_final": round(float(spy.iloc[-1]), 2)}
    out["best_folds"] = folds
    with open(os.path.join(FOLDER, "results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE", json.dumps({a: {r: out["arms"][a][r]["stats"]["final"] for r in ROADS} for a in ARMS}))

if __name__ == "__main__":
    main()
