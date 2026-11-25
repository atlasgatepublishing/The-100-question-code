#!/usr/bin/env python3
"""
Dogs of the Dow + Small Dogs — v12 HOLDINGS-COUNT SWEEP. Spec: SWEEP-SPEC.md
(frozen before runs). Data/engine basis: the v11 native folder (read-only) —
same Yahoo cache, same point-in-time Dow membership, same ranking, same
documented hole (DWDP/WBA tapes deleted; excluded; exclusion flatters).

Lines:  dogs  = top-N by trailing yield.
        small = N lowest-priced of the top-10 Dogs (native N=5; pool caps at 10).
Forms:  native = O'Higgins as published, no floor.
        house  = v9 protections: -15% floor from episode-start balance
                 (close check), liquidate at next open, 90 cash days, restart
                 at the next annual January selection date, episode-2 floor
                 -15% from restart balance, second halt ends the run.
Costs: 0.10%/side + $0.01 per sell order. $100 pot. Dividends as cash on
ex-date (program method). 20-seed placebos per cell (random N from the same
January's investable ranked pool, same form/mechanics — the v11 construction).
"""
import bisect, json, math, os, random, time
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
V11 = os.path.expanduser("~/workspace/stock-app/backtests/v11-native-rules/dogs-dividend")
CACHE = os.path.join(V11, "cache")
START_CASH = 100.0
COST_RATE = 0.001
SELL_FEE = 0.01

# ---------------- data (identical loading to v11 run_native.py) ----------------
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
        o = q["open"][i] if q.get("open") and q["open"][i] else c
        bars[d] = (c, o)
    divs = []
    for _, dv in ((res.get("events") or {}).get("dividends") or {}).items():
        divs.append((time.strftime("%Y-%m-%d", time.gmtime(dv["date"])), float(dv["amount"])))
    divs.sort()
    return bars, divs

TICKERS = ["AAPL","AXP","BA","CAT","CRM","CSCO","CVX","DD","DIS","DOW","GE","GS","HD",
           "HON","IBM","INTC","JNJ","JPM","KO","MCD","MMM","MRK","MSFT","NKE","NVDA",
           "PFE","PG","RTX","SHW","TRV","UNH","V","VZ","WMT","XOM","AMGN","AMZN"]
# NOTE: v11's DATA dict dropped any ticker whose load() returned None; GS tape
# exists in cache but v11's ranking comment records GS as absent from its
# investable set in practice (never ranked). We replicate v11 exactly: its
# load() succeeded for every listed ticker with a cache file, GS included in
# TICKERS there too — ranking() membership/tape checks decide. (Integrity gate
# below verifies the replication to the cent.)
DATA = {t: load(t) for t in TICKERS}
DATA = {t: v for t, v in DATA.items() if v}
DAYS = {t: sorted(DATA[t][0]) for t in DATA}

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
SPY_DAYS = ALL_DAYS
DAY_IDX = {d: i for i, d in enumerate(ALL_DAYS)}

def close_on(t, d):
    bars = DATA[t][0]; ds = DAYS[t]
    i = bisect.bisect_right(ds, d) - 1
    return bars[ds[i]][0] if i >= 0 else None

def open_on(t, d):
    bars = DATA[t][0]; ds = DAYS[t]
    i = bisect.bisect_right(ds, d) - 1
    return bars[ds[i]][1] if i >= 0 else None

def spy_tr(d0, d1):
    i0 = bisect.bisect_right(SPY_DAYS, d0) - 1; i1 = bisect.bisect_right(SPY_DAYS, d1) - 1
    return START_CASH * SPY_BARS[SPY_DAYS[i1]][1] / SPY_BARS[SPY_DAYS[i0]][1]

# ---------------- PIT Dow membership (verbatim from v11) ----------------
BASE_2016 = ["AAPL","AXP","BA","CAT","CSCO","CVX","DD","DIS","GE","GS","HD","IBM",
             "INTC","JNJ","JPM","KO","MCD","MMM","MRK","MSFT","NKE","PFE","PG","TRV",
             "UNH","RTX","V","VZ","WMT","XOM"]
CHANGES = [("2017-09-01", "DD", "DWDP"), ("2018-06-26", "GE", "WBA"),
           ("2019-04-02", "DWDP", "DOW"), ("2020-08-31", "XOM", "AMGN"),
           ("2020-08-31", "PFE", "CRM"), ("2020-08-31", "RTX", "HON"),
           ("2024-02-26", "WBA", "AMZN"), ("2024-11-08", "INTC", "NVDA"),
           ("2024-11-08", "DOW", "SHW")]
