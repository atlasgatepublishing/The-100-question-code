#!/usr/bin/env python3
"""McClellan Oscillator & Summation Index — frozen zero-cross timer (v12 hunt).
SPEC-FROZEN.md: Oscillator = EMA19(NA)-EMA39(NA) on ratio-adjusted net advances
NA = 1000*(adv-dec)/(adv+dec+unch); Summation = running total of Oscillator.
Long SPY when Oscillator>0 at close, exit to cash when it crosses below zero.
Execution next open. Costs 0.10%/side + $0.01 sell fee. $100 pot.
Native: no floor. House v9: plain -15% floor ($85) checked at close, exit next
open, pot halted permanently for that road.
Breadth CONSTRUCTED from program PIT price stack (v7 long-hold pxfull, 155
series). BIAS: survivor-leaning, far smaller than NYSE — FLATTERS stability.
EMA warmup: EMAs seeded at first NA value; breadth series starts at the first
SPY date (2008), roads start >=2010, so >39-day warmup is complete before any
road opens (spec: seed from first 39 days — satisfied by construction).
Placebos: 20-seed circular shift of in-road desired-state series (native).
"""
import json, os, glob, time, random, math, statistics

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
COST = 0.001; SELL_FEE = 0.01; START = 100.0; FLOOR = 85.0
END = "2026-11-20"
ROADS = {"LONG": "2010-01-01", "DECADE": "2016-11-21", "CONT": "2019-01-01", "VAL": "2023-01-01"}

def load_bars(path):
    j = json.loads(open(path, "rb").read())
    res = j["chart"]["result"][0]; ts = res["timestamp"]; q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, c = q["open"][i], q["close"][i]
        if None in (o, c) or c == 0: continue
        a = adj[i] if adj and adj[i] else c
        r = a / c
        bars.append({"d": d, "o": o * r, "c": a})
    bars.sort(key=lambda b: b["d"]); return bars

spy = load_bars(os.path.join(DATA, "pxfull_SPY.json"))
spy_dates = [b["d"] for b in spy]
spy_idx = {d: i for i, d in enumerate(spy_dates)}

# --- constructed breadth ---
closes = {}  # ticker -> {date: adjclose}
for p in sorted(glob.glob(os.path.join(DATA, "pxfull_*.json"))):
    t = os.path.basename(p)[7:-5]
    if t == "SPY": continue
    m = {}
    for b in load_bars(p): m[b["d"]] = b["c"]
    closes[t] = m
tickers = sorted(closes)
breadth = []  # (date, NA_ratio_adj, n_issues)
for k, d in enumerate(spy_dates):
    if k == 0: continue
    prev = spy_dates[k - 1]
    adv = dec = unch = 0
    for t in tickers:
        m = closes[t]
        if d in m and prev in m:
            if m[d] > m[prev]: adv += 1
            elif m[d] < m[prev]: dec += 1
            else: unch += 1
    tot = adv + dec + unch
    if tot < 20: continue
    breadth.append((d, 1000.0 * (adv - dec) / tot, tot))

# --- McClellan oscillator / summation ---
a19, a39 = 2 / 20.0, 2 / 40.0  # 10% and 5% trend constants
e19 = e39 = None; summ = 0.0
osc_by_date = {}
for d, na, n in breadth:
    if e19 is None: e19 = e39 = na
    else:
        e19 += a19 * (na - e19); e39 += a39 * (na - e39)
    osc = e19 - e39; summ += osc
    osc_by_date[d] = osc
want_by_date = {d: (o > 0) for d, o in osc_by_date.items()}

def run(want, start, end, floor=False):
    cash, shares, costs, orders = START, 0.0, 0.0, 0
    curve, pending, halted = [], None, False
    idx = [i for i, b in enumerate(spy) if start <= b["d"] <= end]
    for k, i in enumerate(idx):
        b = spy[i]
        if pending is not None:
            if pending and shares == 0:
                shares = cash / (b["o"] * (1 + COST)); costs += cash * COST; cash = 0.0; orders += 1
            elif not pending and shares > 0:
                v = shares * b["o"]; f = v * COST + SELL_FEE; costs += f; cash = v - f; shares = 0.0; orders += 1
            pending = None
        val = cash + shares * b["c"]
        curve.append([b["d"], round(val, 2)])
        if halted: continue
        if floor and val <= FLOOR:
            if shares > 0: pending = False
            halted = True; continue
        w = want.get(b["d"])
        if w is not None and k < len(idx) - 1 and w != (shares > 0): pending = w
    peak, maxdd = -1.0, 0.0
    for d, v in curve:
        peak = max(peak, v); maxdd = max(maxdd, (peak - v) / peak if peak > 0 else 0)
    inv = 0; prev_long = False
    # time in market from curve steps is approximated by want state; recompute simply:
    return {"final": curve[-1][1] if curve else START, "max_dd_pct": round(maxdd * 100, 2),
            "costs": round(costs, 2), "orders": orders, "halted": halted, "equity_curve": curve}

