#!/usr/bin/env python3
"""V12 CONSTRUCTED dividend capture — gap-a10-div-capture.

Construction frozen in CONSTRUCTION-SPEC.md (read it before touching this):
  PIT S&P 500 membership (fja05680 lifecycles) x Yahoo per-ticker dividend
  events + raw prices. Trade: buy cum-day CLOSE, sell ex-date OPEN, dividend
  credited at sale. Full pot per cum-day, equal split across same-cum-day
  events. Costs 0.10%/side + $0.01/sell order. v9 floor: -15% per episode,
  90-day sit-out after first halt, second halt ends the run.
  Placebos: shifted ex-date twins (+5..60 trading days, no dividend), 20 seeds.
Outputs: results.json (curves, placebos, census) in this folder.
"""
import csv, json, math, os, random
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
COST = 0.001
TICKET = 0.01
FLOOR_FRAC = 0.85
SITOUT_DAYS = 90

WINDOWS = {
    "LONG":   ("2010-01-04", "2026-11-20"),
    "DECADE": ("2016-11-21", "2026-11-20"),
    "CONT":   ("2019-01-02", "2026-11-20"),
    "VAL":    ("2023-01-03", "2026-11-20"),
}
CHAMPION = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}

# ---------- membership ----------
mem_rows = list(csv.DictReader(open(os.path.join(DATA, "sp500_ticker_start_end.csv"))))
MEMBER = {}  # ticker -> list of (start, end or '9999')
for r in mem_rows:
    MEMBER.setdefault(r["ticker"], []).append((r["start_date"], r["end_date"] or "9999-99-99"))

def is_member(t, d):
    return any(s <= d <= e for s, e in MEMBER.get(t, []))

# ---------- price/event loading ----------
def load_ticker(t):
    path = os.path.join(DATA, f"px_{t}.json")
    if not os.path.exists(path) or os.path.getsize(path) <= 200:
        return None
    try:
        d = json.load(open(path))
        res = d["chart"]["result"][0]
        ts = res["timestamp"]
        q = res["indicators"]["quote"][0]
        adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    except Exception:
        return None
    bars = []  # (date, open, close, adjclose)
    for i, epoch in enumerate(ts):
        c = q["close"][i]; o = q["open"][i]
        if c is None or o is None:
            continue
        dt = datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d")
        bars.append((dt, o, c, adj[i] if adj else None))
    divs = []
    ev = res.get("events", {}).get("dividends", {})
    for k, v in ev.items():
        dt = datetime.fromtimestamp(v["date"], tz=timezone.utc).strftime("%Y-%m-%d")
        divs.append((dt, v["amount"]))
    divs.sort()
    return {"bars": bars, "divs": divs}

ALL_TICKERS = sorted({r["ticker"] for r in mem_rows
                      if any(s <= "2026-11-20" and (e == "" or e >= "2010-01-01")
                             for s, e in MEMBER[r["ticker"]])})

print("loading tickers...")
SERIES = {}
no_data = []
for t in ALL_TICKERS:
    s = load_ticker(t)
    if s is None or not s["bars"]:
        no_data.append(t)
    else:
        SERIES[t] = s
print(f"loaded {len(SERIES)} / {len(ALL_TICKERS)} tickers; no data: {len(no_data)}")

# ---------- build event census ----------
# event: ticker, ex_date, div, cum_date, cum_close, ex_open, ex_close
EVENTS = []
lost_no_member = 0
for t, s in SERIES.items():
    dates = [b[0] for b in s["bars"]]
    idx = {d: i for i, d in enumerate(dates)}
    for exd, amt in s["divs"]:
        if exd < "2010-01-01" or exd > "2026-11-20":
            continue
        if not is_member(t, exd):
            lost_no_member += 1
            continue
        if exd not in idx or idx[exd] == 0:
            continue
        i = idx[exd]
        cum = dates[i - 1]
        EVENTS.append({
            "ticker": t, "ex": exd, "cum": cum, "div": amt,
            "cum_close": s["bars"][i - 1][2],
            "ex_open": s["bars"][i][1],
            "ex_close": s["bars"][i][2],
        })
EVENTS.sort(key=lambda e: (e["cum"], e["ticker"]))
print(f"census events (PIT members, complete bars): {len(EVENTS)}; "
      f"dropped non-member-at-ex: {lost_no_member}")

# ---------- SPY benchmark (dividend-adjusted, program construction) ----------
spy = load_ticker("SPY")
def spy_final(start, end):
    bars = [b for b in spy["bars"] if b[3] is not None]
    first = next(b for b in bars if b[0] >= start)
    last = [b for b in bars if b[0] <= end][-1]
    sh = (100.0 * (1 - COST)) / first[3]
    proceeds = sh * last[3]
    return round(proceeds - proceeds * COST - TICKET, 2)

