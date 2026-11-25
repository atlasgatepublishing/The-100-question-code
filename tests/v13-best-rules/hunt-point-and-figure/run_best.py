#!/usr/bin/env python3
"""Point-and-Figure V13 BEST RULES. Implements BEST-RULES-SPEC.md exactly:
2% log-percentage boxes, 3-box reversal, high/low construction,
one-direction-per-day rule, bar-by-bar (no repainting), double-top breakout /
double-bottom breakdown only. Headline system: 10-slot portfolio over the
154-name pond, fresh-breakout entries, breakdown exits, no rebalancing,
no floor. SPY run as same-rules single-asset diagnostic (NATIVE accounting).
Costs 0.10%/side + $0.01 sell fee. $100 pots. 20-seed placebos.
Simulation only. Prior folders read-only."""
import json, os, math, random, statistics, time
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
PXDIR = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
START = 100.0
SCOST = 0.001; SELL_FEE = 0.01
BOX = 1.02
LOG_BOX = math.log(BOX)

# ---------------- P&F engine (2% log boxes) ----------------
def pf_chart(highs, lows, closes):
    """Returns (state, buy_events) where state[i]=1 if long decided at close i,
    buy_events = {i: extension_in_boxes} for days long flips False->True."""
    n = len(closes)
    state = [0] * n
    buy_events = {}
    if n == 0:
        return state, buy_events
    def up(p): return p * BOX
    def down(p): return p / BOX
    cur = closes[0]
    direction = 1
    col_ext = cur
    prev_top = None; prev_bot = None
    long_ = False
    for i in range(n):
        H, L = highs[i], lows[i]
        if H <= 0 or L <= 0:
            state[i] = 1 if long_ else 0
            continue
        if direction == 1:
            ext = False
            while H >= up(col_ext) - 1e-12:
                col_ext = up(col_ext); ext = True
                if prev_top is not None and col_ext > prev_top + 1e-12 and not long_:
                    long_ = True
                    buy_events[i] = math.log(col_ext / prev_top) / LOG_BOX
            if not ext:
                q = col_ext
                for _ in range(3): q = down(q)
                if L <= q + 1e-12:
                    prev_top = col_ext
                    direction = -1
                    col_ext = q
                    while L <= down(col_ext) + 1e-12:
                        col_ext = down(col_ext)
                    if prev_bot is not None and col_ext < prev_bot - 1e-12 and long_:
                        long_ = False
        else:
            ext = False
            while L <= down(col_ext) + 1e-12:
                col_ext = down(col_ext); ext = True
                if prev_bot is not None and col_ext < prev_bot - 1e-12 and long_:
                    long_ = False
            if not ext:
                q = col_ext
                for _ in range(3): q = up(q)
                if H >= q - 1e-12:
                    prev_bot = col_ext
                    direction = 1
                    col_ext = q
                    while H >= up(col_ext) - 1e-12:
                        col_ext = up(col_ext)
                    if prev_top is not None and col_ext > prev_top + 1e-12 and not long_:
                        long_ = True
                        buy_events[i] = math.log(col_ext / prev_top) / LOG_BOX
        state[i] = 1 if long_ else 0
    return state, buy_events

# ---------------- data ----------------
def load_stock(sym):
    p = os.path.join(PXDIR, f"pxfull_{sym}.json")
    j = json.load(open(p))
    r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    dates, h, l, c = [], [], [], []
    for i, t in enumerate(ts):
        if None in (q["close"][i], adj[i], q["high"][i], q["low"][i], q["open"][i]):
            continue
        ratio = adj[i] / q["close"][i]
        dates.append(time.strftime("%Y-%m-%d", time.gmtime(t)))
        h.append(q["high"][i] * ratio); l.append(q["low"][i] * ratio); c.append(adj[i])
    return dates, h, l, c

ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}

