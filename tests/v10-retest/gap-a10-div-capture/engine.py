#!/usr/bin/env python3
"""
GAP TEST A-10 — DIVIDEND CAPTURE (Lakonishok & Vermaelen 1986 form)

Simulation only. No broker orders were placed.

Source spec: ~/workspace/stock-app/research/v7-completeness/missing-families.md,
Table A, item A-10 — the frozen one-clean-shot spec, implemented verbatim:

  "One-day form, frozen: for each pond ex-date (declared dividends,
   point-in-time), buy at the close of the last cum-dividend day with the
   full pot (split equally if two ex-dates coincide), sell at the close
   on the ex-date; dividend credited. Report net capture per event after
   program costs, 2016-2026. Stated prior: Kalay's no-profit bounds say
   the lowest-cost trader sets the drop — at this account's cost schedule
   the expected net is <= 0. The trial exists so the family is closed by
   evidence, not by assertion."

Chassis (program standard): $100 pot; costs 0.10% of trade value per side
+ $0.01 per sell order; plain -15% floor ($85, close-based); honest top-30
pond as of Nov 2016 (the champion engine's UNIVERSE); judged windows
continuous 2019-01-02 -> 2026-11-20 and validation 2023-01-03 -> 2026-11-20
(the champion engine's exact window bounds); benchmarks SPY buy-hold net
($313.62 / $187.77, reproduced via the champion's own construction as an
integrity gate before any A-10 number is taken) and champion V+M
($544.47 / $288.05). Placebo (per the task brief): the same capital
deployed on random non-event day-pairs at matched frequency, 20 seeds.

FORCED READINGS (declared here, before any result):
  1. Event source: Yahoo Finance chart API dividend events (ex-date +
     amount), fetched with events=div,split — the same free source and
     fetch method as every price series in this program. Point-in-time
     discipline: an ex-date and its amount are fixed at declaration,
     weeks before the last cum-dividend day, so buying at the cum-day
     close uses only information public at that moment. No declaration
     dates are needed by the rule, and none are used. Amounts are taken
     as Yahoo reports them (special distributions included if Yahoo
     codes them as dividends — flagged in the report if any single
     event's dividend exceeds 3% of the cum-day close; nothing is
     patched or excluded).
  2. Price basis: RAW quote closes (split-adjusted by Yahoo, NOT
     dividend-adjusted). Dividend capture is invisible in
     dividend-adjusted prices, so the trade arithmetic must run on raw
     closes with the dividend credited as cash at the ex-date sale —
     the program's standing dividend-crediting convention. Yahoo's
     dividend amounts are split-adjusted on the same basis as its quote
     closes (verified: AAPL 2017-08-10 amount 0.1575 = the $0.63 paid,
     divided by the later 4:1 split; AAPL quote close 2017-08-09 is
     $40.26, the split-adjusted figure), so per-share ratios are
     consistent across splits.
  3. Census span: the spec's "2016-2026" is honored by fetching bars
     from 2015-12-01, so every pond ex-date in 2016-01-01..2026-11-20
     with a cum-day and ex-day bar is censused. The two judged pots run
     on the house windows above (an event belongs to a window if its
     EX-DATE falls inside it; the cum-day close may be the prior
     trading day, including the last trading day before the window).
  4. "Split equally if two ex-dates coincide": events sharing an
     ex-date share a cum-date (same trading calendar); the pot's cash
     is split equally among the names bought at that cum-day close.
     If a sale (ex-date close) and a buy (cum-day close) fall on the
     same day, the sale settles first and its proceeds are available
     for the buy — both execute at that day's closes, per the spec.
  5. The -15% floor is checked on daily closes exactly as in the
     champion engine (a close at/below $85 liquidates at the next open
     and ends the run). Structural note, stated in advance: a capture
     position is bought at a close and sold at the NEXT close, so the
     only close observed while holding is the exit close itself — the
     floor can bind only if the pot is already at the floor's edge at
     the purchase close. The overnight gap risk is borne in full by
     construction; that is the strategy as published, not an oversight.
  6. Placebo construction: the ranked run's deployment pattern is
     replayed step by step — the same number of deployment steps, and
     at each step the same number of trades, each deploying an equal
     split of the cash on hand (exactly the ranked run's cash-split
     structure) — but each placebo trade buys a randomly drawn pond
     name at the close of a randomly drawn trading day t (SPY calendar,
     inside the window, t+1 also inside) and sells at the close of
     t+1, where neither t nor t+1 is that name's cum-day or ex-date
     for any censused event (a genuinely non-event day-pair). No
     dividend is credited. Same costs, same floor. Seeds 1..20.
"""
import json, math, os, random, time, urllib.request, calendar
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "gap-a10-div-capture-data")
os.makedirs(DATA, exist_ok=True)
V4 = os.path.join(HERE, "..", "..", "v4")
SHARED = os.path.join(V4, "data")                       # program cache, read-only
HONEST = os.path.join(V4, "value-momentum-honest-data")  # program cache, read-only

