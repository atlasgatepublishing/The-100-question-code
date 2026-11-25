#!/usr/bin/env python3
"""V13 Best Rules — Clare risk-parity-with-trend.
Monthly chassis replicating v12 engine semantics exactly for Arm A:
signal at month-end close t sets weights held t -> t+1; turnover cost
0.10%/side; uninvested weight earns BIL monthly return.
Vol = std of the 12 monthly pct-changes ending at t (trailing only).
Gate = close above mean of last 10 month-end closes (incl. t).
Arms: A published (failures->cash) | B best-rules (renormalize over
survivors) | C no gate | D no scaler (equal-weight survivors).
"""
import json, os
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
FOLDER = os.path.dirname(HERE)
DATA = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/catalog-taa-classical-aa/data")
COST = 0.001
ASSETS = ["SPY", "IWM", "IEF", "DBC", "VNQ"]
ROADS = {"LONG": ("2010-01-01", "2026-10-31"), "DECADE": ("2016-01-01", "2026-10-31"),
         "CONT": ("2019-01-01", "2026-10-31"), "VAL": ("2023-01-01", "2026-10-31")}
CHAMP = {"LONG": 1415.62, "CONT": 544.47, "VAL": 288.05, "DECADE": 667.35}
SPY_REF = {"LONG": 822.94, "CONT": 313.62, "VAL": 187.77, "DECADE": 367.80}

def load_monthly():
    out = {}
    for t in ASSETS + ["BIL"]:
        df = pd.read_csv(os.path.join(DATA, t + ".csv"), parse_dates=["date"])
        s = df.set_index("date")["adjclose"].sort_index()
        me = s.resample("M").last().dropna()
        me.index = me.index.to_period("M").to_timestamp("M")
        out[t] = me
    return out

P = load_monthly()
IDX = P["SPY"].index  # common month-end calendar (all series share trading days)

def inv_vol(t):
    inv = {}
    for a in ASSETS:
        s = P[a]
        if t not in s.index: return None
        i = s.index.get_loc(t)
        if i < 12: return None
        v = s.iloc[i-12:i+1].pct_change().std()
        if v <= 0 or np.isnan(v): return None
        inv[a] = 1.0 / v
    return inv

def gate_ok(t, a):
    s = P[a]
    i = s.index.get_loc(t)
    if i < 9: return None
    return bool(s.iloc[i] > s.iloc[i-9:i+1].mean())

def weights(t, arm):
    inv = inv_vol(t)
    if inv is None: return {}
    if arm == "C":  # no gate
        tot = sum(inv.values())
        return {a: inv[a] / tot for a in ASSETS}
    passed = [a for a in ASSETS if gate_ok(t, a)]
    if not passed: return {}
    if arm == "A":  # published: normalize over ALL, failures to cash
        tot = sum(inv.values())
        return {a: inv[a] / tot for a in passed}
    if arm == "B":  # renormalize over survivors
        tot = sum(inv[a] for a in passed)
        return {a: inv[a] / tot for a in passed}
    if arm == "D":  # equal weight survivors
        return {a: 1.0 / len(passed) for a in passed}
    raise ValueError(arm)

def period_stats(eq):
    r = eq.pct_change().dropna()
    if len(r) == 0: return {}
    ls = cur = 0
    for x in r:
        cur = cur + 1 if x <= 0 else 0; ls = max(ls, cur)
    run_max = eq.cummax(); below = (eq < run_max - 1e-9)
    lb = cur = 0
    for x in below:
        cur = cur + 1 if x else 0; lb = max(lb, cur)
    dd = (eq / run_max - 1).min()
    return {"n_periods": int(len(r)), "share_positive": round(float((r > 0).mean()), 3),
            "median_period": round(float(r.median()), 4), "mean_period_secondary": round(float(r.mean()), 4),
            "best": round(float(r.max()), 4), "worst": round(float(r.min()), 4),
            "longest_losing_streak": int(ls), "longest_below_high_months": int(lb),
            "max_dd": round(float(dd), 4)}

