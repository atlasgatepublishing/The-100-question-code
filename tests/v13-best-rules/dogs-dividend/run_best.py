#!/usr/bin/env python3
"""
Dogs dividend variant - v13 BEST RULES run. Spec: BEST-RULES-SPEC.md (frozen).
Best-rules form: PIT Dow 30; eligibility = trailing div > 0 and no YoY cut in
either of the last two 365d comparisons; rank by 2-year smoothed yield
(divs trailing 730d / 2 / price); top 10 equal weight; annual January
reconstitution; NO floor/stop; ONE intra-year rule: cut-exit - a holding that
pays less than its corresponding payment ~1y earlier, or pays nothing for 200
consecutive days, is sold at that day's close, proceeds in cash to next Jan.
Native mode (top-10, 1y yield, no gate, no exit) = integrity gate vs v11.
Data: v11 dogs-dividend cache (read-only). Costs 0.10%/side + $0.01/sell.
Placebos: 20 seeds, random 10 from the same January's ELIGIBLE pool, same
mechanics AND same cut-exit.
"""
import bisect, json, os, random, time
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
V11 = os.path.expanduser("~/workspace/stock-app/backtests/v11-native-rules/dogs-dividend")
CACHE = os.path.join(V11, "cache")
START_CASH = 100.0
COST_RATE = 0.001
SELL_FEE = 0.01
COUNT = 10
OMISSION_DAYS = 200

def load(t):
    p = os.path.join(CACHE, f"px_{t}.json")
    if not os.path.exists(p):
        return None
    j = json.load(open(p))
    res = j["chart"]["result"][0]
    ts = res["timestamp"]; q = res["indicators"]["quote"][0]
    bars = {}
    for i, tt in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(tt))
        c = q["close"][i]
        if c is None: continue
        bars[d] = c
    divs = []
    for _, dv in ((res.get("events") or {}).get("dividends") or {}).items():
        divs.append((time.strftime("%Y-%m-%d", time.gmtime(dv["date"])), float(dv["amount"])))
    divs.sort()
    return bars, divs

TICKERS = ["AAPL","AXP","BA","CAT","CRM","CSCO","CVX","DD","DIS","DOW","GE","GS","HD",
           "HON","IBM","INTC","JNJ","JPM","KO","MCD","MMM","MRK","MSFT","NKE","NVDA",
           "PFE","PG","RTX","SHW","TRV","UNH","V","VZ","WMT","XOM","AMGN","AMZN"]
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
DAY_IDX = {d: i for i, d in enumerate(ALL_DAYS)}

def close_on(t, d):
    ds = DAYS[t]
    i = bisect.bisect_right(ds, d) - 1
    return DATA[t][0][ds[i]] if i >= 0 else None

def spy_tr(d0, d1):
    i0 = bisect.bisect_right(ALL_DAYS, d0) - 1; i1 = bisect.bisect_right(ALL_DAYS, d1) - 1
    return START_CASH * SPY_BARS[ALL_DAYS[i1]][1] / SPY_BARS[ALL_DAYS[i0]][1]

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

def div_sum(t, lo, hi):
    return sum(a for (d, a) in DATA[t][1] if lo < d <= hi)

def eligible_and_ranked(rank_date):
    d0 = date.fromisoformat(rank_date)
    w = lambda k: (d0 - timedelta(days=365 * k)).isoformat()
    out = []; log = []
    for t in members_on(rank_date):
        if t in NO_TAPE or t not in DATA: continue
        p = close_on(t, rank_date)
        if p is None: continue
        d_cur = div_sum(t, w(1), rank_date)
        d_mid = div_sum(t, w(2), w(1))
        d_old = div_sum(t, w(3), w(2))
        if d_cur <= 0:
            log.append((t, "no trailing dividend")); continue
        if d_cur < d_mid - 1e-9:
            log.append((t, f"cut (recent): {d_cur:.4f} < {d_mid:.4f}")); continue
        if d_mid < d_old - 1e-9:
            log.append((t, f"cut (earlier): {d_mid:.4f} < {d_old:.4f}")); continue
        smoothed_yield = ((d_cur + d_mid) / 2.0) / p
        out.append((t, smoothed_yield, p))
    out.sort(key=lambda x: -x[1])
    return out, log

def ranking_native(rank_date):
    out = []
    for t in members_on(rank_date):
        if t in NO_TAPE or t not in DATA: continue
        p = close_on(t, rank_date)
        td = div_sum(t, (date.fromisoformat(rank_date) - timedelta(days=365)).isoformat(), rank_date)
        if p is None: continue
        out.append((t, td / p, p))
    out.sort(key=lambda x: -x[1])
    return out

