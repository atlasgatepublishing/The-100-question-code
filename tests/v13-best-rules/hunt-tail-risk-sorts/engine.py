#!/usr/bin/env python3
"""Shared chassis for slice-7 hunt families. Simulation only."""
import json, os, time, statistics
from datetime import date

PXDIR = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
START = 100.0
STK_COST = 0.001; STK_SELL_FEE = 0.01
ROADS = {"LONG": ("2010-01-01", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-01", "2026-11-20"), "VAL": ("2023-01-01", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}

def load_px(tk, pxdir=None):
    p = os.path.join(pxdir or PXDIR, f"pxfull_{tk}.json")
    if not os.path.exists(p): return None
    j = json.load(open(p)); r = j["chart"]["result"][0]
    ts = r["timestamp"]; q = r["indicators"]["quote"][0]; adj = r["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i, t in enumerate(ts):
        if q["close"][i] is None or adj[i] is None or q["open"][i] is None: continue
        ratio = adj[i] / q["close"][i]
        bars.append({"d": time.strftime("%Y-%m-%d", time.gmtime(t)),
                     "o": q["open"][i]*ratio, "h": (q["high"][i] or q["close"][i])*ratio,
                     "l": (q["low"][i] or q["close"][i])*ratio, "c": adj[i],
                     "v": q["volume"][i] or 0})
    bars.sort(key=lambda b: b["d"])
    return bars

def dord(s):
    y, m, d = map(int, s.split("-")); return date(y, m, d).toordinal()

def period_stats(curve, tempo="monthly"):
    if tempo == "monthly": key = lambda d: d[:7]
    elif tempo == "weekly":
        def key(d):
            o = dord(d); return str(o - (date.fromordinal(o).weekday()))
    elif tempo == "annual": key = lambda d: d[:4]
    elif tempo == "daily": key = lambda d: d
    else: key = lambda d: d[:7]
    last = {}
    for d, e in curve: last[key(d)] = (d, e)
    pts = [last[k] for k in sorted(last)]
    rets = [pts[i][1]/pts[i-1][1]-1.0 for i in range(1, len(pts)) if pts[i-1][1] > 0]
    if not rets: return {"periods": 0}
    pos = sum(1 for r in rets if r > 0)
    ls = cur = 0
    for r in rets:
        cur = cur+1 if r < 0 else 0; ls = max(ls, cur)
    peak = pts[0][1]; since = 0; longest = 0
    for d, e in pts:
        if e >= peak: peak = e; since = 0
        else: since += 1; longest = max(longest, since)
    return {"periods": len(rets), "share_positive": round(pos/len(rets), 4),
            "median": round(statistics.median(rets), 5), "best": round(max(rets), 5),
            "worst": round(min(rets), 5), "longest_losing_streak": ls,
            "longest_between_highs_periods": longest,
            "average_secondary": round(statistics.mean(rets), 5)}

def max_dd(curve):
    peak = -1; dd = 0
    for _, e in curve:
        peak = max(peak, e)
        if peak > 0: dd = max(dd, 1 - e/peak)
    return round(dd*100, 2)

def simulate_weights(dates, closes, weights_at, start, end, cost=STK_COST, floor=False):
    si = next(i for i, d in enumerate(dates) if d >= start)
    ei = max(i for i, d in enumerate(dates) if d <= end)
    cash = START; shares = {}; curve = []; costs = 0.0; halts = 0; halt_until = -1; ended = False
    cur_w = {}
    for i in range(si, ei+1):
        d = dates[i]
        eq = cash + sum(sh * closes[tk][i] for tk, sh in shares.items() if closes[tk][i])
        curve.append((d, eq))
        if floor and not ended and dord(d) > halt_until and eq <= 85.0:
            for tk, sh in list(shares.items()):
                if closes[tk][i]: cash += sh*closes[tk][i]*(1-cost); costs += sh*closes[tk][i]*cost
            shares = {}; cur_w = {}; halts += 1
            if halts >= 2: ended = True
            else: halt_until = dord(d) + 90
            eq = cash; curve[-1] = (d, eq)
        if dord(d) <= halt_until or ended: continue
        tgt = weights_at.get(d)
        if tgt is not None and tgt != cur_w:
            eq = cash + sum(sh * closes[tk][i] for tk, sh in shares.items() if closes[tk][i])
            for tk, sh in list(shares.items()):
                if closes[tk][i]: cash += sh*closes[tk][i]*(1-cost); costs += sh*closes[tk][i]*cost
            shares = {}
            for tk, w in tgt.items():
                px = closes[tk][i]
                if px and w > 0:
                    amt = eq * w
                    shares[tk] = amt*(1-cost)/px; cash -= amt; costs += amt*cost
            cur_w = dict(tgt)
    return {"final": round(curve[-1][1], 2), "curve": [(d, round(e, 4)) for d, e in curve],
            "costs": round(costs, 2), "max_dd_pct": max_dd(curve), "halts": halts}

def simulate_weights_fast(dates, closes, weights_at, start, end, cost=STK_COST, floor=False):
    """numpy version of simulate_weights — identical semantics."""
    import numpy as np
    tks = sorted({tk for w in weights_at.values() for tk in w})
    tidx = {tk: k for k, tk in enumerate(tks)}
    P = np.zeros((len(dates), len(tks)))
    for tk in tks:
        col = closes[tk]
        for i, v in enumerate(col):
            if v is not None: P[i, tidx[tk]] = v
    si = next(i for i, d in enumerate(dates) if d >= start)
    ei = max(i for i, d in enumerate(dates) if d <= end)
    cash = START; shares = np.zeros(len(tks)); curve = []; costs = 0.0
    halts = 0; halt_until = -1; ended = False; cur_w = {}
    ords = [dord(d) for d in dates]
    for i in range(si, ei+1):
        eq = cash + float(P[i] @ shares)
        curve.append((dates[i], eq))
        if floor and not ended and ords[i] > halt_until and eq <= 85.0:
            val = P[i] * shares; tot = float(val.sum())
            cash += tot * (1 - cost); costs += tot * cost
            shares[:] = 0; cur_w = {}; halts += 1
            if halts >= 2: ended = True
            else: halt_until = ords[i] + 90
            eq = cash; curve[-1] = (dates[i], eq)
        if ords[i] <= halt_until or ended: continue
        tgt = weights_at.get(dates[i])
        if tgt is not None and tgt != cur_w:
            eq = cash + float(P[i] @ shares)
            val = P[i] * shares; tot = float(val.sum())
            cash += tot * (1 - cost); costs += tot * cost
            shares[:] = 0
            for tk, w in tgt.items():
                px = P[i, tidx[tk]]
                if px > 0 and w > 0:
                    amt = eq * w
                    shares[tidx[tk]] = amt * (1 - cost) / px; cash -= amt; costs += amt * cost
            cur_w = dict(tgt)
    return {"final": round(curve[-1][1], 2), "curve": [(d, round(float(e), 4)) for d, e in curve],
            "costs": round(costs, 2), "max_dd_pct": max_dd(curve), "halts": halts}

def simulate_single(bars, state, start, end, cost=STK_COST, sell_fee=STK_SELL_FEE, floor=False, shorts=False):
    si = next((i for i, b in enumerate(bars) if b["d"] >= start), None)
    ei = max((i for i, b in enumerate(bars) if b["d"] <= end), default=None)
    if si is None or ei is None or ei <= si: return None
    cash = START; sh = 0.0; curve = []; costs = 0.0; orders = 0; halts = 0; halt_until = -1; ended = False
    invested_days = 0
    for i in range(si, ei+1):
        b = bars[i]
        eq = cash + sh*b["c"]
        curve.append((b["d"], eq))
        if sh != 0: invested_days += 1
        if floor and not ended and dord(b["d"]) > halt_until and eq <= 85.0:
            if sh > 0:
                cash += sh*b["c"]*(1-cost) - sell_fee; costs += sh*b["c"]*cost + sell_fee; sh = 0; orders += 1
            elif sh < 0:
                cash += sh*b["c"]*(1+cost); costs += abs(sh)*b["c"]*cost; sh = 0; orders += 1
            halts += 1
            if halts >= 2: ended = True
            else: halt_until = dord(b["d"]) + 90
            curve[-1] = (b["d"], cash); eq = cash
        if i >= ei: break
        want = state[i] if i < len(state) else 0
        if shorts:
            want = 1 if want > 0 else (-1 if want < 0 else 0)
            cur = 1 if sh > 0 else (-1 if sh < 0 else 0)
        else:
            want = 1 if want else 0
            cur = 1 if sh > 0 else 0
        if want != cur and dord(b["d"]) > halt_until and not ended:
            nb = bars[i+1]
            if sh > 0:
                cash += sh*nb["o"]*(1-cost) - sell_fee; costs += sh*nb["o"]*cost + sell_fee; sh = 0; orders += 1
            elif sh < 0:
                cash += sh*nb["o"]*(1+cost); costs += abs(sh)*nb["o"]*cost; sh = 0; orders += 1
            if want > 0:
                amt = cash; sh = amt*(1-cost)/nb["o"]; cash -= amt; costs += amt*cost; orders += 1
            elif want < 0:
                amt = cash; sh = -amt*(1-cost)/nb["o"]; cash += amt*(1-cost); costs += amt*cost; orders += 1
    return {"final": round(curve[-1][1], 2), "curve": [(d, round(e, 4)) for d, e in curve],
            "costs": round(costs, 2), "orders": orders, "max_dd_pct": max_dd(curve),
            "halts": halts, "invested_share": round(invested_days/max(1, len(curve)), 3)}

def buy_hold(bars, start, end, cost=STK_COST, sell_fee=STK_SELL_FEE):
    si = next((i for i, b in enumerate(bars) if b["d"] >= start), None)
    ei = max((i for i, b in enumerate(bars) if b["d"] <= end), default=None)
    if si is None or ei is None: return None
    sh = START*(1-cost)/bars[si]["o"]
    curve = [(bars[i]["d"], sh*bars[i]["c"]) for i in range(si, ei+1)]
    return {"final": round(sh*bars[ei]["c"]*(1-cost) - sell_fee, 2),
            "curve": [(d, round(e, 4)) for d, e in curve], "max_dd_pct": max_dd(curve)}
