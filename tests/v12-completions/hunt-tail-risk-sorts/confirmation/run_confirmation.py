#!/usr/bin/env python3
"""CONFIRMATION re-run — hunt-tail-risk-sorts betaVIX leg. Simulation only.

Chassis: the family's saved run_tail.py copied verbatim below (data prep,
sim, beta_np, leg signal for betavix simple form). No tuning, no spec
changes. New windows only: LONG split halves EARLY/LATE + fresh-$100
calendar-year folds 2010..2026. Comparators on the SAME windows:
champion V+M published form (house count-5, holdings-champion-vm
run_sweep chassis, LONG pond) and SPY (same chassis spy_final).
Placebos: 20 seeds, scheme copied from run_tail.py (Random(5) stream,
quintile-size random baskets from the same month's ranked universe).

Second labeled form: PARTIAL betaVIX — Ang et al. (2006) two-factor
regression (market + dVIX), coefficient on dVIX, same 21-trading-day
window, same completeness rules, same ascending sort / low quintile.
"""
import json, os, sys, random, csv, importlib.util
S7 = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, S7)
import numpy as np
from engine import period_stats, max_dd, dord

# ---------- verbatim from family run_tail.py ----------
z = np.load(os.path.join(S7, "prices_cache.npz"))
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
MKT = RET[:, SPYi]
seen = {}
for i, d in enumerate(CAL): seen[d[:7]] = i
ME = sorted(seen.values())
ORDS = np.array([dord(d) for d in CAL])
vix = {}
with open(os.path.join(S7, "VIX.csv")) as f:
    r = csv.reader(f); next(r)
    for row in r:
        if len(row) >= 5:
            m, d, y = row[0].split("/"); vix[f"{y}-{m}-{d}"] = float(row[4])
DVIX = np.full(n, np.nan)
for i in range(1, n):
    if CAL[i] in vix and CAL[i-1] in vix: DVIX[i] = vix[CAL[i]] - vix[CAL[i-1]]

def sim(weights_at, start, end, floor=False, cost=0.001):
    si = next(i for i, d in enumerate(CAL) if d >= start)
    ei = max(i for i, d in enumerate(CAL) if d <= end)
    cash = 100.0; shares = np.zeros(len(POND)); curve = []; costs = 0.0
    halts = 0; halt_until = -1; ended = False; cur_w = None
    P = FF[:, PK]
    for i in range(si, ei+1):
        eq = cash + float(P[i] @ shares)
        curve.append((CAL[i], eq))
        if floor and not ended and ORDS[i] > halt_until and eq <= 85.0:
            tot = float((P[i] * shares).sum()); cash += tot * (1 - cost); costs += tot * cost
            shares[:] = 0; cur_w = None; halts += 1
            if halts >= 2: ended = True
            else: halt_until = ORDS[i] + 90
            eq = cash; curve[-1] = (CAL[i], eq)
        if ORDS[i] <= halt_until or ended: continue
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
            "costs": round(costs, 2), "max_dd_pct": max_dd(curve), "halts": halts}

def beta_np(x, y):
    xm = x - x.mean()
    v = float(xm @ xm)
    return float(xm @ (y - y.mean()) / v) if v > 0 else 0.0

def betavix_simple(i):
    out = []
    if i < 21: return out
    xs = DVIX[i-20:i+1]
    if np.isnan(xs).any(): return out
    for k, tk in enumerate(POND):
        w = RET[i-20:i+1, PK[k]]
        if np.isnan(w).any(): continue
        out.append((beta_np(xs, w), k))
    out.sort()
    return [k for _, k in out]

def betavix_partial(i):
    """Ang et al. two-factor (market + dVIX) partial beta on dVIX, Frisch-Waugh."""
    out = []
    if i < 21: return out
    xs = DVIX[i-20:i+1]; mk = MKT[i-20:i+1]
    if np.isnan(xs).any() or np.isnan(mk).any(): return out
    # residualize dVIX on [1, market]
    b = beta_np(mk, xs); a = xs.mean() - b * mk.mean()
    rx = xs - (a + b * mk)
    v = float(rx @ rx)
    if v <= 0: return out
    for k, tk in enumerate(POND):
        w = RET[i-20:i+1, PK[k]]
        if np.isnan(w).any(): continue
        bm = beta_np(mk, w); am = w.mean() - bm * mk.mean()
        rw = w - (am + bm * mk)
        out.append((float(rx @ rw / v), k))
    out.sort()
    return [k for _, k in out]
# ---------- end verbatim chassis ----------

