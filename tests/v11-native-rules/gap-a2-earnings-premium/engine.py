"""V11 native Earnings Announcement Premium (Frazzini & Lamont 2007), long leg only.
Monthly: at the first trading day of month m, equal-weight every universe firm EXPECTED
to announce that month = it filed a quarterly EPS fact in month m of the prior year
(EDGAR filed dates, point-in-time). Hold one month, rebalance. $100, fractional shares.
Costs: 0.10%/side for v3-cache (large) names, 0.35%/side for v4-only (small/mid) names.
Placebos: random same-count names each month, seeds 1..20. No stop/floor (none published).
"""
import json, os, glob, random, statistics
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
V3 = "/home/hatch/workspace/stock-app/backtests/v3/pead-cache"
V4 = "/home/hatch/workspace/stock-app/backtests/v4/pead-small-cache"
EPS = os.path.join(HERE, "eps_cache")

def load_px(t):
    for c in (V3, V4):
        p = os.path.join(c, f"px_{t}.json")
        if os.path.exists(p):
            d = json.load(open(p))["chart"]["result"][0]
            out = {}
            for i, x in enumerate(d["timestamp"]):
                a = d["indicators"]["adjclose"][0]["adjclose"][i]
                if a: out[date.fromtimestamp(x).isoformat()] = a
            return out
    return {}

large = {os.path.basename(f)[3:-5] for f in glob.glob(os.path.join(V3, "px_*.json"))} - {"SPY"}
tickers = sorted(({os.path.basename(f)[3:-5] for c in (V3, V4)
                   for f in glob.glob(os.path.join(c, "px_*.json"))} - {"SPY"}))
px = {t: load_px(t) for t in tickers}
spy = load_px("SPY")
cal = sorted(spy.keys()); cal_idx = {d: i for i, d in enumerate(cal)}
cost = {t: (0.0010 if t in large else 0.0035) for t in tickers}

# announcement months per ticker: set of (year, month) of EPS fact filed dates
ann_months = {}
for t in tickers:
    fp = os.path.join(EPS, f"eps_{t}.json")
    if not os.path.exists(fp): continue
    ann_months[t] = {(int(f["filed"][:4]), int(f["filed"][5:7])) for f in json.load(open(fp))["facts"]}

def expected(y, m, rng=None):
    base = [t for t in tickers if (y - 1, m) in ann_months.get(t, set())]
    if rng is not None:
        return rng.sample(tickers, min(len(base), len(tickers)))
    return base

def run(start, end, seed=None):
    rng = random.Random(seed) if seed is not None else None
    months = []
    y, m = int(start[:4]), int(start[5:7])
    while (y, m) <= (int(end[:4]), int(end[5:7])):
        months.append((y, m)); m += 1
        if m == 13: y, m = y + 1, 1
    cash, holdings, curve, total_cost = 100.0, {}, [], 0.0
    month_first = {}
    for d in cal:
        ym = (int(d[:4]), int(d[5:7]))
        if ym not in month_first: month_first[ym] = d
    for d in cal:
        if not (start <= d <= end): continue
        ym = (int(d[:4]), int(d[5:7]))
        if month_first.get(ym) == d:
            # sell all
            for t, sh in list(holdings.items()):
                p = px[t].get(d)
                if p: cash += sh * p * (1 - cost[t]); total_cost += sh * p * cost[t]
            holdings = {}
            names = [t for t in expected(ym[0], ym[1], rng) if px[t].get(d)]
            if names:
                per = cash / len(names)
                for t in names:
                    holdings[t] = per * (1 - cost[t]) / px[t][d]; total_cost += per * cost[t]
                cash = 0.0
        eq = cash + sum(sh * px[t].get(d, 0) for t, sh in holdings.items())
        curve.append([d, round(eq, 2)])
    final = curve[-1][1] if curve else 100.0
    peak, mdd = 100.0, 0.0
    for _, v in curve: peak = max(peak, v); mdd = min(mdd, v / peak - 1)
    s0, s1 = spy.get(curve[0][0]), spy.get(curve[-1][0])
    return {"final": final, "max_dd_pct": round(mdd * 100, 2), "costs": round(total_cost, 2),
            "spy_final": round(100 * s1 / s0, 2) if s0 and s1 else None, "curve": curve}

windows = {"FULL_2019_2026": ("2019-01-01", "2026-11-20"),
           "DESIGN_2019_2022": ("2019-01-01", "2022-12-31"),
           "VAL_2023_2026": ("2023-01-01", "2026-11-20")}
out = {"universe_n": len(tickers), "windows": {}}
for w, (a, b) in windows.items():
    out["windows"][w] = run(a, b)
pls = [run(*windows["FULL_2019_2026"], seed=s)["final"] for s in range(1, 21)]
real = out["windows"]["FULL_2019_2026"]["final"]
out["placebos_full"] = {"finals": pls, "beaten": sum(1 for x in pls if real > x),
                        "median": round(statistics.median(pls), 2)}
json.dump(out, open(os.path.join(HERE, "results.json"), "w"))
print({w: out["windows"][w]["final"] for w in windows},
      "spy", {w: out["windows"][w]["spy_final"] for w in windows},
      "dd", {w: out["windows"][w]["max_dd_pct"] for w in windows},
      "placebo beaten", out["placebos_full"]["beaten"], "/20 median", out["placebos_full"]["median"])
