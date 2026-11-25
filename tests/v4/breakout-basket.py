#!/usr/bin/env python3
"""
Breakout BASKET test - Terry's AI stock app (v4 track). Simulation only.

Terry's direction: don't bet on one stock - buy multiple stocks. The
standalone 52-week-high breakout ran max 2 positions at 50% of equity each
and was DEMOTED after deep validation (../v3/breakout-validation.md):
validation 2023-2026 fresh $100 pot = $124.82 vs SPY net $179.10, floor
halt 2026-08-14, validation max drawdown 20.4%; full-window $383.36,
max drawdown 30.2%.

This test changes ONE structural thing: diversification. Same entry signal
(close above the highest close of the prior 252 sessions), same exits
(close below the 20-day average -> next open; -8% intraday stop, gaps fill
at the open), same costs (0.10%/side + $0.01/sell), same floor - but the
pot holds up to FIVE positions at 20% of equity each. If more names signal
than there are free slots, the free slots go to the names with the largest
% gain on the signal day; the rest are skipped.

Runs:
  A. Full continuous 2016-11-21 -> 2026-11-20, $100 and $50 pots,
     per-year tables.
  B. Design (2016-11-21 -> 2022-12-31) vs validation (2023-01-01 ->
     2026-11-20), fresh pots, both sizes.
  C. Placebo on the validation window: random entries with the same
     number of FILLED entries per year as the real basket (iterative
     top-up), same exits/costs/floor, seed 90210, both pot sizes.

The engine is the tournament module itself (../v2/tournament.py), so
Portfolio / cost / floor mechanics are byte-for-byte the tournament's;
only the runner differs (5 slots, 20% sizing, signal-day-gain ordering).

$50 pot (Terry's rule change): floor $42.50; ladder raises the floor to
$50 at a $62.50 close and to $62.50 at a $75 close.

Universe: SPY QQQ NVDA TSLA AAPL MSFT AMZN META AMD AVGO - today's famous
names, so survivorship tilt flatters every number here. Data: Yahoo daily
bars cached by the tournament (split-adjusted, NOT dividend-adjusted).

Outputs: breakout-basket-results.json next to this script, plus a console
summary. The .md report is written from those results.
"""

import contextlib
import json
import os
import sys
from datetime import date

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
V2_DIR = os.path.join(HERE, "..", "v2")
sys.path.insert(0, V2_DIR)

import tournament as T  # the exact tournament engine

UNIVERSE = T.STOCK_UNIVERSE
FULL = (date(2016, 11, 21), date(2026, 11, 20))
DESIGN = (date(2016, 11, 21), date(2022, 12, 31))
VALIDATION = (date(2023, 1, 1), date(2026, 11, 20))
PLACEBO_SEED = 90210
MAX_POSITIONS = 5
FRAC = 0.20
STOP_PCT = 0.08


# ----------------------------------------------------------------------------
# Data / market construction
# ----------------------------------------------------------------------------

def build_frames():
    raw = {sym: T.load_symbol(sym) for sym in UNIVERSE}
    return T.align_frames(raw)


def make_market(frames, window):
    T.TEST_START, T.TEST_END = window
    return T.Market(frames)


# ----------------------------------------------------------------------------
# Scaled-pot configuration (Terry's $50 rule change) - same as v3 validation
# ----------------------------------------------------------------------------

@contextlib.contextmanager
def pot_config(start_cash, floor0, lad1_at, lad1_to, lad2_at, lad2_to):
    orig_start = T.START_CASH
    orig_fc = T.Portfolio.floor_check
    orig_init = T.Portfolio.__init__

    def scaled_init(self, style_name):
        orig_init(self, style_name)
        self.floor = floor0

    def scaled_floor_check(self, d, equity_close):
        if equity_close >= lad2_at:
            self.floor = max(self.floor, lad2_to)
        elif equity_close >= lad1_at:
            self.floor = max(self.floor, lad1_to)
        if equity_close <= self.floor:
            self.halt_pending = True
            self.halt_trigger_date = d
            return True
        return False

    T.START_CASH = start_cash
    T.Portfolio.floor_check = scaled_floor_check
    T.Portfolio.__init__ = scaled_init
    try:
        yield
    finally:
        T.START_CASH = orig_start
        T.Portfolio.floor_check = orig_fc
        T.Portfolio.__init__ = orig_init


