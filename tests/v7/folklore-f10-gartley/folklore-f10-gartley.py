#!/usr/bin/env python3
"""
FOLKLORE TEST F-10 — HARMONIC GARTLEY, FROZEN PARAMETERIZATION.
Terry's AI stock app program. Simulation only.

Spec source: ~/workspace/stock-app/research/v7-completeness/folklore-audit.md,
Spec F-10, implemented VERBATIM. The spec's own caveat is part of the run:

  Harmonic patterns have no canonical swing or tolerance settings. The
  parameters below are the auditor's freeze, chosen at round,
  commonly-taught values. THE RUN GRADES THIS PARAMETERIZATION, not
  "harmonic trading" as believers practice it — practitioners set the
  swing threshold and the tolerance bands by eye and dispute both.

Frozen spec (F-10):
  - Universe/data: the honest top-30 pond, daily closes.
  - Pattern: swings from a ZigZag on closes with an 8% reversal
    threshold. A bullish Gartley is a completed X->A->B->C sequence
    with: B retracing 61.8% of XA within a +/-3 percentage-point band
    (ratio in [0.588, 0.648]); C retracing between 38.2% and 88.6% of
    AB; and a projected D at the 78.6% retracement of XA (+/-3 points).
    Buy at the next open after the first close at or below the D level,
    provided price has not closed below X.
  - Position/exit rules: one position per name, max 5 concurrent,
    1/5 pot slices (as in F-1: each entry commits 1/5 of the pot's
    current value; signals while full are skipped and logged). Exit at
    the first of: close reaching the 38.2% retracement of the AD leg
    (the standard first target); close below X (pattern invalid);
    126 trading days held.

House chassis (audit preamble, shared by all F-specs):
  - $100 starting pot, long-only, fractional shares, cash earns 0%.
  - Execution at the next session's open after a signal computed on
    closes. Costs: 0.10% of trade value per side + $0.01 per sell order.
  - Plain -15% floor at pot level: a close at or below $85 liquidates
    everything at the next open and ends the run (champion convention).
  - A position open at a window's end is liquidated at the final close.
  - Windows: continuous 2019-01-01 -> 2026-11-20; validation
    2023-01-01 -> 2026-11-20 (fresh $100 each).
  - Benchmarks: SPY buy-hold net of the same costs (integrity-checked
    against the program's published $313.62 / $187.77) and the 20-seed
    random placebo on the same universe and cadence. Promotion bar
    (program standing rule): beat SPY AND the placebo median on
    validation.

IMPLEMENTATION READINGS (documented, not parameter changes — the
frozen numbers above are untouched):
  1. "Completed X->A->B->C" means all four pivots are ZigZag-CONFIRMED
     pivots (a pivot exists only once the subsequent 8% reversal prints
     it). The forming leg is never used — the same point-in-time
     discipline as Spec F-1 ("entries may only use completed swings").
     The D watch therefore starts on C's confirmation close itself.
  2. The buy sentence names "the D level": entry triggers on the first
     close at or below the projected D level (the 78.6% retracement
     price). The +/-3-point band is applied where the spec attaches it
     to a completed ratio — B's retracement — and defines D's
     completion zone [75.6%, 81.6%]; the trigger is the central level,
     per the spec's wording.
  3. The X guard is evaluated over the pattern's whole life: any close
     below X from X's pivot date through the trigger close kills the
     pattern (a close below X on the trigger day itself invalidates
     rather than fills).
  4. An armed pattern expires when the next ZigZag pivot after C is
     confirmed (the structure has moved on). A trigger is a single
     dated event: if it cannot be taken (name held, book full), it is
     skipped and logged, not carried.
  5. Exit target uses the pattern's projected D (the AD leg of the
     pattern geometry), not the fill price. The 126 trading days are
     counted in the held name's own sessions from its entry bar.
  6. Placebo (audit: "20-seed random placebo distribution on the same
     universe and cadence"): identical engine, identical trigger
     dates and slice mechanics, but the bought name is a uniform
     random draw (seeded) from the pond names not currently held, and
     its exit geometry is the signal pattern's target/stop distances
     translated as percentages of the placebo fill price (same % up to
     target, same % down to stop, same 126-day cap). This removes the
     pattern's stock selection while keeping dates, sizing, exit
     distances and costs identical.

Data: program price caches, read-only, champion construction (open
scaled by adjclose/close, close = adjclose):
  ~/workspace/stock-app/backtests/v4/data/px_<T>.json, falling back to
  ~/workspace/stock-app/backtests/v4/value-momentum-honest-data/px_<T>.json
  (the champion engine's own two cache locations). Series run
  2017-06-01 -> 2026-11-20, so patterns forming the 2019 window's
  early trades are built from genuine pre-window history.
"""
import json
import os
import random
import statistics
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIRS = [
    os.path.expanduser("~/workspace/stock-app/backtests/v4/data"),
    os.path.expanduser("~/workspace/stock-app/backtests/v4/value-momentum-honest-data"),
]

