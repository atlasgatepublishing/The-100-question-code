#!/usr/bin/env python3
"""V13 BEST RULES — hunt-tail-risk-sorts. Implements BEST-RULES-SPEC.md exactly as frozen.

Form A (PRIMARY, veto): monthly, rank eligible pond names by trailing-21d realized
skewness, veto top quintile, hold the rest equal-weight. No floor.
Form B (SECONDARY, weaker claim): monthly, rank by trailing-21d simple beta on dVIX,
hold low half equal-weight. No floor.
Twins: 20 seeds per form per road — Form A: random quintile vetoed; Form B: random
same-size basket from the same month's eligible universe.
Costs 0.10%/side (v12 chassis). $100 pots. Roads per task standard.
Confirmation (frozen bars in spec): if a form beats champion V+M on any road,
run fresh $100 yearly folds 2010-2026 + EARLY/LATE half-windows with SPY and
twin-median comparators on the halves.
Data (read-only shared inputs): the v12 worker scratch cache prices_cache.npz +
VIX.csv + this folder's copied engine.py (v12 chassis helpers). Simulation only.
"""
import json, os, sys, random, csv
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np
from engine import period_stats, max_dd, dord

SRC = os.path.expanduser("~/workspace/agents/cd3fd65b-e413-4760-815d-70c64f9aaa24/s7")
z = np.load(os.path.join(SRC, "prices_cache.npz"))
CAL = list(z["dates"]); TKS = list(z["tks"])
C = z["C"].astype(float)
SPYi = TKS.index("SPY")
POND = [t for t in TKS if t != "SPY"]; PK = [TKS.index(t) for t in POND]
n, _ = C.shape
FF = C.copy()
for k in range(C.shape[1]):
    col = FF[:, k]; idx = np.where(col > 0, np.arange(n), 0)
    np.maximum.accumulate(idx, out=idx)
    FF[:, k] = col[idx]
RET = np.zeros_like(C)
RET[1:] = np.where((C[:-1] > 0) & (C[1:] > 0), C[1:] / np.where(C[:-1] > 0, C[:-1], 1) - 1, np.nan)
seen = {}
for i, d in enumerate(CAL): seen[d[:7]] = i
ME = sorted(seen.values())
ORDS = np.array([dord(d) for d in CAL])
vix = {}
with open(os.path.join(SRC, "VIX.csv")) as f:
    r = csv.reader(f); next(r)
    for row in r:
        if len(row) >= 5:
            m, d, y = row[0].split("/"); vix[f"{y}-{m}-{d}"] = float(row[4])
DVIX = np.full(n, np.nan)
for i in range(1, n):
    if CAL[i] in vix and CAL[i-1] in vix: DVIX[i] = vix[CAL[i]] - vix[CAL[i-1]]

ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
PUBLISHED = {"LONG": 1468.63, "DECADE": 417.92, "CONT": 336.38, "VAL": 190.87}

def sim(weights_at, start, end, cost=0.001):
    si = next(i for i, d in enumerate(CAL) if d >= start)
    ei = max(i for i, d in enumerate(CAL) if d <= end)
    cash = 100.0; shares = np.zeros(len(POND)); curve = []; costs = 0.0
    cur_w = None
    P = FF[:, PK]
    for i in range(si, ei+1):
        eq = cash + float(P[i] @ shares)
        curve.append((CAL[i], eq))
        tgt = weights_at.get(CAL[i])
        if tgt is not None and tgt is not cur_w:
            eq = cash + float(P[i] @ shares)
            tot = float((P[i] * shares).sum()); cash += tot * (1 - cost); costs += tot * cost
            shares[:] = 0
            for k, w in tgt.items():
                px = P[i, k]
                if px > 0 and w > 0:
                    amt = eq * w; shares[k] = amt * (1 - cost) / px; cash -= amt; costs += amt * cost
            cur_w = tgt
    return {"final": round(curve[-1][1], 2), "curve": [(d, round(float(e), 4)) for d, e in curve],
            "costs": round(costs, 2), "max_dd_pct": max_dd(curve)}

def spy_sim(start, end):
    si = next(i for i, d in enumerate(CAL) if d >= start)
    ei = max(i for i, d in enumerate(CAL) if d <= end)
    sh = 100.0 * (1 - 0.001) / FF[si, SPYi]
    curve = [(CAL[i], sh * FF[i, SPYi]) for i in range(si, ei+1)]
    return {"final": round(curve[-1][1], 2), "curve": [(d, round(float(e), 4)) for d, e in curve],
            "max_dd_pct": max_dd(curve)}

def skew_np(x):
    m = x.mean(); s = x.std()
    return float((((x - m) / s) ** 3).mean()) if s > 0 else 0.0