# ----------------------------------------------------------------------------
# Basket runner - tournament run_discrete semantics, 5 slots x 20%,
# candidates ordered by % gain on the signal day (largest first)
# ----------------------------------------------------------------------------

def signal_day_gain(mkt, sym, pos):
    """% gain on day `pos` itself (the signal day), close vs prior close."""
    df = mkt.frames[sym]
    if pos < 1:
        return 0.0
    prev = df["close"].iloc[pos - 1]
    if prev is None or prev <= 0:
        return 0.0
    return float(df["close"].iloc[pos] / prev - 1)


def run_basket(mkt, style_name, placebo_schedule=None):
    pf = T.Portfolio(style_name)
    pending_entries = []        # list of (symbol, signal-day % gain)
    pending_exits = []          # list of (symbol, reason)
    last_t = len(mkt.test_dates) - 1

    for t, d in enumerate(mkt.test_dates):
        pos = mkt.test_pos[t]
        if pf.halt_pending:
            pf.liquidate_all(d, pos, mkt.open_map(pos), "floor-liquidation")
            pf.halted = True
            pf.halt_date = d
            pf.equity_curve.append((d, pf.equity(mkt.close_map(pos))))
            break

        # 1) close-signal exits scheduled yesterday fill at today's open
        for sym, reason in pending_exits:
            if pf.shares_of(sym) > 0:
                pf.sell(d, pos, sym, mkt.price(sym, pos, "open"), reason)
        pending_exits = []

        # 2) entries at today's open. Real signals arrive pre-sorted by
        #    signal-day gain (largest first); placebo attempts keep their
        #    scheduled order. Free slots fill in that order; the rest skip.
        if placebo_schedule is not None:
            candidates = [(s, 0.0) for s in placebo_schedule.get(d, [])]
        else:
            candidates = list(pending_entries)
        pending_entries = []
        for sym, _gain in candidates:
            if pf.shares_of(sym) > 0 or len(pf.held_symbols()) >= MAX_POSITIONS:
                continue
            eq_open = pf.equity(mkt.open_map(pos))
            pf.buy(d, pos, sym, mkt.price(sym, pos, "open"),
                   FRAC * eq_open, "entry")

        # 3) intraday -8% stop, stop-first semantics identical to tournament
        for sym in list(pf.held_symbols()):
            entry = pf.weighted_entry_price(sym)
            if entry is None:
                continue
            o = mkt.price(sym, pos, "open")
            low = mkt.price(sym, pos, "low")
            stop_px = entry * (1 - STOP_PCT)
            fill, reason = None, None
            if o <= stop_px:
                fill, reason = o, "stop-gap"
            elif low <= stop_px:
                fill, reason = stop_px, "stop"
            if fill is not None:
                pf.sell(d, pos, sym, fill, reason)

        # 4) mark to close, floor ladder + floor test
        eq_close = pf.equity(mkt.close_map(pos))
        pf.equity_curve.append((d, eq_close))
        touched = pf.floor_check(d, eq_close)
        if touched and t == last_t:
            pf.halted = True
            pf.halt_date = d
            break
        if t == last_t:
            break

        # 5) schedule MA exits for tomorrow's open (close below 20-day avg)
        for sym in list(pf.held_symbols()):
            sma20 = mkt.frames[sym]["sma20"].iloc[pos]
            if not np.isnan(sma20) and mkt.price(sym, pos, "close") < sma20:
                pending_exits.append((sym, "ma-exit"))

        # 6) generate tomorrow's entries from today's close signals,
        #    ordered by today's % gain, largest first
        if placebo_schedule is None:
            sigs = []
            for sym in UNIVERSE:
                if pf.shares_of(sym) > 0:
                    continue
                if T.sig_breakout52(mkt, sym, pos):
                    sigs.append((sym, signal_day_gain(mkt, sym, pos)))
            sigs.sort(key=lambda x: -x[1])
            pending_entries = sigs
    return pf