NO_TAPE = {"DWDP", "WBA"}

def members_on(d):
    m = list(BASE_2016)
    for eff, out, inn in CHANGES:
        if d >= eff:
            if out in m: m.remove(out)
            if inn not in m: m.append(inn)
    return m

def trailing_div(t, asof):
    if t not in DATA: return None
    lo = (date.fromisoformat(asof) - timedelta(days=365)).isoformat()
    return sum(a for (d, a) in DATA[t][1] if lo < d <= asof)

def ranking(rank_date):
    out = []
    for t in members_on(rank_date):
        if t in NO_TAPE or t not in DATA: continue
        p = close_on(t, rank_date)
        td = trailing_div(t, rank_date)
        if p is None or td is None: continue
        out.append((t, td / p, p))
    out.sort(key=lambda x: -x[1])
    return out

DIV_EVENTS = {}
for t in DATA:
    for (d, a) in DATA[t][1]:
        DIV_EVENTS.setdefault(d, []).append((t, a))

def selection_dates(start, end):
    """First trading day of each January in [start,end], plus the first
    trading day >= start if not already one."""
    days = [d for d in ALL_DAYS if start <= d <= end]
    sel = []
    for d in days:
        i = DAY_IDX[d]
        if d[5:7] == "01" and i > 0 and ALL_DAYS[i-1][5:7] == "12":
            sel.append(d)
    if days and days[0] not in sel:
        sel = [days[0]] + sel
    return days, sel

def make_picks(rk, line, count, rng):
    pool = [t for t, _, _ in rk]
    if rng is not None:
        n = len(pool) if count == "ALL" else min(count, len(pool))
        return rng.sample(pool, n)
    if line == "dogs":
        n = len(rk) if count == "ALL" else min(count, len(rk))
        return [t for t, _, _ in rk[:n]]
    top10 = rk[:10]
    n = len(top10) if count == "ALL" else min(count, len(top10))
    return [t for t, _, _ in sorted(top10, key=lambda x: x[2])[:n]]

# ---------------- simulation ----------------
def run_window(start, end, line, count, form, seed=None):
    rng = random.Random(seed) if seed is not None else None
    days, sel = selection_dates(start, end)
    sel_set = set(sel)
    cash = START_CASH; shares = {}
    curve = []; picks_by_year = {}
    costs = 0.0; orders = 0; div_cash = 0.0
    halts = []; restarts = []
    mode = "invested"           # invested | liquidate | cash_wait | ended
    episode_floor = 0.85 * START_CASH
    halt_signal_date = None
    for d in days:
        if mode == "liquidate":
            for t, sh in list(shares.items()):
                p = open_on(t, d)
                if p is None: continue
                val = sh * p; c = val * COST_RATE + SELL_FEE
                cash += val - c; costs += c; orders += 1
            shares = {}
            if len(halts) >= 2:
                mode = "ended"
            else:
                mode = "cash_wait"
            eq = cash
            curve.append((d, round(eq, 2)))
            continue
        if mode == "cash_wait":
            day90 = (date.fromisoformat(halt_signal_date) + timedelta(days=90)).isoformat()
            if d in sel_set and d >= day90:
                rk = ranking(ALL_DAYS[DAY_IDX[d] - 1])
                picks = make_picks(rk, line, count, rng)
                picks_by_year[d[:4]] = picks
                episode_floor = 0.85 * cash
                restarts.append({"date": d, "cash": round(cash, 2),
                                 "episode2_floor": round(episode_floor, 2)})
                per = cash / len(picks) if picks else 0
                for t in picks:
                    p = close_on(t, d)
                    if p is None: continue
                    c = per * COST_RATE; costs += c; orders += 1
                    shares[t] = shares.get(t, 0) + (per - c) / p
                    cash -= per
                cash = max(cash, 0.0)
                mode = "invested"
        elif mode == "invested" and d in sel_set:
            rk = ranking(ALL_DAYS[DAY_IDX[d] - 1])
            picks = make_picks(rk, line, count, rng)
            picks_by_year[d[:4]] = picks
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
        # dividends on ex-date
        for (t, a) in DIV_EVENTS.get(d, []):
            if t in shares:
                cash += shares[t] * a; div_cash += shares[t] * a
        eq = cash + sum(sh * (close_on(t, d) or 0) for t, sh in shares.items())
        curve.append((d, round(eq, 2)))
        if form == "house" and mode == "invested" and shares and eq <= episode_floor and d != days[-1]:
            halts.append({"signal_date": d, "signal_close": round(eq, 2),
                          "floor": round(episode_floor, 2)})
            halt_signal_date = d
            mode = "liquidate"
    final = curve[-1][1] if curve else START_CASH
    peak = -1; mdd = 0.0
    for _, v in curve:
        peak = max(peak, v); mdd = max(mdd, (peak - v) / peak if peak > 0 else 0)
    yrs = {}; by_year = {}
    for d, v in curve: by_year.setdefault(d[:4], []).append((d, v))
    prev = START_CASH
    for y in sorted(by_year):
        last = by_year[y][-1][1]
        yrs[y] = round((last / prev - 1) * 100, 2); prev = last
    ndays = max((date.fromisoformat(end) - date.fromisoformat(start)).days, 1)
    return {"final": final,
            "cagr_pct": round(((final / START_CASH) ** (365.25 / ndays) - 1) * 100, 2),
            "max_dd_pct": round(mdd * 100, 2), "costs": round(costs, 2),
            "orders": orders, "div_cash": round(div_cash, 2),
            "halts": halts, "restarts": restarts,
            "picks_by_year": picks_by_year, "year_returns_pct": yrs,
            "curve": curve}