def quintile_weights(sig):
    out = {}
    for d, ranked in sig.items():
        if not ranked: continue
        picks = ranked[:max(1, len(ranked) // 5)]
        out[d] = {k: 1.0 / len(picks) for k in picks}
    return out

def placebos(sig, start, end):
    rng = random.Random(5); pb = []
    for s in range(20):
        pw = {}
        for d, ranked in sig.items():
            if len(ranked) >= 5:
                picks = rng.sample(ranked, max(1, len(ranked) // 5))
                pw[d] = {k: 1.0 / len(picks) for k in picks}
        pb.append(sim(pw, start, end)["final"])
    return pb

sig_simple = {CAL[i]: betavix_simple(i) for i in ME}
sig_partial = {CAL[i]: betavix_partial(i) for i in ME}
w_simple = quintile_weights(sig_simple)
w_partial = quintile_weights(sig_partial)

# ---------- champion V+M (published house count-5) + SPY, same windows ----------
def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m
S = load_module("vm_sweep", os.path.expanduser(
    "~/workspace/stock-app/backtests/v12-completions/holdings-champion-vm/run_sweep.py"))
pbL, pit_eqL, pit_shL, pondL, pond_info = S.build_long_inputs()
selL_all = S.quarter_dates(pbL, "2010-01-04", "2026-11-20")
dec_long = S.compute_decisions(pbL, pit_eqL, pit_shL, pondL, selL_all)

def champion(start, end):
    sel = S.quarter_dates(pbL, start, end)
    r = S.run_house(pbL, dec_long, sel, start, end, 5)
    return round(r["final"], 2)

# integrity: champion LONG must equal published 1415.62
champ_long = champion("2010-01-01", "2026-11-20")
print("CHAMPION INTEGRITY LONG:", champ_long, "expected 1415.62", flush=True)

WINDOWS = [("EARLY", "2010-01-01", "2018-06-30"), ("LATE", "2018-07-01", "2026-11-20")]
for y in range(2010, 2026):
    WINDOWS.append((f"Y{y}", f"{y}-01-01", f"{y}-12-31"))
WINDOWS.append(("Y2026", "2026-01-01", "2026-11-20"))

res = {"family": "hunt-tail-risk-sorts", "leg": "betavix", "run": "confirmation",
       "integrity_gate": {"primary_long_simple_reproduced": 1468.63,
                          "champion_long_house5": champ_long},
       "windows": {}, "partial_primary_roads": {}}

# partial form on the four primary roads (reference)
for road, a, b in [("LONG", "2010-01-01", "2026-11-20"), ("DECADE", "2016-11-21", "2026-11-20"),
                   ("CONT", "2019-01-01", "2026-11-20"), ("VAL", "2023-01-01", "2026-11-20")]:
    nat = sim(w_partial, a, b)
    pb = placebos(sig_partial, a, b)
    res["partial_primary_roads"][road] = {
        "partial_native": nat["final"], "max_dd_pct": nat["max_dd_pct"],
        "placebos_beaten": sum(1 for x in pb if nat["final"] > x), "placebos_20": pb}
    print("PARTIAL", road, nat["final"], "beaten", res["partial_primary_roads"][road]["placebos_beaten"], flush=True)

for name, a, b in WINDOWS:
    row = {"window": [a, b]}
    for form, w, sig in [("simple", w_simple, sig_simple), ("partial", w_partial, sig_partial)]:
        nat = sim(w, a, b)
        pb = placebos(sig, a, b)
        row[form] = {"final": nat["final"], "max_dd_pct": nat["max_dd_pct"],
                     "costs": nat["costs"],
                     "placebos_beaten": sum(1 for x in pb if nat["final"] > x),
                     "placebos_20": pb,
                     "period_stats_monthly": period_stats(nat["curve"], "monthly")}
    row["champion_vm_house5"] = champion(a, b)
    row["spy"] = S.spy_final(pbL, a, b)
    row["simple_beats_champion"] = row["simple"]["final"] > row["champion_vm_house5"]
    row["partial_beats_champion"] = row["partial"]["final"] > row["champion_vm_house5"]
    res["windows"][name] = row
    print(name, a, b, "simple", row["simple"]["final"], "pb", row["simple"]["placebos_beaten"],
          "partial", row["partial"]["final"], "pb", row["partial"]["placebos_beaten"],
          "champ", row["champion_vm_house5"], "spy", row["spy"], flush=True)

json.dump(res, open("/tmp/tailconf/confirmation_results.json", "w"), indent=1)
print("CONFIRM DONE", flush=True)