# ----------------------------------------------------------------------------
# Fixed placebo: match the real basket's filled entries, per year
# ----------------------------------------------------------------------------

def entries_by_year(pf):
    out = {}
    for tr in pf.trades:
        if tr["side"] == "buy":
            y = int(tr["date"][:4])
            out[y] = out.get(y, 0) + 1
    return out


def run_placebo_matched(mkt, target_by_year, seed=PLACEBO_SEED):
    """Random (day, symbol) entry attempts, topped up iteratively until the
    number of FILLED entries matches the real basket's per-year counts.
    A day already carrying MAX_POSITIONS scheduled attempts rolls to the
    next trading day. Deterministic given the seed."""
    rng = np.random.default_rng(seed)
    test_dates = mkt.test_dates
    idx_of = {d: i for i, d in enumerate(test_dates)}
    days_by_year = {}
    for d in test_dates[:-1]:  # never enter on the final day
        days_by_year.setdefault(d.year, []).append(d)
    schedule = {}

    def add_attempts(year, n):
        days = days_by_year.get(year, [])
        if not days:
            return
        for _ in range(n):
            d = days[rng.integers(0, len(days))]
            i = idx_of[d]
            while len(schedule.get(d, [])) >= MAX_POSITIONS and i < len(test_dates) - 1:
                i += 1
                d = test_dates[i]
            sym = UNIVERSE[rng.integers(0, len(UNIVERSE))]
            schedule.setdefault(d, []).append(sym)

    for year, target in sorted(target_by_year.items()):
        add_attempts(year, target)

    pf, actual = None, {}
    for _ in range(80):
        pf = run_basket(mkt, "c_breakout52_basket_placebo",
                        placebo_schedule=schedule)
        actual = entries_by_year(pf)
        missing = {y: target_by_year.get(y, 0) - actual.get(y, 0)
                   for y in target_by_year}
        if all(v <= 0 for v in missing.values()):
            break
        for year, miss in missing.items():
            if miss > 0:
                add_attempts(year, miss)
    attempts = sum(len(v) for v in schedule.values())
    return pf, {"seed": seed, "attempts": attempts,
                "target_by_year": target_by_year, "actual_by_year": actual}


# ----------------------------------------------------------------------------
# Per-year table helper (same construction as the v3 validation report)
# ----------------------------------------------------------------------------

def per_year_table(pf, mkt, frames, start_cash):
    spy_df = frames["SPY"]
    spy_close = {d: float(c) for d, c in zip(spy_df["date"], spy_df["close"])}
    spy_open_first = float(spy_df["open"].iloc[mkt.test_pos[0]])
    curve = list(pf.equity_curve)
    rows = []
    prev_eq, prev_spy_px = start_cash, spy_open_first
    years = sorted({d.year for d, _ in curve})
    for year in years:
        in_year = [(d, e) for d, e in curve if d.year == year]
        if not in_year:
            continue
        end_eq = in_year[-1][1]
        last_day = in_year[-1][0]
        spy_end = spy_close[last_day]
        rows.append({
            "year": year, "start": prev_eq, "end": end_eq,
            "pot_ret_pct": (end_eq / prev_eq - 1) * 100,
            "spy_ret_pct": (spy_end / prev_spy_px - 1) * 100,
        })
        prev_eq, prev_spy_px = end_eq, spy_end
    return rows


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def brief(pf, mkt):
    return T.score(pf, mkt.test_dates[0])


def run_window(frames, window, style):
    mkt = make_market(frames, window)
    pf = run_basket(mkt, style)
    r = brief(pf, mkt)
    g, n = T.spy_benchmark(mkt)
    return pf, mkt, r, g, n


