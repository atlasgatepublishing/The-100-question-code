#!/usr/bin/env python3
"""hunt-tax-loss-reversal, hunt-tsmom-portfolio, hunt-weinstein-stage — cache-based. Simulation only."""
import json, os, sys, random, bisect
from datetime import date
S7 = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, S7)
import numpy as np
from engine import period_stats, max_dd, ROADS, CHAMP, SPYREF, dord

BASE = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions")
z = np.load(os.path.join(S7, "prices_cache.npz"))
CAL = list(z["dates"]); TKS = list(z["tks"])
Cm = z["C"].astype(float); Om = z["O"].astype(float); Hm = z["H"].astype(float); Lm = z["L"].astype(float); Vm = z["V"].astype(float)
SPYi = TKS.index("SPY"); POND = [t for t in TKS if t != "SPY"]; PK = [TKS.index(t) for t in POND]
n = len(CAL)
FF = Cm.copy()
for k in range(Cm.shape[1]):
    col = FF[:, k]; idx = np.where(col > 0, np.arange(n), 0)
    np.maximum.accumulate(idx, out=idx); FF[:, k] = col[idx]
ORDS = np.array([dord(d) for d in CAL])
seen = {}
for i, d in enumerate(CAL): seen[d[:7]] = i
ME = sorted(seen.values())
PFF = FF[:, PK]

def sim(weights_at, start, end, floor=False, cost=0.001):
    si = next(i for i, d in enumerate(CAL) if d >= start)
    ei = max(i for i, d in enumerate(CAL) if d <= end)
    cash = 100.0; shares = np.zeros(len(POND)); curve = []; costs = 0.0
    halts = 0; halt_until = -1; ended = False; cur_w = None
    for i in range(si, ei+1):
        eq = cash + float(PFF[i] @ shares)
        curve.append((CAL[i], eq))
        if floor and not ended and ORDS[i] > halt_until and eq <= 85.0:
            tot = float((PFF[i] * shares).sum()); cash += tot * (1 - cost); costs += tot * cost
            shares[:] = 0; cur_w = None; halts += 1
            if halts >= 2: ended = True
            else: halt_until = ORDS[i] + 90
            eq = cash; curve[-1] = (CAL[i], eq)
        if ORDS[i] <= halt_until or ended: continue
        tgt = weights_at.get(CAL[i])
        if tgt is not None and tgt is not cur_w:
            eq = cash + float(PFF[i] @ shares)
            tot = float((PFF[i] * shares).sum()); cash += tot * (1 - cost); costs += tot * cost
            shares[:] = 0
            for k, w in tgt.items():
                px = PFF[i, k]
                if px > 0 and w > 0:
                    amt = eq * w; shares[k] = amt * (1 - cost) / px; cash -= amt; costs += amt * cost
            cur_w = tgt
    return {"final": round(curve[-1][1], 2), "curve": [(d, round(float(e), 4)) for d, e in curve],
            "costs": round(costs, 2), "max_dd_pct": max_dd(curve), "halts": halts}

# ============ TAX-LOSS REVERSAL ============
COST_TL = 0.003
def dec_jan(year):
    dec = [i for i, d in enumerate(CAL) if d[:4] == str(year) and d[5:7] == "12"]
    jan = [i for i, d in enumerate(CAL) if d[:4] == str(year+1) and d[5:7] == "01"]
    nov = [i for i, d in enumerate(CAL) if d[:4] == str(year) and d[5:7] == "11"]
    jan0 = [i for i, d in enumerate(CAL) if d[:4] == str(year) and d[5:7] == "01"]
    if not dec or not jan or not nov or not jan0: return None
    return jan0[-1], nov[-1], dec[-1], jan[-1]

