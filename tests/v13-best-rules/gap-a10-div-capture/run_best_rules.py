#!/usr/bin/env python3
"""
V13 BEST-RULES — GAP-A10 DIVIDEND CAPTURE (filtered, patient form)

Simulation only. No broker orders were placed.
Spec: BEST-RULES-SPEC.md in this folder, frozen before this run.

Rules (from the frozen spec):
  - Pond: honest top-30 (v7 A-10 universe).
  - Event filter: declared dividend >= 1.25% of the cum-day close.
  - Entry: close 5 trading days BEFORE the ex-date, 20% of pot equity
    per position, max 5 concurrent positions, skip if full.
  - Exit: close 5 trading days AFTER the ex-date; dividend credited as
    cash at the ex-date. No stop, no target.
  - Protections: NO -15% floor. Risk control = filter + position cap.
  - Costs: 0.10% of trade value per side + $0.01 per sell order.
  - Roads (fresh $100 pots): LONG 2010-01-04->2026-11-20,
    DECADE 2016-01-04->2026-11-20, CONT 2019-01-02->2026-11-20,
    VAL 2023-01-03->2026-11-20. An event belongs to a road if its
    ENTRY date falls inside the road.
  - Placebos: 20 seeds/road — same entry dates and sizing pattern,
    random pond names, 11-trading-day windows containing no ex-date
    for that name, no dividend credited, same costs.
Prices: Yahoo chart API, raw closes (split-adj, not div-adj), dividend
events from the same payloads, fetched 2009-06-01->2026-11-21.
Integrity gate: SPY buy-hold via champion construction on the program
cache must reproduce $313.62 (CONT) / $187.77 (VAL) before any number
counts (same gate as v7).
"""
import json, math, os, random, time, urllib.request, calendar

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
os.makedirs(DATA, exist_ok=True)
V7 = os.path.join(HERE, "..", "..", "v7", "gap-a10-div-capture")
V4 = os.path.join(HERE, "..", "..", "v4")
SHARED = os.path.join(V4, "data")
HONEST = os.path.join(V4, "value-momentum-honest-data")

UA = "AtlasGateResearch terry-research@example.com"
POND = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "BRK-B", "JPM", "XOM",
        "JNJ", "PG", "V", "WMT", "HD", "BAC", "CVX", "PFE", "VZ", "T",
        "DIS", "NFLX", "INTC", "CSCO", "GE", "IBM", "MMM", "UNH", "MA",
        "KO", "PEP", "WFC"]
