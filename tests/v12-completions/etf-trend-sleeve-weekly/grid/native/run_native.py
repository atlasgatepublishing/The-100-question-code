#!/usr/bin/env python3
"""Faber GTAA — v11-style NATIVE run for etf-trend-sleeve (v12 grid/native slice).

Frozen native spec (Meben Faber, "A Quantitative Approach to Tactical Asset
Allocation", 2007; updated 2013): five asset classes, equal 20% allocations,
each asset held only when its month-end close is above its 10-month simple
moving average of month-end closes, else that allocation sits in cash;
monthly evaluation. ETF proxies (program-standard rendering, frozen):
SPY (US stocks), EFA (foreign stocks), IEF (US 10-yr bonds), DBC
(commodities), VNQ (real estate). No floor, no stop (the published system
has none). Cash earns 0% (deviation from Faber's T-bill cash, stated in
NATIVE.md; bias: hurts). Costs: program standard 0.10%/side + $0.01 per
sell order. Execution: signal at month-end close, trade at next trading
day's open (dividend-adjusted basis). Fresh-pot roads seeded with the gate
state from the last month-end before the road start (F8 v11 precedent),
first trade at the road's first open. End of road: marked to final close,
no liquidation cost (stated in NATIVE.md).
Placebos: 20 seeds; at every month-end each asset's gate is replaced by a
seeded coin flip (p=0.5), same mechanics and costs.
Simulation only. Shared caches read-only; EFA/VNQ payloads are this
folder's own downloads (data/).
"""
import json, os, math, random, bisect
from datetime import date, datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.expanduser("~/workspace/stock-app/backtests/v3/data_etf")
ASSETS = ["SPY", "EFA", "IEF", "DBC", "VNQ"]
COST_RATE = 0.0010
SELL_FEE = 0.01

def load_bars(t):
    p = os.path.join(CACHE, f"{t}.json")
    if not os.path.exists(p):
        p = os.path.join(HERE, "data", f"{t}.json")
    d = json.load(open(p))
    r = d["chart"]["result"][0]
    ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i, tstamp in enumerate(ts):
        c = q["close"][i]; o = q["open"][i]
        if c is None or o is None or adj[i] is None:
            continue
        dt = datetime.fromtimestamp(tstamp, tz=timezone.utc).date()
        f = adj[i] / c
        bars.append((dt, o * f, adj[i]))  # (date, adj_open, adj_close)
    bars.sort()
    return bars

BARS = {t: load_bars(t) for t in ASSETS}
SPY = BARS["SPY"]

def month_end_closes(bars):
    """dict (y,m) -> (last trading date, adj_close)"""
    out = {}
    for dt, o, c in bars:
        out[(dt.year, dt.month)] = (dt, c)
    return out

MEC = {t: month_end_closes(BARS[t]) for t in ASSETS}

def gates_for(t, mode, rng=None):
    """dict (y,m) -> bool gate state decided at that month-end."""
    mec = MEC[t]
    months = sorted(mec.keys())
    closes = [mec[m][1] for m in months]
    g = {}
    for i, m in enumerate(months):
        if mode == "native":
            if i >= 9:
                sma = sum(closes[i - 9:i + 1]) / 10.0
                g[m] = closes[i] > sma
            else:
                g[m] = False
        else:  # placebo coin flip
            g[m] = rng.random() < 0.5
    return g

