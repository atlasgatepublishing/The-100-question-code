#!/usr/bin/env python3
"""
V13 "BEST RULES" — A-1 SAME-MONTH SEASONALITY (Heston & Sadka 2008)
Terry's AI stock app. Simulation only. No broker orders were placed.

Engine: the v12 holdings-sweep engine (itself the v7/v10 engine verbatim),
copied into this folder with exactly three mechanical changes, all driven
by globals set in main_v13: (1) POSITIVE_FILTER — hold only names whose
same-month mean is > 0; (2) DISABLE_FLOOR — the -15% floor/halt block is
inert; (3) TOPN is a parameter. The frozen design is BEST-RULES-SPEC.md:
semiannual decisions (first trading day of Jan/Jul), top-3 equal-weight,
positive-signal filter, NO floor/halt/restart, honest 30-name pond,
next-open execution, costs 0.10%/side + $0.01/share on sells.
The v9 episode wrapper below is retained ONLY to re-run the published
semiannual count-5 form for confirmation folds.
Original engine provenance: backtests/v7/gap-a1-seasonality/ (decision
dates generated per CADENCE; data read read-only from the v7 cache).

CADENCE TREATMENT (stated before any run — the frozen reading for v10):
  The signal is INHERENTLY monthly: at any decision date falling in
  calendar month (Y, m), the ranking is the Heston-Sadka signal for
  month m = mean of that name's month-m returns over years Y-10..Y-1
  (annual lags only, >= 6 observations). Cadence governs ONLY when that
  ranking is evaluated and the top-5 rotated in / re-equalized:
    daily      = every trading day is a decision date
    weekly     = first trading day of each week
    biweekly   = first trading day of every second week (anchored on the
                 first weekly date of the window)
    monthly    = first trading day of each month  (NATIVE — original form)
    quarterly  = first trading day of each calendar quarter
    semi-annual= first trading day of each half-year
    annual     = first trading day of each year
  Within one calendar month the ranking cannot change (its inputs are
  completed months only), so sub-monthly cadences only re-equalize
  weights more often. Super-monthly cadences only ever sample the
  rankings of their decision months (quarterly: Jan/Apr/Jul/Oct;
  semi-annual: Jan/Jul; annual: January only) and hold those picks past
  their strong month — mechanically expressible, so they are run, with
  that degradation documented. No cadence is N/A for this strategy.
  Targets execute at the NEXT session's open (original R3), at every
  cadence. Costs 0.10%/side + $0.01/share on sells, unchanged.
  Placebos: 5 names drawn uniformly at random (seeds 1..20) from the
  same eligible pool at each decision date, same engine/costs/floor;
  one Random(seed) object flows through both v9 episodes (original R6).

INTEGRITY: before the sweep, the ORIGINAL form (monthly decisions,
plain $85 floor, NO restart — the v7 engine as published) is re-run on
CONT 2019-01-02->2026-11-20 and VAL 2023-01-03->2026-11-20 and must
reproduce CONT $406.91 (costs $39.79, 840 orders, placebos beaten 19/20)
and VAL $278.12 (costs $18.25, 417 orders, placebos beaten 18/20).

SWEEP ROAD: DECADE 2016-11-21 -> 2026-11-20, $100 start, v9 protection.
Data: read-only shared cache backtests/v7/gap-a1-seasonality/data/
(Yahoo adjclose daily bars 2008->2026 for the 30-name pond + SPY).
Only the 31 cached payloads this strategy needs are loaded.
"""
import json, math, os, random, time
import datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
ORIG_DATA = os.path.expanduser(
    "~/workspace/stock-app/backtests/v7/gap-a1-seasonality/data")

UNIVERSE = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "BRK-B", "JPM", "XOM",
            "JNJ", "PG", "V", "WMT", "HD", "BAC", "CVX", "PFE", "VZ", "T",
            "DIS", "NFLX", "INTC", "CSCO", "GE", "IBM", "MMM", "UNH", "MA",
            "KO", "PEP", "WFC"]
PLACEBO_SEEDS = list(range(1, 21))
TOPN = 5  # holdings count; None = ALL-ELIGIBLE
POSITIVE_FILTER = False  # v13: hold only names with same-month mean > 0
DISABLE_FLOOR = False    # v13: no floor / no halt when True
START_CASH = 100.0
FLOOR0 = 85.0
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]

