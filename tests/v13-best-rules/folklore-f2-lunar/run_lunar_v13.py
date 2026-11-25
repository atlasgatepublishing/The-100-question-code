#!/usr/bin/env python3
"""V13 BEST-RULES — F-2 Lunar. Spec: BEST-RULES-SPEC.md (frozen before this run).
New-moon +/-7d window, long SPY / cash, executed AT THE CLOSE on boundary days
(buy at close of last out-window day, sell at close of last in-window day) so every
window day is owned fully, matching the papers' close-to-close measurement.
Costs 0.10%/side + $0.01/sell. No floor. Placebos: 20 circular phase shifts + full-moon control.
Moon dates: synodic (ref new moon 2000-01-06, period 29.530588853 d) — identical to v11."""
import json, os, sys, random
from datetime import date, timedelta
import datetime as _dt

PX = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
raw = json.load(open(PX))["chart"]["result"][0]
ts = raw["timestamp"]; q = raw["indicators"]["quote"][0]; adj = raw["indicators"]["adjclose"][0]["adjclose"]
bars = []
for i, t in enumerate(ts):
    c = q["close"][i]; o = q["open"][i]; a = adj[i]
    if c is None or o is None or a is None: continue
    d = _dt.datetime.utcfromtimestamp(t).date().isoformat()
    bars.append({"date": d, "open": o * (a / c), "close": a})
bars.sort(key=lambda b: b["date"])
BARIDX = {b["date"]: i for i, b in enumerate(bars)}

COST = 0.001; FEE = 0.01

def run_close(bars, desired, start, end):
    """Position during day t = desired[t]. Trades execute at the CLOSE of the day
    before the position changes. $100 start; liquidated at final close."""
    idx = [i for i, b in enumerate(bars) if start <= b["date"] <= end]
    if not idx: return None
    cash = 100.0; shares = 0.0; orders = 0; costs = 0.0; curve = []; in_days = 0
    # pre-window entry: if first day wants long, buy at prior bar's close (fallback: first open)
    first = bars[idx[0]]
    if desired.get(first["date"], False):
        if idx[0] > 0:
            px = bars[idx[0] - 1]["close"]
        else:
            px = first["open"]
        c = cash * COST; shares = (cash - c) / px; costs += c; cash = 0.0; orders += 1
    for j, i in enumerate(idx):
        b = bars[i]
        if shares > 0: in_days += 1
        eq = cash + shares * b["close"]
        curve.append([b["date"], round(eq, 4)])
        # trade at this close for tomorrow's desired state (within window only)
        if j + 1 < len(idx):
            want_next = desired.get(bars[idx[j + 1]]["date"], False)
            if want_next and shares == 0:
                c = cash * COST; shares = (cash - c) / b["close"]; costs += c; cash = 0.0; orders += 1
            elif not want_next and shares > 0:
                val = shares * b["close"]; c = val * COST + FEE; cash = val - c; costs += c; shares = 0.0; orders += 1
    if shares > 0:
        b = bars[idx[-1]]; val = shares * b["close"]; c = val * COST + FEE; cash = val - c; costs += c; orders += 1; shares = 0.0
        curve[-1][1] = round(cash, 4)
    final = curve[-1][1]
    peak = 100.0; mdd = 0.0
    for _, e in curve:
        peak = max(peak, e); mdd = max(mdd, (peak - e) / peak * 100)
    yrs = (date.fromisoformat(end) - date.fromisoformat(start)).days / 365.25
    return {"final": round(final, 2),
            "cagr_pct": round(((final / 100) ** (1 / yrs) - 1) * 100, 2) if final > 0 else -100,
            "max_dd_pct": round(mdd, 2), "costs": round(costs, 2), "orders": orders,
            "time_in_market_pct": round(in_days / max(len(idx), 1) * 100, 1), "curve": curve}

REF = date(2000, 1, 6); SYN = 29.530588853
def events(kind, lo, hi):
    out = []; k = 0
    while True:
        base = REF + timedelta(days=SYN * k) if kind == "new" else REF + timedelta(days=SYN * (k + 0.5))
        if base > hi: break
        if base >= lo: out.append(base)
        k += 1
    return out

def desired_map(half, kind):
    ev = events(kind, date(2007, 1, 1), date(2027, 1, 1))
    des = {}
    for b in bars:
        d = date.fromisoformat(b["date"])
        des[b["date"]] = any(abs((d - e).days) <= half for e in ev)
    return des

