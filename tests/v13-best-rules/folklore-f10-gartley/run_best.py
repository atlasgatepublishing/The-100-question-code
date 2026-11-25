#!/usr/bin/env python3
"""
V13 BEST-RULES — FOLKLORE F-10 HARMONIC GARTLEY.
Frozen in BEST-RULES-SPEC.md in this folder BEFORE this run. Simulation only.

What changed vs the v11 native run (each change reasoned in the spec):
  - Swings: ZigZag on bar EXTREMES (high/low), 5% reversal
    (v11: closes, 8%). Pivot known only from its confirmation bar.
  - B band: retracement of XA in [0.55, 0.68] (v11: 0.618 +/- 3 pts).
    C [0.382, 0.886] of AB and D at 0.786 of XA unchanged.
  - Armed life: until trigger / close below X / close above A /
    126 trading days from C's confirmation (v11: died at next pivot).
    Multiple patterns per name may be armed at once.
  - Universe: BROAD154 (all long-hold-cache names, survivorship
    named in the spec) primary; POND30 identical rules alongside.
  - Sizing: max 4 concurrent x 25% slices (v11: 5 x 20%).
  - Exits: Carney two targets (half at 38.2% of AD, rest at 61.8%),
    stop on close below X — plus a disclosed 252-trading-day time
    exit (spec addition; Carney publishes none).
  - No pot floor. Costs 0.10%/side + $0.01/sell. $100 pots.

Data: ~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_<T>.json
(read-only), champion bar construction (open/high/low scaled by
adjclose/close, close = adjclose). Roads per spec; warm-up from 2008,
only in-road triggers trade. Placebos: v11 design (same trigger dates
and slice mechanics, seeded random unheld name, exit geometry
translated to % of fill), 20 seeds.
"""
import json
import os
import random
import statistics
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")

POND30 = ["AAPL", "MSFT", "AMZN", "GOOG", "META", "BRK-B", "JPM", "XOM",
          "JNJ", "PG", "V", "WMT", "HD", "BAC", "CVX", "PFE", "VZ", "T",
          "DIS", "NFLX", "INTC", "CSCO", "GE", "IBM", "MMM", "UNH", "MA",
          "KO", "PEP", "WFC"]
PLACEBO_SEEDS = list(range(1, 21))

START_CASH = 100.0
COST_RATE = 0.001
SELL_FEE = 0.01

# ---- V13 best-rules parameters (frozen in BEST-RULES-SPEC.md) ----
ZZ_THRESHOLD = 0.05             # ZigZag reversal on bar extremes
B_LO, B_HI = 0.55, 0.68         # B retrace of XA (Carney center 0.618)
C_LO, C_HI = 0.382, 0.886       # C retrace of AB (published, unchanged)
D_FRAC = 0.786                  # D at 78.6% retracement of XA (unchanged)
TARGET_FRAC = 0.382             # Carney target 1 (sell half)
TARGET2_FRAC = 0.618            # Carney target 2 (sell rest)
ARM_MAX_DAYS = 126              # armed-pattern freshness limit (name bars)
MAX_HOLD_DAYS = 252             # disclosed time exit (name bars)
MAX_POSITIONS = 4
SLICES = 4                      # 25% slices

END = "2026-11-20"
ROADS = {"LONG": ("2010-01-04", END), "DECADE": ("2016-11-21", END),
         "CONT": ("2019-01-02", END), "VAL": ("2023-01-03", END),
         "CONFIRM": ("2010-01-04", "2016-11-18")}
CHAMPION = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPY_PUBLISHED = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
V11_POND = {"DECADE": 102.15, "CONT": 101.44, "VAL": 100.00}


