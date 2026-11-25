#!/usr/bin/env python3
"""
V13 BEST-RULES — GOLDEN-CROSS TOURNAMENT. Spec: BEST-RULES-SPEC.md (frozen before this run).
Per sector (9 classic SPDRs): golden-cross state SMA50>SMA200 on dividend-adjusted
daily closes. Monthly tournament: signal at month-end close (plus tournament seeding
from the close before the window), execute next trading day's open. Eligible =
cross-positive sectors, ranked by cross strength SMA50/SMA200-1, hold top 3 equal
weight; fewer eligible -> those only, rest cash; none -> cash.
Costs 0.10%/side + $0.01/sell order. Min trade $0.50. No floor. $100 fresh pot/road.
Placebos: 20 seeds/road — same slot count k per rebalance, random sector picks.
Data (read-only): pxfull adjusted caches — sectors from v13 bollinger-squeeze/data
(same pxfull cache family), SPY from v7/long-hold/data.
"""
import json, os, random, statistics
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SECTOR_DIR = os.path.expanduser("~/workspace/stock-app/backtests/v13-best-rules/bollinger-squeeze/data")
SPY_PATH = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
SECTORS = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]
COST = 0.0010
SELL_FEE = 0.01
MIN_TRADE = 0.50
START = 100.0

def load_pxfull(path):
    with open(path, "rb") as f:
        j = json.loads(f.read())
    res = j["chart"]["result"][0]
    ts, q = res["timestamp"], res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    out = {}
    for i, t in enumerate(ts):
        d = datetime.utcfromtimestamp(t).strftime("%Y-%m-%d")
        o, c = q["open"][i], q["close"][i]
        if c is None or o is None:
            continue
        a = adj[i] if adj and adj[i] else c
        out[d] = (o * a / c, a)
    return out

SERIES = {t: load_pxfull(os.path.join(SECTOR_DIR, f"pxfull_{t}.json")) for t in SECTORS}
SERIES["SPY"] = load_pxfull(SPY_PATH)
CAL = sorted(SERIES["SPY"].keys())
CI = {d: i for i, d in enumerate(CAL)}

# forward-filled closes on the SPY calendar + opens (fall back to close)
CLOSE, OPEN = {}, {}
for t, s in SERIES.items():
    cl, op, last = {}, {}, None
    for d in CAL:
        if d in s:
            op[d], cl[d] = s[d][0], s[d][1]
            last = s[d][1]
        else:
            cl[d] = last
            op[d] = last
    CLOSE[t], OPEN[t] = cl, op

# SMA50 / SMA200 of adjusted closes, and cross strength, per sector per date
SMA = {}
for t in SECTORS:
    closes = [CLOSE[t][d] for d in CAL]
    s50, s200, run50, run200 = {}, {}, 0.0, 0.0
    for i, c in enumerate(closes):
        run50 += c; run200 += c
        if i >= 50: run50 -= closes[i - 50]
        if i >= 200: run200 -= closes[i - 200]
        if i >= 49: s50[CAL[i]] = run50 / 50.0
        if i >= 199: s200[CAL[i]] = run200 / 200.0
    SMA[t] = (s50, s200)

def eligible_ranked(d):
    """Cross-positive sectors at close d, ranked by SMA50/SMA200-1 desc."""
    out = []
    for t in SECTORS:
        s50, s200 = SMA[t]
        if d in s50 and d in s200 and s50[d] > s200[d]:
            out.append((t, s50[d] / s200[d] - 1.0))
    out.sort(key=lambda x: -x[1])
    return [t for t, _ in out]

def signal_schedule(start, end):
    """[(signal_date, ranked_eligible)] — seeding entry (close before window)
    plus every month-end close inside the window."""
    days = [d for d in CAL if start <= d <= end]
    sched = []
    i0 = CI[days[0]]
    if i0 > 0:
        sched.append((CAL[i0 - 1], eligible_ranked(CAL[i0 - 1])))
    for i, d in enumerate(days):
        if i == len(days) - 1:
            break
        if days[i + 1][:7] != d[:7]:  # month-end
            sched.append((d, eligible_ranked(d)))
    return sched