DIV_EVENTS = {}
DIV_DATES = {}
for t in DATA:
    DIV_DATES[t] = [d for d, _ in DATA[t][1]]
    for (d, a) in DATA[t][1]:
        DIV_EVENTS.setdefault(d, []).append((t, a))

def cut_detected(t, d, amount):
    """Payment on day d is a cut if < most recent prior payment 300-460 days earlier."""
    lo = (date.fromisoformat(d) - timedelta(days=460)).isoformat()
    hi = (date.fromisoformat(d) - timedelta(days=300)).isoformat()
    prior = [a for (dd, a) in DATA[t][1] if lo <= dd <= hi]
    if not prior: return False
    return amount < prior[-1] - 1e-9

def last_payment_on_or_before(t, d):
    i = bisect.bisect_right(DIV_DATES[t], d) - 1
    return DIV_DATES[t][i] if i >= 0 else None

def selection_dates(start, end):
    days = [d for d in ALL_DAYS if start <= d <= end]
    sel = []
    for d in days:
        i = DAY_IDX[d]
        if d[5:7] == "01" and i > 0 and ALL_DAYS[i-1][5:7] == "12":
            sel.append(d)
    if days and days[0] not in sel:
        sel = [days[0]] + sel
    return days, sel

def run_window(start, end, mode, seed=None):
    rng = random.Random(seed) if seed is not None else None
    days, sel = selection_dates(start, end)
    sel_set = set(sel)
    cash = START_CASH; shares = {}
    bought_on = {}
    curve = []; picks_by_year = {}; gate_log = {}; exit_log = []
    costs = 0.0; orders = 0; div_cash = 0.0
    for d in days:
        if d in sel_set:
            rank_date = ALL_DAYS[DAY_IDX[d] - 1]
            if mode == "native":
                rk = ranking_native(rank_date)
                picks = [t for t, _, _ in rk[:10]]
            else:
                rk, log = eligible_and_ranked(rank_date)
                gate_log[d[:4]] = log
                if rng is not None:
                    pool = [t for t, _, _ in rk]
                    picks = rng.sample(pool, min(COUNT, len(pool)))
                else:
                    picks = [t for t, _, _ in rk[:COUNT]]
            picks_by_year[d[:4]] = picks
            for t, sh in list(shares.items()):
                p = close_on(t, d)
                if p is None: continue
                val = sh * p; c = val * COST_RATE + SELL_FEE
                cash += val - c; costs += c; orders += 1
            shares = {}; bought_on = {}
            total = cash
            per = total / len(picks) if picks else 0
            for t in picks:
                p = close_on(t, d)
                if p is None: continue
                c = per * COST_RATE; costs += c; orders += 1
                shares[t] = shares.get(t, 0) + (per - c) / p
                bought_on[t] = d
                cash -= per
            cash = max(cash, 0.0)
        # dividend events: credit, then cut check (best mode)
        for (t, a) in DIV_EVENTS.get(d, []):
            if t in shares:
                cash += shares[t] * a; div_cash += shares[t] * a
                if mode == "best" and cut_detected(t, d, a):
                    p = close_on(t, d)
                    if p is not None:
                        val = shares[t] * p; c = val * COST_RATE + SELL_FEE
                        cash += val - c; costs += c; orders += 1
                        exit_log.append((d, t, f"cut: paid {a:.4f}"))
                        del shares[t]
        # omission check (best mode): 200 silent days while held
        if mode == "best":
            for t in list(shares):
                lp = last_payment_on_or_before(t, d)
                ref = lp if (lp and lp >= bought_on.get(t, start)) else bought_on.get(t, start)
                if ref and (date.fromisoformat(d) - date.fromisoformat(ref)).days >= OMISSION_DAYS \
                   and (lp is None or lp < bought_on.get(t, start) or
                        (date.fromisoformat(d) - date.fromisoformat(lp)).days >= OMISSION_DAYS):
                    p = close_on(t, d)
                    if p is not None:
                        val = shares[t] * p; c = val * COST_RATE + SELL_FEE
                        cash += val - c; costs += c; orders += 1
                        exit_log.append((d, t, "omission: 200 silent days"))
                        del shares[t]
        eq = cash + sum(sh * (close_on(t, d) or 0) for t, sh in shares.items())
        curve.append((d, round(eq, 2)))
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
            "picks_by_year": picks_by_year, "gate_log": gate_log,
            "exit_log": exit_log,
            "year_returns_pct": yrs, "curve": curve}

