#!/usr/bin/env python3
"""V13 best-rules run for catalog-taa-keller-daa. See BEST-RULES-SPEC.md (frozen
before this run). Monthly chassis identical to the v12 record: signals at
month-end close, rebalance at that close, cost 0.10% of traded value,
point-in-time only. Forms:
  protected   = DAA exactly as published (canary b-logic, top6/top3/cash)
  unprotected = same 13612W ranking, same risk universe, always top-6 EW,
                canary amputated (isolates the protection's contribution)
Benchmarks: SPY buy-and-hold; static mix = equal-weight buy-and-hold of the
12 risk assets, never rebalanced. Placebos: 20 seeds, protected form.
"""
import json, os
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
FOLDER = os.path.dirname(HERE)
DATA = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/catalog-taa-keller-daa/data")
COST = 0.001
END = "2026-11-20"
ROADS = {"LONG": "2010-01-01", "DECADE": "2016-01-01", "CONT": "2019-01-01", "VAL": "2023-01-01"}
CHAMP = {"LONG": 1415.62, "CONT": 544.47, "VAL": 288.05, "DECADE": 667.35}
RISK = ["SPY", "QQQ", "IWM", "VGK", "EWJ", "VWO", "VNQ", "GSG", "GLD", "TLT", "HYG", "LQD"]
CASHU = ["SHY", "IEF", "LQD"]
HOLDABLE = RISK + ["SHY", "IEF"]

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

def m13612w(i, t):
    if i < 12: return np.nan
    p = ME[t]
    return (12 * (p.iloc[i] / p.iloc[i-1] - 1) + 4 * (p.iloc[i] / p.iloc[i-3] - 1)
            + 2 * (p.iloc[i] / p.iloc[i-6] - 1) + (p.iloc[i] / p.iloc[i-12] - 1))

def canary_b(i):
    can = [m13612w(i, "VWO"), m13612w(i, "BND")]
    if any(np.isnan(can)): return None
    return sum(1 for x in can if x <= 0)

def w_protected(i):
    b = canary_b(i)
    if b is None: return {}
    rs = sorted(RISK, key=lambda t: -m13612w(i, t))
    best_cash = max(CASHU, key=lambda t: m13612w(i, t))
    if b == 2: return {best_cash: 1.0}
    if b == 1:
        w = {t: 0.5 / 3 for t in rs[:3]}
        w[best_cash] = w.get(best_cash, 0) + 0.5
        return w
    return {t: 1.0 / 6 for t in rs[:6]}

def w_unprotected(i):
    if np.isnan(m13612w(i, "SPY")): return {}
    rs = sorted(RISK, key=lambda t: -m13612w(i, t))
    return {t: 1.0 / 6 for t in rs[:6]}

WFUN = {"protected": w_protected, "unprotected": w_unprotected}
WCACHE = {}

def simulate(start, end, form="protected", placebo_seed=None):
    start = pd.Timestamp(start); end = pd.Timestamp(end)
    pos = np.where((DAYS >= start) & (DAYS <= end))[0]
    rng = np.random.default_rng(placebo_seed) if placebo_seed is not None else None
    shares = {}; cash = 100.0
    curve_dates = []; curve_vals = []
    for p in pos:
        row = PXV[p]; d = DAYS[p]
        def equity():
            return cash + sum(s * row[COL[t]] for t, s in shares.items() if not np.isnan(row[COL[t]]))
        if p in REBAL_POS or p == pos[0]:
            mi = ME.index.get_indexer([ME.index[ME.index <= d][-1]])[0]
            ck = (form, mi)
            if ck not in WCACHE: WCACHE[ck] = WFUN[form](mi)
            w = WCACHE[ck]
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
        curve_dates.append(d); curve_vals.append(equity())
    return pd.Series(curve_vals, index=pd.DatetimeIndex(curve_dates))

def buyhold(tickers_weights, start, end):
    days = DAYS[(DAYS >= pd.Timestamp(start)) & (DAYS <= pd.Timestamp(end))]
    sub = PX[tickers_weights.keys()].loc[days]
    w = np.array(list(tickers_weights.values()), dtype=float)
    norm = (sub / sub.iloc[0]).values @ w
    return pd.Series(100.0 * norm, index=days)

