#!/usr/bin/env python3
"""McClellan — V13 BEST RULES (frozen in BEST-RULES-SPEC.md before this run).
Dial design: at each week-end close, f = fraction of that week's trading days
with McClellan Oscillator (EMA19-EMA39 of ratio-adjusted NA) > 0; target SPY
weight = f for the next week; rebalance at next trading day's open.
SPY only, long only, no floor, $100 pot, costs 0.10%/side + $0.01 sell fee.
Breadth CONSTRUCTED from program PIT price stack (v7 long-hold pxfull, 154
non-SPY series), ratio-adjusted NA = 1000*(adv-dec)/total. BIAS: survivor-
leaning, far smaller than NYSE — FLATTERS stability; label travels.
Placebos (20 seeds each): circular shift of weekly target series; random
permutation (random-timing) of weekly target series.
Roads: LONG 2010-01-04, DECADE 2016-11-21, CONT 2019-01-02, VAL 2023-01-03,
all ending 2026-11-20 (first trading day on/after start).
"""
import json, os, glob, time, random, statistics
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
COST = 0.001; SELL_FEE = 0.01; START = 100.0; END = "2026-11-20"
ROADS = {"LONG": "2010-01-04", "DECADE": "2016-11-21", "CONT": "2019-01-02", "VAL": "2023-01-03"}

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
spy_by_date = {b["d"]: b for b in spy}

# --- constructed breadth (identical construction to v12) ---
closes = {}
for p in sorted(glob.glob(os.path.join(DATA, "pxfull_*.json"))):
    t = os.path.basename(p)[7:-5]
    if t == "SPY": continue
    closes[t] = {b["d"]: b["c"] for b in load_bars(p)}
tickers = sorted(closes)
breadth = []
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

a19, a39 = 2 / 20.0, 2 / 40.0
e19 = e39 = None
osc_by_date = {}
for d, na, n in breadth:
    if e19 is None: e19 = e39 = na
    else:
        e19 += a19 * (na - e19); e39 += a39 * (na - e39)
    osc_by_date[d] = e19 - e39

def iso_week(dstr):
    y, m, dd = int(dstr[:4]), int(dstr[5:7]), int(dstr[8:10])
    iso = date(y, m, dd).isocalendar()
    return (iso[0], iso[1])

# weekly targets over the full history: decision date (last trading day of
# week) -> f (fraction of that week's breadth days with osc > 0)
weeks = {}
for d in spy_dates:
    if d in osc_by_date:
        weeks.setdefault(iso_week(d), []).append(d)
weekly_targets = []  # (decision_date, f) sorted
for wk in sorted(weeks):
    ds = sorted(weeks[wk])
    f = sum(1 for d in ds if osc_by_date[d] > 0) / len(ds)
    weekly_targets.append((ds[-1], round(f, 4)))

def run_dial(targets, start, end):
    """targets: list of (decision_date, target_weight) covering the road.
    Rebalance at the open of the first trading day after each decision date."""
    idx = [i for i, b in enumerate(spy) if start <= b["d"] <= end]
    tmap = {}
    for dec, f in targets:
        # execution day = first spy date > dec within road
        nxt = next((spy_dates[j] for j in range(len(spy_dates)) if spy_dates[j] > dec), None)
        if nxt is not None and start <= nxt <= end:
            tmap[nxt] = f
    cash, shares, costs, orders, traded = START, 0.0, 0.0, 0, 0.0
    curve = []
    for i in idx:
        b = spy[i]
        if b["d"] in tmap:
            tgt = tmap[b["d"]]
            val_open = cash + shares * b["o"]
            tgt_shares = (tgt * val_open) / b["o"] if b["o"] > 0 else 0.0
            diff = tgt_shares - shares
            if abs(diff) > 1e-9:
                if diff > 0:  # buy
                    spend = diff * b["o"]
                    fee = spend * COST
                    # cannot spend more cash than held (target<=1 ensures this up to fee)
                    if spend + fee > cash:
                        diff = cash / (b["o"] * (1 + COST)); spend = diff * b["o"]; fee = spend * COST
                    cash -= spend + fee; shares += diff; costs += fee; traded += spend
                else:  # sell
                    proceeds = -diff * b["o"]
                    fee = proceeds * COST + SELL_FEE
                    cash += proceeds - fee; shares += diff; costs += fee; traded += proceeds
                orders += 1
        curve.append([b["d"], round(cash + shares * b["c"], 2)])
    peak, maxdd = -1.0, 0.0
    for d, v in curve:
        peak = max(peak, v); maxdd = max(maxdd, (peak - v) / peak if peak > 0 else 0)
    return {"final": curve[-1][1] if curve else START, "max_dd_pct": round(maxdd * 100, 2),
            "costs": round(costs, 2), "orders": orders, "turnover_traded_usd": round(traded, 2),
            "equity_curve": curve}

