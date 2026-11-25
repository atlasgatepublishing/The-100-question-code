#!/usr/bin/env python3
"""hunt-tail-risk-sorts — numpy implementation on prices_cache.npz. Simulation only."""
import json, os, sys, random, csv
S7 = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, S7)
import numpy as np
from engine import period_stats, max_dd, ROADS, CHAMP, SPYREF, dord

BASE = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions")
z = np.load(os.path.join(S7, "prices_cache.npz"))
CAL = list(z["dates"]); TKS = list(z["tks"])
C = z["C"].astype(float)  # 0 = missing
SPYi = TKS.index("SPY")
POND = [t for t in TKS if t != "SPY"]; PK = [TKS.index(t) for t in POND]
n, _ = C.shape
# forward-filled closes
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
# daily cross-sectional tail series: mean of worst 5% valid pond returns
TAIL = np.zeros(n)
for k in range(n):
    xs = RET[k, PK]; xs = xs[~np.isnan(xs)]
    if len(xs) >= 20:
        k5 = max(1, len(xs) // 20)
        TAIL[k] = np.partition(xs, k5)[:k5].mean()
TAILCUM = np.concatenate([[0], np.cumsum(TAIL)])

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

def skew_np(x):
    m = x.mean(); s = x.std()
    return float((((x - m) / s) ** 3).mean()) if s > 0 else 0.0

def beta_np(x, y):
    xm = x - x.mean()
    v = float(xm @ xm)
    return float(xm @ (y - y.mean()) / v) if v > 0 else 0.0

def leg_signals(leg, i):
    out = []
    if leg == "coskew":
        if i < 252: return out
        mw = MKT[i-251:i+1]; mm = mw.mean(); msd = mw.std()
        m2 = (mw - mm) ** 2
        for k, tk in enumerate(POND):
            w = RET[i-251:i+1, PK[k]]
            if np.isnan(w).any(): continue
            isd = w.std()
            if isd == 0 or msd == 0: continue
            cs = float((((w - w.mean()) * m2).mean()) / (isd * msd * msd))
            out.append((cs, k))
        out.sort()
    elif leg == "rskew":
        if i < 21: return out
        for k, tk in enumerate(POND):
            w = RET[i-20:i+1, PK[k]]
            if np.isnan(w).any(): continue
            out.append((skew_np(w), k))
        out.sort()
    elif leg == "betavix":
        if i < 21: return out
        xs = DVIX[i-20:i+1]
        if np.isnan(xs).any(): return out
        for k, tk in enumerate(POND):
            w = RET[i-20:i+1, PK[k]]
            if np.isnan(w).any(): continue
            out.append((beta_np(xs, w), k))
        out.sort()
    elif leg == "tailbeta":
        if i < 2520: return out
        mes = [j for j in ME if j <= i][-121:]
        if len(mes) < 121: return out
        tfac = np.array([TAILCUM[j+1] - TAILCUM[(mes[idx-1] if idx > 0 else j-21) + 1] for idx, j in enumerate(mes)])
        for k, tk in enumerate(POND):
            ys = []; ok = True
            for idx, j in enumerate(mes):
                pj = mes[idx-1] if idx > 0 else j-21
                if C[j, PK[k]] <= 0 or C[pj, PK[k]] <= 0: ok = False; break
                ys.append(C[j, PK[k]] / C[pj, PK[k]] - 1)
            if not ok: continue
            out.append((-beta_np(tfac, np.array(ys)), k))
        out.sort()
    return [k for _, k in out]

COUNTS = [1, 2, 3, 5, 8, 10, 15, 20, 30, "ALL"]
rest = {"family": "hunt-tail-risk-sorts", "legs": {}}
for leg in ["coskew", "rskew", "betavix", "tailbeta"]:
    sig = {CAL[i]: leg_signals(leg, i) for i in ME}
    def w_at(cnt, sig=sig):
        out = {}
        for d, ranked in sig.items():
            if not ranked: continue
            picks = ranked[:max(1, len(ranked) // 5)] if cnt == "ALL" else ranked[:cnt]
            out[d] = {k: 1.0 / len(picks) for k in picks}
        return out
    legres = {"native_count": "quintile (ALL cell = long quintile)", "roads": {}, "grid": {}}
    wall = w_at("ALL")
    for road in ROADS:
        a, b = ROADS[road]
        nat = sim(wall, a, b); hou = sim(wall, a, b, floor=True)
        rng = random.Random(5); pb = []
        for s in range(20):
            pw = {}
            for d, ranked in sig.items():
                if len(ranked) >= 5:
                    picks = rng.sample(ranked, max(1, len(ranked) // 5))
                    pw[d] = {k: 1.0 / len(picks) for k in picks}
            pb.append(sim(pw, a, b)["final"])
        legres["roads"][road] = {"native": nat, "house": hou, "placebos_20": pb,
                                 "placebos_beaten": sum(1 for x in pb if nat["final"] > x),
                                 "period_stats_monthly_native": period_stats(nat["curve"], "monthly")}
        grid = {str(cnt): sim(w_at(cnt), a, b)["final"] for cnt in COUNTS}
        legres["grid"][road] = grid
        print("TAIL", leg, road, "native(quintile)", nat["final"], "house", hou["final"], "beaten", legres["roads"][road]["placebos_beaten"], "grid", grid, flush=True)
    rest["legs"][leg] = legres
    os.makedirs(f"{BASE}/hunt-tail-risk-sorts/grid", exist_ok=True)
    json.dump({leg: legres["grid"]}, open(f"{BASE}/hunt-tail-risk-sorts/grid/grid-{leg}.json", "w"), indent=1)
json.dump(rest, open(f"{BASE}/hunt-tail-risk-sorts/results.json", "w"), indent=1)
print("tail2 done", flush=True)
