#!/usr/bin/env python3
"""
V13 BEST-RULES — ETF TREND SLEEVE. Spec: BEST-RULES-SPEC.md (frozen before this run).
Monthly (last trading day signal, next-day-open execution).
Trend per asset: signs of 63/126/252d adjusted-close returns; uptrend if >=2 positive.
Risk-on (SPY uptrend): hold SPY+QQQ that are individually in uptrend, equal weight
(100% in the single qualifier if only one). Risk-off: GLD/DBC/UUP in uptrend,
ranked by 126d return, top 2 equal weight; none -> cash.
No TLT/IEF/AGG. Equal weights (no inverse-vol). 20% relative no-trade band.
Costs 0.10%/side + $0.01/sell order. No floor. $100 fresh pot per road.
Data: read-only shared cache backtests/v3/data_etf/ (Yahoo adjusted bars).
Placebos: 20 seeds/road, same regime & holding count, random picks from regime pool.
"""
import json, os, random, statistics
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.expanduser("~/workspace/stock-app/backtests/v3/data_etf")
ON_POOL = ["SPY", "QQQ"]
OFF_POOL = ["GLD", "DBC", "UUP"]
ALL = ON_POOL + OFF_POOL
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

SERIES = {t: load_series(t) for t in ALL}
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
    if i - n < 0: return None
    a, b = close_on(t, CAL[i - n]), close_on(t, d)
    return None if a is None or b is None else b / a - 1.0

def uptrend(t, d):
    rs = [ret_n(t, d, n) for n in (63, 126, 252)]
    if any(r is None for r in rs): return False
    return sum(1 for r in rs if r > 0) >= 2

def vol_free_targets(d, rng=None):
    """Return target weights dict. rng=None -> real rule; else placebo picks."""
    if uptrend("SPY", d):
        pool, mode = ON_POOL, "on"
        if rng is None:
            picks = [t for t in pool if uptrend(t, d)]
        else:
            qual = [t for t in pool if uptrend(t, d)]
            k = len(qual)
            picks = rng.sample(pool, k) if k else []
    else:
        pool, mode = OFF_POOL, "off"
        qual = [t for t in pool if uptrend(t, d)]
        if rng is None:
            qual.sort(key=lambda t: ret_n(t, d, 126), reverse=True)
            picks = qual[:2]
        else:
            k = min(2, len(qual))
            picks = rng.sample(pool, k) if k else []
    if not picks: return {}, mode
    w = 1.0 / len(picks)
    return {t: w for t in picks}, mode

def month_ends(start, end):
    days = [d for d in CAL if start <= d <= end]
    out = []
    for i, d in enumerate(days):
        if i == len(days) - 1 or days[i + 1][:7] != d[:7]:
            out.append(d)
    return out