def period_stats(curve):
    if not curve: return None
    periods = []
    cur_key = None; last_eq = None; start_eq = START
    for d, e in curve:
        key = d[:7]
        if cur_key is None: cur_key = key; start_eq = START
        elif key != cur_key:
            periods.append((cur_key, start_eq, last_eq)); cur_key = key; start_eq = last_eq
        last_eq = e
    periods.append((cur_key, start_eq, last_eq))
    vals = [(b / a - 1) * 100 if a > 0 else 0.0 for _, a, b in periods]
    prof = sum(1 for v in vals if v > 0)
    ll = 0; run = 0
    for v in vals:
        run = run + 1 if v <= 0 else 0; ll = max(ll, run)
    pends = [START] + [b for _, _, b in periods]
    peak = pends[0]; since = 0; longest = 0
    for e in pends[1:]:
        if e > peak: peak = e; since = 0
        else: since += 1; longest = max(longest, since)
    return {"n_periods": len(vals), "pct_profitable": round(100 * prof / len(vals), 1),
            "median_pct": round(statistics.median(vals), 2),
            "mean_pct_secondary": round(statistics.mean(vals), 2),
            "best_pct": round(max(vals), 2), "worst_pct": round(min(vals), 2),
            "longest_losing_run": ll,
            "longest_stretch_between_new_highs_periods": longest}

def max_dd(curve):
    peak = -1.0; mdd = 0.0
    for _, e in curve:
        peak = max(peak, e)
        if peak > 0: mdd = max(mdd, (peak - e) / peak)
    return round(mdd * 100, 2)

# ---------------- portfolio simulator ----------------
def run_portfolio(master_dates, midx0, midx1, charts, mode="real", seed=0,
                  real_schedule=None, real_durations=None):
    """charts: sym -> {date: (close, state, buy_ext_or_None)}.
    mode 'real': signal-driven per spec. mode 'placebo': entries on the real
    run's entry days/counts, random names, durations resampled (seeded)."""
    rng = random.Random(seed)
    cash = START; costs = 0.0
    holdings = {}  # sym -> {shares, entry_midx, last_px}
    curve = []
    positions_log = []  # (entry_midx, exit_midx_or_None, sym)
    entries_per_day = {}
    last_px = {}
    names = sorted(charts.keys())
    for mi in range(midx0, midx1 + 1):
        d = master_dates[mi]
        # update last prices
        for sym in list(holdings.keys()):
            row = charts[sym].get(d)
            if row: last_px[sym] = row[0]
        def equity():
            return cash + sum(h["shares"] * last_px.get(s, h["entry_px"]) for s, h in holdings.items())
        if mode == "real":
            # exits first (state==0 today), at today's close
            for sym in list(holdings.keys()):
                row = charts[sym].get(d)
                if row and row[1] == 0:
                    px = row[0]; h = holdings.pop(sym)
                    gross = h["shares"] * px; fee = gross * SCOST + SELL_FEE
                    cash += gross - fee; costs += fee
                    positions_log.append((h["entry_midx"], mi, sym))
            # entries
            cands = []
            if mi == midx0:
                # road-start fill: long-state names ranked freshest breakout first
                for sym in names:
                    row = charts[sym].get(d)
                    if row and row[1] == 1:
                        be = charts[sym].get("_buy_events", {})
                        past = [k for k in be if k <= d]
                        if past:
                            lb = max(past)
                            age = (date(*map(int, d.split("-"))) - date(*map(int, lb.split("-")))).days
                            cands.append((age, -be[lb], sym))
                cands.sort()
                cands = [(sym, -neg) for _, neg, sym in cands]
            else:
                for sym in names:
                    if sym in holdings: continue
                    row = charts[sym].get(d)
                    if row and row[2] is not None:
                        cands.append((sym, row[2]))
                cands.sort(key=lambda x: (-x[1], x[0]))
            free = 10 - len(holdings)
            take = cands[:free] if free > 0 else []
            if take and cash > 0:
                eq = equity(); target = eq / 10.0
                if cash >= target * len(take):
                    amounts = [target] * len(take)
                else:
                    amounts = [cash / len(take)] * len(take)
                for (sym, _ext), amt in zip(take, amounts):
                    if amt <= 0: continue
                    px = charts[sym][d][0]
                    fee = amt * SCOST
                    holdings[sym] = {"shares": (amt - fee) / px, "entry_midx": mi, "entry_px": px}
                    cash -= amt; costs += fee
                    last_px[sym] = px
                    entries_per_day[mi] = entries_per_day.get(mi, 0) + 1
        else:  # placebo
            # exits by scheduled duration
            for sym in list(holdings.keys()):
                h = holdings[sym]
                if mi >= h["exit_midx"]:
                    px = last_px.get(sym, h["entry_px"])
                    gross = h["shares"] * px; fee = gross * SCOST + SELL_FEE
                    cash += gross - fee; costs += fee
                    positions_log.append((h["entry_midx"], mi, sym))
                    del holdings[sym]
            n_today = real_schedule.get(mi, 0)
            free = 10 - len(holdings)
            k = min(n_today, free)
            if k > 0 and cash > 0 and real_durations:
                eq = equity(); target = eq / 10.0
                if cash >= target * k: amounts = [target] * k
                else: amounts = [cash / k] * k
                placed = 0; tries = 0
                while placed < k and tries < 200:
                    tries += 1
                    sym = rng.choice(names)
                    if sym in holdings: continue
                    row = charts[sym].get(d)
                    if not row: continue
                    dur = rng.choice(real_durations)
                    amt = amounts[placed]
                    px = row[0]; fee = amt * SCOST
                    holdings[sym] = {"shares": (amt - fee) / px, "entry_midx": mi,
                                     "entry_px": px, "exit_midx": min(mi + dur, midx1)}
                    cash -= amt; costs += fee; last_px[sym] = px
                    placed += 1
        curve.append([d, round(equity(), 4)])
    for sym, h in holdings.items():
        positions_log.append((h["entry_midx"], None, sym))
    final = curve[-1][1] if curve else START
    durations = [((e if e is not None else midx1) - s) for s, e, _ in positions_log]
    return {"final": round(final, 2), "max_dd_pct": max_dd(curve), "costs": round(costs, 2),
            "n_positions": len(positions_log), "curve": curve,
            "entries_per_day": entries_per_day, "durations": durations,
            "monthly_stats": period_stats(curve)}