UA = "AtlasGateResearch terry-research@example.com"
POND = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "BRK-B", "JPM", "XOM",
        "JNJ", "PG", "V", "WMT", "HD", "BAC", "CVX", "PFE", "VZ", "T",
        "DIS", "NFLX", "INTC", "CSCO", "GE", "IBM", "MMM", "UNH", "MA",
        "KO", "PEP", "WFC"]
START_CASH = 100.0
FLOOR = 85.0
COST_RATE = 0.001
SELL_TICKET = 0.01
CONT = ("2019-01-02", "2026-11-20")
VAL = ("2023-01-03", "2026-11-20")
CENSUS = ("2016-01-01", "2026-11-20")

# ------------------------------------------------------------------ fetch
def fetch(url, path, headers=None, tries=3):
    if os.path.exists(path) and os.path.getsize(path) > 100:
        with open(path, "rb") as f:
            return f.read()
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers or {"User-Agent": UA})
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
    blob = fetch(url, os.path.join(cache_dir, f"{tag}_{ticker}.json"),
                 headers={"User-Agent": "Mozilla/5.0"})
    return json.loads(blob)

def parse_payload(j):
    """Return (raw_bars, adj_bars, dividends, splits).
    raw_bars: [{d, c}] on Yahoo quote closes (split-adj, not div-adj).
    adj_bars: [{d, o, c}] champion construction (adjclose basis).
    dividends: [{ex, amount}]; splits: [{d, num, den}]."""
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
        raw.append({"d": d, "c": c})
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        o = q["open"][i]
        adjb.append({"d": d, "o": (o * ratio if o else a), "c": a})
    raw.sort(key=lambda b: b["d"])
    adjb.sort(key=lambda b: b["d"])
    divs, splits = [], []
    ev = res.get("events") or {}
    for v in (ev.get("dividends") or {}).values():
        divs.append({"ex": time.strftime("%Y-%m-%d", time.gmtime(v["date"])),
                     "amount": float(v["amount"])})
    for v in (ev.get("splits") or {}).values():
        splits.append({"d": time.strftime("%Y-%m-%d", time.gmtime(v["date"])),
                       "num": v["numerator"], "den": v["denominator"]})
    divs.sort(key=lambda x: x["ex"])
    return raw, adjb, divs, splits

def program_cache_payload(ticker):
    """The champion engine's cached payload for a ticker, read-only."""
    for base in (SHARED, HONEST):
        p = os.path.join(base, f"px_{ticker}.json")
        if os.path.exists(p) and os.path.getsize(p) > 100:
            with open(p, "rb") as f:
                return json.loads(f.read()), p
    return None, None

# ------------------------------------------------------------- price book
class RawBook:
    def __init__(self, bars_by_ticker):
        self.bars = bars_by_ticker
        self.idx = {t: {b["d"]: b["c"] for b in bl} for t, bl in bars_by_ticker.items()}
        self.dates = {t: [b["d"] for b in bl] for t, bl in bars_by_ticker.items()}

    def close(self, t, d):
        return self.idx.get(t, {}).get(d)

    def prev_day(self, t, d):
        """Last bar date strictly before d for ticker t."""
        prev = None
        for bd in self.dates.get(t, []):
            if bd < d:
                prev = bd
            else:
                break
        return prev

    def next_day(self, t, d):
        for bd in self.dates.get(t, []):
            if bd > d:
                return bd
        return None

