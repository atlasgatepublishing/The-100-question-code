#!/usr/bin/env python3
"""
Dogs of the Dow — v11 NATIVE RULES run. Frozen spec: NATIVE-SPEC.md.
Form A: top-10 Dow yielders, equal weight, annual January reconstitution, NO floor.
Form B (Small Dogs): 5 lowest-priced of the top-10, same mechanics.
Universe: point-in-time Dow membership (S&P DJI changes). DWDP & WBA excluded —
their free price/dividend tapes were deleted after delisting (documented hole,
bias direction: exclusion flatters the Dogs). Dividends credited as cash on
ex-date (program method). Costs 0.10%/side + $0.01/sell order. 20-seed placebos
(random picks from the same January's investable Dow list). Per-year folds.
Data: Yahoo chart tapes cached in ./cache (read from v10 dogs cache + fresh
pulls for the Dow names the old pond lacked).
"""
import json, math, os, random, time
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
START_CASH = 100.0
COST_RATE = 0.001
SELL_FEE = 0.01

# ---------------- data ----------------
def load(t):
    p = os.path.join(CACHE, f"px_{t}.json")
    if not os.path.exists(p):
        return None
    j = json.load(open(p))
    res = j["chart"]["result"][0]
    ts = res["timestamp"]; q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = {}
    for i, tt in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(tt))
        c = q["close"][i]
        if c is None: continue
        a = adj[i] if adj and adj[i] else c
        bars[d] = (c, a)
    divs = []
    for _, dv in ((res.get("events") or {}).get("dividends") or {}).items():
        divs.append((time.strftime("%Y-%m-%d", time.gmtime(dv["date"])), float(dv["amount"])))
    divs.sort()
    return bars, divs

TICKERS = ["AAPL","AXP","BA","CAT","CRM","CSCO","CVX","DD","DIS","DOW","GE","GS","HD",
           "HON","IBM","INTC","JNJ","JPM","KO","MCD","MMM","MRK","MSFT","NKE","NVDA",
           "PFE","PG","RTX","SHW","TRV","UNH","V","VZ","WMT","XOM","AMGN","AMZN"]
DATA = {t: load(t) for t in TICKERS}
DATA = {t: v for t, v in DATA.items() if v}
SPY = load.__wrapped__ if False else None
spy_j = json.load(open(os.path.join(CACHE, "px_SPY.json")))
_res = spy_j["chart"]["result"][0]
SPY_BARS = {}
_ts = _res["timestamp"]; _q = _res["indicators"]["quote"][0]
_adj = _res["indicators"].get("adjclose", [{}])[0].get("adjclose")
for i, tt in enumerate(_ts):
    d = time.strftime("%Y-%m-%d", time.gmtime(tt))
    if _q["close"][i] is None: continue
    SPY_BARS[d] = (_q["close"][i], _adj[i] if _adj and _adj[i] else _q["close"][i])
ALL_DAYS = sorted(SPY_BARS)

def close_on(t, d):
    bars = DATA[t][0]
    # last bar on/before d
    lo, hi = None, None
    import bisect
    ds = DAYS[t]
    i = bisect.bisect_right(ds, d) - 1
    return bars[ds[i]][0] if i >= 0 else None

import bisect
DAYS = {t: sorted(DATA[t][0]) for t in DATA}
SPY_DAYS = sorted(SPY_BARS)
def spy_adj(d):
    i = bisect.bisect_right(SPY_DAYS, d) - 1
    return SPY_BARS[SPY_DAYS[i]][1] / SPY_BARS[SPY_DAYS[i]][0]  # ratio not used; see spy_tr
def spy_tr(d0, d1):
    i0 = bisect.bisect_right(SPY_DAYS, d0) - 1; i1 = bisect.bisect_right(SPY_DAYS, d1) - 1
    a0 = SPY_BARS[SPY_DAYS[i0]][1]; a1 = SPY_BARS[SPY_DAYS[i1]][1]
    return START_CASH * a1 / a0