UNIVERSE = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "BRK-B", "JPM", "XOM",
            "JNJ", "PG", "V", "WMT", "HD", "BAC", "CVX", "PFE", "VZ", "T",
            "DIS", "NFLX", "INTC", "CSCO", "GE", "IBM", "MMM", "UNH", "MA",
            "KO", "PEP", "WFC"]
PLACEBO_SEEDS = list(range(1, 21))

START_CASH = 100.0
FLOOR = 85.0            # plain -15% floor on the $100 pot
COST_RATE = 0.001       # 0.10% per side
SELL_FEE = 0.01         # $0.01 per sell order

# ---- F-10 frozen parameters (DO NOT adjust; the freeze is the test) ----
ZZ_THRESHOLD = 0.08             # ZigZag reversal threshold on closes
B_CENTER, B_BAND = 0.618, 0.03  # B retrace of XA: 61.8% +/- 3 points
C_LO, C_HI = 0.382, 0.886       # C retrace of AB
D_FRAC = 0.786                  # D at 78.6% retracement of XA
TARGET_FRAC = 0.382             # exit target: 38.2% retracement of AD leg
MAX_HOLD_DAYS = 126             # trading days
MAX_POSITIONS = 5
SLICES = 5                      # 1/5 pot slices

END = "2026-11-20"
WINDOWS = {"continuous": ("2019-01-01", END),
           "validation": ("2023-01-01", END)}
CHAMPION = {"continuous": 544.47, "validation": 288.05}
SPY_PUBLISHED = {"continuous": 313.62, "validation": 187.77}


# ---------------------------------------------------------------- data
def load_bars(ticker):
    """Champion bar construction from the program caches (read-only)."""
    blob = None
    for d in CACHE_DIRS:
        p = os.path.join(d, f"px_{ticker}.json")
        if os.path.exists(p) and os.path.getsize(p) > 100:
            with open(p, "rb") as f:
                blob = f.read()
            break
    if blob is None:
        raise SystemExit(f"no cached prices for {ticker}")
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


# ------------------------------------------------------- ZigZag + F-10
def zigzag_pivots(bars, threshold=ZZ_THRESHOLD):
    """ZigZag on closes. Returns confirmed pivots only:
    {kind 'L'/'H', idx (extreme bar), date, price, confirm_idx,
    confirm_date}. A pivot exists only from its confirmation bar on."""
    closes = [b["c"] for b in bars]
    pivots = []
    if not closes:
        return pivots
    # undecided phase: track running hi/lo until an 8% move off one of
    # them confirms the opposite pivot
    hi, hi_i = closes[0], 0
    lo, lo_i = closes[0], 0
    mode = None          # 'seek_high' (last pivot is a low) / 'seek_low'
    ext, ext_i = None, None
    for i in range(1, len(closes)):
        p = closes[i]
        if mode is None:
            if p > hi:
                hi, hi_i = p, i
            if p < lo:
                lo, lo_i = p, i
            if p <= hi * (1 - threshold):
                pivots.append({"kind": "H", "idx": hi_i,
                               "date": bars[hi_i]["d"], "price": hi,
                               "confirm_idx": i, "confirm_date": bars[i]["d"]})
                mode, ext, ext_i = "seek_low", p, i
            elif p >= lo * (1 + threshold):
                pivots.append({"kind": "L", "idx": lo_i,
                               "date": bars[lo_i]["d"], "price": lo,
                               "confirm_idx": i, "confirm_date": bars[i]["d"]})
                mode, ext, ext_i = "seek_high", p, i
        elif mode == "seek_high":
            if p > ext:
                ext, ext_i = p, i
            elif p <= ext * (1 - threshold):
                pivots.append({"kind": "H", "idx": ext_i,
                               "date": bars[ext_i]["d"], "price": ext,
                               "confirm_idx": i, "confirm_date": bars[i]["d"]})
                mode, ext, ext_i = "seek_low", p, i
        else:  # seek_low
            if p < ext:
                ext, ext_i = p, i
            elif p >= ext * (1 + threshold):
                pivots.append({"kind": "L", "idx": ext_i,
                               "date": bars[ext_i]["d"], "price": ext,
                               "confirm_idx": i, "confirm_date": bars[i]["d"]})
                mode, ext, ext_i = "seek_high", p, i
    return pivots