# ---------------------------------------------------------------- data
def load_bars(sym):
    j = json.load(open(os.path.join(DATA, f"pxfull_{sym}.json")))
    r = j["chart"]["result"][0]
    ts = r["timestamp"]
    q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i, t in enumerate(ts):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if None in (o, h, l, c) or adj[i] is None:
            continue
        ratio = adj[i] / c if c else 1.0
        bars.append({"d": time.strftime("%Y-%m-%d", time.gmtime(t)),
                     "o": o * ratio, "h": h * ratio, "l": l * ratio,
                     "c": adj[i]})
    bars.sort(key=lambda b: b["d"])
    return bars


# ------------------------------------------------------- ZigZag + F-10
def zigzag_pivots(bars, threshold=ZZ_THRESHOLD):
    """ZigZag on bar extremes. A high pivot is the highest high since
    the last low pivot, confirmed on the first bar whose low falls
    >= threshold below it; lows mirror. Returns confirmed pivots only:
    {kind, idx (extreme bar), date, price, confirm_idx, confirm_date}.
    At the confirmation bar the confirming bar's opposite extreme is
    exactly the running extreme of the new leg (any earlier bar of the
    leg was, by construction, short of the threshold), so the simple
    streaming handoff is exact."""
    pivots = []
    if not bars:
        return pivots
    mode = None            # None / 'seek_high' / 'seek_low'
    hi, hi_i = bars[0]["h"], 0
    lo, lo_i = bars[0]["l"], 0
    ext, ext_i = None, None
    for i in range(1, len(bars)):
        h, l = bars[i]["h"], bars[i]["l"]
        if mode is None:
            if h > hi:
                hi, hi_i = h, i
            if l < lo:
                lo, lo_i = l, i
            if l <= hi * (1 - threshold):
                pivots.append({"kind": "H", "idx": hi_i,
                               "date": bars[hi_i]["d"], "price": hi,
                               "confirm_idx": i, "confirm_date": bars[i]["d"]})
                mode, ext, ext_i = "seek_low", l, i
            elif h >= lo * (1 + threshold):
                pivots.append({"kind": "L", "idx": lo_i,
                               "date": bars[lo_i]["d"], "price": lo,
                               "confirm_idx": i, "confirm_date": bars[i]["d"]})
                mode, ext, ext_i = "seek_high", h, i
        elif mode == "seek_high":
            if h > ext:
                ext, ext_i = h, i
            elif l <= ext * (1 - threshold):
                pivots.append({"kind": "H", "idx": ext_i,
                               "date": bars[ext_i]["d"], "price": ext,
                               "confirm_idx": i, "confirm_date": bars[i]["d"]})
                mode, ext, ext_i = "seek_low", l, i
        else:  # seek_low
            if l < ext:
                ext, ext_i = l, i
            elif h >= ext * (1 + threshold):
                pivots.append({"kind": "L", "idx": ext_i,
                               "date": bars[ext_i]["d"], "price": ext,
                               "confirm_idx": i, "confirm_date": bars[i]["d"]})
                mode, ext, ext_i = "seek_high", h, i
    return pivots


