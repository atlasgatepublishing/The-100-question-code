#!/usr/bin/env python3
"""Per-road runner: python3 run_road.py LONG|DECADE|CONT|VAL
Writes results_<ROAD>.json. Engine per CONSTRUCTION-SPEC.md."""
import json, os, random, statistics, sys
from datetime import date
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)
from rosters import ROSTERS

START_CASH = 100.0
COST_RATE = 0.001
SELL_FEE = 0.01
END = "2026-11-20"
STALE_DAYS = 45
ROAD = sys.argv[1]
START_YEAR = {"LONG": 2010, "DECADE": 2016, "CONT": 2019, "VAL": 2023}[ROAD]

def load_bars(t):
    p = os.path.join(DATA, f"px_{t}.json")
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
    bd = np.array([date.fromisoformat(d).toordinal() for d, _ in bars])
    bp = np.array([p for _, p in bars])
    j = np.searchsorted(bd, CAL_ORD, side="right") - 1
    valid = j >= 0
    last_ord = np.where(valid, bd[np.clip(j, 0, len(bd) - 1)], -10**9)
    fresh = valid & (CAL_ORD - last_ord <= STALE_DAYS)
    stale = valid & ~fresh
    arr[fresh] = bp[j[fresh]]
    arr[stale] = 0.0
    return arr

STRAT = {}
for t in sorted({x for v in ROSTERS.values() for x in v}):
    b = load_bars(t)
    if b:
        STRAT[t] = filled_array(b)
SPY_ARR = filled_array(SPY_BARS)

PJ = json.load(open(os.path.join(DATA, "placebo_index.json")))
MAT = np.load(os.path.join(DATA, "placebo_matrix.npy"))
PIDX = {t: i for i, t in enumerate(PJ["tickers"])}
POOLS = json.load(open(os.path.join(DATA, "pools.json")))

def last_td_of_month(y, m):
    ds = [d for d in CAL if d[:4] == str(y) and d[5:7] == f"{m:02d}"]
    return ds[-1] if ds else None

def formation_date(y):
    return last_td_of_month(y, 1)

def reset_dates(start_y):
    out = []
    for y in range(start_y, 2027):
        for m in (1, 4, 7, 10):
            d = last_td_of_month(y, m)
            if d and d <= END:
                out.append(d)
    return sorted(set(out))

def simulate(start_y, pick_fn, get_arr):
    start = formation_date(start_y)
    si = CAL_IDX[start]
    resets = {CAL_IDX[d] for d in reset_dates(start_y) if d >= start}
    cash = START_CASH
    shares = {}
    curve = []
    costs = 0.0
    orders = 0
    vanished = []
    book = []
    for i in range(si, N):
        d = CAL[i]
        if i in resets:
            if d[5:7] == "01":
                book = pick_fn(int(d[:4]))
            for t, sh in list(shares.items()):
                p = get_arr(t)[i]
                if np.isnan(p):
                    p = 0.0
                if p == 0.0 and sh > 0:
                    vanished.append((d, t))
                val = sh * float(p)
                c = val * COST_RATE + SELL_FEE if val > 0 else 0.0
                cash += val - c
                costs += c
                orders += 1
            shares = {}
            investable = []
            for t in book:
                a = get_arr(t)
                if a is not None and not np.isnan(a[i]) and a[i] > 0:
                    investable.append(t)
            if investable and cash > 0:
                per = cash / len(investable)
                for t in investable:
                    p = float(get_arr(t)[i])
                    c = per * COST_RATE
                    costs += c
                    orders += 1
                    shares[t] = (per - c) / p
                    cash -= per
                cash = max(cash, 0.0)
        eq = cash
        for t, sh in shares.items():
            p = get_arr(t)[i]
            eq += sh * (float(p) if not np.isnan(p) else 0.0)
        curve.append((d, round(float(eq), 2)))
    return curve, costs, orders, vanished

def diagnostics(curve, resets_list):
    final = curve[-1][1]
    peak, mdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        mdd = max(mdd, (peak - v) / peak if peak > 0 else 0.0)
    cd = dict(curve)
    bounds = [d for d in resets_list if curve[0][0] <= d <= curve[-1][0]]
    periods = []
    prev_v = START_CASH
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
            "tempo": "quarterly (equal-weight reset)",
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