def extract_triggers(ticker, bars):
    """Walk one name's full series once: confirm pivots, arm completed
    bullish Gartleys, and emit single-date trigger events. Returns
    (trigger_events, census). Point-in-time throughout: nothing is
    known before its confirmation bar."""
    closes = [b["c"] for b in bars]
    pivots = zigzag_pivots(bars)
    piv_by_confirm = {}
    for pv in pivots:
        piv_by_confirm.setdefault(pv["confirm_idx"], []).append(pv)

    census = {"pivots": len(pivots), "armed": 0, "triggered": 0,
              "expired": 0, "invalid_armed": 0, "invalid_prearm": 0}
    events = []
    confirmed = []       # pivots known so far, in order
    armed = None         # pattern dict being watched

    for i, b in enumerate(bars):
        # (a) pivot confirmations landing on this bar
        for pv in piv_by_confirm.get(i, []):
            if armed is not None:
                # the next pivot after C has confirmed: structure moved on
                census["expired"] += 1
                armed = None
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
                        if (B_CENTER - B_BAND <= b_ratio <= B_CENTER + B_BAND
                                and c_ratio is not None
                                and C_LO <= c_ratio <= C_HI):
                            # X guard over the pattern's life so far
                            if any(closes[j] < x["price"]
                                   for j in range(x["idx"], i + 1)):
                                census["invalid_prearm"] += 1
                            else:
                                d_level = a["price"] - D_FRAC * xa
                                armed = {
                                    "ticker": ticker,
                                    "x_date": x["date"], "x": x["price"],
                                    "a_date": a["date"], "a": a["price"],
                                    "b_date": bb["date"], "b": bb["price"],
                                    "c_date": c["date"], "c": c["price"],
                                    "b_ratio": round(b_ratio, 4),
                                    "c_ratio": round(c_ratio, 4),
                                    "d_level": d_level,
                                    "target": d_level + TARGET_FRAC * (a["price"] - d_level),
                                    "arm_date": b["d"],
                                }
                                census["armed"] += 1
        # (b) armed-pattern watch on this close
        if armed is not None:
            if b["c"] < armed["x"]:
                census["invalid_armed"] += 1
                armed = None
            elif b["c"] <= armed["d_level"]:
                ev = dict(armed)
                ev["trigger_date"] = b["d"]
                ev["trigger_close"] = b["c"]
                events.append(ev)
                census["triggered"] += 1
                armed = None
    return events, census


