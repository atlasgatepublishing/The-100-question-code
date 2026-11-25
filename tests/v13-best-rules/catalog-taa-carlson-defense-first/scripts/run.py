#!/usr/bin/env python3
"""V13 Best Rules — catalog-taa-carlson-defense-first.
Implements BEST-RULES-SPEC.md (frozen before this run):
published Carlson signal EXACTLY (TLT/GLD/DBC/UUP composite avg 1/3/6/12m,
BIL hurdle, failing slot -> SPY), chassis = monthly, EQUAL 25% slots, NO floor.
Also runs: published form (40/30/20/10 tiers) as own-form benchmark, SPY buy-hold,
static-mix control (20% x SPY/TLT/GLD/DBC/UUP monthly rebal), 20-seed placebos.
Chassis semantics replicate the v12 engine_common.simulate: month-end closes,
signal at t earns t->t+1, cost 0.10%/side on turnover, residual cash earns BIL.
"""
import json, os, sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
FOLDER = os.path.dirname(HERE)
SLICE_DATA = "/home/hatch/workspace/stock-app/backtests/v12-completions/catalog-taa-keller-baa/data"
COST = 0.001
ROADS = {"LONG": ("2010-01-01", "2026-10-31"), "DECADE": ("2016-01-01", "2026-10-31"),
         "CONT": ("2019-01-01", "2026-10-31"), "VAL": ("2023-01-01", "2026-10-31")}
CHAMP = {"LONG": 1415.62, "CONT": 544.47, "VAL": 288.05, "DECADE": 667.35}
SPY_REF = {"LONG": 822.94, "CONT": 313.62, "VAL": 187.77, "DECADE": 367.80}
DEF = ["TLT", "GLD", "DBC", "UUP"]

def load_monthly():
    out = {}
    for tk in ["SPY", "TLT", "GLD", "DBC", "BIL"]:
        df = pd.read_csv(os.path.join(SLICE_DATA, tk + ".csv"), parse_dates=["date"])
        s = df.set_index("date")["adjclose"]
        m = s.resample("M").last().dropna()
        m.index = m.index.to_period("M").to_timestamp("M")
        out[tk] = m
    df = pd.read_csv(os.path.join(FOLDER, "data", "UUP.csv"), parse_dates=["date"])
    s = df.set_index("date")["adjclose"]
    m = s.resample("M").last().dropna()
    m.index = m.index.to_period("M").to_timestamp("M")
    out["UUP"] = m
    return out

P = load_monthly()

def ret(t, tk, m):
    s = P[tk]
    if t not in s.index: return None
    idx = s.index.get_loc(t)
    if idx < m: return None
    return s.iloc[idx] / s.iloc[idx - m] - 1

def avg_ret(t, tk, months):
    vals = [ret(t, tk, m) for m in months]
    if any(v is None for v in vals): return None
    return float(np.mean(vals))

def carlson(t, tiers):
    moms = {}
    for a in DEF:
        mm = avg_ret(t, a, [1, 3, 6, 12])
        if mm is None: return {}
        moms[a] = mm
    bm = avg_ret(t, "BIL", [1, 3, 6, 12])
    if bm is None: bm = 0.0
    ranked = sorted(moms, key=moms.get, reverse=True)
    w = {}
    for a, wt in zip(ranked, tiers):
        if moms[a] < bm: w["SPY"] = w.get("SPY", 0) + wt
        else: w[a] = wt
    return w

def carlson_tiered(t, P_, cr): return carlson(t, [0.4, 0.3, 0.2, 0.1])
def carlson_equal(t, P_, cr):  return carlson(t, [0.25, 0.25, 0.25, 0.25])
def spy_hold(t, P_, cr):      return {"SPY": 1.0}
def static_mix(t, P_, cr):    return {a: 0.2 for a in ["SPY"] + DEF}

def cash_ret():
    return P["BIL"].pct_change()

CR = cash_ret()

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
            "median_period": round(float(r.median()), 4),
            "mean_period_secondary": round(float(r.mean()), 4),
            "best": round(float(r.max()), 4), "worst": round(float(r.min()), 4),
            "longest_losing_streak": int(ls), "longest_below_high_months": int(lb),
            "max_dd": round(float(dd), 4)}

