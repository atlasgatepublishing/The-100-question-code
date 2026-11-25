#!/usr/bin/env python3
"""V13 BEST RULES — Permanent Portfolio. Spec frozen in BEST-RULES-SPEC.md.
My rules: 40 SPY / 20 TLT / 25 GLD / 15 SHY, annual rebalance TO TARGET, NO floor.
Comparator (same engine): published 25/25/25/25, 15-35% band, annual check, no floor.
Placebos: 20 Dirichlet random static allocations, annual rebalance to target.
Data: Yahoo chart API adjclose (public), cached in this folder's data/ only.
Costs: 0.10%/side. Close-valued equity, v11-native convention."""
import calendar, json, os, time, urllib.request, datetime, random, statistics

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data"); os.makedirs(DATA, exist_ok=True)
SYMS = ["SPY", "TLT", "GLD", "SHY"]
COST = 0.001
MY_W = {"SPY": 0.40, "TLT": 0.20, "GLD": 0.25, "SHY": 0.15}
PUB_W = {s: 0.25 for s in SYMS}

def fetch(ticker, p1="2009-01-01", p2="2026-11-21"):
    path = os.path.join(DATA, f"px_{ticker}.json")
    if os.path.exists(path) and os.path.getsize(path) > 100:
        blob = open(path, "rb").read()
    else:
        t1 = calendar.timegm(time.strptime(p1, "%Y-%m-%d")); t2 = calendar.timegm(time.strptime(p2, "%Y-%m-%d"))
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?period1={t1}&period2={t2}&interval=1d&events=div,split"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        blob = urllib.request.urlopen(req, timeout=60).read()
        open(path, "wb").write(blob)
    j = json.loads(blob); res = j["chart"]["result"][0]
    ts = res["timestamp"]; adj = res["indicators"]["adjclose"][0]["adjclose"]
    return {datetime.date.fromtimestamp(t): p for t, p in zip(ts, adj) if p}

PX = {s: fetch(s) for s in SYMS}
DATES = sorted(PX["SPY"].keys())

def run(start, end, weights, mode):
    """mode: 'target' = annual rebalance to target; 'band' = published 15-35% band check."""
    dates = [d for d in DATES if start <= d <= end]
    cash = 0.0; shares = {}; costs = 0.0; orders = 0
    d0 = dates[0]
    for s in SYMS:
        v = weights[s] * 100.0; c = COST * v; costs += c; cash -= c
        shares[s] = (v) / PX[s][d0]; orders += 1
    # cash starts at 100, buys funded from it: track equity directly (cash = 100 - spent - costs)
    cash = 100.0 - sum(weights[s] * 100.0 for s in SYMS) - costs
    checkdates = set(); prev = None
    for d in dates:
        if prev and d.year != prev.year: checkdates.add(d)
        prev = d
    curve = []
    for d in dates:
        eq = cash + sum(shares[s] * PX[s][d] for s in SYMS)
        if d in checkdates and d != d0:
            w = {s: shares[s] * PX[s][d] / eq for s in SYMS}
            fire = True if mode == "target" else any(w[s] < 0.15 or w[s] > 0.35 for s in SYMS)
            if fire:
                for s in SYMS:
                    target = weights[s] * eq; cur = shares[s] * PX[s][d]; diff = target - cur
                    if abs(diff) > 1e-9:
                        c = COST * abs(diff); costs += c; cash -= diff + c; shares[s] = target / PX[s][d]; orders += 1
                eq = cash + sum(shares[s] * PX[s][d] for s in SYMS)
        curve.append((str(d), round(eq, 4)))
    return curve, round(costs, 2), orders

def spy_run(start, end):
    dates = [d for d in DATES if start <= d <= end]
    sh = (100.0 * (1 - COST)) / PX["SPY"][dates[0]]
    curve = [(str(d), round(sh * PX["SPY"][d], 4)) for d in dates]
    final = round(curve[-1][1] * (1 - COST), 2)
    return curve, final