def extract_triggers(ticker, bars):
    """Walk one name's full series once. On each pivot confirmation,
    test the last-4 confirmed pivots for a bullish Gartley (L,H,L,H);
    arm valid patterns; then run every armed pattern against today's
    close (expiry -> invalidation -> supersession -> trigger, in that
    order). Point-in-time throughout. Returns (events, census)."""
    closes = [b["c"] for b in bars]
    pivots = zigzag_pivots(bars)
    piv_by_confirm = {}
    for pv in pivots:
        piv_by_confirm.setdefault(pv["confirm_idx"], []).append(pv)

    census = {"pivots": len(pivots), "armed": 0, "triggered": 0,
              "expired": 0, "invalid_armed": 0, "superseded": 0,
              "invalid_prearm": 0}
    events = []
    confirmed = []
    armed = []

    for i, b in enumerate(bars):
        for pv in piv_by_confirm.get(i, []):
            confirmed.append(pv)
            if len(confirmed) >= 4:
                x, a, bb, c = confirmed[-4:]
                if (x["kind"], a["kind"], bb["kind"], c["kind"]) == \
                        ("L", "H", "L", "H"):
                    xa = a["price"] - x["price"]
                    if xa > 0:
                        b_ratio = (a["price"] - bb["price"]) / xa
                        ab = a["price"] - bb["price"]
                        c_ratio = (c["price"] - bb["price"]) / ab if ab > 0 else None
                        if (B_LO <= b_ratio <= B_HI
                                and c_ratio is not None
                                and C_LO <= c_ratio <= C_HI):
                            if any(closes[j] < x["price"]
                                   for j in range(x["idx"], i + 1)):
                                census["invalid_prearm"] += 1
                            else:
                                d_level = a["price"] - D_FRAC * xa
                                armed.append({
                                    "ticker": ticker,
                                    "x_date": x["date"], "x": x["price"],
                                    "a_date": a["date"], "a": a["price"],
                                    "b_date": bb["date"], "b": bb["price"],
                                    "c_date": c["date"], "c": c["price"],
                                    "b_ratio": round(b_ratio, 4),
                                    "c_ratio": round(c_ratio, 4),
                                    "d_level": d_level,
                                    "target": d_level + TARGET_FRAC * (a["price"] - d_level),
                                    "target2": d_level + TARGET2_FRAC * (a["price"] - d_level),
                                    "arm_date": b["d"], "arm_idx": i,
                                })
                                census["armed"] += 1
        if armed:
            still = []
            for pat in armed:
                if i - pat["arm_idx"] > ARM_MAX_DAYS:
                    census["expired"] += 1
                elif b["c"] < pat["x"]:
                    census["invalid_armed"] += 1
                elif b["c"] > pat["a"]:
                    census["superseded"] += 1
                elif b["c"] <= pat["d_level"]:
                    ev = dict(pat)
                    ev["trigger_date"] = b["d"]
                    ev["trigger_close"] = b["c"]
                    events.append(ev)
                    census["triggered"] += 1
                else:
                    still.append(pat)
            armed = still
    return events, census