def placebos(bars, desired, start, end, seeds=20):
    dates = [b["date"] for b in bars if start <= b["date"] <= end]
    vals = [desired.get(d, False) for d in dates]; n = len(vals); out = []
    for s in range(1, seeds + 1):
        rng = random.Random(s); sh = rng.randint(60, n - 60)
        shifted = vals[-sh:] + vals[:-sh]
        des = dict(zip(dates, shifted))
        # desired outside window irrelevant; run_close only consults in-window + prior close
        full = dict(desired); full.update(des)
        out.append(run_close(bars, full, start, end)["final"])
    ss = sorted(out)
    return {"finals": out, "median": ss[len(ss) // 2], "p90": ss[int(len(ss) * 0.9) - 1], "max": max(out)}

def stretch_stats(curve):
    peak = -1; peak_date = None; longest = 0; cur_start = None
    prev_peak_date = None
    for d, e in curve:
        if e >= peak:
            if prev_peak_date is not None:
                gap = (date.fromisoformat(d) - date.fromisoformat(prev_peak_date)).days
                longest = max(longest, gap)
            peak = e; prev_peak_date = d
    # trailing stretch from last high to end
    if curve and prev_peak_date is not None:
        gap = (date.fromisoformat(curve[-1][0]) - date.fromisoformat(prev_peak_date)).days
        longest = max(longest, gap)
    return {"longest_days_between_new_highs": longest}

WINDOWS = [("LONG", "2010-01-01", "2026-11-20"), ("CONT", "2019-01-01", "2026-11-20"),
           ("VAL", "2023-01-01", "2026-11-20"), ("DECADE", "2016-11-21", "2026-11-20")]
des = desired_map(7, "new"); ctrl = desired_map(7, "full")
all_true = {b["date"]: True for b in bars}
res = {"family": "folklore-f2-lunar", "program": "v13-best-rules",
       "form": "new-moon ±7d, close execution, SPY long/cash, no floor, costs 0.10%/side + $0.01/sell",
       "windows": {}}
for w, s, e in WINDOWS:
    r = run_close(bars, des, s, e); c = run_close(bars, ctrl, s, e); sp = run_close(bars, all_true, s, e)
    res["windows"][w] = {"strategy": r, "full_moon_control_final": c["final"],
                         "full_moon_control_dd": c["max_dd_pct"],
                         "spy_final": sp["final"], "spy_max_dd_pct": sp["max_dd_pct"]}
res["placebos_long"] = placebos(bars, des, "2010-01-01", "2026-11-20")
res["placebos_decade"] = placebos(bars, des, "2016-11-21", "2026-11-20")
folds = {}
for y in range(2010, 2027):
    s = f"{y}-01-01"; e = f"{y}-12-31" if y < 2026 else "2026-11-20"
    folds[str(y)] = run_close(bars, des, s, e)
res["year_folds"] = {y: {"final": f["final"], "max_dd_pct": f["max_dd_pct"]} for y, f in folds.items()}
vals = [f["final"] for f in folds.values()]
sv = sorted(vals)
streak = 0; worst_streak = 0
for v in vals:
    streak = streak + 1 if v < 100 else 0
    worst_streak = max(worst_streak, streak)
res["period_distribution"] = {
    "unit": "calendar year, fresh $100 each year, LONG window 2010-2026",
    "median_year_final": sv[len(sv) // 2],
    "share_years_positive": round(sum(1 for v in vals if v > 100) / len(vals) * 100, 1),
    "best_year_final": max(vals), "worst_year_final": min(vals),
    "longest_losing_streak_years": worst_streak,
    **stretch_stats(res["windows"]["LONG"]["strategy"]["curve"])}
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.json")
json.dump(res, open(out, "w"), indent=1)
for w, v in res["windows"].items():
    print(w, "strategy", v["strategy"]["final"], "DD", v["strategy"]["max_dd_pct"],
          "| control", v["full_moon_control_final"], "| SPY", v["spy_final"],
          "| costs", v["strategy"]["costs"], "orders", v["strategy"]["orders"])
print("placebo LONG median/max", res["placebos_long"]["median"], res["placebos_long"]["max"])
print("placebo DECADE median/max", res["placebos_decade"]["median"], res["placebos_decade"]["max"])
print("distribution", res["period_distribution"])