def defense_stats(start, end):
    """Share of rebalance months at each canary state, over the road."""
    idx = [i for i, d in enumerate(ME.index)
           if pd.Timestamp(start) <= d <= pd.Timestamp(end)]
    bs = [canary_b(i) for i in idx]
    bs = [b for b in bs if b is not None]
    n = len(bs)
    if n == 0: return {}
    inv = np.mean([1.0 if b == 0 else (0.5 if b == 1 else 0.0) for b in bs])
    return {"rebalance_months": n,
            "share_b0_full_risk": round(float(np.mean([b == 0 for b in bs])), 3),
            "share_b1_half_defense": round(float(np.mean([b == 1 for b in bs])), 3),
            "share_b2_full_defense": round(float(np.mean([b == 2 for b in bs])), 3),
            "share_any_defense": round(float(np.mean([b > 0 for b in bs])), 3),
            "mean_risk_invested_fraction": round(float(inv), 3)}

def stats(ec):
    if len(ec) == 0: return {}
    dd = float((ec / ec.cummax() - 1).min())
    m = ec.resample("M").last()
    mr = m.pct_change().dropna()
    streak = cur = 0
    for x in mr:
        cur = cur + 1 if x < 0 else 0; streak = max(streak, cur)
    last_high = 0; maxgap = 0
    cm = m.cummax()
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

def monthly_curve(ec):
    m = ec.resample("M").last()
    return {str(d.date()): round(float(v), 4) for d, v in m.items()}

def main():
    out = {"family": "catalog-taa-keller-daa", "program": "v13-best-rules",
           "roads": {}, "confirmation": None}
    static_w = {t: 1.0 / len(RISK) for t in RISK}
    for road, st in ROADS.items():
        ec_p = simulate(st, END, "protected")
        ec_u = simulate(st, END, "unprotected")
        ec_s = buyhold({"SPY": 1.0}, st, END)
        ec_m = buyhold(static_w, st, END)
        sp, su = stats(ec_p), stats(ec_u)
        beaten = 0
        for seed in range(20):
            ecp = simulate(st, END, "protected", placebo_seed=seed)
            if float(ec_p.iloc[-1]) > float(ecp.iloc[-1]): beaten += 1
        out["roads"][road] = {
            "protected": sp, "unprotected": su,
            "protection_delta_final": round(sp["final"] - su["final"], 2),
            "protection_delta_dd_pp": round(sp["max_dd_pct"] - su["max_dd_pct"], 1),
            "spy": stats(ec_s), "static_mix": stats(ec_m),
            "defense": defense_stats(st, END),
            "placebos_beaten_of_20": beaten,
            "champion_vm": CHAMP[road],
            "curves_monthly": {"protected": monthly_curve(ec_p),
                               "unprotected": monthly_curve(ec_u),
                               "spy": monthly_curve(ec_s),
                               "static_mix": monthly_curve(ec_m)},
        }
        if road == "LONG":
            out["long_daily_curves"] = {
                f: {str(d.date()): round(float(v), 4) for d, v in ec.items()}
                for f, ec in [("protected", ec_p), ("unprotected", ec_u),
                              ("spy", ec_s), ("static_mix", ec_m)]}
        print(road, "protected", sp["final"], "unprotected", su["final"],
              "spy", round(float(ec_s.iloc[-1]), 2), "static", round(float(ec_m.iloc[-1]), 2),
              "placebos", beaten, flush=True)
    # Confirmation (frozen bars): only for roads beating champion V+M.
    conf = {}
    for road, st in ROADS.items():
        if out["roads"][road]["protected"]["final"] > CHAMP[road]:
            folds = {}
            for nm, (a, b) in {"fold_2010_2018": ("2010-01-01", "2018-12-31"),
                               "fold_2019_2026": ("2019-01-01", END)}.items():
                folds[nm] = stats(simulate(a, b, "protected"))
            mid = (pd.Timestamp(st) + (pd.Timestamp(END) - pd.Timestamp(st)) / 2).strftime("%Y-%m-%d")
            halves = {"first_half": stats(simulate(st, mid, "protected")),
                      "second_half": stats(simulate(mid, END, "protected"))}
            conf[road] = {"folds": folds, "half_windows": halves}
    out["confirmation"] = conf or None
    with open(os.path.join(FOLDER, "results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("done")

if __name__ == "__main__":
    main()