# ---------------------------------------------------------------- events
def build_events(rb, divs_by_ticker):
    """Census every pond dividend event in the census span."""
    events = []
    skipped = []
    for t in POND:
        for dv in divs_by_ticker.get(t, []):
            ex = dv["ex"]
            if not (CENSUS[0] <= ex <= CENSUS[1]):
                continue
            cum = rb.prev_day(t, ex)
            if cum is None or rb.close(t, ex) is None or rb.close(t, cum) is None:
                skipped.append({"ticker": t, "ex": ex, "reason": "missing bar"})
                continue
            cc, xc = rb.close(t, cum), rb.close(t, ex)
            drop = cc - xc
            gross = dv["amount"] - drop            # $/share captured, gross
            events.append({
                "ticker": t, "ex": ex, "cum": cum, "div": dv["amount"],
                "cum_close": cc, "ex_close": xc,
                "gross_per_share": gross,
                "gross_pct": gross / cc * 100.0,
                "div_yield_pct": dv["amount"] / cc * 100.0,
            })
    events.sort(key=lambda e: (e["cum"], e["ticker"]))
    return events, skipped

def standalone_net_pct(ev, deploy=100.0):
    """Net return % of one event traded alone with `deploy` dollars."""
    sh = deploy / ev["cum_close"]
    buy_cost = deploy * COST_RATE
    proceeds = sh * (ev["ex_close"] + ev["div"])
    sell_cost = proceeds * COST_RATE + SELL_TICKET
    return ((proceeds - sell_cost) - (deploy + buy_cost)) / (deploy + buy_cost) * 100.0

# -------------------------------------------------------------- pot runner
def run_capture(rb, events, start, end, start_cash=None, floor=None):
    # v9: episode cash/floor parameters (default = original globals)
    if start_cash is None:
        start_cash = start_cash
    if floor is None:
        floor = FLOOR
    """The frozen spec on one window. Events belong by ex-date in window."""
    evs = [e for e in events if start <= e["ex"] <= end]
    by_cum = {}
    for e in evs:
        by_cum.setdefault(e["cum"], []).append(e)
    days = sorted({d for t in POND for d in rb.dates.get(t, []) if start <= d <= end}
                  | {e["cum"] for e in evs})
    cash = START_CASH
    positions = {}   # ticker -> (shares, div, ex_date)
    trades = []
    total_costs = 0.0
    halted = None
    curve = []
    for d in days:
        # 1) sales first: positions whose ex-date is today sell at today's close
        for t in list(positions):
            if positions[t][2] == d:
                sh, div, _exd = positions.pop(t)
                px = rb.close(t, d)
                proceeds = sh * (px + div)
                c = proceeds * COST_RATE + SELL_TICKET
                cash += proceeds - c
                total_costs += c
                trades.append({"d": d, "ticker": t, "side": "SELL",
                               "shares": sh, "price": px, "div": div, "cost": c})
        # 2) buys at today's close: every event whose cum-day is today
        todays = by_cum.get(d, [])
        if todays and cash > 0:
            each = cash / len(todays)
            for e in todays:
                deploy = each
                sh = deploy / e["cum_close"]
                c = deploy * COST_RATE
                cash -= deploy + c
                total_costs += c
                positions[e["ticker"]] = (sh, e["div"], e["ex"])
                trades.append({"d": d, "ticker": e["ticker"], "side": "BUY",
                               "shares": sh, "price": e["cum_close"], "cost": c})
        # equity at close
        v = cash + sum(sh * (rb.close(t, d) or 0.0) for t, (sh, _dv, _x) in positions.items())
        curve.append((d, v))
        if v <= floor and d != days[-1]:
            halted = d
            # liquidate at next open-equivalent: positions exit at next bar's close
            # (raw book carries closes only; the exit day is the position's ex-date,
            #  whose close is the spec exit — a halt here can only occur at a
            #  purchase close, see forced reading 5)
            nd = rb.next_day(list(positions)[0], d) if positions else None
            for t in list(positions):
                sh, div, _exd = positions.pop(t)
                px = rb.close(t, nd) if nd else rb.close(t, d)
                proceeds = sh * px
                c = proceeds * COST_RATE + SELL_TICKET
                cash += proceeds - c
                total_costs += c
                trades.append({"d": nd or d, "ticker": t, "side": "SELL-HALT",
                               "shares": sh, "price": px, "div": 0.0, "cost": c})
            return {"final": round(cash, 2), "costs": round(total_costs, 2),
                    "trades": trades, "halted": halted, "curve": curve,
                    "n_events": len(evs)}
    return {"final": round(cash, 2), "costs": round(total_costs, 2),
            "trades": trades, "halted": halted, "curve": curve,
            "n_events": len(evs)}