def beta_np(x, y):
    xm = x - x.mean(); v = float(xm @ xm)
    return float(xm @ (y - y.mean()) / v) if v > 0 else 0.0

def ranked(leg, i):
    out = []
    if i < 21: return out
    if leg == "betavix":
        xs = DVIX[i-20:i+1]
        if np.isnan(xs).any(): return out
    for k in range(len(POND)):
        w = RET[i-20:i+1, PK[k]]
        if np.isnan(w).any(): continue
        out.append((skew_np(w) if leg == "rskew" else beta_np(DVIX[i-20:i+1], w), k))
    out.sort()
    return [k for _, k in out]

SIG = {leg: {CAL[i]: ranked(leg, i) for i in ME} for leg in ["rskew", "betavix"]}

def weights_form(form, sig, rng=None):
    """form A: veto top rskew quintile, hold rest EW. form B: low betavix half EW.
    rng given -> twin: A vetoes a random quintile; B holds a random same-size basket."""
    out = {}
    for d, rk in sig.items():
        if len(rk) < 5: continue
        if form == "A":
            nveto = max(1, len(rk) // 5)
            if rng is None:
                keep = rk[:len(rk) - nveto]
            else:
                veto = set(rng.sample(rk, nveto)); keep = [k for k in rk if k not in veto]
        else:
            nh = max(1, len(rk) // 2)
            keep = rk[:nh] if rng is None else rng.sample(rk, nh)
        out[d] = {k: 1.0 / len(keep) for k in keep}
    return out

def run_form(form, leg, windows):
    sig = SIG[leg]
    real_w = weights_form(form, sig)
    res = {}
    for name, (a, b) in windows.items():
        real = sim(real_w, a, b)
        twins = []
        for s in range(20):
            rng = random.Random(1000 + s)
            twins.append(sim(weights_form(form, sig, rng), a, b)["final"])
        res[name] = {"real": real, "twins_20": twins,
                     "twins_beaten": sum(1 for x in twins if real["final"] > x),
                     "twin_median": round(float(np.median(twins)), 2),
                     "period_stats_monthly": period_stats(real["curve"], "monthly"),
                     "spy_same_window": spy_sim(a, b)}
        print(form, name, "real", real["final"], "dd", real["max_dd_pct"],
              "twins_beaten", res[name]["twins_beaten"], "twin_med", res[name]["twin_median"],
              "spy", res[name]["spy_same_window"]["final"], flush=True)
    return res

out = {"family": "hunt-tail-risk-sorts", "program": "v13-best-rules",
       "roads": ROADS, "champion": CHAMP, "spy_ref": SPYREF, "published_best": PUBLISHED,
       "forms": {}}
forms = {}
for form, leg, label in [("A", "rskew", "veto basket (PRIMARY)"),
                         ("B", "betavix", "good-tail engine, low half (SECONDARY, weaker claim)")]:
    forms[form] = {"label": label, "roads": run_form(form, leg, ROADS)}
out["forms"] = forms

# Confirmation — only for a form that beat the champion on any road (spec bars frozen).
conf = {}
for form, leg in [("A", "rskew"), ("B", "betavix")]:
    beaten = [r for r in ROADS if forms[form]["roads"][r]["real"]["final"] > CHAMP[r]]
    if not beaten: continue
    print("CONFIRMATION triggered for form", form, "roads", beaten, flush=True)
    halves = {"EARLY": ("2010-01-04", "2018-06-30"), "LATE": ("2018-07-01", "2026-11-20")}
    hres = run_form(form, leg, halves)
    folds = {}
    for y in range(2010, 2027):
        a = f"{y}-01-01"; b = "2026-11-20" if y == 2026 else f"{y}-12-31"
        r = sim(weights_form(form, SIG[leg]), a, b)
        folds[str(y)] = {"final": r["final"], "max_dd_pct": r["max_dd_pct"],
                         "spy": spy_sim(a, b)["final"]}
    pos_folds = sum(1 for v in folds.values() if v["final"] > 100.0)
    ok = all(hres[h]["real"]["final"] > hres[h]["spy_same_window"]["final"] and
             hres[h]["real"]["final"] > hres[h]["twin_median"] for h in halves) and pos_folds >= 9
    conf[form] = {"champion_roads_beaten": beaten, "halves": hres, "yearly_folds": folds,
                  "positive_folds": pos_folds, "confirmed_per_frozen_bars": bool(ok)}
    print("CONFIRMATION form", form, "confirmed:", bool(ok), "pos folds", pos_folds, flush=True)
out["confirmation"] = conf
json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
print("v13 tail-risk done", flush=True)
