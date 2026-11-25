#!/usr/bin/env python3
"""hunt-wilder-dmi-system — fast timer sim (state at close t earns t->t+1,
close-to-close; shorts earn the mirror return, no margin interest/borrow fee,
stated). Simulation only."""
import json, os, sys, csv, random
S7 = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, S7)
import numpy as np
from engine import period_stats, max_dd, ROADS, CHAMP, SPYREF
from datetime import date, timedelta

BASE = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions")
z = np.load(os.path.join(S7, "prices_cache.npz"))
CAL = list(z["dates"]); TKS = list(z["tks"])

def bars_from_cache(sym):
    k = TKS.index(sym)
    out = []
    for i, d in enumerate(CAL):
        if z["C"][i, k] > 0:
            out.append({"d": d, "o": float(z["O"][i, k]), "h": float(z["H"][i, k]), "l": float(z["L"][i, k]), "c": float(z["C"][i, k])})
    return out

def timer_sim(dates, px, state, start, end, cost=0.001, fee=0.01, floor=False, shorts=False):
    idx = [i for i, d in enumerate(dates) if start <= d <= end]
    eq = 100.0; curve = []; pos = 0; costs = 0.0; orders = 0
    halts = 0; halt_until = ""; ended = False; invested = 0
    for k, i in enumerate(idx):
        curve.append((dates[i], eq))
        if pos != 0: invested += 1
        if floor and not ended and dates[i] > halt_until and eq <= 85.0:
            if pos != 0: eq *= (1 - cost); costs += eq * cost; pos = 0; orders += 1
            halts += 1
            if halts >= 2: ended = True
            else: halt_until = (date.fromisoformat(dates[i]) + timedelta(days=90)).isoformat()
            curve[-1] = (dates[i], eq)
        if k + 1 >= len(idx): break
        want = state[i] if shorts else (1 if state[i] else 0)
        if want != pos and not ended and dates[i] >= halt_until:
            if pos != 0: eq *= (1 - cost); costs += eq * cost + (fee if pos > 0 else 0); orders += 1
            if want != 0: eq *= (1 - cost); costs += eq * cost; orders += 1
            pos = want
        if pos == 1: eq *= px[idx[k+1]] / px[i]
        elif pos == -1: eq *= max(0.0, 2.0 - px[idx[k+1]] / px[i])
    return {"final": round(eq, 2), "curve": [(d, round(float(e), 4)) for d, e in curve],
            "costs": round(costs, 2), "orders": orders, "max_dd_pct": max_dd(curve),
            "halts": halts, "invested_share": round(invested / max(1, len(curve)), 3)}

def bh(dates, px, start, end, cost=0.001, fee=0.01):
    idx = [i for i, d in enumerate(dates) if start <= d <= end]
    sh = 100 * (1 - cost) / px[idx[0]]
    curve = [(dates[i], sh * px[i]) for i in idx]
    return {"final": round(sh * px[idx[-1]] * (1 - cost) - fee, 2), "curve": [(d, round(float(e), 4)) for d, e in curve], "max_dd_pct": max_dd(curve)}

def dmi(bars, n=14):
    N = len(bars); tr = [0.0]*N; pdm = [0.0]*N; ndm = [0.0]*N
    for i in range(1, N):
        h, l, pc = bars[i]["h"], bars[i]["l"], bars[i-1]["c"]
        up = h - bars[i-1]["h"]; dn = bars[i-1]["l"] - l
        pdm[i] = up if (up > dn and up > 0) else 0.0
        ndm[i] = dn if (dn > up and dn > 0) else 0.0
        tr[i] = max(h-l, abs(h-pc), abs(l-pc))
    def smooth(x):
        out = [0.0]*N; s = 0.0
        for i in range(N):
            if i == n: s = sum(x[1:n+1])
            elif i > n: s = s - s/n + x[i]
            out[i] = s
        return out
    str_, sp, sn = smooth(tr), smooth(pdm), smooth(ndm)
    pdi = [100*sp[i]/str_[i] if str_[i] > 0 else 0.0 for i in range(N)]
    ndi = [100*sn[i]/str_[i] if str_[i] > 0 else 0.0 for i in range(N)]
    dx = [100*abs(pdi[i]-ndi[i])/(pdi[i]+ndi[i]) if (pdi[i]+ndi[i]) > 0 else 0.0 for i in range(N)]
    adx = [0.0]*N; s = 0.0
    for i in range(N):
        if i == 2*n: s = sum(dx[n+1:2*n+1])/n; adx[i] = s
        elif i > 2*n: s = (s*(n-1) + dx[i])/n; adx[i] = s
    return pdi, ndi, adx