# ---------------- SPY diagnostic (v12 accounting, NATIVE) ----------------
def run_spy_timer(dates, closes, state, i0, i1):
    cash = START; shares = 0.0; costs = 0.0; trades = 0; curve = []
    def bal(px): return cash + shares * px
    for i in range(i0, i1 + 1):
        px = closes[i]; want = state[i]
        if want == 1 and shares == 0 and cash > 0:
            fee = cash * SCOST; shares = (cash - fee) / px; costs += fee; cash = 0.0; trades += 1
        elif want == 0 and shares > 0:
            gross = shares * px; fee = gross * SCOST + SELL_FEE; cash = gross - fee
            costs += fee; shares = 0.0; trades += 1
        curve.append([dates[i], round(bal(px), 4)])
    return {"final": round(bal(closes[i1]), 2), "max_dd_pct": max_dd(curve),
            "costs": round(costs, 2), "trades": trades, "curve": curve,
            "monthly_stats": period_stats(curve)}

def spy_placebo_states(state, i0, i1, seed):
    rng = random.Random(seed)
    durs = []; cur = None
    for i in range(i0, i1 + 1):
        if state[i] == 1 and cur is None: cur = i
        if state[i] == 0 and cur is not None: durs.append(i - cur); cur = None
    if cur is not None: durs.append(i1 + 1 - cur)
    if not durs: return [0] * (i1 + 1)
    out = [0] * (i1 + 1)
    span = i1 - i0 + 1
    for dur in durs:
        for _ in range(50):
            s = i0 + rng.randrange(max(1, span - dur + 1))
            if all(out[j] == 0 for j in range(s, min(s + dur, i1 + 1))):
                for j in range(s, min(s + dur, i1 + 1)): out[j] = 1
                break
    return out