def taxloss_run(cnt, road, floor=False, seed=None):
    a, b = ROADS[road]
    cash = 100.0; curve = []; halts = 0; ended = False
    trades = []; missing_jan = 0; total_names = 0
    ci = next(i for i, d in enumerate(CAL) if d >= a)
    ei = max(i for i, d in enumerate(CAL) if d <= b)
    formations = {}
    for y in range(int(a[:4]), int(b[:4])+1):
        dj = dec_jan(y)
        if dj: formations[dj[2]] = (y, dj)
    pos = np.zeros(len(POND)); sell_at = None
    for i in range(ci, ei+1):
        eq = cash + float(PFF[i] @ pos)
        curve.append((CAL[i], eq))
        if floor and pos.any() and eq <= 85.0 and not ended:
            cash += float((PFF[i] * pos).sum()) * (1 - COST_TL); pos[:] = 0; halts += 1
            if halts >= 2: ended = True
            curve[-1] = (CAL[i], cash)
        if sell_at is not None and i == sell_at and pos.any():
            for k in np.nonzero(pos)[0]:
                if Cm[i, PK[k]] <= 0: missing_jan += 1
                cash += pos[k] * (PFF[i, k] if Cm[i, PK[k]] > 0 else 0.0) * (1 - COST_TL)
            pos[:] = 0; sell_at = None
        if i in formations and not ended and not pos.any():
            y, (j0, nI, dI, jaI) = formations[i]
            ranked = []
            for k, tk in enumerate(POND):
                if Cm[nI, PK[k]] > 0 and Cm[j0, PK[k]] > 0 and Cm[dI, PK[k]] > 5:
                    ranked.append((Cm[nI, PK[k]] / Cm[j0, PK[k]] - 1, k))
            ranked.sort()
            if seed is not None:
                rng = random.Random(seed * 1000 + y)
                c2 = max(1, len(ranked) // 5) if cnt == "ALL" else cnt
                picks = [k for _, k in rng.sample(ranked, min(c2, len(ranked)))]
            elif cnt == "ALL":
                picks = [k for _, k in ranked[:max(1, len(ranked) // 5)]]
            else:
                picks = [k for _, k in ranked[:cnt]]
            total_names += len(picks)
            eq = cash
            for k in picks:
                amt = eq / len(picks)
                pos[k] = amt * (1 - COST_TL) / PFF[i, k]; cash -= amt
            sell_at = jaI; trades.append(y)
    return {"final": round(curve[-1][1], 2), "curve": [(d, round(float(e), 4)) for d, e in curve],
            "max_dd_pct": max_dd(curve), "jan_trades_years": trades, "names_total": total_names,
            "missing_jan_bars": missing_jan, "halts": halts}

COUNTS = [1, 2, 3, 5, 8, 10, 15, 20, 30, "ALL"]
res = {"family": "hunt-tax-loss-reversal", "roads": {}, "grid": {},
       "headline_note": "Papers publish no basket count; headline = n=10 cell, grid printed whole. Costs 0.30%/side small-name habitat rate."}
for road in ROADS:
    nat = taxloss_run(10, road); hou = taxloss_run(10, road, floor=True)
    pb = [taxloss_run(10, road, seed=s)["final"] for s in range(20)]
    grid = {str(c): taxloss_run(c, road)["final"] for c in COUNTS}
    res["roads"][road] = {"native_n10": nat, "house_n10": hou, "placebos_20_random_dec_baskets_n10": pb,
                          "placebos_beaten": sum(1 for x in pb if nat["final"] > x),
                          "period_stats_annual_native_n10": period_stats(nat["curve"], "annual")}
    res["grid"][road] = grid
    print("TAXLOSS", road, "n10", nat["final"], "house", hou["final"], "beaten", res["roads"][road]["placebos_beaten"], "missing_jan", nat["missing_jan_bars"], "grid", grid, flush=True)
json.dump(res, open(f"{BASE}/hunt-tax-loss-reversal/results.json", "w"), indent=1)
os.makedirs(f"{BASE}/hunt-tax-loss-reversal/grid", exist_ok=True)
json.dump(res["grid"], open(f"{BASE}/hunt-tax-loss-reversal/grid/grid.json", "w"), indent=1)

# ============ TSMOM PORTFOLIO ============
RET = np.zeros_like(Cm)
RET[1:] = np.where((Cm[:-1] > 0) & (Cm[1:] > 0), Cm[1:] / np.where(Cm[:-1] > 0, Cm[:-1], 1) - 1, 0.0)
def ewma_sigma_col(col_rets):
    lam = 60 / 61.0; var = 0.0; out = np.zeros(n)
    for i in range(n):
        r = col_rets[i]
        var = lam * var + (1 - lam) * r * r if i > 0 else r * r
        out[i] = (var * 261) ** 0.5
    return out
SIG = {tk: ewma_sigma_col(RET[:, TKS.index(tk)]) for tk in POND + ["SPY"]}
UNIV = POND + ["SPY"]; UK = [TKS.index(t) for t in UNIV]
def tsmom_weights(cnt=None):
    w = {}
    for i in ME:
        if i < 252: continue
        raw = {}
        for k, tk in enumerate(UNIV):
            if Cm[i, UK[k]] <= 0 or Cm[i-252, UK[k]] <= 0 or SIG[tk][i] <= 0: continue
            r12 = Cm[i, UK[k]] / Cm[i-252, UK[k]] - 1
            if r12 > 0: raw[k] = (0.40 / SIG[tk][i], r12)
        if not raw: continue
        items = sorted(raw.items(), key=lambda kv: -kv[1][1])
        if cnt is not None: items = items[:cnt]
        tot = sum(v[0] for _, v in items)
        # map UNIV index -> POND index (SPY excluded from holdings matrix: treat SPY as pond slot via PFF? SPY not in POND)
        w[CAL[i]] = {}
        for k, v in items:
            tk = UNIV[k]
            if tk == "SPY": continue
            w[CAL[i]][POND.index(tk)] = v[0] / tot
        s = sum(w[CAL[i]].values())
        if s > 0: w[CAL[i]] = {k: v / s for k, v in w[CAL[i]].items()}
    return w
res2 = {"family": "hunt-tsmom-portfolio", "roads": {}, "grid": {},
        "note": "Universe = program pond (154 names incl. SPY-class names in the cache); SPY itself excluded from holdings (it is the benchmark class), stated as a translation detail. Long-only, vol-normalized (MOP eq.1 EWMA, 261 convention), monthly."}
wall = tsmom_weights()
for road in ROADS:
    a, b = ROADS[road]
    nat = sim(wall, a, b); hou = sim(wall, a, b, floor=True)
    rng = random.Random(9); pb = []
    for s in range(20):
        pw = {}
        for d, wdict in wall.items():
            picks = rng.sample(range(len(POND)), min(len(wdict), len(POND)))
            pw[d] = {k: 1.0 / len(picks) for k in picks}
        pb.append(sim(pw, a, b)["final"])
    grid = {}
    for c in COUNTS:
        wn = tsmom_weights(None if c == "ALL" else c)
        grid[str(c)] = sim(wn, a, b)["final"]
    res2["roads"][road] = {"native": nat, "house": hou, "placebos_20": pb,
                           "placebos_beaten": sum(1 for x in pb if nat["final"] > x),
                           "period_stats_monthly_native": period_stats(nat["curve"], "monthly"),
                           "champion_vm": CHAMP[road], "spy_ref": SPYREF[road]}
    res2["grid"][road] = grid
    print("TSMOM", road, "native", nat["final"], "house", hou["final"], "beaten", res2["roads"][road]["placebos_beaten"], "grid", grid, flush=True)
json.dump(res2, open(f"{BASE}/hunt-tsmom-portfolio/results.json", "w"), indent=1)
os.makedirs(f"{BASE}/hunt-tsmom-portfolio/grid", exist_ok=True)
json.dump(res2["grid"], open(f"{BASE}/hunt-tsmom-portfolio/grid/grid.json", "w"), indent=1)

# ============ WEINSTEIN STAGE ============
WEEKID = np.array([o - date.fromordinal(int(o)).weekday() for o in ORDS])
def weekly_series(k):
    out = {}
    for i in range(n):
        wk = WEEKID[i]
        cur = out.get(wk)
        if Cm[i, k] <= 0: continue
        if cur is None: out[wk] = [CAL[i], Om[i, k], Hm[i, k], Lm[i, k], Cm[i, k], Vm[i, k]]
        else:
            cur[2] = max(cur[2], Hm[i, k]); cur[3] = min(cur[3], Lm[i, k]); cur[4] = Cm[i, k]; cur[5] += Vm[i, k]; cur[0] = CAL[i]
    return [out[w] for w in sorted(out)]
SPYW = weekly_series(SPYi); SPYW_D = [x[0] for x in SPYW]; SPYW_C = [x[4] for x in SPYW]
def sma(vals, i, nn):
    if i < nn - 1: return None
    return sum(vals[i-nn+1:i+1]) / nn
ALL_ENTRIES = []
for tk in POND:
    k = TKS.index(tk)
    w = weekly_series(k); closes = [x[4] for x in w]; vols = [x[5] for x in w]
    entries = []; s1 = 0; bh = None; bl = None
    for i in range(30, len(w)):
        ma = sma(closes, i, 30); ma4 = sma(closes, i-4, 30)
        if ma is None or ma4 is None: continue
        slope = (ma - ma4) / ma; price = closes[i]
        in_base = abs(slope) <= 0.005 and abs(price / ma - 1) < 0.08
        if in_base:
            s1 += 1
            seg = closes[max(0, i - s1 + 1):i + 1]; bh = max(seg); bl = min(seg)
        else:
            if s1 >= 10 and bh and bl and bh / bl <= 1.25 and i >= 26:
                volavg = sum(vols[i-13:i]) / 13 if i >= 13 else 0
                j = bisect.bisect_left(SPYW_D, w[i][0])
                if 26 <= j < len(SPYW):
                    r_stock = closes[i] / closes[i-26] - 1
                    r_spy = SPYW_C[j] / SPYW_C[j-26] - 1
                    sma_spy = sma(SPYW_C, j, 30)
                    if price > bh and slope > -0.005 and vols[i] >= 2 * volavg and r_stock > r_spy and sma_spy and SPYW_C[j] > sma_spy:
                        entries.append(i)
            s1 = 0; bh = None; bl = None
    for ei_ in entries:
        xi = len(w) - 1
        for kk in range(ei_ + 1, len(w)):
            ma = sma(closes, kk, 30)
            if ma is not None and closes[kk] < ma: xi = kk; break
            if closes[kk] < closes[ei_] * 0.92 and closes[kk] < closes[ei_] * 1.10: xi = kk; break
        ALL_ENTRIES.append((w[ei_][0], w[xi][0], tk))
ALL_ENTRIES.sort()
print("weinstein total entries", len(ALL_ENTRIES), flush=True)
def weinstein_run(maxn, road, floor=False, seed=None):
    a, b = ROADS[road]
    entries = ALL_ENTRIES
    if seed is not None:
        rng = random.Random(seed)
        entries = [(e[0], e[1], rng.choice(POND)) for e in ALL_ENTRIES]
    entry_map = {}
    for e in entries: entry_map.setdefault(e[0], []).append(e)
    cash = 100.0; curve = []; active = {}; halts = 0; ended = False
    ci = next(i for i, d in enumerate(CAL) if d >= a); ei2 = max(i for i, d in enumerate(CAL) if d <= b)
    for i in range(ci, ei2 + 1):
        d = CAL[i]
        for tk in list(active):
            if d >= active[tk][0]:
                cash += active[tk][1] * PFF[i, POND.index(tk)]; del active[tk]
        eq = cash + sum(v[1] * PFF[i, POND.index(tk)] for tk, v in active.items())
        curve.append((d, eq))
        if floor and active and eq <= 85.0 and not ended:
            for tk, v in active.items(): cash += v[1] * PFF[i, POND.index(tk)] * 0.999
            active = {}; halts += 1
            if halts >= 2: ended = True
            curve[-1] = (d, cash); eq = cash
        if d in entry_map and not ended:
            for e in entry_map[d]:
                if len(active) >= maxn or e[2] in active: continue
                eq = cash + sum(v[1] * PFF[i, POND.index(k)] for k, v in active.items())
                amt = min(eq / maxn, cash)
                if amt <= 0: continue
                sh = amt * 0.999 / PFF[i, POND.index(e[2])]; cash -= amt
                active[e[2]] = (e[1], sh)
    return {"final": round(curve[-1][1], 2), "curve": [(d, round(float(e), 4)) for d, e in curve],
            "max_dd_pct": max_dd(curve), "n_entries_total": len(ALL_ENTRIES), "halts": halts}
res3 = {"family": "hunt-weinstein-stage", "roads": {}, "grid": {}}
for road in ROADS:
    nat = weinstein_run(5, road); hou = weinstein_run(5, road, floor=True)
    pb = [weinstein_run(5, road, seed=s)["final"] for s in range(20)]
    grid = {str(c): weinstein_run(30 if c == "ALL" else c, road)["final"] for c in COUNTS}
    res3["roads"][road] = {"native_max5": nat, "house_max5": hou, "placebos_20_random_names": pb,
                           "placebos_beaten": sum(1 for x in pb if nat["final"] > x),
                           "period_stats_weekly_native": period_stats(nat["curve"], "weekly"),
                           "champion_vm": CHAMP[road], "spy_ref": SPYREF[road]}
    res3["grid"][road] = grid
    print("WEINSTEIN", road, nat["final"], "house", hou["final"], "beaten", res3["roads"][road]["placebos_beaten"], "grid", grid, flush=True)
json.dump(res3, open(f"{BASE}/hunt-weinstein-stage/results.json", "w"), indent=1)
os.makedirs(f"{BASE}/hunt-weinstein-stage/grid", exist_ok=True)
json.dump(res3["grid"], open(f"{BASE}/hunt-weinstein-stage/grid/grid.json", "w"), indent=1)
print("selection2b done", flush=True)