def buy_hold(start, end):
    idx = [i for i, b in enumerate(spy) if start <= b["d"] <= end]
    sh = START / (spy[idx[0]]["o"] * (1 + COST))
    curve = [[spy[i]["d"], round(sh * spy[i]["c"], 2)] for i in idx]
    v = sh * spy[idx[-1]]["c"]; final = v - (v * COST + SELL_FEE)
    peak, maxdd = -1.0, 0.0
    for d, vv in curve:
        peak = max(peak, vv); maxdd = max(maxdd, (peak - vv) / peak if peak > 0 else 0)
    return {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 2), "equity_curve": curve}

def exposure(want, start, end):
    ds = [d for d in spy_dates if start <= d <= end and d in want]
    return round(100 * sum(1 for d in ds if want[d]) / max(len(ds), 1), 1)

def monthly_dist(curve):
    by = {}
    for d, v in curve: by.setdefault(d[:7], []).append(v)
    months = sorted(by); rets = []; prev = START
    for m in months:
        e = by[m][-1]; rets.append((m, (e / prev - 1) * 100 if prev else 0.0)); prev = e
    vals = [r for _, r in rets]
    if not vals: return {}
    longest_loss = cur = 0
    for v in vals:
        cur = cur + 1 if v < 0 else 0; longest_loss = max(longest_loss, cur)
    peak = -1; last_high = 0; longest_gap = 0
    for i, (d, v) in enumerate(curve):
        if v >= peak: peak = v; last_high = i
        longest_gap = max(longest_gap, i - last_high)
    gap_months = None
    # stretch between new highs in months from daily curve indices -> convert via dates
    peak = -1; last_d = None; longest_days = 0
    for d, v in curve:
        if v >= peak: peak = v; last_d = d
        if last_d:
            dd = (time.mktime(time.strptime(d, "%Y-%m-%d")) - time.mktime(time.strptime(last_d, "%Y-%m-%d"))) / 86400
            longest_days = max(longest_days, dd)
    return {"periods": len(vals), "pct_profitable": round(100 * sum(1 for v in vals if v > 0) / len(vals), 1),
            "median_pct": round(statistics.median(vals), 2), "best_pct": round(max(vals), 2),
            "worst_pct": round(min(vals), 2), "longest_losing_run_periods": longest_loss,
            "longest_stretch_between_new_highs_days": int(longest_days),
            "average_pct_secondary": round(statistics.mean(vals), 2)}

def placebos(want, start, end, seeds=20):
    ds = [d for d in spy_dates if start <= d <= end]
    states = [want.get(d, False) for d in ds]
    out = []
    for s in range(seeds):
        rng = random.Random(1000 + s)
        sh = rng.randrange(1, len(states))
        shifted = states[sh:] + states[:sh]
        w = {d: shifted[i] for i, d in enumerate(ds)}
        out.append(run(w, start, end, floor=False)["final"])
    return out

results = {"family": "McClellan Oscillator & Summation Index", "ledger_disposition": "HUNT-FOUND (deep-hunt-nonus)",
           "breadth_universe": f"CONSTRUCTED from program PIT price stack: {len(tickers)} non-SPY daily series (v7 long-hold pxfull), ratio-adjusted NA=1000*(adv-dec)/total",
           "bias": "FLATTERS — survivor-leaning universe, far smaller than NYSE; breadth smoother, trends with universe composition",
           "warmup": "EMAs seeded at first NA value; breadth computed from first SPY date (2008); all roads start >=2010, >39 breadth days after seed",
           "breadth_coverage": {"first": breadth[0][0], "last": breadth[-1][0], "days": len(breadth),
                                "min_issues": min(n for _, _, n in breadth), "max_issues": max(n for _, _, n in breadth)},
           "roads": {}}
for name, start in ROADS.items():
    end = min(END, spy_dates[-1])
    nat = run(want_by_date, start, end, floor=False)
    hou = run(want_by_date, start, end, floor=True)
    bh = buy_hold(start, end)
    pl = placebos(want_by_date, start, end)
    beaten = sum(1 for x in pl if nat["final"] > x)
    results["roads"][name] = {"window": [start, end], "native": {k: v for k, v in nat.items()},
        "house_v9": {k: v for k, v in hou.items()}, "spy_buy_hold": {k: v for k, v in bh.items()},
        "exposure_pct": exposure(want_by_date, start, end),
        "placebo_finals": [round(x, 2) for x in pl], "placebos_beaten": f"{beaten}/20",
        "placebo_median": round(statistics.median(pl), 2),
        "monthly_distribution_native": monthly_dist(nat["equity_curve"]),
        "monthly_distribution_house_v9": monthly_dist(hou["equity_curve"])}
    print(name, "native", nat["final"], "house", hou["final"], "SPY", bh["final"], "placebo", beaten, "/20", flush=True)

# confirmation splits (different years) for any road beating SPY
results["confirmation_splits"] = {}
for a, b in [("2010-01-01", "2018-12-31"), ("2019-01-01", "2026-11-20")]:
    nat = run(want_by_date, a, b); bh = buy_hold(a, b)
    results["confirmation_splits"][f"{a[:4]}-{b[:4]}"] = {"native_final": nat["final"], "spy_final": bh["final"]}
json.dump(results, open(os.path.join(HERE, "results.json"), "w"), indent=1)
print("done")
