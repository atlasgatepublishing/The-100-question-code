#!/usr/bin/env python3
"""
Dividend Growth — v13 BEST RULES run. Spec: BEST-RULES-SPEC.md (frozen).
Form: S&P published Aristocrats rosters (point-in-time, from v12 folder,
read-only); at each January formation close rank the roster by trailing
yield (trailing-365d cash DPS / raw close), hold TOP 20 equal weight,
ANNUAL reconstitution only (weights drift between formations), NO floor.
Returns: adjusted-close total return (v12 tapes, read-only). Costs
0.10%/side + $0.01/sell order. $100 pot.
Integrity gate: published mode (all names, quarterly resets) must
reproduce v12 finals before the best-rules numbers count.
Placebos: 20 seeds, random 20 from the same January's eligible pool.
Yield-uncomputable names (no dividend-event tape anywhere free: BMS, LM,
PBCT, WBA, KVUE, LEG) are excluded from BOTH strategy and placebo pools.
Successor chaining for yield data: PX->LIN, UTX->RTX, CTL->LUMN,
HCP->DOC, BBT->TFC (v12 convention; return tapes already embody it).
"""
import bisect, json, os, random, statistics, sys, time
from datetime import date, timedelta
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
V12 = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/dividend-growth")
V12DATA = os.path.join(V12, "data")
sys.path.insert(0, V12)
from rosters import ROSTERS, SUCCESSOR

START_CASH = 100.0
COST_RATE = 0.001
SELL_FEE = 0.01
END = "2026-11-20"
STALE_DAYS = 45
TOPN = 20

# ---------- return tapes: v12 adj-close px files (read-only) ----------
def load_bars(t):
    p = os.path.join(V12DATA, f"px_{t}.json")
    if not os.path.exists(p):
        return None
    j = json.load(open(p))
    bars = [(b[0][:10], float(b[1])) for b in j["bars"]]
    bars.sort()
    return bars

SPY_BARS = load_bars("SPY")
CAL = [d for d, _ in SPY_BARS if d <= END]
CAL_IDX = {d: i for i, d in enumerate(CAL)}
CAL_ORD = np.array([date.fromisoformat(d).toordinal() for d in CAL])
N = len(CAL)

def filled_array(bars):
    arr = np.full(N, np.nan)
    if not bars:
        return arr
    bd = [date.fromisoformat(d).toordinal() for d, _ in bars]
    bp = [p for _, p in bars]
    j = np.searchsorted(bd, CAL_ORD, side="right") - 1
    for i in range(N):
        k = j[i]
        if k >= 0 and CAL_ORD[i] - bd[k] <= STALE_DAYS:
            arr[i] = bp[k]
        elif k >= 0:
            arr[i] = 0.0
    return arr

STRAT = {}
for t in sorted({x for v in ROSTERS.values() for x in v}):
    b = load_bars(t)
    if b:
        STRAT[t] = filled_array(b)
SPY_ARR = filled_array(SPY_BARS)

# ---------- yield data: full Yahoo payloads in this folder ----------
def load_full(t):
    """Return (raw_close dict date->price, div list [(date, amount)]) or None."""
    src = SUCCESSOR.get(t, t)
    p = os.path.join(DATA, f"full_{src}.json")
    if not os.path.exists(p):
        return None
    try:
        res = json.load(open(p))["chart"]["result"][0]
    except Exception:
        return None
    ts = res.get("timestamp") or []
    if len(ts) < 100:
        return None
    q = res["indicators"]["quote"][0]
    closes = {}
    for i, tt in enumerate(ts):
        c = q["close"][i]
        if c is None:
            continue
        closes[time.strftime("%Y-%m-%d", time.gmtime(tt))] = float(c)
    divs = []
    for _, dv in ((res.get("events") or {}).get("dividends") or {}).items():
        divs.append((time.strftime("%Y-%m-%d", time.gmtime(dv["date"])), float(dv["amount"])))
    divs.sort()
    return closes, divs

FULL = {t: load_full(t) for t in sorted({x for v in ROSTERS.values() for x in v})}
NO_YIELD_DATA = sorted(t for t, v in FULL.items() if v is None)
print("no yield data (excluded from pools):", NO_YIELD_DATA, flush=True)