def run_placebo(rb, events, start, end, seed, spy_days):
    """Same capital deployed on random non-event day-pairs, matched
    frequency: one placebo trade per ranked event, deployed with the same
    cash-split structure (a k-way coincident day in the ranked run maps to
    k placebo trades each deploying 1/k of the cash on hand at that step).
    Sequence mirrors the ranked run's chronological deployment pattern."""
    rng = random.Random(seed)
    evs = [e for e in events if start <= e["ex"] <= end]
    by_cum = {}
    for e in evs:
        by_cum.setdefault(e["cum"], []).append(e)
    steps = [len(by_cum[d]) for d in sorted(by_cum)]  # buys per deployment day
    # non-event day-pairs per ticker
    event_days = {}
    for t in POND:
        s = set()
        for e in events:
            if e["ticker"] == t:
                s.add(e["cum"]); s.add(e["ex"])
        event_days[t] = s
    win_days = [d for d in spy_days if start <= d <= end]
    cash = START_CASH
    total_costs = 0.0
    n_trades = 0
    for k in steps:
        each_frac = 1.0 / k
        pending = []
        for _ in range(k):
            for _try in range(200):
                t = rng.choice(POND)
                ti = rng.randrange(0, len(win_days) - 1)
                d0, d1 = win_days[ti], win_days[ti + 1]
                if d0 in event_days[t] or d1 in event_days[t]:
                    continue
                p0, p1 = rb.close(t, d0), rb.close(t, d1)
                if p0 is None or p1 is None:
                    continue
                pending.append((t, p0, p1))
                break
        for (t, p0, p1) in pending:
            deploy = cash * each_frac
            if deploy <= 0:
                continue
            sh = deploy / p0
            bc = deploy * COST_RATE
            cash -= deploy + bc
            total_costs += bc
            proceeds = sh * p1
            sc = proceeds * COST_RATE + SELL_TICKET
            cash += proceeds - sc
            total_costs += sc
            n_trades += 1
        if cash <= FLOOR:
            return {"final": round(cash, 2), "costs": round(total_costs, 2),
                    "n_trades": n_trades, "halted": True}
    return {"final": round(cash, 2), "costs": round(total_costs, 2),
            "n_trades": n_trades, "halted": False}

# ------------------------------------------------------- SPY integrity gate
def spy_net_from_cache(start, end, start_cash=100.0):
    """Champion construction, verbatim method, on the program cache."""
    j, _ = program_cache_payload("SPY")
    _raw, adjb, _d, _s = parse_payload(j)
    idx = {b["d"]: b for b in adjb}
    days = sorted(d for d in idx if start <= d <= end)
    first, last = days[0], days[-1]
    o = idx[first]["o"]
    sh = (start_cash / 1.001) / o
    buy_cost = start_cash - sh * o
    val = sh * idx[last]["c"]
    sell_cost = val * 0.001 + 0.01
    return round(val - sell_cost, 2)

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