# ---------------------------------------------------------------- engine
def run_pot(bars_by, idx_by, calendar, events_by_date, universe,
            placebo_rng=None):
    """Event engine (v11 chassis, v13 sizing/exits). If placebo_rng is
    given, entries buy a random unheld universe name with the signal
    pattern's exit geometry translated into % of the fill price."""
    cash = START_CASH
    positions = {}
    pending_entries = []
    pending_exits = {}
    pending_partials = set()
    trades = []
    orders = 0
    total_costs = 0.0
    curve = []
    skips = []
    days_invested = 0

    def close_on_or_before(t, d):
        bars = bars_by[t]
        j = idx_by[t].get(d)
        if j is None:
            lo, hi = 0, len(bars) - 1
            best = None
            while lo <= hi:
                mid = (lo + hi) // 2
                if bars[mid]["d"] <= d:
                    best = mid
                    lo = mid + 1
                else:
                    hi = mid - 1
            return bars[best]["c"] if best is not None else None
        return bars[j]["c"]

    def pot_value(d):
        v = cash
        for t, pos in positions.items():
            c = close_on_or_before(t, d)
            if c:
                v += pos["shares"] * c
        return v

    def sell_position(t, price, date, reason):
        nonlocal cash, total_costs, orders
        pos = positions.pop(t)
        val = pos["shares"] * price
        cost = val * COST_RATE + SELL_FEE
        total_costs += cost
        orders += 1
        proceeds = val - cost
        cash += proceeds
        trades.append({
            "ticker": t,
            "entry_date": pos["entry_date"], "entry_price": round(pos["entry_price"], 2),
            "exit_date": date, "exit_price": round(price, 2),
            "pnl": round(proceeds - pos["cost_basis"], 2),
            "ret_pct": round((proceeds / pos["cost_basis"] - 1.0) * 100, 2),
            "exit_reason": reason,
            "pattern": pos.get("pattern"),
        })

    def sell_partial(t, price, date):
        nonlocal cash, total_costs, orders
        pos = positions[t]
        half = pos["shares"] / 2.0
        val = half * price
        cost = val * COST_RATE + SELL_FEE
        total_costs += cost
        orders += 1
        proceeds = val - cost
        cash += proceeds
        basis_removed = pos["cost_basis"] * 0.5
        trades.append({
            "ticker": t,
            "entry_date": pos["entry_date"], "entry_price": round(pos["entry_price"], 2),
            "exit_date": date, "exit_price": round(price, 2),
            "pnl": round(proceeds - basis_removed, 2),
            "ret_pct": round((proceeds / basis_removed - 1.0) * 100, 2),
            "exit_reason": "target1_38.2_partial",
            "pattern": pos.get("pattern"),
        })
        pos["shares"] -= half
        pos["cost_basis"] -= basis_removed
        pos["partial_done"] = True

    last_day = calendar[-1] if calendar else None
    for d in calendar:
        # ---- 1. executions at today's opens
        for t in list(pending_partials):
            if t in positions:
                j = idx_by[t].get(d)
                if j is not None:
                    sell_partial(t, bars_by[t][j]["o"], d)
                    pending_partials.discard(t)
        for t in list(pending_exits):
            if t in positions:
                j = idx_by[t].get(d)
                if j is not None:
                    sell_position(t, bars_by[t][j]["o"], d, pending_exits.pop(t))
        still_pending = []
        for od in pending_entries:
            t = od["ticker"]
            j = idx_by[t].get(d)
            if j is None:
                still_pending.append(od)
                continue
            if t in positions:
                skips.append({"date": od["signal_date"], "ticker": od["signal_ticker"],
                              "reason": "name_held_at_execution"})
                continue
            px = bars_by[t][j]["o"]
            buy_val = min(od["slice"], cash / (1.0 + COST_RATE))
            if buy_val <= 0.005:
                skips.append({"date": od["signal_date"], "ticker": od["signal_ticker"],
                              "reason": "no_cash"})
                continue
            cost = buy_val * COST_RATE
            total_costs += cost
            orders += 1
            cash -= buy_val + cost
            if od.get("pct_up") is not None:   # placebo: translate geometry
                target = px * (1.0 + od["pct_up"])
                target2 = px * (1.0 + od["pct_up2"])
                stop = px * (1.0 - od["pct_dn"])
            else:
                target, stop = od["target"], od["stop"]
                target2 = od["target2"]
            positions[t] = {
                "shares": buy_val / px, "entry_date": d,
                "entry_price": px, "cost_basis": buy_val + cost,
                "target": target, "stop": stop, "target2": target2,
                "partial_done": False,
                "entry_idx": j, "pattern": od.get("pattern"),
            }
        pending_entries = still_pending

        # ---- 2. equity curve at today's close
        v = pot_value(d)
        curve.append((d, v))
        if positions:
            days_invested += 1
        if d == last_day:
            break

        # ---- 3. exit signals on today's closes
        for t, pos in list(positions.items()):
            j = idx_by[t].get(d)
            if j is None:
                continue
            c = bars_by[t][j]["c"]
            if c < pos["stop"]:
                pending_exits[t] = "invalid_below_x" if placebo_rng is None else "stop"
            elif not pos.get("partial_done") and c >= pos["target"]:
                pending_partials.add(t)
            elif pos.get("partial_done") and c >= pos["target2"]:
                pending_exits[t] = "target2_61.8"
            elif j - pos["entry_idx"] >= MAX_HOLD_DAYS:
                pending_exits[t] = "time_252d"

        # ---- 4. trigger events on today's close (alphabetical, spec)
        for ev in events_by_date.get(d, []):
            held_names = set(positions) | {od["ticker"] for od in pending_entries}
            if len(held_names) >= MAX_POSITIONS:
                skips.append({"date": d, "ticker": ev["ticker"], "reason": "book_full"})
                continue
            slice_val = v / SLICES
            if placebo_rng is not None:
                cands = sorted(t for t in universe if t not in held_names)
                if not cands:
                    skips.append({"date": d, "ticker": ev["ticker"], "reason": "no_candidate"})
                    continue
                pick = placebo_rng.choice(cands)
                pending_entries.append({
                    "ticker": pick, "signal_ticker": ev["ticker"],
                    "signal_date": d, "slice": slice_val,
                    "pct_up": (ev["target"] - ev["d_level"]) / ev["d_level"],
                    "pct_up2": (ev["target2"] - ev["d_level"]) / ev["d_level"],
                    "pct_dn": (ev["d_level"] - ev["x"]) / ev["d_level"],
                    "pattern": None,
                })
            else:
                if ev["ticker"] in held_names:
                    skips.append({"date": d, "ticker": ev["ticker"], "reason": "name_held"})
                    continue
                pending_entries.append({
                    "ticker": ev["ticker"], "signal_ticker": ev["ticker"],
                    "signal_date": d, "slice": slice_val,
                    "target": ev["target"], "target2": ev["target2"], "stop": ev["x"],
                    "pattern": {"x_date": ev["x_date"], "a_date": ev["a_date"],
                                "b_date": ev["b_date"], "c_date": ev["c_date"],
                                "b_ratio": ev["b_ratio"], "c_ratio": ev["c_ratio"],
                                "d_level": round(ev["d_level"], 2),
                                "arm_date": ev["arm_date"]},
                })

    # ---- end of window: liquidate at the final close
    if positions:
        for t in list(positions):
            c = close_on_or_before(t, last_day)
            sell_position(t, c, last_day, "window_end")
        if curve:
            curve[-1] = (last_day, cash)

    final = cash
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    worst, worst_d = float("inf"), None
    for d, val in curve:
        if val > peak:
            peak = val
        if peak > 0:
            dd = (peak - val) / peak
            if dd > maxdd:
                maxdd, maxdd_d = dd, d
        if val < worst:
            worst, worst_d = val, d
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    return {
        "final": round(final, 2),
        "return_pct": round(final / START_CASH * 100 - 100, 2),
        "orders": orders, "costs": round(total_costs, 2),
        "trades_n": len(trades), "trades": trades,
        "max_drawdown_pct": round(maxdd * 100, 2), "max_drawdown_date": maxdd_d,
        "worst_close": round(worst, 2) if worst != float("inf") else None,
        "worst_close_date": worst_d,
        "win_rate_pct": round(100.0 * len(wins) / len(trades), 1) if trades else None,
        "avg_win": round(sum(t["pnl"] for t in wins) / len(wins), 2) if wins else None,
        "avg_loss": round(sum(t["pnl"] for t in losses) / len(losses), 2) if losses else None,
        "expectancy_per_trade": round(sum(t["pnl"] for t in trades) / len(trades), 2) if trades else None,
        "time_in_market_pct": round(100.0 * days_invested / len(calendar), 1) if calendar else None,
        "skips": skips,
        "curve": curve,
    }