def period_distribution(curve):
    by_year = {}
    for d, v in curve: by_year.setdefault(d[:4], []).append((d, v))
    rets = []; prev = START_CASH
    for y in sorted(by_year):
        last = by_year[y][-1][1]
        rets.append((y, (last / prev - 1) * 100)); prev = last
    vals = [r for _, r in rets]
    n = len(vals)
    svals = sorted(vals)
    med = svals[n // 2] if n % 2 else (svals[n // 2 - 1] + svals[n // 2]) / 2
    longest_loss = 0; cur = 0
    for v in vals:
        cur = cur + 1 if v < 0 else 0
        longest_loss = max(longest_loss, cur)
    high = -1; last_high = None; max_gap = 0
    for d, v in curve:
        if v > high:
            high = v
            if last_high is not None:
                max_gap = max(max_gap, (date.fromisoformat(d) - date.fromisoformat(last_high)).days)
            last_high = d
    return {"periods": n,
            "period_returns_pct": {y: round(r, 2) for y, r in rets},
            "pct_profitable": round(100.0 * sum(1 for v in vals if v > 0) / n, 1) if n else None,
            "median_pct": round(med, 2),
            "best_pct": round(max(vals), 2), "worst_pct": round(min(vals), 2),
            "longest_losing_run_periods": longest_loss,
            "longest_stretch_between_new_highs_days": max_gap,
            "average_pct_secondary": round(sum(vals) / n, 2) if n else None}

ROADS = {"LONG": ("2017-01-03", "2026-11-20"),
         "DECADE": ("2017-01-03", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"),
         "VAL": ("2023-01-03", "2026-11-20")}
CHAMPION_VM = {"LONG": 1415.62, "CONT": 544.47, "VAL": 288.05, "DECADE": 667.35}

def main():
    t0 = time.time()
    result = {"family": "dogs-dividend (dividend-focused Dogs variant)",
              "spec": "BEST-RULES-SPEC.md (frozen before runs)",
              "hole": "DWDP (2017-19) and WBA (2018-24) excluded: free tapes deleted after delisting; exclusion flatters the Dogs",
              "roads": ROADS, "integrity": {}, "spy": {}, "best": {}, "confirmation": {}}
    published = {"LONG": 280.80, "CONT": 241.55, "VAL": 184.44}
    for road, pub in published.items():
        s, e = ROADS[road]
        got = run_window(s, e, "native")["final"]
        result["integrity"][road] = {"published_v11_dogs10": pub, "reproduced": got,
                                     "match": abs(got - pub) < 0.02}
    print("INTEGRITY:", json.dumps(result["integrity"]), flush=True)
    if not all(v["match"] for v in result["integrity"].values()):
        with open(os.path.join(HERE, "results.json"), "w") as f:
            json.dump(result, f, indent=1)
        raise SystemExit("INTEGRITY GATE FAILED")
    for road in ("LONG", "CONT", "VAL"):
        s, e = ROADS[road]
        result["spy"][road] = round(spy_tr(s, e), 2)
        r = run_window(s, e, "best")
        twins = [run_window(s, e, "best", seed=sd)["final"] for sd in range(1, 21)]
        entry = {k: v for k, v in r.items() if k != "curve"}
        entry["placebo_beaten"] = sum(1 for x in twins if r["final"] > x)
        entry["placebo_median"] = round(sorted(twins)[10], 2)
        entry["placebo_finals"] = [round(x, 2) for x in twins]
        entry["distribution"] = period_distribution(r["curve"])
        result["best"][road] = entry
        result.setdefault("curves", {})[road] = r["curve"]
        print(f"{road}: best ${r['final']} (DD {r['max_dd_pct']}%, placebos {entry['placebo_beaten']}/20, "
              f"exits {len(r['exit_log'])}) SPY ${result['spy'][road]} ({time.time()-t0:.0f}s)", flush=True)
    result["best"]["DECADE"] = result["best"]["LONG"]
    result["spy"]["DECADE"] = result["spy"]["LONG"]
    beats = [r for r in ("LONG", "CONT", "VAL", "DECADE")
             if result["best"][r]["final"] > CHAMPION_VM[r]]
    result["champion_roads_beaten"] = beats
    if beats:
        for cname, (s, e) in {"CONF-A_2018": ("2018-01-02", "2026-11-20"),
                              "CONF-B_2021": ("2021-01-04", "2026-11-20")}.items():
            result["confirmation"][cname] = run_window(s, e, "best")["final"]
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(result, f, indent=1)
    print(f"DONE in {time.time()-t0:.0f}s")

if __name__ == "__main__":
    main()