def buy_hold(start, end):
    idx = [i for i, b in enumerate(spy) if start <= b["d"] <= end]
    sh = START / (spy[idx[0]]["o"] * (1 + COST))
    curve = [[spy[i]["d"], round(sh * spy[i]["c"], 2)] for i in idx]
    v = sh * spy[idx[-1]]["c"]; final = v - (v * COST + SELL_FEE)
    peak, maxdd = -1.0, 0.0
    for d, vv in curve:
        peak = max(peak, vv); maxdd = max(maxdd, (peak - vv) / peak if peak > 0 else 0)
    return {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 2), "equity_curve": curve}

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

def road_targets(start, end):
    return [(dec, f) for dec, f in weekly_targets if start <= dec <= end]

def avg_exposure(targets):
    return round(statistics.mean([f for _, f in targets]), 3) if targets else 0.0

results = {"family": "McClellan Oscillator & Summation Index", "program": "v13-best-rules",
           "design": "Oscillator-as-dial: weekly target SPY weight = fraction of week's days with Oscillator>0; rebalance next open; no floor",
           "breadth_universe": f"CONSTRUCTED from program PIT price stack: {len(tickers)} non-SPY daily series (v7 long-hold pxfull), ratio-adjusted NA=1000*(adv-dec)/total",
           "bias": "FLATTERS — survivor-leaning universe, far smaller than NYSE; breadth smoother, trends with universe composition. Constructed equity stack largely avoids the modern published NYSE A/D ETF/preferred pollution the McClellans discuss, at the cost of this survivor/small-universe bias.",
           "warmup": "EMAs seeded at first NA value (2008); all roads start >=2010, warmup complete",
           "breadth_coverage": {"first": breadth[0][0], "last": breadth[-1][0], "days": len(breadth),
                                "min_issues": min(n for _, _, n in breadth), "max_issues": max(n for _, _, n in breadth)},
           "roads": {}}
for name, start in ROADS.items():
    end = min(END, spy_dates[-1])
    tg = road_targets(start, end)
    real = run_dial(tg, start, end)
    bh = buy_hold(start, end)
    # placebo 1: circular shift of weekly target weights
    vals = [f for _, f in tg]; decs = [d for d, _ in tg]
    shift_finals = []
    for s in range(20):
        rng = random.Random(2000 + s)
        sh = rng.randrange(1, len(vals))
        sv = vals[sh:] + vals[:sh]
        shift_finals.append(run_dial(list(zip(decs, sv)), start, end)["final"])
    # placebo 2: random permutation (random timing)
    perm_finals = []
    for s in range(20):
        rng = random.Random(3000 + s)
        pv = vals[:]; rng.shuffle(pv)
        perm_finals.append(run_dial(list(zip(decs, pv)), start, end)["final"])
    results["roads"][name] = {
        "window": [start, end], "best_rules": real, "spy_buy_hold": bh,
        "avg_target_weight": avg_exposure(tg), "weeks": len(tg),
        "placebo_shift_finals": [round(x, 2) for x in shift_finals],
        "placebo_shift_beaten": f"{sum(1 for x in shift_finals if real['final'] > x)}/20",
        "placebo_shift_median": round(statistics.median(shift_finals), 2),
        "placebo_perm_finals": [round(x, 2) for x in perm_finals],
        "placebo_perm_beaten": f"{sum(1 for x in perm_finals if real['final'] > x)}/20",
        "placebo_perm_median": round(statistics.median(perm_finals), 2),
        "monthly_distribution": monthly_dist(real["equity_curve"])}
    print(name, "dial", real["final"], "dd", real["max_dd_pct"], "orders", real["orders"],
          "costs", real["costs"], "SPY", bh["final"], "shift", results["roads"][name]["placebo_shift_beaten"],
          "perm", results["roads"][name]["placebo_perm_beaten"], flush=True)
json.dump(results, open(os.path.join(HERE, "results.json"), "w"), indent=1)
print("done")