def buy_hold_spy(spy_bars, start, end):
    idx = [i for i, b in enumerate(spy_bars) if start <= b["d"] <= end]
    first, last = spy_bars[idx[0]], spy_bars[idx[-1]]
    shares = START_CASH / (first["o"] * (1.0 + COST_RATE))
    val = shares * last["c"]
    final = val - (val * COST_RATE + SELL_FEE)
    peak, maxdd = -1.0, 0.0
    for i in idx:
        v = shares * spy_bars[i]["c"]
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(final, 2),
            "return_pct": round(final / START_CASH * 100 - 100, 2),
            "max_drawdown_pct": round(maxdd * 100, 2)}


def period_distribution(curve):
    """Calendar-year returns from the daily equity curve (program
    per-period rule): median year, share positive, best/worst year,
    longest run of negative years, longest stretch (trading days)
    without a new equity high."""
    by_year = {}
    for d, v in curve:
        by_year.setdefault(d[:4], []).append(v)
    years = sorted(by_year)
    rets = {}
    prev = START_CASH
    for y in years:
        last = by_year[y][-1]
        rets[y] = round((last / prev - 1.0) * 100, 2) if prev else None
        prev = last
    vals = [rets[y] for y in years]
    med = round(statistics.median(vals), 2) if vals else None
    pos = sum(1 for v in vals if v > 0)
    streak = run = 0
    for v in vals:
        run = run + 1 if v <= 0 else 0
        streak = max(streak, run)
    peak = -1.0
    since = longest = 0
    for d, v in curve:
        if v >= peak:
            peak = v
            since = 0
        else:
            since += 1
            longest = max(longest, since)
    return {"year_returns_pct": {y: rets[y] for y in years},
            "median_year_pct": med,
            "share_years_positive_pct": round(100.0 * pos / len(vals), 1) if vals else None,
            "best_year_pct": max(vals) if vals else None,
            "worst_year_pct": min(vals) if vals else None,
            "longest_negative_year_streak": streak,
            "longest_days_without_new_high": longest}