def trailing_yield(t, asof):
    v = FULL.get(t)
    if v is None:
        return None
    closes, divs = v
    lo = (date.fromisoformat(asof) - timedelta(days=365)).isoformat()
    dps = sum(a for d, a in divs if lo < d <= asof)
    if dps <= 0:
        return None
    days = sorted(d for d in closes if d <= asof)
    if not days:
        return None
    px = closes[days[-1]]
    if px <= 0:
        return None
    return dps / px

# ---------- calendar helpers ----------
def last_td_of_month(y, m):
    ds = [d for d in CAL if d[:4] == str(y) and d[5:7] == f"{m:02d}"]
    return ds[-1] if ds else None

def formation_date(y):
    return last_td_of_month(y, 1)

def reset_dates(start_y, months):
    out = []
    for y in range(start_y, 2027):
        for m in months:
            d = last_td_of_month(y, m)
            if d and d <= END:
                out.append(d)
    return sorted(set(out))

# ---------- simulation (v12 chassis) ----------
def simulate(start_y, pick_fn, months):
    start = formation_date(start_y)
    si = CAL_IDX[start]
    resets = {CAL_IDX[d] for d in reset_dates(start_y, months) if d >= start}
    cash = START_CASH
    shares = {}
    curve = []
    costs = 0.0
    orders = 0
    vanished = []
    book = []
    picks_log = {}
    for i in range(si, N):
        d = CAL[i]
        if i in resets:
            if d[5:7] == "01":
                book = pick_fn(int(d[:4]))
                picks_log[d[:4]] = list(book)
            for t, sh in list(shares.items()):
                p = STRAT[t][i]
                if np.isnan(p):
                    p = 0.0
                if p == 0.0 and sh > 0:
                    vanished.append((d, t))
                val = sh * p
                c = val * COST_RATE + SELL_FEE if val > 0 else 0.0
                cash += val - c
                costs += c
                orders += 1
            shares = {}
            investable = [t for t in book
                          if t in STRAT and not np.isnan(STRAT[t][i]) and STRAT[t][i] > 0]
            if investable and cash > 0:
                per = cash / len(investable)
                for t in investable:
                    p = STRAT[t][i]
                    c = per * COST_RATE
                    costs += c
                    orders += 1
                    shares[t] = (per - c) / p
                    cash -= per
                cash = max(cash, 0.0)
        eq = cash
        for t, sh in shares.items():
            p = STRAT[t][i]
            eq += sh * (p if not np.isnan(p) else 0.0)
        curve.append((d, round(float(eq), 2)))
    return curve, costs, orders, vanished, picks_log

def diagnostics(curve, period_dates):
    final = curve[-1][1]
    peak, mdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        mdd = max(mdd, (peak - v) / peak if peak > 0 else 0.0)
    cd = dict(curve)
    bounds = [d for d in period_dates if curve[0][0] < d <= curve[-1][0]]
    periods = []
    prev_v = START_CASH
    prev_d = curve[0][0]
    for d in bounds:
        v = cd[d]
        periods.append(((v / prev_v) - 1) * 100)
        prev_v = v
    if curve[-1][0] not in bounds:
        periods.append(((final / prev_v) - 1) * 100)
    pos = sum(1 for r in periods if r > 0)
    longest_loss = cur = 0
    for r in periods:
        cur = cur + 1 if r <= 0 else 0
        longest_loss = max(longest_loss, cur)
    peak_v, peak_i, longest_under = -1.0, 0, 0
    for i, (_, v) in enumerate(curve):
        if v >= peak_v:
            peak_v, peak_i = v, i
        longest_under = max(longest_under, i - peak_i)
    yrs = (date.fromisoformat(curve[-1][0]) - date.fromisoformat(curve[0][0])).days / 365.25
    return {
        "final": final,
        "cagr_pct": round(((final / START_CASH) ** (1 / yrs) - 1) * 100, 2),
        "max_dd_pct": round(mdd * 100, 2),
        "periods_native_tempo": {
            "tempo": "annual (formation to formation)",
            "n_periods": len(periods),
            "pct_positive": round(100 * pos / len(periods), 1) if periods else None,
            "median_pct": round(statistics.median(periods), 2) if periods else None,
            "mean_pct_secondary": round(statistics.mean(periods), 2) if periods else None,
            "best_pct": round(max(periods), 2) if periods else None,
            "worst_pct": round(min(periods), 2) if periods else None,
            "longest_losing_streak_periods": longest_loss,
            "longest_stretch_between_new_highs_trading_days": longest_under,
            "period_returns_pct": [round(r, 2) for r in periods],
        },
    }