START_CASH = 100.0
COST_RATE = 0.001
SELL_TICKET = 0.01
YIELD_MIN = 0.0125          # 1.25% of cum-day close (frozen spec)
PRE = 5                     # entry: trading days before ex-date
POST = 5                    # exit: trading days after ex-date
POS_FRAC = 0.20             # 20% of equity per position
MAX_POS = 5
ROADS = {"LONG": ("2010-01-04", "2026-11-20"),
         "DECADE": ("2016-01-04", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"),
         "VAL": ("2023-01-03", "2026-11-20")}
GATE_ROADS = {"CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}

# ------------------------------------------------------------------ fetch
def fetch(url, path, tries=3):
    if os.path.exists(path) and os.path.getsize(path) > 100:
        with open(path, "rb") as f:
            return f.read()
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                blob = r.read()
            with open(path, "wb") as f:
                f.write(blob)
            return blob
        except Exception as e:  # noqa
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"fetch failed {url}: {last}")

def yahoo_payload(ticker, p1, p2, cache_dir, tag):
    t1 = calendar.timegm(time.strptime(p1, "%Y-%m-%d"))
    t2 = calendar.timegm(time.strptime(p2, "%Y-%m-%d"))
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={t1}&period2={t2}&interval=1d&events=div,split")
    blob = fetch(url, os.path.join(cache_dir, f"{tag}_{ticker}.json"))
    return json.loads(blob)

def parse_payload(j):
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    raw, adjb = [], []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        c = q["close"][i]
        if c is None:
            continue
        raw.append({"d": d, "c": c, "o": q["open"][i]})
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        o = q["open"][i]
        adjb.append({"d": d, "o": (o * ratio if o else a), "c": a})
    raw.sort(key=lambda b: b["d"])
    adjb.sort(key=lambda b: b["d"])
    divs = []
    ev = res.get("events") or {}
    for v in (ev.get("dividends") or {}).values():
        divs.append({"ex": time.strftime("%Y-%m-%d", time.gmtime(v["date"])),
                     "amount": float(v["amount"])})
    divs.sort(key=lambda x: x["ex"])
    return raw, adjb, divs

def program_cache_payload(ticker):
    for base in (SHARED, HONEST):
        p = os.path.join(base, f"px_{ticker}.json")
        if os.path.exists(p) and os.path.getsize(p) > 100:
            with open(p, "rb") as f:
                return json.loads(f.read())
    return None

def spy_net_from_cache(start, end, start_cash=100.0):
    j = program_cache_payload("SPY")
    _raw, adjb, _d = parse_payload(j)
    idx = {b["d"]: b for b in adjb}
    days = sorted(d for d in idx if start <= d <= end)
    first, last = days[0], days[-1]
    o = idx[first]["o"]
    sh = (start_cash / 1.001) / o
    val = sh * idx[last]["c"]
    sell_cost = val * 0.001 + 0.01
    return round(val - sell_cost, 2)

# ------------------------------------------------------------- price book
class Book:
    def __init__(self, bars):
        self.bars = bars                                # ticker -> [{d,c,o}]
        self.idx = {t: {b["d"]: b["c"] for b in bl} for t, bl in bars.items()}
        self.dates = {t: [b["d"] for b in bl] for t, bl in bars.items()}
        self.pos = {t: {b["d"]: i for i, b in enumerate(bl)} for t, bl in bars.items()}

    def close(self, t, d):
        return self.idx.get(t, {}).get(d)

    def close_on_or_before(self, t, d):
        prev = None
        for bd in self.dates.get(t, []):
            if bd <= d:
                prev = bd
            else:
                break
        return self.idx[t][prev] if prev else None

# ---------------------------------------------------------------- events
def build_events(book, divs_by):
    """All pond events with full pre/post bars; filter applied later."""
    events = []
    for t in POND:
        bl = book.bars.get(t, [])
        pos = book.pos.get(t, {})
        for dv in divs_by.get(t, []):
            ex = dv["ex"]
            if ex not in pos:
                continue
            i = pos[ex]
            if i - 1 < 0 or i - PRE < 0 or i + POST >= len(bl):
                continue
            cum = bl[i - 1]
            entry, exitb = bl[i - PRE], bl[i + POST]
            drop = cum["c"] - bl[i]["c"]
            gross = dv["amount"] - drop
            events.append({
                "ticker": t, "ex": ex, "cum": cum["d"], "div": dv["amount"],
                "cum_close": cum["c"], "ex_close": bl[i]["c"],
                "entry_date": entry["d"], "entry_close": entry["c"],
                "exit_date": exitb["d"], "exit_close": exitb["c"],
                "div_yield_pct": dv["amount"] / cum["c"] * 100.0,
                "gross_pct": gross / cum["c"] * 100.0,
            })
    events.sort(key=lambda e: (e["entry_date"], e["ticker"]))
    return events

def standalone_net_pct(ev, deploy=100.0):
    """One-day capture net % (v7 definition) for this event, full-pot."""
    sh = deploy / ev["cum_close"]
    buy_cost = deploy * COST_RATE
    proceeds = sh * (ev["ex_close"] + ev["div"])
    sell_cost = proceeds * COST_RATE + SELL_TICKET
    return ((proceeds - sell_cost) - (deploy + buy_cost)) / (deploy + buy_cost) * 100.0

# -------------------------------------------------------------- pot runner
def run_pot(book, trades_plan, start, end, spy_days):
    """trades_plan: list of dicts {ticker, entry_date, exit_date,
    entry_close, exit_close, div (credited at ex), ex}. Executes the
    frozen sizing: 20% of equity per entry, max 5 concurrent."""
    plan_by_entry = {}
    for p in trades_plan:
        plan_by_entry.setdefault(p["entry_date"], []).append(p)
    days = [d for d in spy_days if start <= d <= end]
    cash = START_CASH
    positions = []   # {ticker, shares, exit_date, exit_close, div, ex, entry_cost_basis}
    trades = []
    total_costs = 0.0
    curve = []
    pending_div = []  # (ex_date, amount_cash) credited when ex passes
    for d in days:
        # exits at today's close first (frees slots/cash for same-day entries)
        still = []
        for p in positions:
            if p["exit_date"] == d:
                proceeds = p["shares"] * p["exit_close"]
                c = proceeds * COST_RATE + SELL_TICKET
                cash += proceeds - c
                total_costs += c
                div_cash = p.get("div_cash", 0.0)
                trades.append({"ticker": p["ticker"], "entry_date": p["entry_date"],
                               "exit_date": d, "side": "SELL", "proceeds": round(proceeds, 2),
                               "cost": round(c, 4), "deploy": p["deploy"],
                               "div_cash": round(div_cash, 4),
                               "net_ret_pct": round((proceeds - c + div_cash) /
                                                    (p["deploy"] + p["buy_cost"]) * 100 - 100, 4)})
            else:
                still.append(p)
        positions = still
        # dividend credits whose ex-date is today (cash arrives while holding)
        for p in positions:
            if p.get("ex") == d and not p.get("div_paid"):
                amt = p["shares"] * p["div"]
                cash += amt
                p["div_paid"] = True
                p["div_cash"] = amt
        # entries at today's close
        for p in plan_by_entry.get(d, []):
            if len(positions) >= MAX_POS or cash <= 0:
                trades.append({"ticker": p["ticker"], "entry_date": d,
                               "side": "SKIP-FULL", "ex": p["ex"]})
                continue
            equity = cash + sum(q["shares"] * (book.close_on_or_before(q["ticker"], d) or q["entry_close"])
                                for q in positions)
            deploy = min(POS_FRAC * equity, cash / (1 + COST_RATE))
            if deploy <= 0:
                continue
            sh = deploy / p["entry_close"]
            bc = deploy * COST_RATE
            cash -= deploy + bc
            total_costs += bc
            positions.append({"ticker": p["ticker"], "shares": sh,
                              "exit_date": p["exit_date"], "exit_close": p["exit_close"],
                              "div": p.get("div", 0.0), "ex": p.get("ex"),
                              "entry_date": d, "entry_close": p["entry_close"],
                              "deploy": deploy, "buy_cost": bc, "div_paid": False})
            trades.append({"ticker": p["ticker"], "entry_date": d, "side": "BUY",
                           "deploy": round(deploy, 2), "cost": round(bc, 4),
                           "ex": p.get("ex"), "exit_date": p["exit_date"]})
        v = cash + sum(q["shares"] * (book.close_on_or_before(q["ticker"], d) or q["entry_close"])
                       for q in positions)
        curve.append((d, round(v, 4)))
    # any position still open at road end: value at last mark (no forced sale cost)
    final = curve[-1][1] if curve else START_CASH
    return {"final": round(final, 2), "costs": round(total_costs, 2),
            "trades": trades, "curve": curve}

def make_placebo_plan(book, ranked_events, start, end, seed, ex_by_ticker):
    rng = random.Random(seed)
    plan = []
    for e in ranked_events:
        for _try in range(300):
            t = rng.choice(POND)
            bl = book.bars.get(t, [])
            if len(bl) < PRE + POST + 1:
                continue
            # entry on/after road start, exit within fetched span
            cand = [i for i, b in enumerate(bl)
                    if start <= b["d"] <= end and i + (PRE + POST) < len(bl)]
            if not cand:
                continue
            i = rng.choice(cand)
            window_ex = [x for x in ex_by_ticker.get(t, [])
                         if bl[i]["d"] <= x <= bl[i + PRE + POST]["d"]]
            if window_ex:
                continue
            plan.append({"ticker": t, "entry_date": bl[i]["d"],
                         "entry_close": bl[i]["c"],
                         "exit_date": bl[i + PRE + POST]["d"],
                         "exit_close": bl[i + PRE + POST]["c"],
                         "div": 0.0, "ex": None})
            break
    plan.sort(key=lambda p: p["entry_date"])
    return plan

# ------------------------------------------------------------ distribution
def pct(sorted_vals, q):
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if lo == hi:
        return sorted_vals[lo]
    f = pos - lo
    return sorted_vals[lo] * (1 - f) + sorted_vals[hi] * f

def describe(vals):
    if not vals:
        return {"n": 0}
    s = sorted(vals)
    return {"n": len(vals), "mean": round(sum(vals) / len(vals), 4),
            "median": round(pct(s, 0.5), 4), "p25": round(pct(s, 0.25), 4),
            "p75": round(pct(s, 0.75), 4), "min": round(s[0], 4),
            "max": round(s[-1], 4),
            "pos_share": round(sum(1 for x in vals if x > 0) / len(vals), 4)}

def period_stats(curve):
    """Calendar-year distribution + drawdown + new-high stretch."""
    if not curve:
        return {}
    by_year = {}
    for d, v in curve:
        by_year.setdefault(d[:4], []).append((d, v))
    years = sorted(by_year)
    rets, prev_end = [], START_CASH
    for y in years:
        end_v = by_year[y][-1][1]
        rets.append((y, (end_v / prev_end - 1) * 100.0))
        prev_end = end_v
    vals = [r for _y, r in rets]
    # longest losing streak (consecutive negative years)
    streak = longest = 0
    for r in vals:
        streak = streak + 1 if r < 0 else 0
        longest = max(longest, streak)
    # max drawdown + longest stretch between new highs (calendar days)
    peak, peak_date, maxdd = -1.0, None, 0.0
    last_high = curve[0][0]
    longest_gap = 0
    from datetime import date as _date
    def pd(s):
        return _date(int(s[:4]), int(s[5:7]), int(s[8:10]))
    for d, v in curve:
        if v >= peak:
            if peak_date is not None:
                longest_gap = max(longest_gap, (pd(d) - pd(last_high)).days)
            peak, peak_date, last_high = v, d, d
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak * 100.0)
    longest_gap = max(longest_gap, (pd(curve[-1][0]) - pd(last_high)).days)
    svals = sorted(vals)
    return {"years": [{"year": y, "ret_pct": round(r, 2)} for y, r in rets],
            "median_year_pct": round(pct(svals, 0.5), 2) if svals else None,
            "share_years_positive": round(sum(1 for r in vals if r > 0) / len(vals), 3) if vals else None,
            "best_year": {"year": max(rets, key=lambda x: x[1])[0],
                          "ret_pct": round(max(rets, key=lambda x: x[1])[1], 2)} if rets else None,
            "worst_year": {"year": min(rets, key=lambda x: x[1])[0],
                           "ret_pct": round(min(rets, key=lambda x: x[1])[1], 2)} if rets else None,
            "longest_losing_streak_years": longest,
            "max_drawdown_pct": round(maxdd, 2),
            "longest_stretch_between_new_highs_days": longest_gap}