def strategy_pick(year):
    return [t for t in ROSTERS[year] if t in STRAT]

MODE = sys.argv[2] if len(sys.argv) > 2 else "all"
if MODE == "placebo":
    s0, s1 = int(sys.argv[3]), int(sys.argv[4])
    def placebo_arr(t):
        r = PIDX.get(t)
        return MAT[r] if r is not None else None
    finals = {}
    for seed in range(s0, s1 + 1):
        rng = random.Random(1000 * seed + START_YEAR)
        cache = {}
        def placebo_pick(year, _rng=rng, _cache=cache):
            if year not in _cache:
                n = len(strategy_pick(year))
                pool = POOLS[str(year)]
                _cache[year] = _rng.sample(pool, min(n, len(pool)))
            return _cache[year]
        pc, _, _, _ = simulate(START_YEAR, placebo_pick, placebo_arr)
        finals[str(seed)] = round(pc[-1][1], 2)
        print("seed", seed, finals[str(seed)], flush=True)
    # NOTE: python file writes are sandbox-blocked in this environment;
    # results go to stdout and the calling shell redirects them to disk.
    sys.stdout.write("RESULTJSON:" + json.dumps(finals) + "\n")
    sys.exit(0)

resets = reset_dates(START_YEAR)
curve, costs, orders, vanished = simulate(START_YEAR, strategy_pick, lambda t: STRAT.get(t))
diag = diagnostics(curve, resets)
si = CAL_IDX[formation_date(START_YEAR)]
diag.update({"costs": round(costs, 2), "orders": orders,
             "spy_same_window_final": round(START_CASH * float(SPY_ARR[-1]) / float(SPY_ARR[si]), 2),
             "start": curve[0][0], "end": curve[-1][0],
             "vanished_zeroed": vanished, "curve": curve})

def placebo_arr(t):
    r = PIDX.get(t)
    return MAT[r] if r is not None else None

if MODE == "strategy":
    finals = []
    for s0 in (1, 6, 11, 16):
        bf = json.load(open(os.path.join(HERE, f"placebo_{ROAD}_{s0}_{s0 + 4}.json")))
        finals += [bf[str(s)] for s in range(s0, s0 + 5)]
else:
    finals = []
    for seed in range(1, 21):
        rng = random.Random(1000 * seed + START_YEAR)
        cache = {}
        def placebo_pick(year, _rng=rng, _cache=cache):
            if year not in _cache:
                n = len(strategy_pick(year))
                pool = POOLS[str(year)]
                _cache[year] = _rng.sample(pool, min(n, len(pool)))
            return _cache[year]
        pc, _, _, _ = simulate(START_YEAR, placebo_pick, placebo_arr)
        finals.append(round(pc[-1][1], 2))
        print("seed", seed, finals[-1], flush=True)
diag["placebo_beaten"] = sum(1 for x in finals if diag["final"] > x)
diag["placebo_median"] = round(statistics.median(finals), 2)
diag["placebo_finals"] = finals
print(ROAD, diag["final"], "SPY", diag["spy_same_window_final"], "placebos", diag["placebo_beaten"], "/20", flush=True)
if os.environ.get("DG_MONTHLY"):
    me = {}
    for d, v in diag["curve"]:
        me[d[:7]] = [d, v]
    sys.stdout.write("MONTHLY:" + json.dumps([me[k] for k in sorted(me)]) + "\n")
elif os.environ.get("DG_CURVE_SLICE"):
    a, b = (int(x) for x in os.environ["DG_CURVE_SLICE"].split(":"))
    sys.stdout.write("CURVESLICE:" + json.dumps(diag["curve"][a:b]) + "\n")
elif os.environ.get("DG_NOCURVE"):
    diag = {k: v for k, v in diag.items() if k != "curve"}
    sys.stdout.write("RESULTJSON:" + json.dumps(diag) + "\n")
else:
    sys.stdout.write("RESULTJSON:" + json.dumps(diag) + "\n")
