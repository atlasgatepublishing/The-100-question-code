import json, math, os, random, statistics, time
from datetime import date, timedelta

START = 100.0
STK_COST = 0.001; STK_FEE = 0.01
CRY_COST = 0.006
ROADS = {"LONG": ("2010-01-01", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-01", "2026-11-20"), "VAL": ("2023-01-01", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
V7 = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")

def load_pxfull(sym):
    j = json.load(open(os.path.join(V7, f"pxfull_{sym}.json")))
    r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i, t in enumerate(ts):
        if q["close"][i] is None or adj[i] is None or q["open"][i] is None: continue
        ratio = adj[i] / q["close"][i]
        bars.append({"d": time.strftime("%Y-%m-%d", time.gmtime(t)), "o": q["open"][i]*ratio, "c": adj[i]})
    bars.sort(key=lambda b: b["d"]); return bars

def load_yahoo_file(path):
    j = json.load(open(path)); r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    try: adj = r["indicators"]["adjclose"][0]["adjclose"]
    except Exception: adj = q["close"]
    bars = []
    for i, t in enumerate(ts):
        if q["close"][i] is None or adj[i] is None: continue
        o = q["open"][i] if q["open"][i] is not None else q["close"][i]
        ratio = adj[i] / q["close"][i]
        bars.append({"d": time.strftime("%Y-%m-%d", time.gmtime(t)), "o": o*ratio, "c": adj[i]})
    bars.sort(key=lambda b: b["d"]); return bars

def load_cm(asset):
    rows = json.load(open(f"/tmp/hunt1/cm_{asset}.json"))
    return [{"d": d, "o": c, "c": c} for d, c in rows]  # close-only series; o=c (close-to-close chassis)

def slice_bars(bars, start, end):
    return [b for b in bars if (start is None or b["d"] >= start) and b["d"] <= end]

def sim_open_exec(bars, states, cost=STK_COST, fee=STK_FEE, house=False):
    """states[i] in {0,1}: desired position decided at close of bar i; trades at open i+1.
    House: plain -15% floor vs $100 start, checked at close -> exit next open, halted for good."""
    cash, shares = START, 0.0; curve = []; trades = 0; costs = 0.0; halted = False
    invested_days = 0
    for i, b in enumerate(bars):
        if i > 0 and not halted:
            want = states[i-1]
            if want == 1 and shares == 0:
                spend = cash * (1 - cost); costs += cash * cost; shares = spend / b["o"]; cash = 0.0; trades += 1
            elif want == 0 and shares > 0:
                proceeds = shares * b["o"] * (1 - cost) - fee; costs += shares * b["o"] * cost + fee
                cash = proceeds; shares = 0.0; trades += 1
        eq = cash + shares * b["c"]
        if shares > 0: invested_days += 1
        curve.append({"d": b["d"], "eq": round(eq, 4)})
        if house and not halted and eq <= 85.0:
            halted = True
            if shares > 0 and i + 1 < len(bars):
                nb = bars[i+1]; proceeds = shares * nb["o"] * (1 - cost) - fee
                costs += shares * nb["o"] * cost + fee; cash = proceeds; shares = 0.0; trades += 1
                curve.append({"d": nb["d"], "eq": round(cash, 4)})
                for rb in bars[i+2:]: curve.append({"d": rb["d"], "eq": round(cash, 4)})
                break
    final = curve[-1]["eq"] if curve else START
    return {"final": final, "curve": curve, "trades": trades, "costs": round(costs, 2),
            "maxdd": maxdd(curve), "invested_frac": round(invested_days / max(1, len(bars)), 4), "halted": halted}

def sim_close_exec(bars, states, cost=CRY_COST, house=False):
    """Crypto chassis: state decided at close t earns t->t+1; changes charged cost at close t."""
    cash_frac = 1.0; pos = 0; eq = START; curve = []; trades = 0; costs = 0.0; halted = False
    prev_c = None
    for i, b in enumerate(bars):
        if prev_c is not None and pos == 1 and not halted:
            eq *= b["c"] / prev_c
        if not halted:
            want = states[i]
            if want != pos:
                costs += eq * cost; eq *= (1 - cost); trades += 1; pos = want
        curve.append({"d": b["d"], "eq": round(eq, 4)})
        if house and not halted and eq <= 85.0:
            if pos == 1: costs += eq * cost; eq *= (1 - cost); trades += 1; pos = 0
            halted = True; curve[-1] = {"d": b["d"], "eq": round(eq, 4)}
        prev_c = b["c"]
    return {"final": curve[-1]["eq"] if curve else START, "curve": curve, "trades": trades,
            "costs": round(costs, 2), "maxdd": maxdd(curve),
            "invested_frac": round(sum(1 for s in states if s == 1) / max(1, len(states)), 4), "halted": halted}

def buyhold_open(bars, cost=STK_COST, fee=STK_FEE):
    if len(bars) < 2: return START
    shares = START * (1 - cost) / bars[0]["o"]
    return shares * bars[-1]["c"] * (1 - cost) - fee

def buyhold_close(bars, cost=CRY_COST):
    if len(bars) < 2: return START
    return START * (1 - cost) * (bars[-1]["c"] / bars[0]["c"]) * (1 - cost)

def maxdd(curve):
    peak = -1e18; dd = 0.0
    for p in curve:
        peak = max(peak, p["eq"]); dd = max(dd, (peak - p["eq"]) / peak if peak > 0 else 0.0)
    return round(dd * 100, 2)

def period_stats(curve, tempo="monthly"):
    if not curve: return {}
    if tempo == "daily":
        rets = []
        for i in range(1, len(curve)):
            rets.append(curve[i]["eq"] / curve[i-1]["eq"] - 1 if curve[i-1]["eq"] > 0 else 0.0)
    else:
        months = {}
        for c in curve: months[c["d"][:7]] = c["eq"]
        ks = sorted(months); rets = []
        prev = START
        for k in ks:
            rets.append(months[k] / prev - 1 if prev > 0 else 0.0); prev = months[k]
    if not rets: return {}
    pos = sum(1 for r in rets if r > 0)
    streak = 0; worst_streak = 0
    for r in rets:
        streak = streak + 1 if r < 0 else 0; worst_streak = max(worst_streak, streak)
    if tempo == "daily":
        vals = [c["eq"] for c in curve]
    else:
        months = {}
        for c in curve: months[c["d"][:7]] = c["eq"]
        vals = [START] + [months[k] for k in sorted(months)]
    peak = vals[0]; since = 0; longest = 0
    for v in vals:
        if v >= peak: peak = v; since = 0
        else: since += 1; longest = max(longest, since)
    return {"tempo": tempo, "n_periods": len(rets), "share_positive": round(pos / len(rets), 4),
            "median_pct": round(statistics.median(rets) * 100, 3),
            "best_pct": round(max(rets) * 100, 3), "worst_pct": round(min(rets) * 100, 3),
            "longest_losing_streak": worst_streak, "longest_between_highs_periods": longest,
            "average_pct_secondary": round(statistics.mean(rets) * 100, 3)}

def placebo_shift(states, seed):
    n = len(states)
    if n == 0: return states
    rng = random.Random(seed); k = rng.randrange(1, n)
    return states[k:] + states[:k]

def ema_series(vals, n):
    k = 2 / (n + 1); out = []; e = None
    for v in vals:
        e = v if e is None else v * k + e * (1 - k); out.append(e)
    return out

def sma_series(vals, n):
    out = [None] * len(vals); s = 0.0
    for i, v in enumerate(vals):
        s += v
        if i >= n: s -= vals[i - n]
        if i >= n - 1: out[i] = s / n
    return out
