#!/usr/bin/env python3
"""Shared v12 slice-4 chassis: daily long/cash timer simulation with
program costs (0.10%/side + $0.01 sell fee), native (no floor) and
house v9 forms (plain -15% floor from episode anchor, daily-close check,
90-day sit-out, one restart, second halt ends the run in cash).
Per-period distribution reporting per Terry's standard."""
import json, time, statistics

COST = 0.001
SELLFEE = 0.01

def load_bars(path):
    """Yahoo chart-format JSON -> [{d,o,c,v}] with dividend/split-adjusted
    open/close (adjclose ratio), raw volume."""
    j = json.load(open(path))
    r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i, t in enumerate(ts):
        if q["close"][i] is None or adj[i] is None or q["open"][i] is None:
            continue
        ratio = adj[i] / q["close"][i]
        bars.append({"d": time.strftime("%Y-%m-%d", time.gmtime(t)),
                     "o": q["open"][i] * ratio, "c": adj[i],
                     "v": q["volume"][i] if q.get("volume") and q["volume"][i] else 0})
    bars.sort(key=lambda b: b["d"])
    return bars

def _house_desired(form, pos, eq, anchor, halts, sitout_left, ended):
    """Returns (desired_override or None, halts, sitout_left, ended, anchor)."""
    if form != "house":
        return None, halts, sitout_left, ended, anchor
    if ended or sitout_left > 0:
        if sitout_left > 0:
            sitout_left -= 1
            if sitout_left == 0 and not ended:
                anchor = eq
        return 0, halts, sitout_left, ended, anchor
    if pos == 1 and eq <= 0.85 * anchor:
        halts += 1
        if halts >= 2:
            return 0, halts, sitout_left, True, anchor
        return 0, halts, 63, ended, anchor
    return None, halts, sitout_left, ended, anchor

def simulate(bars, state, start, end, form="native"):
    """state[i] in {0,1}: desired position decided at close of day i,
    earns day i -> i+1 (close fill). Fresh $100 at first bar >= start."""
    idx = [i for i, b in enumerate(bars) if start <= b["d"] <= end]
    if len(idx) < 2: return None
    eq = 100.0; pos = 0; curve = []; trades = 0; costs = 0.0
    anchor = 100.0; halts = 0; sitout_left = 0; ended = False
    peak = 100.0; maxdd = 0.0
    for k, i in enumerate(idx):
        b = bars[i]
        if k > 0 and pos == 1:
            eq *= b["c"] / bars[idx[k-1]]["c"]
        desired = state[i]
        ov, halts, sitout_left, ended, anchor = _house_desired(
            form, pos, eq, anchor, halts, sitout_left, ended)
        if ov is not None: desired = ov
        if desired != pos:
            if desired == 1:
                c = eq * COST; eq -= c; costs += c; trades += 1; pos = 1
            else:
                c = eq * COST + SELLFEE; eq -= c; costs += c; trades += 1; pos = 0
        curve.append([b["d"], round(eq, 4)])
        peak = max(peak, eq); maxdd = max(maxdd, 1 - eq / peak)
    return {"final": round(eq, 2), "curve": curve, "trades": trades,
            "costs": round(costs, 2), "halts": halts, "max_dd": round(maxdd, 4),
            "ended_by_halt": ended}

def simulate_openfill(bars, state, start, end, form="native"):
    """State changes decided at close of day i execute at the OPEN of
    day i+1 (frozen fill convention of the monthly macro timers)."""
    idx = [i for i, b in enumerate(bars) if start <= b["d"] <= end]
    if len(idx) < 2: return None
    eq = 100.0; pos = 0; curve = []; trades = 0; costs = 0.0
    anchor = 100.0; halts = 0; sitout_left = 0; ended = False
    peak = 100.0; maxdd = 0.0
    pending = None
    for k, i in enumerate(idx):
        b = bars[i]; prev = bars[idx[k-1]] if k > 0 else None
        if k > 0:
            if pending is not None and pending != pos:
                if pos == 1:
                    eq *= b["o"] / prev["c"]; c = eq * COST + SELLFEE
                    eq -= c; costs += c; trades += 1; pos = 0
                else:
                    c = eq * COST; eq -= c; costs += c; trades += 1; pos = 1
                    eq *= b["c"] / b["o"]
                pending = None
            elif pos == 1:
                eq *= b["c"] / prev["c"]
        desired = state[i]
        ov, halts, sitout_left, ended, anchor = _house_desired(
            form, pos, eq, anchor, halts, sitout_left, ended)
        if ov is not None: desired = ov
        pending = desired
        curve.append([b["d"], round(eq, 4)])
        peak = max(peak, eq); maxdd = max(maxdd, 1 - eq / peak)
    return {"final": round(eq, 2), "curve": curve, "trades": trades,
            "costs": round(costs, 2), "halts": halts, "max_dd": round(maxdd, 4),
            "ended_by_halt": ended}

def buy_hold(bars, start, end, cost=COST):
    idx = [i for i, b in enumerate(bars) if start <= b["d"] <= end]
    if len(idx) < 2: return None
    eq = 100.0 * (1 - cost)
    eq *= bars[idx[-1]]["c"] / bars[idx[0]]["c"]
    eq *= (1 - cost)
    return round(eq, 2)

def period_stats(curve, freq="M"):
    marks = {}
    for d, v in curve:
        if freq == "M": key = d[:7]
        elif freq == "H": key = d[:4] + "-H" + ("1" if d[5:7] <= "06" else "2")
        elif freq == "Y": key = d[:4]
        else: key = d[:7]
        marks[key] = v
    keys = sorted(marks)
    vals = [100.0] + [marks[k] for k in keys]
    rets = [vals[i+1] / vals[i] - 1 for i in range(len(vals) - 1)]
    if not rets: return {}
    pos = sum(1 for r in rets if r > 0)
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; streak = max(streak, cur)
    peak = vals[0]; since_high = cur2 = 0
    for v in vals[1:]:
        if v >= peak: peak = v; cur2 = 0
        else: cur2 += 1
        since_high = max(since_high, cur2)
    return {"periods": len(rets), "share_positive": round(pos / len(rets), 3),
            "median": round(statistics.median(rets), 4),
            "best": round(max(rets), 4), "worst": round(min(rets), 4),
            "longest_losing_streak": streak, "longest_below_high_periods": since_high,
            "average_secondary": round(sum(rets) / len(rets), 4)}

ROADS = {"LONG": ("2010-01-01", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-01", "2026-11-20"), "VAL": ("2023-01-01", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
