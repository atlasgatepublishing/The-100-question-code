#!/usr/bin/env python3
"""
V13 BEST-RULES — GEM DUAL MOMENTUM. Spec: BEST-RULES-SPEC.md (frozen before this run).
Monthly, month-end-close signal, next-trading-day-open execution.
MY RULES: offense shelf SPY/EFA/EEM ranked by 252d return; winner held only if it
beats SHY at >=2 of {63,126,252}d lookbacks; else hold better-252d of AGG/GLD if it
beats SHY over 252d, else SHY. 100% single position. NO floor.
COMPARATOR: published form on same engine/data — SPY vs SHY 252d absolute; winner of
SPY/EFA 252d relative; else AGG.
Placebos: 20 seeds/road, monthly uniform random pick from {SPY,EFA,EEM,AGG,GLD,SHY}.
Costs 0.10%/side + $0.01/sell order. $100 fresh pot per road.
Data: read-only shared cache v12-completions/catalog-taa-keller-faa/data_etf_cache/
(Yahoo adjusted bars; adjusted open = open * adjclose/close).
"""
import json, os, random, statistics
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/catalog-taa-keller-faa/data_etf_cache")
OFFENSE = ["SPY", "EFA", "EEM"]
DEFENSE = ["AGG", "GLD"]
BENCH = "SHY"
SHELF = OFFENSE + DEFENSE + [BENCH]
COST = 0.0010
SELL_FEE = 0.01
START = 100.0

def load_series(t):
    with open(os.path.join(CACHE, f"{t}.json")) as f:
        data = json.load(f)
    res = data["chart"]["result"][0]
    ts, q = res["timestamp"], res["indicators"]["quote"][0]
    adj = res["indicators"]["adjclose"][0]["adjclose"] if "adjclose" in res["indicators"] else None
    out = {}
    for i, tt in enumerate(ts):
        d = datetime.fromtimestamp(tt, tz=timezone.utc).strftime("%Y-%m-%d")
        c, o = q["close"][i], q["open"][i]
        if c is None or o is None:
            continue
        if adj is not None and adj[i]:
            out[d] = (o * adj[i] / c, adj[i])
        else:
            out[d] = (o, c)
    return out

SERIES = {t: load_series(t) for t in SHELF}
CAL = sorted(SERIES["SPY"].keys())
CI = {d: i for i, d in enumerate(CAL)}

def close_on(t, d):
    s = SERIES[t]
    if d in s: return s[d][1]
    i = CI[d]
    for j in range(i - 1, -1, -1):
        if CAL[j] in s: return s[CAL[j]][1]
    return None

def open_on(t, d):
    s = SERIES[t]
    return s[d][0] if d in s else close_on(t, d)

def ret_n(t, d, n):
    i = CI[d]
    if i < n: return None
    a, b = close_on(t, CAL[i - n]), close_on(t, d)
    if a is None or b is None: return None
    return b / a - 1.0

def month_ends(ds):
    out = []
    for i, d in enumerate(ds):
        if i + 1 >= len(ds) or ds[i + 1][:7] != d[:7]:
            out.append(d)
    return out

def pick_mine(d):
    rets = {s: ret_n(s, d, 252) for s in OFFENSE}
    if any(v is None for v in rets.values()): return None
    winner = max(OFFENSE, key=lambda s: rets[s])
    votes = 0
    for n in (63, 126, 252):
        rw, rb = ret_n(winner, d, n), ret_n(BENCH, d, n)
        if rw is not None and rb is not None and rw > rb: votes += 1
    if votes >= 2: return winner
    dret = {s: ret_n(s, d, 252) for s in DEFENSE}
    best_def = max(DEFENSE, key=lambda s: dret[s])
    if dret[best_def] > ret_n(BENCH, d, 252): return best_def
    return BENCH

def pick_published(d):
    r_spy, r_shy = ret_n("SPY", d, 252), ret_n(BENCH, d, 252)
    if r_spy is None or r_shy is None: return None
    if r_spy <= r_shy: return "AGG"
    r_efa = ret_n("EFA", d, 252)
    return "SPY" if r_spy >= r_efa else "EFA"