def spy_buyhold(start_y):
    si = CAL_IDX[formation_date(start_y)]
    return round(START_CASH * float(SPY_ARR[-1]) / float(SPY_ARR[si]), 2)

# ---------- picks ----------
def eligible_pool(year):
    fd = formation_date(year)
    i = CAL_IDX[fd]
    out = []
    for t in ROSTERS[year]:
        if t not in STRAT or np.isnan(STRAT[t][i]) or STRAT[t][i] <= 0:
            continue
        y = trailing_yield(t, fd)
        if y is None:
            continue
        out.append((t, y))
    return out

POOLS = {y: eligible_pool(y) for y in range(2010, 2027)}
YIELD_LOG = {y: {t: round(yy, 4) for t, yy in POOLS[y]} for y in POOLS}

def strategy_pick(year):
    ranked = sorted(POOLS[year], key=lambda x: (-x[1], x[0]))
    return [t for t, _ in ranked[:TOPN]]

def published_pick(year):
    return [t for t in ROSTERS[year] if t in STRAT]

ROADS = {"LONG": 2010, "DECADE": 2016, "CONT": 2019, "VAL": 2023}
V12_FINALS = {"LONG": 555.20, "DECADE": 247.96, "CONT": 181.07, "VAL": 123.00}
CHAMPION = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}

out = {"family": "dividend-growth (Aristocrats) — v13 best rules",
       "spec": "BEST-RULES-SPEC.md",
       "form": "PIT published Aristocrats roster; rank by trailing yield at January formation; top 20 equal weight; annual reconstitution only, weights drift; no floor",
       "no_yield_data_excluded": NO_YIELD_DATA,
       "yield_log_by_year": YIELD_LOG,
       "integrity_gate": {}, "roads": {}}

# ---------- integrity gate: published mode vs v12 ----------
print("integrity gate (published mode, quarterly resets)...", flush=True)
for road, sy in ROADS.items():
    curve, _, _, _, _ = simulate(sy, published_pick, (1, 4, 7, 10))
    got = curve[-1][1]
    out["integrity_gate"][road] = {"expected_v12": V12_FINALS[road], "got": got,
                                   "match": abs(got - V12_FINALS[road]) < 0.02}
    print(" gate", road, "expected", V12_FINALS[road], "got", got, flush=True)

# ---------- best-rules run + placebos ----------
for road, sy in ROADS.items():
    resets = reset_dates(sy, (1,))
    curve, costs, orders, vanished, picks_log = simulate(sy, strategy_pick, (1,))
    diag = diagnostics(curve, resets)
    diag.update({"costs": round(costs, 2), "orders": orders,
                 "spy_same_window_final": spy_buyhold(sy),
                 "start": curve[0][0], "end": curve[-1][0],
                 "vanished_zeroed": vanished, "picks_by_year": picks_log,
                 "curve": curve})
    finals = []
    for seed in range(1, 21):
        rng = random.Random(1000 * seed + sy)
        cache = {}
        def placebo_pick(year, _rng=rng, _cache=cache):
            if year not in _cache:
                pool = [t for t, _ in POOLS[year]]
                _cache[year] = _rng.sample(pool, min(TOPN, len(pool)))
            return _cache[year]
        pc, _, _, _, _ = simulate(sy, placebo_pick, (1,))
        finals.append(round(pc[-1][1], 2))
    diag["placebo_beaten"] = sum(1 for x in finals if diag["final"] > x)
    diag["placebo_median"] = round(statistics.median(finals), 2)
    diag["placebo_finals"] = finals
    out["roads"][road] = diag
    print(road, diag["final"], "SPY", diag["spy_same_window_final"],
          "placebos beaten", diag["placebo_beaten"], "/20",
          "costs", diag["costs"], "DD", diag["max_dd_pct"], flush=True)

with open(os.path.join(HERE, "results.json"), "w") as f:
    json.dump(out, f, indent=1)
print("done")