# ------------------------------------------------------------- data (v7 cache)
def get_prices(ticker):
    path = os.path.join(ORIG_DATA, f"px_{ticker}.json")
    with open(path, "rb") as f:
        blob = f.read()
    j = json.loads(blob)
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, c = q["open"][i], q["close"][i]
        if c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        bars.append({"d": d, "o": (o * ratio if o else a), "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars

class PriceBook:
    def __init__(self, bars_by_ticker):
        self.bars = bars_by_ticker
        self.dates = sorted({b["d"] for bl in bars_by_ticker.values() for b in bl})
        self.idx = {t: {b["d"]: b for b in bl} for t, bl in bars_by_ticker.items()}
        # per-ticker sorted date lists for bisect lookups (speed only; the
        # v7 engine's linear scan returns exactly the same bar)
        import bisect as _bisect
        self._bisect = _bisect
        self._dlists = {t: [b["d"] for b in bl] for t, bl in bars_by_ticker.items()}

    def bar(self, t, d):
        return self.idx.get(t, {}).get(d)

    def close_on_or_before(self, t, d):
        dl = self._dlists.get(t)
        if not dl:
            return None
        i = self._bisect.bisect_right(dl, d) - 1
        if i < 0:
            return None
        return self.bars[t][i]["c"]

# ------------------------------------------------------------- seasonal signal
def month_end_closes(bars):
    out = {}
    for b in bars:
        out[(int(b["d"][:4]), int(b["d"][5:7]))] = b["c"]
    return out

def monthly_returns(bars):
    me = month_end_closes(bars)
    out = {}
    for (y, m), c in sorted(me.items()):
        py, pm = (y - 1, 12) if m == 1 else (y, m - 1)
        prev = me.get((py, pm))
        if prev:
            out[(y, m)] = c / prev - 1.0
    return out

def seasonal_signal(mrets, year, month):
    vals = [mrets[(y, month)] for y in range(year - 10, year)
            if (y, month) in mrets]
    if len(vals) < 6:
        return None, len(vals)
    return sum(vals) / len(vals), len(vals)

# ------------------------------------------------------------- cadence dates
def decision_dates(pb, start, end, cadence):
    days = [d for d in pb.dates if start <= d <= end]
    if cadence == "daily":
        return days
    out, seen = [], set()
    if cadence in ("weekly", "biweekly"):
        weekly = []
        for d in days:
            iso = dt.date.fromisoformat(d).isocalendar()
            key = (iso[0], iso[1])
            if key not in seen:
                seen.add(key)
                weekly.append(d)
        if cadence == "weekly":
            return weekly
        return weekly[::2]
    for d in days:
        y, m = d[:4], d[5:7]
        if cadence == "monthly":
            key = (y, m)
        elif cadence == "quarterly":
            key = (y, (int(m) - 1) // 3)
        elif cadence == "semiannual":
            key = (y, (int(m) - 1) // 6)
        elif cadence == "annual":
            key = (y,)
        else:
            raise ValueError(cadence)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out

# ------------------------------------------------------------------ engine
# run_pot is the v7 engine verbatim except sel_dates come from the cadence.
def run_pot(pb, mrets_by, start, end, sel_dates, placebo_rng=None, label="",
            quiet=True, collect_spread=False):
    cash = START_CASH
    positions = {}
    trades = []
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []
    picks_log = []
    spread_months = []
    sel_set = set(sel_dates)
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
    pending = None
    pending_meta = None

    def portfolio_close(d):
        v = cash
        for t, sh in positions.items():
            c = pb.close_on_or_before(t, d)
            if c:
                v += sh * c
        return v

    def execute_rebalance(d, targets):
        nonlocal cash, total_costs
        cost = 0.0
        opens = {}
        for t in set(list(positions) + list(targets)):
            b = pb.bar(t, d)
            if b:
                opens[t] = b["o"]
        for t in list(positions):
            if t not in opens:
                continue
            cur_val = positions[t] * opens[t]
            tgt = targets.get(t, 0.0)
            if cur_val > tgt + 0.005:
                sell_val = cur_val - tgt
                sh = sell_val / opens[t]
                c = sell_val * 0.001 + 0.01
                cash += sell_val - c
                cost += c
                positions[t] -= sh
                trades.append((d, t, "SELL", sh, opens[t], sell_val, c))
                if positions[t] < 1e-9:
                    del positions[t]
        for t, tgt in targets.items():
            if t not in opens:
                continue
            cur_val = positions.get(t, 0.0) * opens[t]
            buy_val = tgt - cur_val
            if buy_val > 0.005:
                buy_val = min(buy_val, cash / 1.001)
                if buy_val <= 0.005:
                    continue
                sh = buy_val / opens[t]
                c = buy_val * 0.001
                cash -= buy_val + c
                cost += c
                positions[t] = positions.get(t, 0.0) + sh
                trades.append((d, t, "BUY", sh, opens[t], buy_val, c))
        total_costs += cost
        return cost

    for di, d in enumerate(days):
        if pending is not None:
            execute_rebalance(d, pending)
            if collect_spread and pending_meta is not None:
                spread_months.append((pending_meta[0], pending_meta[1],
                                      pending_meta[2], d))
            pending = None
            pending_meta = None
        if d in sel_set:
            y, m = int(d[:4]), int(d[5:7])
            signals = {}
            for t in UNIVERSE:
                s, _n = seasonal_signal(mrets_by[t], y, m)
                if s is not None:
                    signals[t] = s
            if len(signals) >= 5:
                ranked = sorted(signals, key=lambda t: (-signals[t], t))
                pool = [t for t in ranked if signals[t] > 0] if POSITIVE_FILTER else ranked
                n_eff = len(pool) if TOPN is None else min(TOPN, len(pool))
                top5 = pool[:n_eff]
                bot5 = ranked[-5:]
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(signals), n_eff)
                else:
                    picks = top5
                picks_log.append({"date": d, "pool": len(signals),
                                  "picks": list(picks),
                                  "signals": {t: round(signals[t], 6) for t in picks}})
                if len(picks) == 0:
                    pending = {}
                else:
                    pv = portfolio_close(d)
                    each = pv / len(picks)
                    pending = {t: each for t in picks}
                pending_meta = (d, top5, bot5)
        v = portfolio_close(d)
        curve.append((d, v))
        if not DISABLE_FLOOR and v <= FLOOR0 and di < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": FLOOR0}
            nd = days[di + 1]
            for t in list(positions):
                b = pb.bar(t, nd)
                if b:
                    val = positions[t] * b["o"]
                    c = val * 0.001 + 0.01
                    cash += val - c
                    total_costs += c
                    trades.append((nd, t, "SELL-HALT", positions[t], b["o"], val, c))
            positions = {}
            return {"label": label, "final": cash, "costs": total_costs,
                    "trades": trades, "halted": halted, "end": nd,
                    "halt_info": halt_info, "curve": curve,
                    "picks_log": picks_log, "spread_months": spread_months}
    last = days[-1]
    for t in list(positions):
        c_ = pb.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_
            cst = val * 0.001 + 0.01
            cash += val - cst
            total_costs += cst
            trades.append((last, t, "SELL-END", positions[t], c_, val, cst))
    return {"label": label, "final": cash, "costs": total_costs,
            "trades": trades, "halted": None, "end": last,
            "halt_info": None, "curve": curve,
            "picks_log": picks_log, "spread_months": spread_months}

def spy_net(pb, start, end, start_cash=100.0):
    days = [d for d in pb.dates if start <= d <= end]
    first, last = days[0], days[-1]
    o = pb.bar("SPY", first)["o"]
    sh = (start_cash / 1.001) / o
    buy_cost = start_cash - sh * o
    c_ = pb.close_on_or_before("SPY", last)
    val = sh * c_
    sell_cost = val * 0.001 + 0.01
    return val - sell_cost, buy_cost + sell_cost

# ------------------------------------------------------------- v9 wrapper
def run_pot_v9(pb, mrets_by, start, end, cadence, placebo_rng=None, label=""):
    global START_CASH, FLOOR0
    sel_dates = decision_dates(pb, start, end, cadence)
    START_CASH, FLOOR0 = 100.0, 85.0
    ep1 = run_pot(pb, mrets_by, start, end, sel_dates,
                  placebo_rng=placebo_rng, label=label + " EP1")
    base = {"label": label, "episodes": 1,
            "ep1_halted": ep1["halted"], "ep1_end": ep1["end"],
            "ep1_final": round(ep1["final"], 2),
            "costs": ep1["costs"], "orders": len(ep1["trades"]),
            "curve": list(ep1["curve"]),
            "restart": None, "ep2_halted": None, "halts": 0,
            "halt_dates": []}
    if not ep1["halted"]:
        base.update({"final": ep1["final"], "status": "no_halt"})
        return base
    base["halts"] = 1
    base["halt_dates"].append(ep1["halted"])
    liq_date = ep1["end"]
    cash1 = ep1["final"]
    base["curve"].append((liq_date, cash1))
    eligible = (dt.date.fromisoformat(liq_date) + dt.timedelta(days=90)).isoformat()
    restart = next((d for d in sel_dates if d >= eligible), None)
    if restart is None:
        base.update({"final": cash1, "status": "halted_ep1_no_restart_in_window"})
        return base
    floor2 = 0.85 * cash1
    START_CASH, FLOOR0 = cash1, floor2
    try:
        ep2 = run_pot(pb, mrets_by, restart, end, sel_dates,
                      placebo_rng=placebo_rng, label=label + " EP2")
    finally:
        START_CASH, FLOOR0 = 100.0, 85.0
    base["curve"].extend(ep2["curve"])
    if ep2["halted"]:
        base["halts"] = 2
        base["halt_dates"].append(ep2["halted"])
        base["curve"].append((ep2["end"], ep2["final"]))
    base.update({"episodes": 2, "final": ep2["final"],
                 "costs": ep1["costs"] + ep2["costs"],
                 "orders": len(ep1["trades"]) + len(ep2["trades"]),
                 "ep2_halted": ep2["halted"],
                 "status": "halted_ep2_run_ends" if ep2["halted"] else "restarted_completed",
                 "restart": {"liquidation_date": liq_date,
                             "cash_at_halt": round(cash1, 2),
                             "eligible_from": eligible,
                             "restart_decision_date": restart,
                             "restart_balance": round(cash1, 2),
                             "episode2_floor": round(floor2, 2)}})
    return base

# ------------------------------------------------------------- stats helpers
def max_dd(curve):
    peak, mdd = -1.0, 0.0
    for _d, v in curve:
        if v > peak:
            peak = v
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak)
    return round(mdd * 100, 2)

def cagr(final, start, end):
    days = (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days
    years = days / 365.25
    if final <= 0 or years <= 0:
        return None
    return round(((final / 100.0) ** (1.0 / years) - 1.0) * 100, 2)


# ------------------------------------------------------------- v13 driver
import statistics

def period_distribution(curve, cadence):
    """Per-period record at the form's tempo, from the equity curve
    (verbatim from the v12 sweep). Period = calendar half-year here."""
    def key(d):
        y, m = int(d[:4]), int(d[5:7])
        return (y, m) if cadence == "monthly" else (y, (m - 1) // 6)
    ends, order = {}, []
    for d, v in curve:
        k = key(d)
        if k not in ends:
            order.append(k)
        ends[k] = v
    vals = [ends[k] for k in order]
    rets, prev = [], 100.0
    for v in vals:
        rets.append(v / prev - 1.0)
        prev = v
    if not rets:
        return None
    prof = sum(1 for r in rets if r > 0)
    longest_loss, cur = 0, 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0
        longest_loss = max(longest_loss, cur)
    peak, since_high, longest_gap = -1.0, 0, 0
    for v in vals:
        if v >= peak:
            peak, since_high = v, 0
        else:
            since_high += 1
            longest_gap = max(longest_gap, since_high)
    return {"periods": len(rets),
            "pct_profitable": round(100.0 * prof / len(rets), 1),
            "median_period_pct": round(statistics.median(rets) * 100, 2),
            "best_period_pct": round(max(rets) * 100, 2),
            "worst_period_pct": round(min(rets) * 100, 2),
            "longest_losing_run_periods": longest_loss,
            "longest_stretch_between_new_highs_periods": longest_gap,
            "average_period_pct_secondary": round(statistics.mean(rets) * 100, 2)}

ROADS = [("DECADE", "2016-11-21", "2026-11-20"),
         ("CONT", "2019-01-02", "2026-11-20"),
         ("VAL", "2023-01-03", "2026-11-20")]
CHAMPIONS = {"LONG": 1415.62, "CONT": 544.47, "VAL": 288.05, "DECADE": 667.35}
PUBLISHED_SEMIANNUAL_N5 = {"DECADE": 760.50, "CONT": 555.69, "VAL": 398.75}
PUBLISHED_MONTHLY_N5 = {"DECADE": 591.60, "CONT": 406.91, "VAL": 278.12}

def set_form(topn, pos_filter, no_floor):
    global TOPN, POSITIVE_FILTER, DISABLE_FLOOR
    TOPN, POSITIVE_FILTER, DISABLE_FLOOR = topn, pos_filter, no_floor

def run_my_form(pb, mrets_by, start, end, rng=None, label=""):
    sel = decision_dates(pb, start, end, "semiannual")
    r = run_pot(pb, mrets_by, start, end, sel, placebo_rng=rng, label=label)
    return {"final": r["final"], "costs": r["costs"],
            "orders": len(r["trades"]), "halts": 1 if r["halted"] else 0,
            "curve": r["curve"], "picks_log": r["picks_log"],
            "status": "halted" if r["halted"] else "no_halt"}

def main_v13():
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = get_prices(t)
    pb = PriceBook(bars)
    mrets_by = {t: monthly_returns(bars[t]) for t in UNIVERSE}
    print(f"loaded {len(bars)} tickers; dates {pb.dates[0]}..{pb.dates[-1]}", flush=True)

    # INTEGRITY: original published form (monthly, count 5, plain $85 floor,
    # no filter) must reproduce the v7 record exactly before anything runs.
    set_form(5, False, False)
    integ = {}
    for wname, ws, we in [("CONT", "2019-01-02", "2026-11-20"),
                          ("VAL", "2023-01-03", "2026-11-20")]:
        sel = decision_dates(pb, ws, we, "monthly")
        r = run_pot(pb, mrets_by, ws, we, sel, label=wname + " INTEGRITY")
        finals = []
        for seed in PLACEBO_SEEDS:
            pr = run_pot(pb, mrets_by, ws, we, sel,
                         placebo_rng=random.Random(seed), label="P")
            finals.append(round(pr["final"], 2))
        beats = sum(1 for v in finals if r["final"] > v)
        integ[wname] = {"final": round(r["final"], 2), "costs": round(r["costs"], 2),
                        "orders": len(r["trades"]), "placebo_beaten": beats}
        print(f"INTEGRITY {wname}: ${r['final']:.2f} costs ${r['costs']:.2f} "
              f"orders {len(r['trades'])} beats {beats}/20", flush=True)
    integ_ok = (integ["CONT"]["final"] == 406.91 and integ["VAL"]["final"] == 278.12
                and integ["CONT"]["costs"] == 39.79 and integ["VAL"]["costs"] == 18.25
                and integ["CONT"]["orders"] == 840 and integ["VAL"]["orders"] == 417
                and integ["CONT"]["placebo_beaten"] == 19
                and integ["VAL"]["placebo_beaten"] == 18)
    print("INTEGRITY STATUS:", "reproduced" if integ_ok else "FAILED", flush=True)
    if not integ_ok:
        raise SystemExit("integrity gate failed — aborting")

    spy = {rn: round(spy_net(pb, s, e)[0], 2) for rn, s, e in ROADS}
    print("SPY:", spy, flush=True)

    # MY FORM (frozen spec): semiannual, top-3, positive filter, NO floor.
    set_form(3, True, True)
    cells, curves, dists = {}, {}, {}
    for rname, rs, re_ in ROADS:
        r = run_my_form(pb, mrets_by, rs, re_, label=f"V13 {rname}")
        finals = []
        for seed in PLACEBO_SEEDS:
            pr = run_my_form(pb, mrets_by, rs, re_,
                             rng=random.Random(seed), label="P")
            finals.append(round(pr["final"], 2))
        beats = sum(1 for v in finals if r["final"] > v)
        cells[rname] = {"final": round(r["final"], 2),
                        "cagr_pct": cagr(r["final"], rs, re_),
                        "max_dd_pct": max_dd(r["curve"]),
                        "costs": round(r["costs"], 2),
                        "orders": r["orders"], "halts": r["halts"],
                        "placebo_beaten": beats, "placebo_finals": finals,
                        "picks_log": r["picks_log"]}
        curves[rname] = r["curve"]
        dists[rname] = period_distribution(r["curve"], "semiannual")
        print(f"V13 {rname}: ${r['final']:.2f} DD {max_dd(r['curve'])} "
              f"costs ${r['costs']:.2f} orders {r['orders']} beats {beats}/20",
              flush=True)

    # CONFIRMATION (Terry's rule): if my form beats a champion on any road,
    # re-run on different years — fresh $100 yearly folds 2017..2026 — my
    # form vs the published semiannual count-5 v9 form, same fold windows
    # as the v12 confirmation.
    confirm = None
    beat_roads = [r for r, _, _ in ROADS if cells[r]["final"] > CHAMPIONS[r]]
    print("champion roads beaten:", beat_roads, flush=True)
    if beat_roads:
        foldrec = {}
        for form_key in ["v13_best", "published_semiannual_n5_v9"]:
            tot, yrs = 1.0, {}
            for yr in range(2017, 2027):
                s = f"{yr}-01-01"
                e = f"{yr}-12-31" if yr < 2026 else "2026-11-20"
                if form_key == "v13_best":
                    set_form(3, True, True)
                    fr = run_my_form(pb, mrets_by, s, e, label="FOLD")
                    ffinal = fr["final"]
                else:
                    set_form(5, False, False)
                    fr = run_pot_v9(pb, mrets_by, s, e, "semiannual", label="FOLD PUB")
                    ffinal = fr["final"]
                yrs[str(yr)] = round(ffinal, 2)
                tot *= ffinal / 100.0
            foldrec[form_key] = {"folds": yrs, "fold_compounded": round(tot * 100, 2)}
        wins = sum(1 for yr in foldrec["v13_best"]["folds"]
                   if foldrec["v13_best"]["folds"][yr]
                   > foldrec["published_semiannual_n5_v9"]["folds"][yr])
        foldrec["fold_years_won_vs_published"] = wins
        foldrec["confirmed"] = (foldrec["v13_best"]["fold_compounded"]
                                > foldrec["published_semiannual_n5_v9"]["fold_compounded"]
                                and wins >= 6)
        confirm = foldrec
        print(f"CONFIRM: folds won {wins}/10, compounded "
              f"${foldrec['v13_best']['fold_compounded']} vs published "
              f"${foldrec['published_semiannual_n5_v9']['fold_compounded']} -> "
              f"{'CONFIRMED' if foldrec['confirmed'] else 'NOT CONFIRMED'}", flush=True)
    set_form(3, True, True)

    out = {"family": "gap-a1-seasonality (Heston & Sadka same-month seasonality)",
           "program": "v13-best-rules",
           "my_form": "semiannual decisions (first trading day of Jan/Jul); top-3 "
                      "equal-weight; positive-signal filter (same-month mean > 0); "
                      "NO floor/halt/sit-out/restart; honest 30-name pond; "
                      "next-open execution",
           "costs": "0.10%/side + $0.01/share on sells",
           "roads": {r: [s, e] for r, s, e in ROADS},
           "long_road": "NOT RUN — no honest 2010 road exists: signal needs >=6 "
                        "same-month returns from prior 10y; price data begins "
                        "2008-01; eligible pool first reaches 29/30 in Jul 2014.",
           "spy_finals": spy,
           "champions_vm": CHAMPIONS,
           "published_semiannual_n5_v9_finals": PUBLISHED_SEMIANNUAL_N5,
           "published_monthly_n5_finals": PUBLISHED_MONTHLY_N5,
           "integrity": {"status": "reproduced" if integ_ok else "FAILED",
                         "cells": integ},
           "cells": cells,
           "period_distributions": dists,
           "champion_roads_beaten": beat_roads,
           "confirmation_folds": confirm,
           "curves": {r: [[d, round(v, 4)] for d, v in c]
                      for r, c in curves.items()}}
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE", flush=True)

if __name__ == "__main__":
    main_v13()