def run_road(start, end, seed=None):
    rng = random.Random(seed) if seed is not None else None
    days = [d for d in CAL if start <= d <= end]
    rebal = set(month_ends(start, end))
    cash, shares = START, {t: 0.0 for t in ALL}
    costs, orders = 0.0, 0
    pending = None
    curve = []
    def value(d, use_open=False):
        v = cash
        for t in ALL:
            if shares[t]:
                p = open_on(t, d) if use_open else close_on(t, d)
                if p: v += shares[t] * p
        return v
    for idx, d in enumerate(days):
        if pending is not None:  # execute at today's open
            targets = pending; pending = None
            total = value(d, use_open=True)
            cur_w = {}
            for t in ALL:
                p = open_on(t, d)
                cur_w[t] = (shares[t] * p / total) if (shares[t] and p and total > 0) else 0.0
            for t in ALL:
                tw = targets.get(t, 0.0)
                if shares[t] > 0 and tw > 0 and abs(tw - cur_w[t]) / tw <= 0.20:
                    continue  # no-trade band
                p = open_on(t, d)
                if not p: continue
                delta_val = tw * total - shares[t] * p
                if abs(delta_val) < 0.01: continue
                if delta_val < 0:  # sell
                    amt = min(-delta_val, shares[t] * p)
                    fee = amt * COST + SELL_FEE
                    cash += amt - fee; costs += fee; orders += 1
                    shares[t] -= amt / p
                else:  # buy
                    amt = min(delta_val, max(cash - 0.0, 0.0))
                    if amt <= 0: continue
                    fee = amt * COST
                    if amt + fee > cash: amt = cash / (1 + COST); fee = amt * COST
                    cash -= amt + fee; costs += fee; orders += 1
                    shares[t] += amt / p
        curve.append([d, round(value(d), 4)])
        if d in rebal and idx < len(days) - 1:
            pending, _ = vol_free_targets(d, rng)
    final = curve[-1][1] if curve else START
    peak, maxdd = -1e18, 0.0
    for _, v in curve:
        peak = max(peak, v); maxdd = min(maxdd, v / peak - 1.0)
    yrs = (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days / 365.25
    return {"start": start, "end": end, "final": round(final, 2),
            "cagr_pct": round(((final / START) ** (1 / yrs) - 1) * 100, 2),
            "max_dd_pct": round(maxdd * 100, 2), "costs": round(costs, 2),
            "orders": orders, "equity_curve": curve}

def spy_bh(start, end):
    days = [d for d in CAL if start <= d <= end]
    o = open_on("SPY", days[0])
    sh = (START - START * COST) / o
    curve = [[d, round(sh * close_on("SPY", d), 4)] for d in days]
    last = curve[-1][1] - curve[-1][1] * COST - SELL_FEE
    peak, maxdd = -1e18, 0.0
    for _, v in curve:
        peak = max(peak, v); maxdd = min(maxdd, v / peak - 1.0)
    return {"final": round(last, 2), "max_dd_pct": round(maxdd * 100, 2), "equity_curve": curve}

def monthly_dist(curve):
    # month-end values from curve
    me = {}
    for d, v in curve: me[d[:7]] = v
    keys = sorted(me)
    rets = [me[keys[i]] / me[keys[i - 1]] - 1 for i in range(1, len(keys))]
    if not rets: return {}
    los, cur = 0, 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0; los = max(los, cur)
    peak, since, longest = -1e18, 0, 0
    for _, v in curve:
        if v >= peak: peak, since = v, 0
        else: since += 1
        longest = max(longest, since)
    return {"median_month_pct": round(statistics.median(rets) * 100, 2),
            "share_months_positive_pct": round(sum(1 for r in rets if r > 0) / len(rets) * 100, 1),
            "best_month_pct": round(max(rets) * 100, 2), "worst_month_pct": round(min(rets) * 100, 2),
            "longest_losing_month_streak": los, "longest_days_between_highs": longest,
            "n_months": len(rets)}

def year_return(curve, y):
    pts = [(d, v) for d, v in curve if d.startswith(str(y))]
    prev = [(d, v) for d, v in curve if d < f"{y}-01-01"]
    if not pts or not prev: return None
    return round((pts[-1][1] / prev[-1][1] - 1) * 100, 2)

ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CONF = {"CONF_A_2010_2018": ("2010-01-04", "2018-12-31"), "CONF_B_2013_2022": ("2013-01-02", "2022-12-30")}

out = {"slug": "etf-trend-sleeve", "program": "v13-best-rules", "spec": "BEST-RULES-SPEC.md",
       "champions_vm": {"LONG": 1415.62, "CONT": 544.47, "VAL": 288.05, "DECADE": 667.35},
       "published_best_prior": {"DECADE_monthly_final": 194.61, "DECADE_monthly_max_dd_pct": -13.73,
                                "DECADE_weekly_final": 189.75, "DECADE_weekly_max_dd_pct": -10.97,
                                "VAL_monthly_note": "prior monthly VAL not published as a fresh-pot road; weekly VAL $127.14 (v3 window B)"},
       "roads": {}, "confirmation": {}}

for name, (s, e) in ROADS.items():
    r = run_road(s, e)
    spy = spy_bh(s, e)
    twins = [run_road(s, e, seed=1000 + i)["final"] for i in range(20)]
    beaten = sum(1 for t in twins if r["final"] > t)
    yrs_list = sorted({int(d[:4]) for d, _ in r["equity_curve"]})
    r["placebo_beaten"] = beaten
    r["placebo_finals"] = twins
    r["placebo_median"] = round(statistics.median(twins), 2)
    r["monthly_distribution"] = monthly_dist(r["equity_curve"])
    r["year_returns_pct"] = {str(y): year_return(r["equity_curve"], y) for y in yrs_list}
    out["roads"][name] = {"run": r, "spy": {"final": spy["final"], "max_dd_pct": spy["max_dd_pct"]}}
    print(name, r["final"], r["max_dd_pct"], "spy", spy["final"], spy["max_dd_pct"], "placebo", beaten, "/20", flush=True)

# confirmation windows run regardless (frozen in spec; claim only if a champion is beaten)
for name, (s, e) in CONF.items():
    r = run_road(s, e); spy = spy_bh(s, e)
    out["confirmation"][name] = {"run": {k: r[k] for k in ("start", "end", "final", "cagr_pct", "max_dd_pct", "costs", "orders")},
                                "spy": {"final": spy["final"], "max_dd_pct": spy["max_dd_pct"]},
                                "equity_curve": r["equity_curve"]}
    print(name, r["final"], "spy", spy["final"], flush=True)

# standalone calendar-year folds (per-period distribution, fresh $100 each Jan)
folds = {}
for y in range(2010, 2027):
    s = f"{y}-01-01"; e = f"{y}-12-31"
    days = [d for d in CAL if s <= d <= e]
    if len(days) < 20: continue
    r = run_road(days[0], days[-1])
    folds[str(y)] = {"final": r["final"], "max_dd_pct": r["max_dd_pct"]}
out["year_folds"] = folds
vals = [v["final"] - 100 for v in folds.values()]
out["year_fold_summary"] = {"median_year_pct": round(statistics.median(vals), 2),
    "share_years_positive_pct": round(sum(1 for v in vals if v > 0) / len(vals) * 100, 1),
    "best_year": max(folds, key=lambda k: folds[k]["final"]), "worst_year": min(folds, key=lambda k: folds[k]["final"])}
print("folds", folds, flush=True)

with open(os.path.join(HERE, "results.json"), "w") as f:
    json.dump(out, f, indent=1)
print("WROTE results.json")