def simulate(signal_fn, road, placebo_seed=None, rng_assets=None, track_weights=False):
    start, end = ROADS[road]
    start = pd.Timestamp(start); end = pd.Timestamp(end)
    idx = P["SPY"].index; idx = idx[(idx >= start) & (idx <= end)]
    rng = np.random.default_rng(placebo_seed) if placebo_seed is not None else None
    eq = 100.0; curve = {}; weights = {}; total_cost = 0.0; whist = []
    months = list(idx)
    for i, t in enumerate(months):
        curve[t] = eq
        if i == len(months) - 1: break
        t1 = months[i + 1]
        if rng is not None:
            assets = rng_assets; k = int(rng.integers(1, len(assets) + 1))
            pick = rng.choice(assets, size=k, replace=False)
            w = rng.dirichlet(np.ones(k))
            new_w = {a: float(x) for a, x in zip(pick, w)}
        else:
            new_w = signal_fn(t, P, CR)
            new_w = {k: float(v) for k, v in new_w.items() if abs(v) > 1e-9}
        if track_weights: whist.append((t, dict(new_w)))
        allk = set(weights) | set(new_w)
        turn = sum(abs(new_w.get(k, 0) - weights.get(k, 0)) for k in allk)
        c = eq * turn * COST; total_cost += c; eq -= c
        crv = CR.get(t1, 0.0) if t1 in CR.index else 0.0
        if crv is None or pd.isna(crv): crv = 0.0
        r = (1 - sum(new_w.values())) * crv
        for k, w in new_w.items():
            s = P[k]
            if t in s.index and t1 in s.index: r += w * (s[t1] / s[t] - 1)
            else: r += w * crv
        eq *= (1 + r); weights = new_w
    return pd.Series(curve), total_cost, whist

def exposure(whist):
    if not whist: return {}
    spy_w = [w.get("SPY", 0.0) for _, w in whist]
    return {"avg_spy_weight": round(float(np.mean(spy_w)), 3),
            "avg_defensive_weight": round(float(1 - np.mean(spy_w)), 3),
            "share_months_any_spy": round(float(np.mean([1 if x > 0 else 0 for x in spy_w])), 3),
            "share_months_fully_defensive": round(float(np.mean([1 if x == 0 else 0 for x in spy_w])), 3)}

def yearly(eq):
    out = {}
    yrs = sorted(set(eq.index.year))
    for y in yrs:
        seg = eq[eq.index.year == y]
        prev = eq[eq.index < seg.index[0]]
        if len(prev) == 0: continue
        out[str(y)] = round(float(seg.iloc[-1] / prev.iloc[-1] - 1), 4)
    return out

def main():
    res = {"family": "catalog-taa-carlson-defense-first", "spec": "BEST-RULES-SPEC.md",
           "my_rules": {}, "published_form": {}, "spy_buyhold": {}, "static_mix": {},
           "placebos": {}, "champion_vm": CHAMP, "spy_reference": SPY_REF,
           "confirmation": {}}
    fns = {"my_rules": carlson_equal, "published_form": carlson_tiered,
           "spy_buyhold": spy_hold, "static_mix": static_mix}
    curves = {}
    for name, fn in fns.items():
        for road in ROADS:
            track = (name == "my_rules")
            eq, cost, wh = simulate(fn, road, track_weights=track)
            d = {"final": round(float(eq.iloc[-1]), 2), "cost": round(cost, 2),
                 "stats": period_stats(eq),
                 "curve": {str(k.date()): round(float(v), 4) for k, v in eq.items()}}
            if track: d["exposure"] = exposure(wh)
            res[name][road] = d
            curves[(name, road)] = eq
    res["yearly_long"] = {"my_rules": yearly(curves[("my_rules", "LONG")]),
                          "published_form": yearly(curves[("published_form", "LONG")]),
                          "spy": yearly(curves[("spy_buyhold", "LONG")]),
                          "static_mix": yearly(curves[("static_mix", "LONG")])}
    for road in ("LONG", "CONT"):
        beats = 0; finals = []
        for seed in range(20):
            eqp, _, _ = simulate(carlson_equal, road, placebo_seed=seed,
                                 rng_assets=["TLT", "GLD", "DBC", "UUP", "SPY"])
            finals.append(float(eqp.iloc[-1]))
            if res["my_rules"][road]["final"] > finals[-1]: beats += 1
        res["placebos"][road] = {"beats": beats, "median_placebo": round(float(np.median(finals)), 2),
                                 "best_placebo": round(float(np.max(finals)), 2),
                                 "finals": [round(x, 2) for x in finals]}
    # Confirmation (frozen bars in spec) — only if a road beats the champion
    for road in ROADS:
        if res["my_rules"][road]["final"] > CHAMP[road]:
            res["confirmation"][road] = "TRIGGERED — see confirm.py (not run in main pass)"
        else:
            res["confirmation"][road] = "not triggered (road did not beat champion V+M)"
    json.dump(res, open(os.path.join(FOLDER, "results.json"), "w"), indent=1)
    for name in fns:
        print(name, {r: res[name][r]["final"] for r in ROADS},
              "maxDD", {r: res[name][r]["stats"]["max_dd"] for r in ROADS})
    print("exposure LONG", res["my_rules"]["LONG"]["exposure"])
    print("placebos", {r: (res["placebos"][r]["beats"], res["placebos"][r]["median_placebo"]) for r in res["placebos"]})

if __name__ == "__main__":
    main()