def buyhold(closes_i0, closes_i1):
    sh = (START * (1 - SCOST)) / closes_i0
    gross = sh * closes_i1
    return round(gross - gross * SCOST - SELL_FEE, 2)

def main():
    out = {"family": "hunt-point-and-figure", "program": "v13-best-rules",
           "spec": "2% log boxes, 3-box reversal, double-top/bottom only, 10-slot portfolio, no floor",
           "stock_cost": "0.10%/side + $0.01 sell fee", "portfolio": {}, "spy_diagnostic": {},
           "bullish_percent_2pct": {}}
    tickers = sorted(fn[len("pxfull_"):-len(".json")] for fn in os.listdir(PXDIR)
                     if fn.startswith("pxfull_"))
    pond = [t for t in tickers if t != "SPY"]
    out["pond_n"] = len(pond)
    # master calendar from SPY
    spy_dates, spy_h, spy_l, spy_c = load_stock("SPY")
    master = spy_dates
    midx = {d: i for i, d in enumerate(master)}
    # build charts for all names
    charts = {}
    spy_state = None
    for sym in tickers:
        dates, h, l, c = load_stock(sym) if sym != "SPY" else (spy_dates, spy_h, spy_l, spy_c)
        state, be = pf_chart(h, l, c)
        if sym == "SPY":
            spy_state = state; spy_be = be
            continue
        m = {}
        be_by_date = {}
        for i, d in enumerate(dates):
            m[d] = (c[i], state[i], be.get(i))
        for i, ext in be.items():
            be_by_date[dates[i]] = ext
        m["_buy_events"] = be_by_date
        charts[sym] = m
        print("chart done", sym, flush=True)
    # ---- portfolio roads ----
    for road, (s, e) in ROADS.items():
        ii = [i for i, d in enumerate(master) if s <= d <= e]
        i0, i1 = ii[0], ii[-1]
        r = run_portfolio(master, i0, i1, charts, mode="real")
        sched = r.pop("entries_per_day"); durs = r.pop("durations")
        twins = []
        for seed in range(20):
            t = run_portfolio(master, i0, i1, charts, mode="placebo",
                              seed=9000 + seed, real_schedule=sched, real_durations=durs)
            twins.append(t["final"])
        r["placebo_finals"] = twins
        r["placebos_beaten"] = sum(1 for t in twins if r["final"] > t)
        out["portfolio"][road] = r
        print("portfolio road done", road, r["final"], flush=True)
    # Bullish Percent descriptive at each road end (2% rules)
    for road, (s, e) in ROADS.items():
        ii = [i for i, d in enumerate(master) if s <= d <= e]
        d_end = master[ii[-1]]
        cnt = sum(1 for sym in pond if charts[sym].get(d_end, (0, 0, None))[1] == 1)
        tot = sum(1 for sym in pond if d_end in charts[sym])
        out["bullish_percent_2pct"][road] = round(100 * cnt / tot, 1) if tot else None
    # ---- SPY diagnostic ----
    for road, (s, e) in ROADS.items():
        ii = [i for i, d in enumerate(spy_dates) if s <= d <= e]
        i0, i1 = ii[0], ii[-1]
        r = run_spy_timer(spy_dates, spy_c, spy_state, i0, i1)
        twins = []
        for seed in range(20):
            pst = spy_placebo_states(spy_state, i0, i1, 5000 + seed)
            twins.append(run_spy_timer(spy_dates, spy_c, pst, i0, i1)["final"])
        r["placebo_finals"] = twins
        r["placebos_beaten"] = sum(1 for t in twins if r["final"] > t)
        r["buyhold_spy"] = buyhold(spy_c[i0], spy_c[i1])
        out["spy_diagnostic"][road] = r
        print("spy diag done", road, r["final"], flush=True)
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"))
    print("ALL SAVED")

if __name__ == "__main__":
    main()