def run_road(start, end, seed=None):
    rng = random.Random(seed) if seed is not None else None
    days = [d for d in CAL if start <= d <= end]
    sched = signal_schedule(start, end)
    pending = {}  # exec_date -> picks
    for sig_d, ranked in sched:
        k = min(3, len(ranked))
        if rng is None:
            picks = ranked[:3]
        else:
            picks = rng.sample(SECTORS, k) if k else []
        # execution: first trading day strictly after signal date, within window
        j = CI[sig_d] + 1
        while j < len(CAL) and CAL[j] < start:
            j += 1
        if j < len(CAL) and CAL[j] <= end:
            pending[CAL[j]] = picks
    cash, shares = START, {t: 0.0 for t in SECTORS}
    costs, orders = 0.0, 0
    curve = []
    def value(d, use_open=False):
        src = OPEN if use_open else CLOSE
        return cash + sum(shares[t] * src[t][d] for t in SECTORS if shares[t])
    for d in days:
        if d in pending:
            picks = pending[d]
            total = value(d, use_open=True)
            targets = {t: (total / len(picks) if t in picks else 0.0) for t in SECTORS}
            # sells first (non-picks and trims), then buys
            for t in SECTORS:
                if not shares[t]:
                    continue
                cur = shares[t] * OPEN[t][d]
                delta = targets[t] - cur
                if delta < -MIN_TRADE:
                    amt = min(-delta, cur)
                    fee = amt * COST + SELL_FEE
                    cash += amt - fee; costs += fee; orders += 1
                    shares[t] -= amt / OPEN[t][d]
                    if shares[t] * OPEN[t][d] < 0.01:
                        cash += shares[t] * OPEN[t][d]  # dust sweep, no extra order
                        shares[t] = 0.0
            for t in SECTORS:
                if t not in picks:
                    continue
                cur = shares[t] * OPEN[t][d]
                delta = targets[t] - cur
                if delta > MIN_TRADE:
                    amt = min(delta, cash / (1 + COST)) if cash > 0 else 0.0
                    if amt > MIN_TRADE:
                        fee = amt * COST
                        cash -= amt + fee; costs += fee; orders += 1
                        shares[t] += amt / OPEN[t][d]
        curve.append([d, round(value(d), 4)])
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
    o = OPEN["SPY"][days[0]]
    sh = (START - START * COST) / o
    curve = [[d, round(sh * CLOSE["SPY"][d], 4)] for d in days]
    last = curve[-1][1] - curve[-1][1] * COST - SELL_FEE
    peak, maxdd = -1e18, 0.0
    for _, v in curve:
        peak = max(peak, v); maxdd = min(maxdd, v / peak - 1.0)
    return {"final": round(last, 2), "max_dd_pct": round(maxdd * 100, 2), "equity_curve": curve}

def monthly_dist(curve):
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

def year_returns(curve):
    yrs, out = {}, {}
    for d, v in curve: yrs.setdefault(d[:4], []).append(v)
    keys = sorted(yrs)
    for i, y in enumerate(keys):
        base = 100.0 if i == 0 else yrs[keys[i - 1]][-1]
        # first year of a road starts at $100 by construction
        out[y] = round((yrs[y][-1] / base - 1) * 100, 2)
    return out

ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CONF = {"CONF_A_2010_2018": ("2010-01-04", "2018-12-31"), "CONF_B_2013_2022": ("2013-01-02", "2022-12-30")}

out = {"slug": "golden-cross-tournament", "program": "v13-best-rules", "spec": "BEST-RULES-SPEC.md",
       "champions_vm": {"LONG": 1415.62, "CONT": 544.47, "VAL": 288.05, "DECADE": 667.35},
       "spy_reference": {"LONG": 822.94, "CONT": 313.62, "VAL": 187.77, "DECADE": 367.80},
       "published_form_native_bare_cross": {"LONG": 355.44, "DECADE": 240.15, "CONT": 191.65, "VAL": 152.20},
       "roads": {}, "confirmation": {}}

for name, (s, e) in ROADS.items():
    r = run_road(s, e)
    spy = spy_bh(s, e)
    twins = [run_road(s, e, seed=2000 + i)["final"] for i in range(20)]
    beaten = sum(1 for t in twins if r["final"] > t)
    r["placebo_beaten"] = beaten
    r["placebo_finals"] = twins
    r["placebo_median"] = round(statistics.median(twins), 2)
    r["monthly_distribution"] = monthly_dist(r["equity_curve"])
    r["year_returns_pct"] = year_returns(r["equity_curve"])
    out["roads"][name] = {"run": r, "spy": {"final": spy["final"], "max_dd_pct": spy["max_dd_pct"]}}
    print(name, r["final"], r["max_dd_pct"], "spy", spy["final"], spy["max_dd_pct"],
          "placebo", beaten, "/20  med", r["placebo_median"], "orders", r["orders"], "costs", r["costs"], flush=True)

for name, (s, e) in CONF.items():
    r = run_road(s, e); spy = spy_bh(s, e)
    out["confirmation"][name] = {"run": {k: r[k] for k in ("start", "end", "final", "cagr_pct", "max_dd_pct", "costs", "orders")},
                                 "spy": {"final": spy["final"], "max_dd_pct": spy["max_dd_pct"]},
                                 "equity_curve": r["equity_curve"]}
    print(name, r["final"], "spy", spy["final"], flush=True)

folds = {}
for y in range(2010, 2027):
    days = [d for d in CAL if f"{y}-01-01" <= d <= f"{y}-12-31"]
    if len(days) < 20: continue
    r = run_road(days[0], days[-1])
    folds[str(y)] = {"final": r["final"], "max_dd_pct": r["max_dd_pct"]}
out["year_folds_fresh_pot"] = folds
vals = [v["final"] - 100 for v in folds.values()]
out["year_fold_summary"] = {"median_year_pct": round(statistics.median(vals), 2),
    "share_years_positive_pct": round(sum(1 for v in vals if v > 0) / len(vals) * 100, 1),
    "best_year": max(folds, key=lambda k: folds[k]["final"]),
    "worst_year": min(folds, key=lambda k: folds[k]["final"])}
print("folds", folds, flush=True)

with open(os.path.join(HERE, "results.json"), "w") as f:
    json.dump(out, f, indent=1)
print("WROTE results.json")