def run_road(start, end, mode="native", seed=None):
    rng = random.Random(seed) if mode == "placebo" else None
    gates = {t: gates_for(t, mode, rng) for t in ASSETS}
    # trading calendar = SPY dates in [start, end]
    cal = [b for b in SPY if start <= b[0] <= end]
    dates = [b[0] for b in cal]
    # per-asset lookup
    idx = {}
    for t in ASSETS:
        idx[t] = {b[0]: (b[1], b[2]) for b in BARS[t]}
    # decision events: for each month-end <= end, execution = first cal date
    # strictly after the month-end date (and >= start). Seed: month-ends
    # before start set the initial state, executed at the first cal open.
    events = {}  # cal_date -> {asset: gate}
    all_months = sorted({m for t in ASSETS for m in MEC[t].keys()})
    for m in all_months:
        me_date = max(MEC[t][m][0] for t in ASSETS if m in MEC[t])
        # execution date
        j = bisect.bisect_left(dates, me_date)
        # first cal date > me_date
        while j < len(dates) and dates[j] <= me_date:
            j += 1
        if j >= len(dates):
            continue
        ex = dates[j]
        if ex < start:
            continue
        ev = events.setdefault(ex, {})
        for t in ASSETS:
            if m in gates[t]:
                ev[t] = gates[t][m]
    # seed event at first cal date from latest month-end before start
    pre = [m for m in all_months if MEC["SPY"].get(m, (end,))[0] < start]
    if pre and dates:
        m0 = pre[-1]
        ev = events.setdefault(dates[0], {})
        for t in ASSETS:
            if m0 in gates[t] and t not in ev:
                ev[t] = gates[t][m0]
    cash = 100.0
    shares = {t: 0.0 for t in ASSETS}
    state = {t: False for t in ASSETS}
    costs = 0.0; orders = 0
    curve = []
    for dt in dates:
        if dt in events:
            for t, g in events[dt].items():
                state[t] = g
            # portfolio value at today's open (approx: use open for traded
            # assets, last close for others — use today's open for all via
            # adj_open where available, else adj_close)
            def px_open(t, dt=dt):
                v = idx[t].get(dt)
                return v[0] if v else None
            val = cash + sum(shares[t] * (px_open(t) or 0) for t in ASSETS)
            for t in ASSETS:
                target = 0.20 * val if state[t] else 0.0
                cur = shares[t] * (px_open(t) or 0)
                diff = target - cur
                p = px_open(t)
                if p is None or abs(diff) < 0.01:
                    continue
                if diff > 0:  # buy
                    spend = min(diff, cash)
                    if spend <= 0: continue
                    cst = spend * COST_RATE
                    shares[t] += (spend - cst) / p if False else spend / p
                    # cost taken from cash on top of spend
                    cash -= spend + cst; costs += cst; orders += 1
                else:  # sell
                    sell_val = min(-diff, cur)
                    if sell_val <= 0: continue
                    shares[t] -= sell_val / p
                    cst = sell_val * COST_RATE + SELL_FEE
                    cash += sell_val - cst; costs += cst; orders += 1
        # mark at close
        v = cash
        for t in ASSETS:
            vv = idx[t].get(dt)
            if vv: v += shares[t] * vv[1]
            elif shares[t]:
                # last known close
                past = [d for d in idx[t] if d < dt]
                if past: v += shares[t] * idx[t][max(past)][1]
        curve.append((dt.isoformat(), round(v, 4)))
    final = curve[-1][1] if curve else 100.0
    # max drawdown
    peak = -1; mdd = 0.0
    for _, v in curve:
        peak = max(peak, v); mdd = min(mdd, v / peak - 1.0)
    yrs = (end - start).days / 365.25
    cagr = (final / 100.0) ** (1 / yrs) - 1 if final > 0 else -1
    return dict(final=round(final, 2), cagr_pct=round(cagr * 100, 2),
                max_dd_pct=round(mdd * 100, 2), costs=round(costs, 2),
                orders=orders, equity_curve=curve)

def period_distribution(curve):
    """Monthly distribution from a daily equity curve."""
    months = {}
    for dstr, v in curve:
        months[dstr[:7]] = v
    keys = sorted(months.keys())
    vals = [100.0] + [months[k] for k in keys]
    rets = [vals[i + 1] / vals[i] - 1 for i in range(len(vals) - 1)]
    if not rets:
        return {}
    srt = sorted(rets); n = len(rets)
    med = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2
    # longest losing streak + longest time between new highs (months)
    streak = mx = 0
    for r in rets:
        streak = streak + 1 if r < 0 else 0
        mx = max(mx, streak)
    peak = vals[0]; since = 0; longest = 0
    for v in vals[1:]:
        if v >= peak:
            peak = v; longest = max(longest, since); since = 0
        else:
            since += 1
    longest = max(longest, since)
    return dict(periods=n, pct_positive=round(100.0 * sum(1 for r in rets if r > 0) / n, 1),
                median_pct=round(med * 100, 2), best_pct=round(max(rets) * 100, 2),
                worst_pct=round(min(rets) * 100, 2), avg_pct=round(sum(rets) / n * 100, 2),
                longest_losing_streak_months=mx, longest_months_between_new_highs=longest)

def spy_hold(start, end):
    pts = [b for b in SPY if start <= b[0] <= end]
    if not pts: return None
    return round(100.0 * pts[-1][2] / pts[0][2], 2)

ROADS = {
    "LONG": (date(2010, 1, 4), date(2026, 11, 20)),
    "DECADE": (date(2016, 11, 21), date(2026, 11, 20)),
    "CONT": (date(2019, 1, 2), date(2026, 11, 20)),
    "VAL": (date(2023, 1, 3), date(2026, 11, 20)),
}
SPY_REF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}

out = {"family": "etf-trend-sleeve", "native_form": "Faber GTAA (2007/2013), 5 asset classes, 10-month SMA gate, equal 20% allocations, monthly",
       "roads": {}}
for name, (s, e) in ROADS.items():
    r = run_road(s, e, "native")
    twins = []
    for seed in range(1, 21):
        twins.append(run_road(s, e, "placebo", seed)["final"])
    beaten = sum(1 for x in twins if r["final"] > x)
    out["roads"][name] = {
        "window": [s.isoformat(), e.isoformat()], "final": r["final"],
        "cagr_pct": r["cagr_pct"], "max_dd_pct": r["max_dd_pct"],
        "costs": r["costs"], "orders": r["orders"],
        "spy_in_plumbing": spy_hold(s, e), "spy_program_reference": SPY_REF[name],
        "placebo_beaten": f"{beaten}/20", "placebo_twin_finals": twins,
        "monthly_distribution": period_distribution(r["equity_curve"]),
        "equity_curve": r["equity_curve"],
    }
    print(name, r["final"], r["cagr_pct"], r["max_dd_pct"], "placebos", beaten, "/20")
json.dump(out, open(os.path.join(HERE, "native_results.json"), "w"), indent=1)
print("saved native_results.json")