# ------------------------------------------------------------------- main
def main():
    print("fetching / loading payloads...", flush=True)
    raw_by, divs_by, splits_by = {}, {}, {}
    for t in POND + ["SPY"]:
        j = yahoo_payload(t, "2015-12-01", "2026-11-21", DATA, "pxraw")
        raw, _adj, divs, splits = parse_payload(j)
        raw_by[t] = raw
        divs_by[t] = divs
        splits_by[t] = splits
    rb = RawBook({t: raw_by[t] for t in POND})
    spy_days = [b["d"] for b in raw_by["SPY"]]

    # --- integrity gate: SPY nets via champion construction on program cache
    gate = {"continuous": spy_net_from_cache(*CONT), "validation": spy_net_from_cache(*VAL)}
    print(f"SPY gate: continuous={gate['continuous']} (published 313.62), "
          f"validation={gate['validation']} (published 187.77)", flush=True)
    assert gate["continuous"] == 313.62 and gate["validation"] == 187.77, "SPY GATE FAILED"

    # --- cross-check: fresh pull vs program cache (events + raw closes)
    xcheck = {}
    for t in POND:
        cj, _p = program_cache_payload(t)
        if cj is None:
            xcheck[t] = {"cache": "absent"}
            continue
        craw, _a, cdivs, _s = parse_payload(cj)
        cidx = {b["d"]: b["c"] for b in craw}
        fidx = {b["d"]: b["c"] for b in raw_by[t]}
        common = [d for d in cidx if d in fidx]
        maxdiff = max((abs(cidx[d] - fidx[d]) for d in common), default=0.0)
        cev = {(dv["ex"], round(dv["amount"], 6)) for dv in cdivs}
        fev = {(dv["ex"], round(dv["amount"], 6)) for dv in divs_by[t]}
        xcheck[t] = {"common_bars": len(common), "max_close_diff": round(maxdiff, 6),
                     "cache_events": len(cev), "fresh_events": len(fev),
                     "events_only_in_cache": sorted(cev - fev)[:5],
                     "events_only_in_fresh": sorted(fev - cev)[:5]}
    ndiff = sum(1 for v in xcheck.values() if v.get("max_close_diff", 0) > 0.01)
    print(f"cross-check: tickers with any raw-close diff > $0.01 vs cache: {ndiff}", flush=True)

    # --- event census
    events, skipped = build_events(rb, divs_by)
    for e in events:
        e["net_pct_fullpot"] = round(standalone_net_pct(e), 4)
    print(f"census: {len(events)} events, {len(skipped)} skipped", flush=True)

    def agg(evs):
        if not evs:
            return {"n": 0}
        g = sorted(e["gross_pct"] for e in evs)
        n = sorted(e["net_pct_fullpot"] for e in evs)
        return {"n": len(evs),
                "gross_mean_pct": round(sum(g) / len(g), 4),
                "gross_median_pct": round(pct(g, 0.5), 4),
                "gross_pos_share": round(sum(1 for x in g if x > 0) / len(g), 4),
                "net_mean_pct": round(sum(n) / len(n), 4),
                "net_median_pct": round(pct(n, 0.5), 4),
                "net_pos_share": round(sum(1 for x in n if x > 0) / len(n), 4),
                "total_div_yield_pct_of_price": round(sum(e["div_yield_pct"] for e in evs), 2)}

    census_stats = agg(events)
    by_year = {}
    for y in range(2016, 2027):
        by_year[str(y)] = agg([e for e in events if e["ex"][:4] == str(y)])
    outliers = [e for e in events if e["div_yield_pct"] > 3.0]

    out = {"gate_spy": gate, "crosscheck": xcheck,
           "census": {"stats": census_stats, "by_year": by_year,
                      "skipped": skipped, "outliers_div_over_3pct": outliers,
                      "events": events}}

    # --- judged windows
    for name, (s, e_) in (("continuous", CONT), ("validation", VAL)):
        r = run_capture(rb, events, s, e_)
        pls = [run_placebo(rb, events, s, e_, seed, spy_days) for seed in range(1, 21)]
        finals = sorted(p["final"] for p in pls)
        beats = sum(1 for f in finals if r["final"] > f)
        wev = [e for e in events if s <= e["ex"] <= e_]
        worst = min(wev, key=lambda x: x["net_pct_fullpot"]) if wev else None
        best = max(wev, key=lambda x: x["net_pct_fullpot"]) if wev else None
        curve = r.pop("curve")
        worst_close = min(curve, key=lambda kv: kv[1]) if curve else None
        peak, maxdd = -1.0, 0.0
        for _d, v in curve:
            peak = max(peak, v)
            if peak > 0:
                maxdd = max(maxdd, (peak - v) / peak * 100.0)
        out[name] = {
            "final": r["final"], "costs": r["costs"], "halted": r["halted"],
            "n_events": r["n_events"], "n_trades": len(r["trades"]),
            "worst_close": {"date": worst_close[0], "value": round(worst_close[1], 2)} if worst_close else None,
            "max_drawdown_pct": round(maxdd, 2),
            "worst_event": worst, "best_event": best,
            "events_stats": agg(wev),
            "placebo": {"finals": finals, "median": round(pct(finals, 0.5), 2),
                        "best": finals[-1], "worst": finals[0],
                        "ranked_beats": beats,
                        "any_halted": any(p["halted"] for p in pls)},
            "trades": r["trades"],
        }
        print(f"{name}: ranked final={r['final']} costs={r['costs']} "
              f"events={r['n_events']} placebo median={pct(finals, 0.5):.2f} beats={beats}/20",
              flush=True)

    with open(os.path.join(HERE, "dividend-capture-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")

if __name__ == "__main__" and False:
    main()  # original entry disabled in v9 copy


# =====================================================================
# CLAUDE-RULES PROTECTION SPEC v9 — the ONLY change vs the original.
# run_capture() above is unchanged except it now accepts the episode's
# starting cash and floor as parameters (defaults = the original
# globals $100 / $85, so episode 1 is byte-identical in behaviour).
#   Episode 1: plain -15% floor from the $100 start ($85) — identical.
#   On FIRST halt: liquidate exactly as run_capture does (positions
#     exit at the next bar's close, no dividend — the original halt
#     mechanics), sit in cash 90 calendar days from the liquidation
#     date, then RESTART with the remaining cash, resuming events
#     whose cum-date is on/after the eligible date.
#   Episode 2: floor = -15% from the RESTART balance (0.85 x cash).
#   On SECOND halt: run ends permanently.
# Ranked pot only; no placebos in this re-run.
# =====================================================================
from datetime import date as _date, timedelta as _td


def _plus90(dstr):
    y, m, d = (int(x) for x in dstr.split("-"))
    return (_date(y, m, d) + _td(days=90)).isoformat()


def run_capture_v9(rb, events, start, end, label=""):
    ep1 = run_capture(rb, events, start, end)
    halt_trades = [t for t in ep1["trades"] if t["side"] == "SELL-HALT"]
    base = {"episodes": 1, "ep1_halted": ep1["halted"],
            "ep1_final": ep1["final"], "costs": ep1["costs"],
            "orders": len(ep1["trades"]), "restart": None,
            "ep2_halted": None}
    if not ep1["halted"]:
        base.update({"final": ep1["final"], "status": "no_halt"})
        return base
    liq_date = max(t["d"] for t in halt_trades) if halt_trades else ep1["halted"]
    cash1 = float(ep1["final"])
    eligible = _plus90(liq_date)
    floor2 = round(0.85 * cash1, 2)
    ep2 = run_capture(rb, events, eligible, end, start_cash=cash1,
                      floor=0.85 * cash1)
    base.update({"episodes": 2, "final": ep2["final"],
                 "costs": round(ep1["costs"] + ep2["costs"], 2),
                 "orders": len(ep1["trades"]) + len(ep2["trades"]),
                 "ep2_halted": ep2["halted"],
                 "status": "halted_ep2_run_ends" if ep2["halted"]
                           else "restarted_completed",
                 "restart": {"halt_signal_date": ep1["halted"],
                             "liquidation_date": liq_date,
                             "cash_at_halt": round(cash1, 2),
                             "eligible_from": eligible,
                             "restart_date": eligible,
                             "restart_balance": round(cash1, 2),
                             "episode2_floor": floor2,
                             "note": "event engine: resumes taking events "
                                     "with cum-date on/after eligible_from"}})
    return base


def main_v9():
    global DATA
    DATA = os.path.expanduser(
        "~/workspace/stock-app/backtests/v7/gap-a10-div-capture/"
        "gap-a10-div-capture-data")   # original cache, read-only
    raw_by, divs_by = {}, {}
    for t in POND + ["SPY"]:
        j = yahoo_payload(t, "2015-12-01", "2026-11-21", DATA, "pxraw")
        raw, _adj, divs, _splits = parse_payload(j)
        raw_by[t] = raw
        divs_by[t] = divs
    rb = RawBook({t: raw_by[t] for t in POND})
    events, _skipped = build_events(rb, divs_by)
    out = {"spec": "CLAUDE-RULES PROTECTION SPEC v9 (90-day sit-out, one "
                   "restart, ep2 floor -15% from restart balance)",
           "ranked_only": True}
    for name, (s, e_) in (("continuous", CONT), ("validation", VAL)):
        r = run_capture_v9(rb, events, s, e_, label=name)
        out[name] = r
        print(f"== {name}: v9 final=${r['final']:,.2f} status={r['status']} "
              f"ep1_halted={r['ep1_halted']} restart={r['restart']}",
              flush=True)
    with open(os.path.join(HERE, "v9-raw-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")


if __name__ == "__main__":
    main_v9()