def stats(curve, final=None):
    vals = [v for _, v in curve]
    peak = -1; mdd = 0.0; mdd_d = None; since_high = 0; longest_no_high = 0
    for d, v in curve:
        if v >= peak: peak = v; since_high = 0
        else:
            since_high += 1; longest_no_high = max(longest_no_high, since_high)
            dd = (v / peak - 1) * 100
            if dd < mdd: mdd, mdd_d = dd, d
    yrs = {}
    for ds, v in curve: yrs.setdefault(ds[:4], []).append(v)
    yr = {}; prev_last = 100.0
    for y in sorted(yrs):
        yr[y] = round((yrs[y][-1] / prev_last - 1) * 100, 2); prev_last = yrs[y][-1]
    rets = list(yr.values())
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0; streak = max(streak, cur)
    return {"final": round(final if final is not None else vals[-1], 2),
            "max_dd_pct": round(mdd, 2), "max_dd_date": mdd_d,
            "year_returns_pct": yr,
            "median_year_pct": round(statistics.median(rets), 2),
            "share_years_positive_pct": round(100 * sum(1 for r in rets if r > 0) / len(rets), 1),
            "best_year_pct": max(rets), "worst_year_pct": min(rets),
            "longest_losing_year_streak": streak,
            "longest_no_new_high_trading_days": longest_no_high}

ROADS = {"LONG": (datetime.date(2010, 1, 4), datetime.date(2026, 11, 20)),
         "DECADE": (datetime.date(2016, 11, 21), datetime.date(2026, 11, 20)),
         "CONT": (datetime.date(2019, 1, 2), datetime.date(2026, 11, 20)),
         "VAL": (datetime.date(2023, 1, 3), datetime.date(2026, 11, 20))}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}

out = {"slug": "permanent-portfolio", "program": "v13-best-rules",
       "spec": "MY: 40/20/25/15 SPY/TLT/GLD/SHY, annual rebalance to target, NO floor. PUBLISHED: 25/25/25/25, 15-35% band, annual check, no floor. Costs 0.10%/side.",
       "windows": {}}
for name, (a, b) in ROADS.items():
    mc, mcost, mord = run(a, b, MY_W, "target"); ms = stats(mc); ms.update(costs=mcost, orders=mord)
    pc, pcost, pord = run(a, b, PUB_W, "band"); ps = stats(pc); ps.update(costs=pcost, orders=pord)
    sc, sfin = spy_run(a, b); ss = stats(sc, final=sfin)
    rng = random.Random(1300 + hash(name) % 10000)
    placebo_finals = []
    for seed in range(20):
        r2 = random.Random(7000 + seed)
        xs = [r2.random() for _ in SYMS]; tot = sum(xs)
        w = {s: x / tot for s, x in zip(SYMS, xs)}
        c2, _, _ = run(a, b, w, "target"); placebo_finals.append(round(c2[-1][1], 2))
    placebo_finals_sorted = sorted(placebo_finals)
    block = {"window": [str(a), str(b)], "my_rules": {**ms, "equity_curve": mc},
             "published": {**ps, "equity_curve": pc},
             "spy": {**ss, "equity_curve": sc},
             "placebo_random_allocations": {"finals_sorted": placebo_finals_sorted,
                "median": round(statistics.median(placebo_finals), 2),
                "max": max(placebo_finals),
                "my_beats": sum(1 for f in placebo_finals if ms["final"] > f),
                "published_beats": sum(1 for f in placebo_finals if ps["final"] > f)},
             "champion_VM": CHAMP[name]}
    out["windows"][name] = block
    print(name, "MY", ms["final"], "DD", ms["max_dd_pct"], "| PUB", ps["final"], "DD", ps["max_dd_pct"],
          "| SPY", ss["final"], "| placebo med", block["placebo_random_allocations"]["median"],
          "my beats", block["placebo_random_allocations"]["my_beats"], "/20", flush=True)

# Confirmation windows (spec S8) — computed for the record; claim only if a champion was beaten.
out["confirmation_windows"] = {}
for name, (a, b) in {"CONF1_2010_2018": (datetime.date(2010, 1, 4), datetime.date(2018, 12, 31)),
                     "CONF2_2013_2022": (datetime.date(2013, 1, 2), datetime.date(2022, 12, 30))}.items():
    mc, _, _ = run(a, b, MY_W, "target"); pc, _, _ = run(a, b, PUB_W, "band"); sc, sfin = spy_run(a, b)
    out["confirmation_windows"][name] = {"window": [str(a), str(b)], "my_final": round(mc[-1][1], 2),
        "my_max_dd_pct": stats(mc)["max_dd_pct"], "published_final": round(pc[-1][1], 2), "spy_final": sfin}
    print(name, out["confirmation_windows"][name], flush=True)

json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
print("DONE")
