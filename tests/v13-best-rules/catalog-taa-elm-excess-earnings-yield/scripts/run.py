#!/usr/bin/env python3
"""V13 best-rules run: catalog-taa-elm-excess-earnings-yield.
Spec: ../BEST-RULES-SPEC.md (frozen before this run).
Signal EXACTLY as published (EEY = 1/CAPE - DFII10, CAPE lagged >=3 months).
ONE chassis change: Merton sizing denominator gamma*sigma^2 = 2*0.182^2.
Monthly month-end rebalance at close, cost 0.10% of traded value, $100 pots.
Data read-only from the v12 family folder.
"""
import json, os
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
FOLDER = os.path.dirname(HERE)
DATA = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/catalog-taa-elm-excess-earnings-yield/data")
COST = 0.001
END = "2026-11-20"
ROADS = {"LONG": "2010-01-01", "DECADE": "2016-01-01", "CONT": "2019-01-01", "VAL": "2023-01-01"}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
DENOM_PUB = 2 * 0.182
DENOM_V13 = 2 * 0.182 ** 2

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

def fred(name):
    df = pd.read_csv(os.path.join(DATA, name + ".csv"))
    df.columns = ["date"] + list(df.columns[1:])
    df["date"] = pd.to_datetime(df["date"])
    return pd.to_numeric(df.set_index("date").iloc[:, 0], errors="coerce")

DFII10 = fred("DFII10"); CAPE = fred("CAPE")

def eey_at(me_date):
    s = CAPE[CAPE.index <= me_date - pd.DateOffset(months=3)]
    if len(s) == 0: return np.nan
    cape = s.iloc[-1]
    t = DFII10[DFII10.index <= me_date]
    if len(t) == 0: return np.nan
    return 1.0 / cape - t.iloc[-1] / 100.0

def w_elm(i, denom):
    e = eey_at(ME.index[i])
    if np.isnan(e): return {}
    w = min(max(e / denom, 0.0), 1.0)
    out = {}
    if w > 0: out["SPY"] = w
    if w < 1: out["TIP"] = 1 - w
    return out

PXV = PX.values
COL = {t: j for j, t in enumerate(PX.columns)}
REBAL_POS = set(PX.index.get_indexer(ME.index))
WCACHE = {}

def simulate(start, end, weight_fn, placebo_seed=None):
    start = pd.Timestamp(start); end = pd.Timestamp(end)
    pos = np.where((DAYS >= start) & (DAYS <= end))[0]
    rng = np.random.default_rng(placebo_seed) if placebo_seed is not None else None
    shares = {}; cash = 100.0; dates = []; vals = []
    for p in pos:
        row = PXV[p]; d = DAYS[p]
        def equity():
            return cash + sum(s * row[COL[t]] for t, s in shares.items() if not np.isnan(row[COL[t]]))
        if p in REBAL_POS or p == pos[0]:
            mi = ME.index.get_indexer([ME.index[ME.index <= d][-1]])[0]
            key = (weight_fn.__name__, mi)
            if key not in WCACHE: WCACHE[key] = weight_fn(mi)
            w = WCACHE[key]
            if w:
                eq = equity()
                if rng is not None:
                    inv = sum(v for t, v in w.items() if t != "BIL")
                    k = sum(1 for v in w.values() if v > 0.01)
                    pool = ["SPY", "TIP"]
                    picks = list(rng.choice(pool, size=min(k, len(pool)), replace=False))
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
            "months": int(len(mr)), "share_pos": round(float((mr > 0).mean()), 3),
            "median_month_pct": round(100 * float(mr.median()), 2),
            "avg_month_pct": round(100 * float(mr.mean()), 2),
            "best_month_pct": round(100 * float(mr.max()), 2),
            "worst_month_pct": round(100 * float(mr.min()), 2),
            "longest_losing_streak_months": int(streak),
            "longest_below_high_months": int(maxgap)}

def main():
    fn_v13 = lambda i: w_elm(i, DENOM_V13)
    fn_v13.__name__ = "elm_v13"
    fn_pub = lambda i: w_elm(i, DENOM_PUB)
    fn_pub.__name__ = "elm_pub"
    fn_static = lambda i: {"SPY": 0.5, "TIP": 0.5}
    fn_static.__name__ = "static5050"
    out = {"family": "catalog-taa-elm-excess-earnings-yield", "program": "v13-best-rules",
           "denominator_v13": DENOM_V13, "denominator_published": DENOM_PUB, "roads": {}}
    curves = {}
    champ_beaten = []
    for road, st in ROADS.items():
        ec = simulate(st, END, fn_v13); s = stats(ec)
        ecp = simulate(st, END, fn_pub); sp = stats(ecp)
        ecs = simulate(st, END, fn_static); ss = stats(ecs)
        spy = spy_road(st, END)
        beaten = 0; pfin = []
        for seed in range(20):
            epl = simulate(st, END, fn_v13, placebo_seed=seed)
            pfin.append(round(float(epl.iloc[-1]), 2))
            if s["final"] > float(epl.iloc[-1]): beaten += 1
        out["roads"][road] = {"v13": s, "published_form_rerun": sp, "static_50_50": ss,
                              "spy_final": round(float(spy.iloc[-1]), 2),
                              "champion_vm": CHAMP[road], "placebos_beaten": beaten,
                              "placebo_finals": pfin}
        curves[road] = {str(d.date()): round(float(v), 4) for d, v in ec.items()}
        if s["final"] > CHAMP[road]: champ_beaten.append(road)
        print(road, "v13", s["final"], "dd", s["max_dd_pct"], "| pub", sp["final"],
              "| static", ss["final"], "| spy", round(float(spy.iloc[-1]), 2), "| pb", beaten)
    out["equity_curves"] = curves
    # average stock weight actually held on LONG road (mechanics diagnostic, post-run reporting)
    ws = [w_elm(i, DENOM_V13).get("SPY", 0.0) for i in range(len(ME))
          if ME.index[i] >= pd.Timestamp(ROADS["LONG"]) and ME.index[i] <= pd.Timestamp(END)]
    wp = [w_elm(i, DENOM_PUB).get("SPY", 0.0) for i in range(len(ME))
          if ME.index[i] >= pd.Timestamp(ROADS["LONG"]) and ME.index[i] <= pd.Timestamp(END)]
    out["avg_spy_weight_LONG"] = {"v13": round(float(np.mean(ws)), 3), "published": round(float(np.mean(wp)), 3)}
    # Confirmation (frozen bars in spec) — only if a champion fell
    out["champion_roads_beaten"] = champ_beaten
    if champ_beaten:
        conf = {}
        windows = {"fold_2010_2018": ("2010-01-01", "2018-12-31"), "fold_2019_2026": ("2019-01-01", END)}
        for road in champ_beaten:
            st = pd.Timestamp(ROADS[road]); en = pd.Timestamp(END)
            mid = st + (en - st) / 2
            windows[f"{road}_half1"] = (str(st.date()), str(mid.date()))
            windows[f"{road}_half2"] = (str(mid.date()), END)
        for nm, (a, b) in windows.items():
            ec = simulate(a, b, fn_v13); spy = spy_road(a, b)
            conf[nm] = {"final": stats(ec)["final"], "spy_final": round(float(spy.iloc[-1]), 2),
                        "beats_spy": bool(ec.iloc[-1] > spy.iloc[-1])}
        out["confirmation"] = conf
        print("CONFIRMATION:", json.dumps(conf))
    with open(os.path.join(FOLDER, "results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("done")

if __name__ == "__main__":
    main()