SPY = {w: spy_final(*WINDOWS[w]) for w in WINDOWS}
print("SPY:", SPY)

# ---------- pot engine ----------
def run_pot(events, start, end):
    """events: list of dicts with cum/ex dates and entry/exit prices + div credit.
    Full pot per cum-day, equal split; sells at ex open before cum buys same day.
    Returns dict with final, curve, costs, orders, halts, trades."""
    evs = [e for e in events if start <= e["ex"] <= end]
    by_cum = {}
    for e in evs:
        by_cum.setdefault(e["cum"], []).append(e)
    cash = 100.0
    episode_start_cash = 100.0
    halts = []          # list of (date, balance)
    sitout_until = None
    curve = []
    total_costs = 0.0
    orders = 0
    trades = 0
    open_positions = []  # (ex_date, shares, ex_open, div) — all exit next morning
    days = sorted(set(list(by_cum.keys()) + [e["ex"] for e in evs]))
    for d in days:
        # 1) sells at ex-date open
        still = []
        for exd, sh, xo, dv in open_positions:
            if exd == d:
                proceeds = sh * (xo + dv)
                c = proceeds * COST + TICKET
                cash += proceeds - c
                total_costs += c; orders += 1; trades += 1
            else:
                still.append((exd, sh, xo, dv))
        open_positions = still
        # equity after sales (positions are overnight only; none carried past ex)
        equity = cash + sum(sh * xo for _, sh, xo, _ in open_positions)
        # 2) floor check after sales
        if equity <= episode_start_cash * FLOOR_FRAC and open_positions == []:
            if sitout_until is not None and len(halts) >= 1:
                pass  # already in episode 2 handling below
            halts.append((d, round(equity, 2)))
            if len(halts) >= 2:
                curve.append((d, round(equity, 2)))
                return {"final": round(equity, 2), "curve": curve, "costs": round(total_costs, 2),
                        "orders": orders, "trades": trades, "halts": halts,
                        "restart": True, "second_halt": True}
            sitout_until = (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=SITOUT_DAYS)).strftime("%Y-%m-%d")
            episode_start_cash = equity
            curve.append((d, round(equity, 2)))
            continue
        # 3) buys at cum-day close (skip while sitting out)
        if sitout_until is not None and d < sitout_until:
            curve.append((d, round(equity, 2)))
            continue
        if sitout_until is not None and d >= sitout_until:
            sitout_until = None
        todays = by_cum.get(d, [])
        if todays and cash > 0:
            deploy = cash / len(todays)
            for e in todays:
                sh = deploy / e["cum_close"]
                bc = deploy * COST
                cash -= deploy + bc
                total_costs += bc; orders += 1
                open_positions.append((e["ex"], sh, e["ex_open"], e.get("div_credit", e["div"])))
        equity = cash + sum(sh * xo for _, sh, xo, _ in open_positions)
        curve.append((d, round(equity, 2)))
    # end: any open position exits at its ex open (all ex dates <= end by construction)
    final = curve[-1][1] if curve else 100.0
    return {"final": final, "curve": curve, "costs": round(total_costs, 2),
            "orders": orders, "trades": trades, "halts": halts,
            "restart": len(halts) == 1, "second_halt": len(halts) >= 2}

def max_dd(curve):
    peak, mdd = -1e18, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1.0)
    return round(mdd * 100, 1)