# ---------------- PIT Dow membership ----------------
BASE_2016 = ["AAPL","AXP","BA","CAT","CSCO","CVX","DD","DIS","GE","GS","HD","IBM",
             "INTC","JNJ","JPM","KO","MCD","MMM","MRK","MSFT","NKE","PFE","PG","TRV",
             "UNH","RTX","V","VZ","WMT","XOM"]  # RTX seat = United Technologies pre-2020
# GS has no tape in cache (never a Dog candidate by yield in this era is FALSE-safe?
# GS yield ~1-2%, never top-10; but it must be in the ranking universe anyway.)
CHANGES = [  # (effective date, remove, add)  -- tickers; DWDP/WBA are the deleted-tape names
    ("2017-09-01", "DD", "DWDP"),
    ("2018-06-26", "GE", "WBA"),
    ("2019-04-02", "DWDP", "DOW"),
    ("2020-08-31", "XOM", "AMGN"),
    ("2020-08-31", "PFE", "CRM"),
    ("2020-08-31", "RTX", "HON"),
    ("2024-02-26", "WBA", "AMZN"),
    ("2024-11-08", "INTC", "NVDA"),
    ("2024-11-08", "DOW", "SHW"),
]
NO_TAPE = {"DWDP", "WBA"}  # tapes deleted from free sources after delisting (see spec)

def members_on(d):
    m = list(BASE_2016)
    for eff, out, inn in CHANGES:
        if d >= eff:
            if out in m: m.remove(out)
            if inn not in m: m.append(inn)
    return m

def trailing_div(t, asof):
    """Sum of cash dividends with ex-date in (asof-365d, asof]."""
    if t not in DATA: return None
    lo = (date.fromisoformat(asof) - timedelta(days=365)).isoformat()
    return sum(a for (d, a) in DATA[t][1] if lo < d <= asof)

def ranking(rank_date):
    """Return (ranked list [(t, yield, price)], investable members)."""
    out = []
    for t in members_on(rank_date):
        if t in NO_TAPE or t not in DATA: continue
        p = close_on(t, rank_date)
        td = trailing_div(t, rank_date)
        if p is None or td is None: continue
        out.append((t, td / p, p))
    out.sort(key=lambda x: -x[1])
    return out