# ------------------------------------------------------------------- main
def main():
    print("fetching / loading payloads...", flush=True)
    bars_by, divs_by = {}, {}
    for t in POND + ["SPY"]:
        j = yahoo_payload(t, "2009-06-01", "2026-11-21", DATA, "px")
        raw, _adj, divs = parse_payload(j)
        bars_by[t] = raw
        divs_by[t] = divs
    book = Book({t: bars_by[t] for t in POND})
    spy_days = [b["d"] for b in bars_by["SPY"]]

    gate = {k: spy_net_from_cache(*v) for k, v in GATE_ROADS.items()}
    print(f"SPY gate: CONT={gate['CONT']} (published 313.62), VAL={gate['VAL']} (published 187.77)", flush=True)
    assert gate["CONT"] == 313.62 and gate["VAL"] == 187.77, "SPY GATE FAILED"

    all_events = build_events(book, divs_by)
    filtered = [e for e in all_events if e["div_yield_pct"] >= YIELD_MIN * 100]
    for e in filtered:
        e["net_pct_1day_fullpot"] = round(standalone_net_pct(e), 4)
    print(f"events total={len(all_events)} filtered(>=1.25%)={len(filtered)}", flush=True)

    ex_by_ticker = {}
    for t in POND:
        ex_by_ticker[t] = [dv["ex"] for dv in divs_by.get(t, [])]

    out = {"gate_spy": gate,
           "spec": {"yield_min_pct": YIELD_MIN * 100, "pre_days": PRE, "post_days": POST,
                    "pos_frac": POS_FRAC, "max_pos": MAX_POS, "floor": None,
                    "cost_rate_per_side": COST_RATE, "sell_ticket": SELL_TICKET},
           "census": {"all_events": len(all_events),
                      "filtered_events": len(filtered),
                      "filtered_gross_capture": describe([e["gross_pct"] for e in filtered]),
                      "filtered_net_capture_1day": describe([e["net_pct_1day_fullpot"] for e in filtered]),
                      "all_gross_capture": describe([e["gross_pct"] for e in all_events])},
           "roads": {}}

    for name, (s, e_) in ROADS.items():
        evs = [e for e in filtered if s <= e["entry_date"] <= e_]
        plan = [{"ticker": e["ticker"], "entry_date": e["entry_date"],
                 "entry_close": e["entry_close"], "exit_date": e["exit_date"],
                 "exit_close": e["exit_close"], "div": e["div"], "ex": e["ex"]}
                for e in evs]
        r = run_pot(book, plan, s, e_, spy_days)
        # attach per-trade actual net returns to events (match on entry+ticker)
        sell_by_key = {}
        for tr in r["trades"]:
            if tr["side"] == "SELL":
                sell_by_key[(tr["ticker"], tr["entry_date"])] = tr["net_ret_pct"]
        traded = []
        for e in evs:
            key = (e["ticker"], e["entry_date"])
            traded.append({**e, "trade_net_ret_pct": sell_by_key.get(key)})
        pls = []
        for seed in range(1, 21):
            pp = make_placebo_plan(book, evs, s, e_, seed, ex_by_ticker)
            pr = run_pot(book, pp, s, e_, spy_days)
            pls.append(pr["final"])
        pls_sorted = sorted(pls)
        ps = period_stats(r["curve"])
        out["roads"][name] = {
            "window": [s, e_], "final": r["final"], "costs": r["costs"],
            "n_events_filtered": len(evs),
            "n_buys": sum(1 for t in r["trades"] if t["side"] == "BUY"),
            "n_skipped_full": sum(1 for t in r["trades"] if t["side"] == "SKIP-FULL"),
            "period": ps,
            "placebo": {"finals": pls_sorted, "median": round(pct(pls_sorted, 0.5), 2),
                        "best": pls_sorted[-1], "worst": pls_sorted[0],
                        "ranked_beats": sum(1 for f in pls if r["final"] > f)},
            "events": traded,
            "trades": r["trades"],
            "curve": r["curve"],
            "event_capture_dist": {
                "gross_pct": describe([e["gross_pct"] for e in traded]),
                "net_1day_pct": describe([e["net_pct_1day_fullpot"] for e in traded]),
                "trade_net_ret_pct": describe([e["trade_net_ret_pct"] for e in traded
                                               if e["trade_net_ret_pct"] is not None]),
            },
        }
        print(f"{name}: final={r['final']} costs={r['costs']} events={len(evs)} "
              f"maxDD={ps['max_drawdown_pct']}% placebo median={pct(pls_sorted,0.5):.2f} "
              f"beats={out['roads'][name]['placebo']['ranked_beats']}/20", flush=True)

    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")

if __name__ == "__main__":
    main()