# ---------------------------------------------------------------- engine
def run_pot(bars_by, idx_by, calendar, events_by_date, start, end,
            placebo_rng=None):
    """Event engine on the house chassis. If placebo_rng is given,
    entries buy a random unheld pond name with the signal pattern's
    exit geometry translated into percentages of the fill price."""
    cash = START_CASH
    positions = {}       # ticker -> position dict
    pending_entries = [] # order dicts, execute at name's first bar > signal date
    pending_exits = {}   # ticker -> reason
    pending_liquidation = False
    halted = None
    halt_signal_date = None
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
            # last bar strictly before d
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

    last_day = calendar[-1] if calendar else None
    for d in calendar:
        # ---- 1. executions at today's opens (orders signaled before today)
        if pending_liquidation:
            for t in list(positions):
                j = idx_by[t].get(d)
                if j is not None:
                    sell_position(t, bars_by[t][j]["o"], d, "floor")
            pending_entries = []
            pending_exits = {}
            if not positions:
                pending_liquidation = False
                halted = halt_signal_date
        else:
            # exits first (frees cash and names), then entries
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
                    stop = px * (1.0 - od["pct_dn"])
                else:
                    target, stop = od["target"], od["stop"]
                positions[t] = {
                    "shares": buy_val / px, "entry_date": d,
                    "entry_price": px, "cost_basis": buy_val + cost,
                    "target": target, "stop": stop,
                    "entry_idx": j, "pattern": od.get("pattern"),
                }
            pending_entries = still_pending

        # ---- 2. equity curve at today's close
        v = pot_value(d)
        curve.append((d, v))
        if positions:
            days_invested += 1
        if halted is not None:
            break

        is_last = d == last_day

        # ---- 3. floor check at the close
        if not is_last and v <= FLOOR:
            pending_liquidation = True
            halt_signal_date = d
            pending_entries = []
            pending_exits = {}
            continue
        if is_last:
            break

        # ---- 4. exit signals on today's closes
        for t, pos in list(positions.items()):
            j = idx_by[t].get(d)
            if j is None:
                continue
            c = bars_by[t][j]["c"]
            if c < pos["stop"]:
                pending_exits[t] = "invalid_below_x" if placebo_rng is None else "stop"
            elif c >= pos["target"]:
                pending_exits[t] = "target_38.2"
            elif j - pos["entry_idx"] >= MAX_HOLD_DAYS:
                pending_exits[t] = "time_126d"

        # ---- 5. trigger events on today's close
        for ev in events_by_date.get(d, []):
            held_names = set(positions) | {od["ticker"] for od in pending_entries}
            if len(held_names) >= MAX_POSITIONS:
                skips.append({"date": d, "ticker": ev["ticker"], "reason": "book_full"})
                continue
            slice_val = v / SLICES
            if placebo_rng is not None:
                cands = sorted(t for t in UNIVERSE if t not in held_names)
                if not cands:
                    skips.append({"date": d, "ticker": ev["ticker"], "reason": "no_candidate"})
                    continue
                pick = placebo_rng.choice(cands)
                pending_entries.append({
                    "ticker": pick, "signal_ticker": ev["ticker"],
                    "signal_date": d, "slice": slice_val,
                    "pct_up": (ev["target"] - ev["d_level"]) / ev["d_level"],
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
                    "target": ev["target"], "stop": ev["x"],
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
        "halted": halted,
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
    """SPY buy-hold, fresh $100, same costs, no floor (F-8 construction)."""
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


def placebo_block(bars_by, idx_by, calendar, events_by_date, start, end,
                  ranked_final):
    finals, rows = [], []
    for seed in PLACEBO_SEEDS:
        rng = random.Random(seed)
        pr = run_pot(bars_by, idx_by, calendar, events_by_date, start, end,
                     placebo_rng=rng)
        finals.append(pr["final"])
        rows.append({"seed": seed, "final": pr["final"],
                     "halted": pr["halted"], "trades": pr["trades_n"],
                     "costs": pr["costs"]})
        print(f"  PLACEBO seed {seed:2d}: final=${pr['final']:,.2f} "
              f"trades={pr['trades_n']} halted={pr['halted']}", flush=True)
    srt = sorted(finals)
    below = sum(1 for f in finals if f < ranked_final)
    ties = sum(1 for f in finals if f == ranked_final)
    pctile = 100.0 * (below + 0.5 * ties) / len(finals)
    return {"median": round(statistics.median(finals), 2),
            "q1": round(srt[len(srt) // 4], 2), "q3": round(srt[3 * len(srt) // 4], 2),
            "best": round(srt[-1], 2), "worst": round(srt[0], 2),
            "mean": round(sum(finals) / len(finals), 2),
            "halted_count": sum(1 for r in rows if r["halted"]),
            "ranked_final": round(ranked_final, 2),
            "ranked_percentile": round(pctile, 1),
            "seeds_beaten": below, "rows": rows}


def summarize(r):
    return {k: r[k] for k in ("final", "return_pct", "orders", "costs",
                              "trades_n", "halted", "max_drawdown_pct",
                              "max_drawdown_date", "worst_close",
                              "worst_close_date", "win_rate_pct", "avg_win",
                              "avg_loss", "expectancy_per_trade",
                              "time_in_market_pct")}


def main():
    bars_by, idx_by = {}, {}
    coverage = {}
    for t in UNIVERSE + ["SPY"]:
        bars = load_bars(t)
        bars_by[t] = bars
        idx_by[t] = {b["d"]: i for i, b in enumerate(bars)}
        coverage[t] = {"first": bars[0]["d"], "last": bars[-1]["d"], "bars": len(bars)}
        print(f"DATA {t}: {bars[0]['d']} -> {bars[-1]['d']} ({len(bars)} bars)", flush=True)

    # ---- trigger extraction over the FULL series, per name
    all_events = {}
    census_total = {"pivots": 0, "armed": 0, "triggered": 0, "expired": 0,
                    "invalid_armed": 0, "invalid_prearm": 0}
    census_by_name = {}
    for t in UNIVERSE:
        evs, cen = extract_triggers(t, bars_by[t])
        census_by_name[t] = cen
        for k in census_total:
            census_total[k] += cen[k]
        for ev in evs:
            all_events.setdefault(ev["trigger_date"], []).append(ev)
    for d in all_events:
        all_events[d].sort(key=lambda e: e["ticker"])
    print(f"PATTERN CENSUS (full series): {census_total}", flush=True)

    spy = bars_by["SPY"]
    out = {"strategy": "FOLKLORE F-10 harmonic Gartley, FROZEN parameterization "
                       "(ZigZag 8% on closes, B 61.8% +/-3pts, C 38.2-88.6%, "
                       "D 78.6%, target 38.2% of AD, stop below X, 126-day cap, "
                       "top-30 pond, 1/5 slices, max 5 concurrent)",
           "pot": START_CASH, "floor": FLOOR,
           "costs": "0.10%/side + $0.01/sell",
           "champion_reference": CHAMPION,
           "coverage": coverage,
           "pattern_census_full_series": census_total,
           "pattern_census_by_name": census_by_name}

    for name, (ws, we) in WINDOWS.items():
        calendar = sorted({b["d"] for t in UNIVERSE + ["SPY"]
                           for b in bars_by[t] if ws <= b["d"] <= we})
        events_by_date = {d: evs for d, evs in all_events.items() if ws <= d <= we}
        n_events = sum(len(v) for v in events_by_date.values())

        bh = buy_hold_spy(spy, ws, we)
        pub = SPY_PUBLISHED[name]
        match = abs(bh["final"] - pub) < 0.02
        print(f"INTEGRITY {name}: SPY buy-hold ${bh['final']:,.2f} vs "
              f"published ${pub:,.2f} match={match}", flush=True)
        if not match:
            raise SystemExit("SPY control does not reproduce published net "
                             "— results untrusted")

        r = run_pot(bars_by, idx_by, calendar, events_by_date, ws, we)
        print(f"{name.upper()} {ws}->{we}: F-10 ${r['final']:,.2f} "
              f"({r['return_pct']:+.2f}%) triggers={n_events} "
              f"trades={r['trades_n']} orders={r['orders']} "
              f"win={r['win_rate_pct']}% maxDD={r['max_drawdown_pct']}% "
              f"worst=${r['worst_close']} ({r['worst_close_date']}) "
              f"costs=${r['costs']} halted={r['halted']} "
              f"skips={len(r['skips'])}", flush=True)
        print(f"   buy-hold SPY ${bh['final']:,.2f} ({bh['return_pct']:+.2f}%) "
              f"| champion ${CHAMPION[name]:,.2f}", flush=True)

        pl = placebo_block(bars_by, idx_by, calendar, events_by_date, ws, we,
                           r["final"])
        print(f"{name.upper()} PLACEBO: median=${pl['median']:,.2f} "
              f"best=${pl['best']:,.2f} worst=${pl['worst']:,.2f} "
              f"halted={pl['halted_count']}/20 | RANKED ${pl['ranked_final']:,.2f} "
              f"= {pl['ranked_percentile']}th pctile (beat {pl['seeds_beaten']}/20)",
              flush=True)

        out[name] = {"window": [ws, we], "f10": summarize(r),
                     "f10_trades": r["trades"], "f10_skips": r["skips"],
                     "triggers_in_window": n_events,
                     "buy_hold": bh, "spy_published": pub,
                     "spy_reproduced": match,
                     "champion": CHAMPION[name], "placebo": pl}

    with open(os.path.join(HERE, "folklore-f10-gartley-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")


if __name__ == "__main__":
    main()