def run(start, end, mode, seed=None):
    rng = random.Random(seed) if seed is not None else None
    ds = [d for d in CAL if start <= d <= end]
    mes = [d for d in month_ends(CAL) if start <= d < end]
    decisions = {}
    for me in mes:
        if rng is not None:
            if ret_n("SPY", me, 252) is None: continue
            decisions[me] = rng.choice(SHELF)
        else:
            p = pick_mine(me) if mode == "mine" else pick_published(me)
            if p is not None: decisions[me] = p
    cash, held, shares, costs, orders = START, None, 0.0, 0.0, 0
    curve, pending = [], None
    for d in ds:
        if pending is not None:
            if held:
                v = shares * open_on(held, d); c = COST * v + SELL_FEE
                cash += v - c; costs += c; orders += 1; held, shares = None, 0.0
            v = cash / (1 + COST); c = COST * v
            shares = v / open_on(pending, d); cash -= v + c; costs += c; orders += 1
            held, pending = pending, None
        if d in decisions and decisions[d] != held:
            pending = decisions[d]
        eq = cash + (shares * close_on(held, d) if held else 0.0)
        curve.append((d, round(eq, 4)))
    return curve, costs, orders

def stats(curve):
    peak, mdd = -1.0, 0.0
    last_high_i, longest_gap, prev_high_val = 0, 0, curve[0][1]
    high_i = 0; runmax = curve[0][1]
    for i, (_, v) in enumerate(curve):
        peak = max(peak, v); mdd = min(mdd, (v / peak - 1) * 100)
        if v >= runmax:
            longest_gap = max(longest_gap, i - high_i); runmax = v; high_i = i
    longest_gap = max(longest_gap, len(curve) - 1 - high_i)
    # monthly period returns
    mvals = {}
    for d, v in curve: mvals[d[:7]] = v
    months = sorted(mvals)
    mrets, prev = [], START
    for m in months:
        mrets.append(mvals[m] / prev - 1.0); prev = mvals[m]
    pos = sum(1 for r in mrets if r > 0)
    streak = longest = 0
    for r in mrets:
        streak = streak + 1 if r <= 0 else 0
        longest = max(longest, streak)
    yrs, prev = {}, START
    ylast = {}
    for d, v in curve: ylast[d[:4]] = v
    for y in sorted(ylast):
        yrs[y] = round((ylast[y] / prev - 1) * 100, 2); prev = ylast[y]
    return {
        "final": round(curve[-1][1], 2), "max_dd_pct": round(mdd, 2),
        "monthly": {"n_months": len(mrets), "median_pct": round(statistics.median(mrets) * 100, 2),
                    "share_positive_pct": round(100 * pos / len(mrets), 1),
                    "best_pct": round(max(mrets) * 100, 2), "worst_pct": round(min(mrets) * 100, 2),
                    "longest_losing_streak_months": longest,
                    "mean_pct_secondary": round(statistics.mean(mrets) * 100, 2)},
        "longest_days_between_new_highs": longest_gap,
        "year_returns_pct": yrs, "worst_year_pct": min(yrs.values()),
    }

ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
res = {"slug": "gem-dual-momentum", "program": "v13-best-rules",
       "spec": "offense SPY/EFA/EEM 252d rank; winner needs >=2 of 63/126/252d beats-SHY votes; else better of AGG/GLD if it beats SHY 252d, else SHY; monthly, next-open, NO floor",
       "windows": {}}
for name, (a, b) in ROADS.items():
    entry = {}
    for mode in ("mine", "published"):
        curve, costs, orders = run(a, b, mode)
        s = stats(curve)
        s.update({"costs": round(costs, 2), "orders": orders, "equity_curve": curve})
        entry[mode] = s
    pls = []
    for i in range(20):
        c, _, _ = run(a, b, "placebo", seed=3000 + i)
        pls.append(round(c[-1][1], 2))
    entry["placebo_beaten"] = sum(1 for p in pls if entry["mine"]["final"] > p)
    entry["placebo_twin_finals"] = pls
    entry["published_placebo_beaten"] = sum(1 for p in pls if entry["published"]["final"] > p)
    res["windows"][name] = entry
    print(name, "mine", entry["mine"]["final"], entry["mine"]["max_dd_pct"],
          "| published", entry["published"]["final"], entry["published"]["max_dd_pct"],
          "| placebo beaten", entry["placebo_beaten"], "/20", flush=True)
json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
print("WROTE results.json")