def main():
    print("Loading data (tournament cache)...")
    frames = build_frames()
    results = {}

    # ---------- $100 pots ---------------------------------------------------
    # A. full continuous
    pf, mkt, r, g, n = run_window(frames, FULL, "c_breakout52_basket")
    results["full_100"] = {"strategy": r, "spy_gross": g, "spy_net": n,
                          "per_year": per_year_table(pf, mkt, frames, 100.0)}
    print(f"FULL $100: basket ${r['final']:,.2f} ({r['total_pct']:+.1f}%) vs "
          f"SPY net ${n:,.2f}, maxDD {r['max_dd_pct']:.1f}%, "
          f"halt {r['halt_date'] or '-'}")

    # B. design vs validation
    for name, window in (("design", DESIGN), ("validation", VALIDATION)):
        pf, mkt, r, g, n = run_window(frames, window, "c_breakout52_basket")
        results[f"{name}_100"] = {"strategy": r, "spy_gross": g, "spy_net": n}
        print(f"{name.upper()} $100: basket ${r['final']:,.2f} "
              f"({r['total_pct']:+.1f}%) vs SPY net ${n:,.2f}, "
              f"maxDD {r['max_dd_pct']:.1f}%, halt {r['halt_date'] or '-'}")

    # C. placebo on validation (matched per-year, seed 90210)
    mkt_v = make_market(frames, VALIDATION)
    real_v = run_basket(mkt_v, "c_breakout52_basket")
    target = entries_by_year(real_v)
    ppf, meta = run_placebo_matched(mkt_v, target)
    pr = brief(ppf, mkt_v)
    results["placebo_validation_100"] = {"placebo": pr, **meta}
    print(f"PLACEBO VALIDATION $100: ${pr['final']:,.2f} "
          f"(real ${results['validation_100']['strategy']['final']:,.2f}, "
          f"attempts {meta['attempts']}, target {meta['target_by_year']}, "
          f"actual {meta['actual_by_year']})")

    # ---------- $50 pots ------------------------------------------------------
    with pot_config(50.0, 42.50, 62.50, 50.0, 75.0, 62.50):
        pf, mkt, r, g, n = run_window(frames, FULL, "c_breakout52_basket_50")
        results["full_50"] = {"strategy": r, "spy_gross": g, "spy_net": n,
                              "per_year": per_year_table(pf, mkt, frames, 50.0),
                              "costs_pct_of_pot": r["total_costs"] / 50.0 * 100}
        print(f"FULL $50: basket ${r['final']:,.2f} ({r['total_pct']:+.1f}%) "
              f"vs SPY net ${n:,.2f}, maxDD {r['max_dd_pct']:.1f}%, "
              f"costs ${r['total_costs']:,.2f}, halt {r['halt_date'] or '-'}")

        for name, window in (("design", DESIGN), ("validation", VALIDATION)):
            pf, mkt, r, g, n = run_window(frames, window,
                                          "c_breakout52_basket_50")
            results[f"{name}_50"] = {
                "strategy": r, "spy_gross": g, "spy_net": n,
                "costs_pct_of_pot": r["total_costs"] / 50.0 * 100}
            print(f"{name.upper()} $50: basket ${r['final']:,.2f} "
                  f"({r['total_pct']:+.1f}%) vs SPY net ${n:,.2f}, "
                  f"maxDD {r['max_dd_pct']:.1f}%, halt {r['halt_date'] or '-'}")

        mkt_v = make_market(frames, VALIDATION)
        real_v = run_basket(mkt_v, "c_breakout52_basket_50")
        target = entries_by_year(real_v)
        ppf, meta = run_placebo_matched(mkt_v, target)
        pr = brief(ppf, mkt_v)
        results["placebo_validation_50"] = {"placebo": pr, **meta}
        print(f"PLACEBO VALIDATION $50: ${pr['final']:,.2f} "
              f"(real ${results['validation_50']['strategy']['final']:,.2f}, "
              f"attempts {meta['attempts']}, target {meta['target_by_year']}, "
              f"actual {meta['actual_by_year']})")

    results["full_100"]["costs_pct_of_pot"] = \
        results["full_100"]["strategy"]["total_costs"]
    results["validation_100"]["costs_pct_of_pot"] = \
        results["validation_100"]["strategy"]["total_costs"]

    out = os.path.join(HERE, "breakout-basket-results.json")
    with open(out, "w") as fh:
        json.dump(results, fh, indent=2, default=str)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