def dmi_states(bars, formB, long_only):
    """Wilder extreme-point rule as documented (eSignal / Wilder restatements):
    the crossover day that establishes a position sets its REVERSE POINT --
    low of the buy-cross day for a long, high of the sell-cross day for a
    short. A reversal requires (a) the contrary DI cross to have occurred
    (it stays armed while the lines remain crossed contrary) AND (b) price
    penetration of the reverse point. A favourable re-cross disarms."""
    pdi, ndi, adx = dmi(bars)
    N = len(bars); state = [0]*N; pos = 0; rp = None; armed = False; arm_rp_new = None
    counts = {"crosses": 0, "gated_crosses": 0}
    for i in range(1, N):
        cross_up = pdi[i] > ndi[i] and pdi[i-1] <= ndi[i-1]
        cross_dn = ndi[i] > pdi[i] and ndi[i-1] <= pdi[i-1]
        gate = (not formB) or (adx[i] > 25 and adx[i] > adx[i-1])
        if cross_up or cross_dn: counts["crosses"] += 1
        if pos == 0:
            if cross_up and gate:
                counts["gated_crosses"] += 1
                pos = 1; rp = bars[i]["l"]; armed = False
            elif cross_dn and gate and not long_only:
                counts["gated_crosses"] += 1
                pos = -1; rp = bars[i]["h"]; armed = False
        elif pos == 1:
            if cross_dn: armed = True; arm_rp_new = bars[i]["h"]
            elif cross_up: armed = False
            if armed and rp is not None and bars[i]["l"] < rp:
                if long_only: pos = 0; rp = None
                else: pos = -1; rp = arm_rp_new
                armed = False
        elif pos == -1:
            if cross_up: armed = True; arm_rp_new = bars[i]["l"]
            elif cross_dn: armed = False
            if armed and rp is not None and bars[i]["h"] > rp:
                pos = 1; rp = arm_rp_new; armed = False
        state[i] = pos
    dmi_states.counts = counts
    return state

assets = {"SPY": bars_from_cache("SPY")}
for sym in ["BTC", "ETH"]:
    rows = []
    with open(os.path.expanduser(f"~/workspace/stock-app/backtests/v4/crypto-trend-data/{sym}-USD.csv")) as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append({"d": row["date"], "o": float(row["open"]), "h": float(row["high"]), "l": float(row["low"]), "c": float(row["close"])})
    assets[sym] = rows

resd = {"family": "hunt-wilder-dmi-system",
        "execution_note": "state at close t earns t->t+1 close-to-close in this implementation; shorts earn mirror return, no margin interest or borrow fee charged (flatters the long-short forms, stated)",
        "assets": {}}
for sym, bars in assets.items():
    cry = sym in ("BTC", "ETH")
    cost = 0.006 if cry else 0.001; fee = 0.0 if cry else 0.01
    roads = ROADS if not cry else {"FULL": ("2014-09-17", "2026-11-20"), "CONT": ("2019-01-01", "2026-11-20"), "VAL": ("2023-01-01", "2026-11-20")}
    dates = [b["d"] for b in bars]; px = np.array([b["c"] for b in bars])
    entry = {}
    for form, fb, lo in [("A_literal_longshort", False, False), ("B_adx_gate_longshort", True, False), ("A_longonly_constructed", False, True)]:
        stt = dmi_states(bars, fb, lo)
        entry[form] = {}
        for road, (a, b) in roads.items():
            nat = timer_sim(dates, px, stt, a, b, cost=cost, fee=fee, shorts=not lo)
            hou = timer_sim(dates, px, stt, a, b, cost=cost, fee=fee, shorts=not lo, floor=True)
            bhh = bh(dates, px, a, b, cost=cost, fee=fee)
            pb = []; beaten = None
            if (form.startswith("A_") and road in ("LONG", "FULL", "VAL")) or (form.startswith("B_") and road in ("LONG", "FULL")):
                idx = [i for i, d in enumerate(dates) if a <= d <= b]
                seg = stt[idx[0]:idx[-1]+1]
                rng = random.Random(3)
                for s in range(20):
                    sh = rng.randint(30, max(31, len(seg) - 30))
                    rot = seg[-sh:] + seg[:-sh]
                    shifted = list(stt)
                    for k2, i2 in enumerate(idx): shifted[i2] = rot[k2]
                    pb.append(timer_sim(dates, px, shifted, a, b, cost=cost, fee=fee, shorts=not lo)["final"])
                beaten = sum(1 for x in pb if nat["final"] > x)
            entry[form][road] = {"native": nat, "house": hou, "buy_hold": bhh, "placebos_20": pb,
                                 "placebos_beaten": beaten,
                                 "period_stats_monthly_native": period_stats(nat["curve"], "monthly")}
    resd["assets"][sym] = entry
    print("DMI", sym, {f: {r: (v["native"]["final"], v["placebos_beaten"]) for r, v in entry[f].items()} for f in entry}, flush=True)
json.dump(resd, open(f"{BASE}/hunt-wilder-dmi-system/results.json", "w"), indent=1)
print("dmi2 done")