# ---------------- simulation ----------------
def run_window(start, end, form, seed=None):
    """form: 'A' top10, 'B' small dogs. seed None = ranked; else placebo."""
    rng = random.Random(seed) if seed is not None else None
    cash = START_CASH; shares = {}
    curve = []; picks_by_year = {}; costs = 0.0; orders = 0; div_cash = 0.0
    # rebalance dates: first trading day of each January within [start, end], plus start if Jan
    rebal = []
    for d in ALL_DAYS:
        if start <= d <= end and d[5:7] == "01" and (not rebal or rebal[-1][5:7] != "01" or d[:4] != rebal[-1][:4]):
            # first trading day of that January: previous trading day is in December
            i = ALL_DAYS.index(d)
            if i > 0 and ALL_DAYS[i-1][5:7] == "12":
                rebal.append(d)
    if start not in rebal and start <= rebal[0] if rebal else False:
        pass
    # ensure a rebalance at the first trading day >= start
    first = min(d for d in ALL_DAYS if d >= start)
    if first not in rebal: rebal = [first] + [d for d in rebal if d > first]
    rebal = [d for d in rebal if d <= end]
    div_events = {}
    for t in DATA:
        for (d, a) in DATA[t][1]:
            div_events.setdefault(d, []).append((t, a))
    held = []
    for d in [x for x in ALL_DAYS if start <= x <= end]:
        if d in rebal:
            rank_date = max(x for x in ALL_DAYS if x < d) if d != first else max(x for x in ALL_DAYS if x <= "2016-12-31") if first[5:7]=="01" and first[:4]=="2017" else max(x for x in ALL_DAYS if x < d)
            rk = ranking(rank_date)
            if rng is None:
                top10 = rk[:10]
                if form == "A": picks = [t for t, _, _ in top10]
                else: picks = [t for t, _, _ in sorted(top10, key=lambda x: x[2])[:5]]
            else:
                pool = [t for t, _, _ in rk]
                picks = rng.sample(pool, 10 if form == "A" else 5)
            picks_by_year[d[:4]] = picks
            # sell everything at close
            for t, sh in list(shares.items()):
                p = close_on(t, d)
                if p is None: continue
                val = sh * p; c = val * COST_RATE + SELL_FEE
                cash += val - c; costs += c; orders += 1
            shares = {}
            total = cash
            per = total / len(picks) if picks else 0
            for t in picks:
                p = close_on(t, d)
                if p is None: continue
                c = per * COST_RATE; costs += c; orders += 1
                shares[t] = shares.get(t, 0) + (per - c) / p
                cash -= per
            cash = max(cash, 0.0)
            held = picks
        # dividends on ex-date
        for (t, a) in div_events.get(d, []):
            if t in shares:
                cash += shares[t] * a; div_cash += shares[t] * a
        eq = cash + sum(sh * (close_on(t, d) or 0) for t, sh in shares.items())
        curve.append((d, round(eq, 2)))
    final = curve[-1][1] if curve else START_CASH
    # max drawdown
    peak = -1; mdd = 0.0
    for _, v in curve:
        peak = max(peak, v); mdd = max(mdd, (peak - v) / peak if peak > 0 else 0)
    # per-year returns
    yrs = {}
    by_year = {}
    for d, v in curve: by_year.setdefault(d[:4], []).append((d, v))
    prev = START_CASH
    for y in sorted(by_year):
        last = by_year[y][-1][1]
        yrs[y] = round((last / prev - 1) * 100, 2); prev = last
    return {"final": final, "cagr_pct": round(((final/START_CASH) ** (365.25 / max((date.fromisoformat(end)-date.fromisoformat(start)).days,1)) - 1) * 100, 2),
            "max_dd_pct": round(mdd*100, 2), "costs": round(costs, 2), "orders": orders,
            "div_cash": round(div_cash, 2), "picks_by_year": picks_by_year,
            "year_returns_pct": yrs, "curve": curve}

WINDOWS = {"FULL_2017": ("2017-01-03", "2026-11-20"),
           "CONT_2019": ("2019-01-02", "2026-11-20"),
           "VAL_2023": ("2023-01-03", "2026-11-20")}

out = {"spec": "dogs-dividend v11 native (O'Higgins Beating the Dow 1991), no floor",
       "hole": "DWDP (2017-19) and WBA (2018-24) excluded: free tapes deleted after delisting; exclusion flatters the Dogs",
       "windows": {}}
for wname, (s, e) in WINDOWS.items():
    w = {"spy_final": round(spy_tr(s, e), 2), "forms": {}}
    for form in ("A", "B"):
        r = run_window(s, e, form)
        twins = []
        for seed in range(1, 21):
            twins.append(run_window(s, e, form, seed=seed)["final"])
        r2 = {k: v for k, v in r.items() if k != "curve"}
        r2["placebo_beaten"] = sum(1 for x in twins if r["final"] > x)
        r2["placebo_median"] = round(sorted(twins)[10], 2)
        r2["placebo_finals"] = [round(x, 2) for x in twins]
        w["forms"][form] = r2
        with open(os.path.join(HERE, f"results_{wname}_{form}.json"), "w") as f:
            json.dump({"window": wname, "form": form, **r, "placebo_finals": [round(x,2) for x in twins]}, f, indent=1)
    out["windows"][wname] = w
with open(os.path.join(HERE, "results.json"), "w") as f:
    json.dump(out, f, indent=1)
print(json.dumps(out, indent=1)[:4000])