def cagr(final, start, end):
    yrs = (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days / 365.25
    return round(((final / 100.0) ** (1 / yrs) - 1) * 100, 2) if final > 0 else -100.0

# ---------- census stats ----------
def census_stats(events):
    rows = []
    for e in events:
        gross_open = (e["ex_open"] + e["div"] - e["cum_close"]) / e["cum_close"] * 100
        gross_close = (e["ex_close"] + e["div"] - e["cum_close"]) / e["cum_close"] * 100
        net_open = gross_open - 0.21  # approx program round trip on full pot ($0.01 ticket ~0.01%)
        rows.append((e, gross_open, gross_close, net_open))
    n = len(rows)
    def mean(xs): return sum(xs) / len(xs) if xs else 0.0
    def med(xs):
        s = sorted(xs); return s[len(s) // 2] if s else 0.0
    by_yield = {}
    terc = sorted(rows, key=lambda r: r[0]["div"] / r[0]["cum_close"])
    for i, r in enumerate(terc):
        by_yield.setdefault("low" if i < n / 3 else "mid" if i < 2 * n / 3 else "high", []).append(r)
    return {
        "n_events": n,
        "gross_open_mean_pct": round(mean([r[1] for r in rows]), 4),
        "gross_open_median_pct": round(med([r[1] for r in rows]), 4),
        "gross_open_pos_frac": round(sum(1 for r in rows if r[1] > 0) / n, 3) if n else None,
        "gross_close_mean_pct": round(mean([r[2] for r in rows]), 4),
        "gross_close_median_pct": round(med([r[2] for r in rows]), 4),
        "net_open_mean_pct_approx": round(mean([r[3] for r in rows]), 4),
        "div_mean_pct_of_price": round(mean([r[0]["div"] / r[0]["cum_close"] * 100 for r in rows]), 4),
        "drop_open_mean_pct": round(mean([(r[0]["cum_close"] - r[0]["ex_open"]) / r[0]["cum_close"] * 100 for r in rows]), 4),
        "drop_close_mean_pct": round(mean([(r[0]["cum_close"] - r[0]["ex_close"]) / r[0]["cum_close"] * 100 for r in rows]), 4),
        "specials_div_gt_3pct": sum(1 for r in rows if r[0]["div"] / r[0]["cum_close"] > 0.03),
        "by_yield_tercile": {k: {"n": len(v),
                                 "gross_open_mean_pct": round(mean([r[1] for r in v]), 4),
                                 "net_open_mean_pct_approx": round(mean([r[3] for r in v]), 4)}
                             for k, v in by_yield.items()},
        "by_year_net_open_mean_pct": {y: round(mean([r[3] for r in rows if r[0]["ex"][:4] == y]), 4)
                                      for y in sorted({r[0]["ex"][:4] for r in rows})},
    }

# ---------- placebos ----------
IDX = {t: {b[0]: i for i, b in enumerate(s["bars"])} for t, s in SERIES.items()}
DATES = {t: [b[0] for b in s["bars"]] for t, s in SERIES.items()}

def shifted_events(seed):
    rng = random.Random(seed)
    out = []
    for e in EVENTS:
        s = SERIES[e["ticker"]]
        dates = DATES[e["ticker"]]
        i = IDX[e["ticker"]][e["ex"]]
        j = i + rng.randint(5, 60)
        if j >= len(dates) or j == 0:
            continue
        out.append({"ticker": e["ticker"], "ex": dates[j], "cum": dates[j - 1],
                    "div": e["div"], "div_credit": 0.0,
                    "cum_close": s["bars"][j - 1][2], "ex_open": s["bars"][j][1],
                    "ex_close": s["bars"][j][2]})
    out.sort(key=lambda e: (e["cum"], e["ticker"]))
    return out

# ---------- main runs ----------
results = {
    "slug": "gap-a10-div-capture",
    "program": "v12-completions",
    "construction": "CONSTRUCTED portfolio layer on documented trade (buy cum close, sell ex open, dividend credited); PIT S&P 500 census via Yahoo per-ticker events",
    "champion": CHAMPION,
    "spy": SPY,
    "census_meta": {
        "tickers_in_pit_union_2010_2026": len(ALL_TICKERS),
        "tickers_with_yahoo_data": len(SERIES),
        "tickers_no_data": len(no_data),
        "no_data_tickers_sample": no_data[:60],
        "events_dropped_not_member_at_ex": lost_no_member,
    },
    "census": {},
    "runs": {},
}
for w, (a, b) in WINDOWS.items():
    wev = [e for e in EVENTS if a <= e["ex"] <= b]
    results["census"][w] = census_stats(wev)
    r = run_pot(EVENTS, a, b)
    r["cagr_pct"] = cagr(r["final"], a, b)
    r["max_dd_pct"] = max_dd(r["curve"])
    r["start"], r["end"] = a, b
    results["runs"][w] = r
    print(w, "final", r["final"], "trades", r["trades"], "costs", r["costs"], "halts", r["halts"])

print("placebos (20 seeds, built once, x 4 windows)...", flush=True)
SEED_EVENTS = {seed: shifted_events(seed) for seed in range(1, 21)}
for w, (a, b) in WINDOWS.items():
    finals = []
    for seed in range(1, 21):
        pr = run_pot(SEED_EVENTS[seed], a, b)
        finals.append(pr["final"])
    beaten = sum(1 for f in finals if results["runs"][w]["final"] > f)
    results["runs"][w]["placebo_finals"] = finals
    results["runs"][w]["placebo_beaten"] = f"{beaten}/20"
    print(w, "placebo beaten", beaten, "/20  median twin",
          sorted(finals)[len(finals) // 2])

with open(os.path.join(HERE, "results.json"), "w") as f:
    json.dump(results, f, indent=1)
print("wrote results.json")