def simulate(start, end, arm=None, fixed_w=None, placebo_seed=None):
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    months = [t for t in IDX if start <= t <= end]
    bil = P["BIL"]
    rng = np.random.default_rng(placebo_seed) if placebo_seed is not None else None
    eq = 100.0; curve = {}; w_prev = {}; total_cost = 0.0
    for i, t in enumerate(months):
        curve[t] = eq
        if i == len(months) - 1: break
        t1 = months[i + 1]
        if rng is not None:
            k = int(rng.integers(1, len(ASSETS) + 1))
            pick = rng.choice(ASSETS, size=k, replace=False)
            w = {a: float(x) for a, x in zip(pick, rng.dirichlet(np.ones(k)))}
        elif fixed_w is not None:
            w = dict(fixed_w)
        else:
            w = weights(t, arm)
        allk = set(w_prev) | set(w)
        turn = sum(abs(w.get(k, 0) - w_prev.get(k, 0)) for k in allk)
        c = eq * turn * COST; total_cost += c; eq -= c
        crv = bil[t1] / bil[t] - 1 if (t in bil.index and t1 in bil.index) else 0.0
        ret = (1 - sum(w.values())) * crv
        for k, wk in w.items():
            s = P[k]
            ret += wk * (s[t1] / s[t] - 1) if (t in s.index and t1 in s.index) else wk * crv
        eq *= (1 + ret); w_prev = w
    return pd.Series(curve), round(total_cost, 2)

def spy_hold(start, end):
    months = [t for t in IDX if pd.Timestamp(start) <= t <= pd.Timestamp(end)]
    s = P["SPY"]
    return pd.Series({t: 100.0 * s[t] / s[months[0]] for t in months})

def pack(eq, cost=None):
    d = {"final": round(float(eq.iloc[-1]), 2), "stats": period_stats(eq),
         "curve": {str(k.date()): round(float(v), 4) for k, v in eq.items()}}
    if cost is not None: d["cost"] = cost
    return d

def main():
    out = {"family": "catalog-taa-clare-riskparity-trend", "program": "v13-best-rules",
           "arms": {}, "benchmarks": {}, "placebos": {}, "stress_2022": {},
           "champion_VM": CHAMP, "spy_reference_v12": SPY_REF}
    for arm in ["A", "B", "C", "D"]:
        out["arms"][arm] = {}
        for road, (a, b) in ROADS.items():
            eq, cost = simulate(a, b, arm=arm)
            out["arms"][arm][road] = pack(eq, cost)
    for road, (a, b) in ROADS.items():
        eq, cost = simulate(a, b, fixed_w={t: 0.2 for t in ASSETS})
        out["benchmarks"].setdefault("static_mix_equal5", {})[road] = pack(eq, cost)
        out["benchmarks"].setdefault("spy_buyhold", {})[road] = pack(spy_hold(a, b))
    for road in ["LONG", "CONT"]:
        a, b = ROADS[road]
        finals = []
        for seed in range(20):
            eqp, _ = simulate(a, b, placebo_seed=seed)
            finals.append(float(eqp.iloc[-1]))
        fb = out["arms"]["B"][road]["final"]
        out["placebos"][road] = {"beats_of_20": int(sum(1 for f in finals if fb > f)),
                                 "median_placebo": round(float(np.median(finals)), 2),
                                 "placebo_finals": [round(f, 2) for f in finals]}
    for name, fn in [("A", "A"), ("B", "B"), ("C", "C"), ("D", "D")]:
        eq, cost = simulate("2022-01-01", "2022-12-31", arm=fn)
        out["stress_2022"][name] = pack(eq, cost)
    eq, cost = simulate("2022-01-01", "2022-12-31", fixed_w={t: 0.2 for t in ASSETS})
    out["stress_2022"]["static_mix"] = pack(eq, cost)
    out["stress_2022"]["spy_buyhold"] = pack(spy_hold("2022-01-01", "2022-12-31"))
    # Confirmation gate: only if Arm B beats champion on any road
    beats = [r for r in ROADS if out["arms"]["B"][r]["final"] > CHAMP[r]]
    out["confirmation"] = {"armB_roads_beating_champion": beats, "required": bool(beats)}
    if beats:
        folds = {}
        for nm, (a, b) in {"2010_2018": ("2010-01-01", "2018-12-31"),
                           "2019_2026": ("2019-01-01", "2026-10-31")}.items():
            eq, cost = simulate(a, b, arm="B")
            folds[nm] = pack(eq, cost)
        out["confirmation"]["folds_armB"] = folds
    with open(os.path.join(FOLDER, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    for arm in ["A", "B", "C", "D"]:
        print(arm, {r: out["arms"][arm][r]["final"] for r in ROADS},
              "DD", {r: out["arms"][arm][r]["stats"]["max_dd"] for r in ROADS})
    print("static", {r: out["benchmarks"]["static_mix_equal5"][r]["final"] for r in ROADS})
    print("spy   ", {r: out["benchmarks"]["spy_buyhold"][r]["final"] for r in ROADS})
    print("placebos B", out["placebos"])
    print("2022", {k: (v["final"], v["stats"]["max_dd"]) for k, v in out["stress_2022"].items()})
    print("confirmation required:", out["confirmation"]["required"])

if __name__ == "__main__":
    main()
