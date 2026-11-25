#!/usr/bin/env python3
"""
Dividend Growth / S&P 500 Dividend Aristocrats — v12 CONSTRUCTED run.
Frozen spec: CONSTRUCTION-SPEC.md. Roster = S&P's published index membership
(rosters.py). Mechanics: annual January reconstitution (effective at the close
of the last January trading day), quarterly equal-weight resets, adjusted-close
total return, costs 0.10%/side + $0.01/sell order, $100 pot, no floor.
Vanished tape (>45 days stale, no successor) -> valued at ZERO.
Placebos: 20 seeds, random draws of the same size from the point-in-time
S&P 500 roster (fja05680) with prices from the Johnbrick123 parquet.
Engine: all tapes aligned to the SPY calendar as forward-filled numpy arrays
(staleness-zeroed), so runs are fast and light.
"""
import bisect, csv, json, os, random, statistics, sys
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

# ---------------- calendar from SPY tape ----------------
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
    """Forward-filled prices on CAL; 0 where no bar within STALE_DAYS, NaN where never yet priced."""
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

# strategy tapes
STRAT = {}
for t in sorted({x for v in ROSTERS.values() for x in v}):
    b = load_bars(t)
    if b:
        STRAT[t] = filled_array(b)
SPY_ARR = filled_array(SPY_BARS)

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

# ---------------- PIT S&P 500 roster ----------------
PIT = []
with open(os.path.join(DATA, "sp500_hist.csv")) as f:
    for row in csv.DictReader(f):
        PIT.append((row["date"], row["tickers"].split(",")))
PIT_DATES = [d for d, _ in PIT]

def pit_members(d):
    i = bisect.bisect_right(PIT_DATES, d) - 1
    return PIT[i][1]

# ---------------- simulation ----------------
def simulate(start_y, pick_fn, tape_map):
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
                p = tape_map[t][i]
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
                          if t in tape_map and not np.isnan(tape_map[t][i]) and tape_map[t][i] > 0]
            if investable and cash > 0:
                per = cash / len(investable)
                for t in investable:
                    p = tape_map[t][i]
                    c = per * COST_RATE
                    costs += c
                    orders += 1
                    shares[t] = (per - c) / p
                    cash -= per
                cash = max(cash, 0.0)
        eq = cash
        for t, sh in shares.items():
            p = tape_map[t][i]
            eq += sh * (p if not np.isnan(p) else 0.0)
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

def spy_buyhold(start_y):
    si = CAL_IDX[formation_date(start_y)]
    return round(START_CASH * float(SPY_ARR[-1]) / float(SPY_ARR[si]), 2)

ROADS = {"LONG": 2010, "DECADE": 2016, "CONT": 2019, "VAL": 2023}
EXCLUDED_NO_TAPE = ["BCR", "FDO", "SIAL", "GCI"]

def strategy_pick(year):
    return [t for t in ROSTERS[year] if t in STRAT]

out = {"family": "dividend-growth (S&P 500 Dividend Aristocrats, v12 constructed)",
       "spec": "CONSTRUCTION-SPEC.md", "excluded_no_tape": EXCLUDED_NO_TAPE,
       "roads": {}}

# ---- placebo tapes from parquet, one road at a time is unnecessary: load all pool names as arrays
pool_names = set()
for y in range(2010, 2027):
    pool_names.update(pit_members(formation_date(y)))
print("loading parquet tapes...", flush=True)
import duckdb
con = duckdb.connect()
df = con.sql(
    "SELECT ticker, CAST(date AS DATE) d, adj_close FROM read_parquet(?) "
    "WHERE ticker IN (SELECT UNNEST(?)) AND adj_close IS NOT NULL "
    "AND date >= DATE '2009-01-01' ORDER BY ticker, date",
    params=[os.path.join(DATA, "prices_jb.parquet"), sorted(pool_names)]).df()
PLACEBO = {}
for t, grp in df.groupby("ticker"):
    bars = list(zip(grp["d"].astype(str), grp["adj_close"].astype(float)))
    PLACEBO[t] = filled_array(bars)
del df
print(f"placebo tapes: {len(PLACEBO)}", flush=True)

def pit_pool(fd):
    ok = []
    i = CAL_IDX[fd]
    for t in pit_members(fd):
        cand = t if t in PLACEBO else t.replace(".", "-")
        if cand in PLACEBO and not np.isnan(PLACEBO[cand][i]) and PLACEBO[cand][i] > 0:
            ok.append(cand)
    return ok

POOLS = {y: pit_pool(formation_date(y)) for y in range(2010, 2027)}

for road, sy in ROADS.items():
    resets = reset_dates(sy)
    curve, costs, orders, vanished = simulate(sy, strategy_pick, STRAT)
    diag = diagnostics(curve, resets)
    diag.update({"costs": round(costs, 2), "orders": orders,
                 "spy_same_window_final": spy_buyhold(sy),
                 "start": curve[0][0], "end": curve[-1][0],
                 "vanished_zeroed": vanished, "curve": curve})
    finals = []
    for seed in range(1, 21):
        rng = random.Random(1000 * seed + sy)
        cache = {}
        def placebo_pick(year, _rng=rng, _cache=cache):
            if year not in _cache:
                n = len(strategy_pick(year))
                _cache[year] = _rng.sample(POOLS[year], min(n, len(POOLS[year])))
            return _cache[year]
        pc, _, _, _ = simulate(sy, placebo_pick, PLACEBO)
        finals.append(round(pc[-1][1], 2))
    diag["placebo_beaten"] = sum(1 for x in finals if diag["final"] > x)
    diag["placebo_median"] = round(statistics.median(finals), 2)
    diag["placebo_finals"] = finals
    out["roads"][road] = diag
    print(road, diag["final"], "SPY", diag["spy_same_window_final"],
          "placebos beaten", diag["placebo_beaten"], "/20", flush=True)

with open(os.path.join(HERE, "results.json"), "w") as f:
    json.dump(out, f, indent=1)
print("done")
