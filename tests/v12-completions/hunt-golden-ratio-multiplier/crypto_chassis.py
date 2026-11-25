#!/usr/bin/env python3
"""Crypto daily chassis (program crypto standard): $100 pot, long/cash,
signal at day-t close earns t->t+1, 0.60%/side on switches. House (V9):
plain -15% floor, daily-close check -> exit at next day's close, run stops."""
import statistics

COST = 0.006

def simulate(days, state, start, end, form="native"):
    """days: [{d, c}]; state[i] desired position at close of day i."""
    idx = [i for i, b in enumerate(days) if start <= b["d"] <= end]
    if len(idx) < 2: return None
    eq = 100.0; pos = 0; curve = []; trades = 0; costs = 0.0; halted = False
    peak = 100.0; maxdd = 0.0
    for k, i in enumerate(idx):
        if k > 0 and pos == 1:
            eq *= days[i]["c"] / days[idx[k-1]]["c"]
        desired = state[i]
        if form == "house" and pos == 1 and eq <= 85.0:
            desired = 0; halted = True
        if halted: desired = 0
        if desired != pos:
            c = eq * COST; eq -= c; costs += c; trades += 1; pos = desired
        curve.append([days[i]["d"], round(eq, 4)])
        peak = max(peak, eq); maxdd = max(maxdd, 1 - eq / peak)
    return {"final": round(eq, 2), "curve": curve, "trades": trades,
            "costs": round(costs, 2), "max_dd": round(maxdd, 4), "halted": halted}

def buy_hold(days, start, end):
    idx = [i for i, b in enumerate(days) if start <= b["d"] <= end]
    if len(idx) < 2: return None
    eq = 100.0 * (1 - COST) * days[idx[-1]]["c"] / days[idx[0]]["c"] * (1 - COST)
    return round(eq, 2)

def period_stats(curve, freq="M"):
    marks = {}
    for d, v in curve:
        key = d[:7] if freq == "M" else d[:4]
        marks[key] = v
    keys = sorted(marks)
    vals = [100.0] + [marks[k] for k in keys]
    rets = [vals[i+1] / vals[i] - 1 for i in range(len(vals) - 1)]
    if not rets: return {}
    pos = sum(1 for r in rets if r > 0)
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; streak = max(streak, cur)
    peak = vals[0]; since = cur2 = 0
    for v in vals[1:]:
        if v >= peak: peak = v; cur2 = 0
        else: cur2 += 1
        since = max(since, cur2)
    return {"periods": len(rets), "share_positive": round(pos / len(rets), 3),
            "median": round(statistics.median(rets), 4), "best": round(max(rets), 4),
            "worst": round(min(rets), 4), "longest_losing_streak": streak,
            "longest_below_high_periods": since,
            "average_secondary": round(sum(rets) / len(rets), 4)}

def sma(xs, n):
    out = [None] * len(xs); s = 0.0
    for i, x in enumerate(xs):
        s += x
        if i >= n: s -= xs[i - n]
        if i >= n - 1: out[i] = s / n
    return out
