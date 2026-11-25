#!/usr/bin/env python3
"""V13 best-rules run — Choi DGA. Monthly chassis replicating the v12 gate
implementation exactly; sizing per BEST-RULES-SPEC.md (frozen):
risk-on 50/50 QQQ/SCHD; risk-off split when both legs qualify; no floor.
Costs 0.10%/side on turnover, $100 pots, cash earns BIL."""
import json, os, sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
FOLDER = os.path.dirname(HERE)
SHARED = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/catalog-taa-classical-aa/data")
DATA = os.path.join(FOLDER, "data")
COST = 0.001
END = pd.Timestamp("2026-11-20")
ROADS = {"LONG": "2010-01-01", "DECADE": "2016-01-01", "CONT": "2019-01-01", "VAL": "2023-01-01"}
CHAMP = {"LONG": 1415.62, "CONT": 544.47, "VAL": 288.05, "DECADE": 667.35}
SPY_REF = {"LONG": 822.94, "CONT": 313.62, "VAL": 187.77, "DECADE": 367.80}

def daily(tk):
    df = pd.read_csv(os.path.join(SHARED, tk + ".csv"), parse_dates=["date"])
    return df.set_index("date")["adjclose"].sort_index()

def monthly(s):
    m = s.resample("M").last().dropna()
    m.index = m.index.to_period("M").to_timestamp("M")
    return m

P = {tk: monthly(daily(tk)) for tk in ("SPY", "QQQ", "TIP", "TLT", "DBC", "BIL")}
schd = pd.read_csv(os.path.join(DATA, "SCHD.csv"), parse_dates=["date"]).set_index("date")["adjclose"].sort_index()
P["SCHD"] = monthly(schd)
spy_y = pd.read_csv(os.path.join(DATA, "SPY_yahoo.csv"), parse_dates=["date"]).set_index("date").sort_index()
SPY_CLOSE_M = monthly(spy_y["close"])
SPYDIV = pd.read_csv(os.path.join(DATA, "spy_div_monthly.csv"), index_col=0, parse_dates=True).iloc[:, 0]
SPYDIV.index = SPYDIV.index.to_period("M").to_timestamp("M")

def fred_m(name):
    df = pd.read_csv(os.path.join(SHARED, name + ".csv"))
    df.columns = ["date", "v"]
    df["date"] = pd.to_datetime(df["date"])
    s = pd.to_numeric(df.set_index("date")["v"], errors="coerce")
    m = s.resample("M").last()
    m.index = m.index.to_period("M").to_timestamp("M")
    return m

D10, D3 = fred_m("DGS10"), fred_m("DGS3MO")
CASH_R = P["BIL"].pct_change()

def ret(t, tk, m):
    s = P[tk]
    if t not in s.index: return None
    i = s.index.get_loc(t)
    if i < m: return None
    return s.iloc[i] / s.iloc[i - m] - 1

def avg_ret(t, tk, months):
    vals = [ret(t, tk, m) for m in months]
    if any(v is None for v in vals): return None
    return float(np.mean(vals))

def gates(t):
    """Published gates, v12 implementation replicated. Returns True/False/None."""
    s = P["TIP"]
    if t not in s.index: return None
    idx = s.index.get_loc(t)
    if idx < 15: return None
    risk_on = bool(s.iloc[idx] > s.iloc[idx - 12:idx].mean())
    if risk_on:
        spy = SPY_CLOSE_M
        if t not in spy.index: return None
        si = spy.index.get_loc(t)
        if si < 13: return None
        div_ttm = SPYDIV.reindex(spy.index).fillna(0).iloc[si - 13:si - 1].sum()
        if div_ttm / spy.iloc[si - 1] < 0.016:
            risk_on = False
        else:
            for k in range(7, 16):
                tt = s.index[idx - k]
                if tt in D10.index and tt in D3.index and D10[tt] < D3[tt] - 0.5:
                    risk_on = False
    return risk_on

def def_mom(t, tk):
    s = P[tk]
    if t not in s.index: return None
    i = s.index.get_loc(t)
    if i < 6: return None
    return s.iloc[i] / s.iloc[i - 6:i].mean() - 1

def choi_published(t):
    ro = gates(t)
    if ro is None: return {}
    if ro:
        a = avg_ret(t, "QQQ", [1, 3, 6, 9, 12]); b = avg_ret(t, "SCHD", [1, 3, 6, 9, 12])
        if a is None or b is None: return {}
        return {"QQQ": 1.0} if a >= b else {"SCHD": 1.0}
    best, bestv = None, 0.0
    for a in ("TLT", "DBC"):
        v = def_mom(t, a)
        if v is not None and v > bestv: bestv, best = v, a
    return {best: 1.0} if best else {}

def choi_best(t):
    ro = gates(t)
    if ro is None: return {}
    if ro:
        if t not in P["SCHD"].index or t not in P["QQQ"].index: return {}
        return {"QQQ": 0.5, "SCHD": 0.5}
    pos = [a for a in ("TLT", "DBC") if (def_mom(t, a) or -1) > 0]
    if len(pos) == 2: return {"TLT": 0.5, "DBC": 0.5}
    if len(pos) == 1: return {pos[0]: 1.0}
    return {}

def static_mix(t):
    if t in P["SCHD"].index: return {"QQQ": 0.5, "SCHD": 0.5}
    return {"QQQ": 1.0}

def spy_hold(t):
    return {"SPY": 1.0}