def placebo_block(bars_by, idx_by, calendar, events_by_date, universe,
                  ranked_final):
    finals, rows = [], []
    for seed in PLACEBO_SEEDS:
        rng = random.Random(seed)
        pr = run_pot(bars_by, idx_by, calendar, events_by_date, universe,
                     placebo_rng=rng)
        finals.append(pr["final"])
        rows.append({"seed": seed, "final": pr["final"],
                     "trades": pr["trades_n"], "costs": pr["costs"]})
        print(f"  PLACEBO seed {seed:2d}: final=${pr['final']:,.2f} "
              f"trades={pr['trades_n']}", flush=True)
    srt = sorted(finals)
    below = sum(1 for f in finals if f < ranked_final)
    ties = sum(1 for f in finals if f == ranked_final)
    pctile = 100.0 * (below + 0.5 * ties) / len(finals)
    return {"median": round(statistics.median(finals), 2),
            "q1": round(srt[len(srt) // 4], 2), "q3": round(srt[3 * len(srt) // 4], 2),
            "best": round(srt[-1], 2), "worst": round(srt[0], 2),
            "mean": round(sum(finals) / len(finals), 2),
            "ranked_final": round(ranked_final, 2),
            "ranked_percentile": round(pctile, 1),
            "seeds_beaten": below, "rows": rows}


def summarize(r):
    return {k: r[k] for k in ("final", "return_pct", "orders", "costs",
                              "trades_n", "max_drawdown_pct",
                              "max_drawdown_date", "worst_close",
                              "worst_close_date", "win_rate_pct", "avg_win",
                              "avg_loss", "expectancy_per_trade",
                              "time_in_market_pct")}


def main():
    all_syms = sorted(f[7:-5] for f in os.listdir(DATA)
                      if f.startswith("pxfull_") and f.endswith(".json"))
    broad = [s for s in all_syms if s != "SPY"]
    universes = {"BROAD154": broad, "POND30": POND30}
    print(f"UNIVERSES: BROAD154={len(broad)} POND30={len(POND30)}", flush=True)

    bars_by, idx_by = {}, {}
    coverage = {}
    for t in all_syms:
        bars = load_bars(t)
        bars_by[t] = bars
        idx_by[t] = {b["d"]: i for i, b in enumerate(bars)}
        coverage[t] = {"first": bars[0]["d"], "last": bars[-1]["d"], "bars": len(bars)}
    print(f"DATA loaded: {len(all_syms)} symbols", flush=True)

    # ---- trigger extraction over the FULL series, per name
    events_by_name = {}
    census_by_name = {}
    for t in broad:
        evs, cen = extract_triggers(t, bars_by[t])
        events_by_name[t] = evs
        census_by_name[t] = cen
    census_broad = {k: sum(c[k] for c in census_by_name.values())
                    for k in ("pivots", "armed", "triggered", "expired",
                              "invalid_armed", "superseded", "invalid_prearm")}
    census_pond = {k: sum(census_by_name[t][k] for t in POND30)
                   for k in census_broad}
    print(f"CENSUS BROAD154 (full series): {census_broad}", flush=True)
    print(f"CENSUS POND30 (full series): {census_pond}", flush=True)

    spy = bars_by["SPY"]
    out = {"strategy": "V13 BEST-RULES harmonic Gartley (ZigZag 5% on bar "
                       "extremes, B 0.55-0.68 of XA, C 0.382-0.886 of AB, "
                       "D 0.786 of XA, armed life to trigger/X-stop/A-break/"
                       "126d, Carney two targets, 252d time exit, 4x25% "
                       "slices, no floor)",
           "pot": START_CASH, "floor": None,
           "costs": "0.10%/side + $0.01/sell",
           "champion_reference": CHAMPION,
           "spy_published": SPY_PUBLISHED,
           "v11_pond_reference": V11_POND,
           "coverage": coverage,
           "census_broad154_full_series": census_broad,
           "census_pond30_full_series": census_pond,
           "census_by_name": census_by_name}

    for uname, universe in universes.items():
        all_events = {}
        for t in universe:
            for ev in events_by_name[t]:
                all_events.setdefault(ev["trigger_date"], []).append(ev)
        for d in all_events:
            all_events[d].sort(key=lambda e: e["ticker"])
        out[uname] = {}
        for name, (ws, we) in ROADS.items():
            calendar = sorted({b["d"] for t in universe + ["SPY"]
                               for b in bars_by[t] if ws <= b["d"] <= we})
            events_by_date = {d: evs for d, evs in all_events.items()
                              if ws <= d <= we}
            n_events = sum(len(v) for v in events_by_date.values())
            bh = buy_hold_spy(spy, ws, we)
            r = run_pot(bars_by, idx_by, calendar, events_by_date, universe)
            dist = period_distribution(r["curve"])
            print(f"[{uname}] {name} {ws}->{we}: GARTLEY ${r['final']:,.2f} "
                  f"({r['return_pct']:+.2f}%) triggers={n_events} "
                  f"trades={r['trades_n']} orders={r['orders']} "
                  f"win={r['win_rate_pct']}% maxDD={r['max_drawdown_pct']}% "
                  f"worst=${r['worst_close']} costs=${r['costs']} "
                  f"skips={len(r['skips'])} | SPY ${bh['final']:,.2f} "
                  f"(pub {SPY_PUBLISHED.get(name, 'n/a')})", flush=True)
            pl = placebo_block(bars_by, idx_by, calendar, events_by_date,
                               universe, r["final"])
            print(f"[{uname}] {name} PLACEBO: median=${pl['median']:,.2f} "
                  f"best=${pl['best']:,.2f} worst=${pl['worst']:,.2f} | "
                  f"RANKED ${pl['ranked_final']:,.2f} = "
                  f"{pl['ranked_percentile']}th pctile "
                  f"(beat {pl['seeds_beaten']}/20)", flush=True)
            out[uname][name] = {
                "window": [ws, we], "gartley": summarize(r),
                "trades": r["trades"], "skips": r["skips"],
                "triggers_in_window": n_events,
                "buy_hold_spy": bh, "spy_published": SPY_PUBLISHED.get(name),
                "champion": CHAMPION.get(name),
                "period_distribution": dist,
                "placebo": pl,
                "curve": [[d, round(v, 2)] for d, v in r["curve"]],
            }

    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")


if __name__ == "__main__":
    main()