def period_distribution(curve):
    """Annual holding-year distribution from a daily equity curve
    (REPORTING STANDARD). Period = calendar year of the curve."""
    by_year = {}
    for d, v in curve: by_year.setdefault(d[:4], []).append((d, v))
    rets = []; prev = START_CASH
    for y in sorted(by_year):
        last = by_year[y][-1][1]
        rets.append((y, (last / prev - 1) * 100)); prev = last
    vals = [r for _, r in rets]
    n = len(vals)
    med = sorted(vals)[n // 2] if n % 2 else (sorted(vals)[n // 2 - 1] + sorted(vals)[n // 2]) / 2
    longest_loss = 0; cur = 0
    for v in vals:
        cur = cur + 1 if v < 0 else 0
        longest_loss = max(longest_loss, cur)
    # longest stretch between new highs (calendar days between successive
    # dates on which the curve set a new all-time high; window start counts)
    high = -1; last_high = None; max_gap = 0
    for d, v in curve:
        if v > high:
            high = v
            if last_high is not None:
                gap = (date.fromisoformat(d) - date.fromisoformat(last_high)).days
                max_gap = max(max_gap, gap)
            last_high = d
    return {"periods": n,
            "period_returns_pct": {y: round(r, 2) for y, r in rets},
            "pct_profitable": round(100.0 * sum(1 for v in vals if v > 0) / n, 1) if n else None,
            "median_pct": round(med, 2),
            "best_pct": round(max(vals), 2), "worst_pct": round(min(vals), 2),
            "longest_losing_run_periods": longest_loss,
            "longest_stretch_between_new_highs_days": max_gap,
            "average_pct_secondary": round(sum(vals) / n, 2) if n else None}

# ---------------- sweep ----------------
ROADS = {"LONG": ("2017-01-03", "2026-11-20"),
         "DECADE": ("2017-01-03", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"),
         "VAL": ("2023-01-03", "2026-11-20")}
CONF_ROADS = {"CONF-A_2018": ("2018-01-02", "2026-11-20"),
              "CONF-B_2021": ("2021-01-04", "2026-11-20")}
DOGS_COUNTS = [1, 2, 3, 5, 8, 10, 15, 20, 30, "ALL"]
SMALL_COUNTS = [1, 2, 3, 5, 8, 10, "ALL"]   # 15/20/30 cap at the 10-Dog pool
FORMS = ["native", "house"]

def cell(start, end, line, count, form):
    r = run_window(start, end, line, count, form)
    twins = []
    # placebo degenerate when count covers the whole pool every year
    pool_min = min(len(ranking(ALL_DAYS[DAY_IDX[d] - 1])) for d in
                   selection_dates(start, end)[1])
    eff_n = pool_min if count == "ALL" else count
    degenerate = (line == "dogs" and eff_n >= pool_min) or \
                 (line == "small" and count in (10, "ALL"))
    if not degenerate:
        for seed in range(1, 21):
            twins.append(run_window(start, end, line, count, form, seed=seed)["final"])
    out = {k: v for k, v in r.items() if k != "curve"}
    if twins:
        out["placebo_beaten"] = sum(1 for x in twins if r["final"] > x)
        out["placebo_median"] = round(sorted(twins)[10], 2)
        out["placebo_finals"] = [round(x, 2) for x in twins]
    else:
        out["placebo_beaten"] = None
        out["placebo_note"] = "degenerate: count covers the whole eligible pool; random draw = the ranked set"
    return r, out

def main():
    t0 = time.time()
    result = {"family": "dogs-dividend (Dogs of the Dow + Small Dogs)",
              "spec": "SWEEP-SPEC.md (frozen before runs)",
              "hole": "DWDP (2017-19) and WBA (2018-24) excluded: free tapes deleted after delisting; exclusion flatters the Dogs",
              "roads": ROADS, "spy": {}, "integrity": {}, "cells": {},
              "curves": {}, "distributions": {}, "confirmation": {}}
    # ---- integrity gate: reproduce v11 native finals at native counts ----
    published = {("dogs", "LONG"): 280.80, ("dogs", "CONT"): 241.55, ("dogs", "VAL"): 184.44,
                 ("small", "LONG"): 293.66, ("small", "CONT"): 218.89, ("small", "VAL"): 180.56}
    for (line, road), pub in published.items():
        s, e = ROADS[road]
        cnt = 10 if line == "dogs" else 5
        got = run_window(s, e, line, cnt, "native")["final"]
        result["integrity"][f"{line}_{road}"] = {"published": pub, "reproduced": got,
                                                 "match": abs(got - pub) < 0.02}
    print("INTEGRITY:", json.dumps(result["integrity"]), flush=True)
    if not all(v["match"] for v in result["integrity"].values()):
        raise SystemExit("INTEGRITY GATE FAILED — sweep aborted, see results.json")
    for road, (s, e) in ROADS.items():
        result["spy"][road] = round(spy_tr(s, e), 2)
    # ---- full grid (LONG and DECADE share a window: run once, print both) ----
    distinct_roads = ["LONG", "CONT", "VAL"]
    for line, counts in (("dogs", DOGS_COUNTS), ("small", SMALL_COUNTS)):
        for form in FORMS:
            for count in counts:
                key = f"{line}|{form}|{count}"
                result["cells"][key] = {}
                for road in distinct_roads:
                    s, e = ROADS[road]
                    r, c = cell(s, e, line, count, form)
                    result["cells"][key][road] = c
                    result["cells"][key]["DECADE"] = c if road == "LONG" else result["cells"][key].get("DECADE")
                    if road == "LONG":
                        result["curves"][key] = r["curve"]
                print(f"{key}: LONG {result['cells'][key]['LONG']['final']} "
                      f"CONT {result['cells'][key]['CONT']['final']} "
                      f"VAL {result['cells'][key]['VAL']['final']} "
                      f"({time.time()-t0:.0f}s)", flush=True)
    # ---- winning counts (highest LONG final per line x form) + distributions ----
    winners = {}
    for line, counts in (("dogs", DOGS_COUNTS), ("small", SMALL_COUNTS)):
        native_count = 10 if line == "dogs" else 5
        for form in FORMS:
            best = max(counts, key=lambda c: result["cells"][f"{line}|{form}|{c}"]["LONG"]["final"])
            winners[f"{line}|{form}"] = {"winning_count": best, "native_count": native_count}
            for c in {best, native_count}:
                key = f"{line}|{form}|{c}"
                result["distributions"][key] = period_distribution(result["curves"][key])
    result["winners"] = winners
    # ---- confirmation rule ----
    for line in ("dogs", "small"):
        native_count = 10 if line == "dogs" else 5
        for form in FORMS:
            nk = f"{line}|{form}|{native_count}"
            for count in (DOGS_COUNTS if line == "dogs" else SMALL_COUNTS):
                if count == native_count: continue
                ck = f"{line}|{form}|{count}"
                beats_all = all(result["cells"][ck][r]["final"] > result["cells"][nk][r]["final"]
                                for r in distinct_roads)
                if beats_all:
                    entry = {"beats_native_all_roads": True, "windows": {}}
                    for cname, (s, e) in CONF_ROADS.items():
                        cand = run_window(s, e, line, count, form)["final"]
                        nat = run_window(s, e, line, native_count, form)["final"]
                        entry["windows"][cname] = {"candidate": cand, "native": nat,
                                                   "beats": cand > nat}
                    entry["variant_candidate"] = all(w["beats"] for w in entry["windows"].values())
                    result["confirmation"][ck] = entry
                    print(f"CONFIRMATION {ck}: {entry}", flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(result, f, indent=1)
    print(f"DONE in {time.time()-t0:.0f}s")

if __name__ == "__main__":
    main()