def simulate(signal_fn, start, end=END, placebo_seed=None):
    start = pd.Timestamp(start)
    idx = P["SPY"].index
    idx = idx[(idx >= start) & (idx <= end)]
    months = list(idx)
    eq, curve, weights, total_cost = 100.0, {}, {}, 0.0
    rng = np.random.default_rng(placebo_seed) if placebo_seed is not None else None
    pool = ["QQQ", "SCHD", "TLT", "DBC"]
    for i, t in enumerate(months):
        curve[t] = eq
        if i == len(months) - 1: break
        t1 = months[i + 1]
        if rng is not None:
            k = int(rng.integers(1, len(pool) + 1))
            pick = rng.choice(pool, size=k, replace=False)
            w = rng.dirichlet(np.ones(k))
            new_w = {a: float(x) for a, x in zip(pick, w)}
        else:
            new_w = {k2: float(v) for k2, v in signal_fn(t).items() if abs(v) > 1e-9}
        allk = set(weights) | set(new_w)
        turn = sum(abs(new_w.get(k2, 0) - weights.get(k2, 0)) for k2 in allk)
        c = eq * turn * COST; total_cost += c; eq -= c
        crv = CASH_R.get(t1, 0.0)
        if crv is None or pd.isna(crv): crv = 0.0
        r = (1 - sum(new_w.values())) * crv
        for k2, w in new_w.items():
            s = P[k2]
            r += w * (s[t1] / s[t] - 1) if (t in s.index and t1 in s.index) else w * crv
        eq *= (1 + r); weights = new_w
    return pd.Series(curve), total_cost

def period_stats(eq):
    r = eq.pct_change().dropna()
    if len(r) == 0: return {}
    ls = cur = 0
    for x in r:
        cur = cur + 1 if x <= 0 else 0; ls = max(ls, cur)
    run_max = eq.cummax(); below = eq < run_max - 1e-9
    lb = cur = 0
    for x in below:
        cur = cur + 1 if x else 0; lb = max(lb, cur)
    return {"n_periods": int(len(r)), "share_positive": round(float((r > 0).mean()), 3),
            "median_period": round(float(r.median()), 4), "mean_period_secondary": round(float(r.mean()), 4),
            "best": round(float(r.max()), 4), "worst": round(float(r.min()), 4),
            "longest_losing_streak": int(ls), "longest_below_high_months": int(lb),
            "max_dd": round(float((eq / run_max - 1).min()), 4)}

def main():
    out = {"family": "catalog-taa-choi-dividend-growth-alloc", "form": "v13 best rules (spec frozen)",
           "roads": {}, "published_form_rebuilt": {}, "references": {}, "placebos": {}}
    for road, st in ROADS.items():
        eq, cost = simulate(choi_best, st)
        out["roads"][road] = {"final": round(float(eq.iloc[-1]), 2), "cost": round(float(cost), 2),
                              "stats": period_stats(eq),
                              "curve": {str(k.date()): round(float(v), 4) for k, v in eq.items()}}
        eqp, _ = simulate(choi_published, st)
        out["published_form_rebuilt"][road] = {"final": round(float(eqp.iloc[-1]), 2), "stats": period_stats(eqp)}
        eqs, _ = simulate(spy_hold, st)
        eqm, _ = simulate(static_mix, st)
        out["references"][road] = {"spy_rebuilt": round(float(eqs.iloc[-1]), 2), "spy_reference_v12": SPY_REF[road],
                                   "static_mix_QQQ_SCHD_50_50": round(float(eqm.iloc[-1]), 2),
                                   "static_mix_stats": period_stats(eqm), "champion_VM": CHAMP[road]}
        print(road, "best", out["roads"][road]["final"], "published-rebuilt", out["published_form_rebuilt"][road]["final"],
              "spy", out["references"][road]["spy_rebuilt"], "mix", out["references"][road]["static_mix_QQQ_SCHD_50_50"],
              "dd", out["roads"][road]["stats"]["max_dd"])
    for road in ("LONG", "CONT"):
        finals = []
        for seed in range(20):
            eqp, _ = simulate(choi_best, ROADS[road], placebo_seed=seed)
            finals.append(float(eqp.iloc[-1]))
        beats = int(sum(1 for f in finals if out["roads"][road]["final"] > f))
        out["placebos"][road] = {"beats": beats, "median_placebo": round(float(np.median(finals)), 2)}
        print("placebo", road, beats, "/20 median", out["placebos"][road]["median_placebo"])
    # Confirmation only if a champion is beaten (frozen bars in spec)
    beaten = [r for r in ROADS if out["roads"][r]["final"] > CHAMP[r]]
    out["champion_roads_beaten"] = beaten
    if beaten:
        conf = {}
        for nm, (a, b) in {"half1_2010_2018": ("2010-01-01", "2018-12-31"), "half2_2019_2026": ("2019-01-01", "2026-11-20")}.items():
            eq, _ = simulate(choi_best, a, pd.Timestamp(b)); eqs, _ = simulate(spy_hold, a, pd.Timestamp(b))
            conf[nm] = {"final": round(float(eq.iloc[-1]), 2), "spy": round(float(eqs.iloc[-1]), 2), "max_dd": period_stats(eq)["max_dd"]}
        yrs = {}
        for y in range(2010, 2027):
            eq, _ = simulate(choi_best, f"{y}-01-01", pd.Timestamp(f"{y}-12-31"))
            eqs, _ = simulate(spy_hold, f"{y}-01-01", pd.Timestamp(f"{y}-12-31"))
            yrs[str(y)] = {"final": round(float(eq.iloc[-1]), 2), "spy": round(float(eqs.iloc[-1]), 2)}
        conf["yearly_folds"] = yrs
        out["confirmation"] = conf
        print("CONFIRMATION RUN:", json.dumps(conf, indent=1))
    with open(os.path.join(FOLDER, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("done")

if __name__ == "__main__":
    main()
