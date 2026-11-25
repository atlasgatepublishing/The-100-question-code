#!/usr/bin/env python3
"""
BREAKOUT + REGIME FILTER combination test - Terry's AI stock app (v4 track).
Simulation only - no broker orders.

The standalone 52-week-high breakout was DEMOTED in v3
(../v3/breakout-validation.md): it won in the design years 2016-2022
($348.73 vs SPY net $174.13 at $100) but lost to SPY in the validation
years 2023-2026 ($124.82 vs SPY net $179.10) and breached Terry's floor
(halted 2026-08-14). Its own report suggested it might only work as a
component inside a regime-filtered pot. This script tests exactly that
combination, with the rule frozen in advance - no tuning:

  ENTRY: a name closes at a new 252-day high (close above the highest close
         of the prior 252 sessions) AND the regime gate is open. Gate: SPY's
         prior close - the last close before the fill, i.e. the signal day's
         close - is above SPY's 200-day average on that day. Entries fill at
         the next open, as in the tournament engine.
  SIZE:  max 2 positions, 50% of equity each.
  EXIT:  next open after a close below the name's 20-day average, or an -8%
         intraday stop (stop-first; gaps fill at the open).
  COSTS: 0.10% of trade value per side + $0.01 per sell order.
  FLOOR: Terry's floor active at BOTH pot sizes - $100 start (floor $85,
         ladder to $100 at a $125 close, $125 at a $150 close) and $50 start
         (floor $42.50, ladder to $50 at a $62.50 close, $62.50 at a $75
         close). A close at/below the floor liquidates at the next open and
         ends the run.

Universe: SPY QQQ NVDA TSLA AAPL MSFT AMZN META AMD AVGO (today's famous
names - survivorship tilt flatters every number here). Data: Yahoo daily
bars cached by the v2 tournament (split-adjusted, NOT dividend-adjusted).

Runs:
  (A) Full continuous 2016-11-21 -> 2026-11-20, both pot sizes, per-year
      table.
  (B) Design 2016-11-21 -> 2022-12-31 vs validation 2023-01-01 ->
      2026-11-20, fresh pots, both sizes. An UNGATED control (the original
      demoted breakout) is run on the same windows in the same engine so
      the gate's effect is isolated; at $100 it must reproduce the v3
      numbers ($383.36 full / $124.82 validation) as an engine check.
  (C) Placebo on the validation window: random entries matched per-year in
      filled count to the real gated strategy, same gate (attempts only on
      gate-open days), same exits/costs/floor. Seed stated below.

Mechanics (Portfolio, costs, floor, alignment) are imported from the v2
tournament module itself, byte-for-byte; the scaled-pot context manager is
the same one used by the v3 validation.
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
PLACEBO_SEED = 777001

POT_CONFIGS = {
    100: dict(start_cash=100.0, floor0=85.0, lad1_at=125.0, lad1_to=100.0,
              lad2_at=150.0, lad2_to=125.0),
    50: dict(start_cash=50.0, floor0=42.50, lad1_at=62.50, lad1_to=50.0,
             lad2_at=75.0, lad2_to=62.50),
}


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
# Signals
# ----------------------------------------------------------------------------

def regime_on(mkt, pos):
    """Regime gate, evaluated on the signal day (frame index `pos`): SPY's
    close at `pos` - the last close before tomorrow's entry fill - is above
    SPY's 200-day average at `pos`."""
    spy = mkt.frames["SPY"]
    if pos < 200:
        return False
    ma = spy["sma200"].iloc[pos]
    if np.isnan(ma):
        return False
    return bool(spy["close"].iloc[pos] > ma)


def gate_open_for_fill(mkt, fill_pos):
    """Gate status for an entry filling at the open of frame day `fill_pos`:
    SPY's prior close (frame day fill_pos - 1) above its 200-day average."""
    return regime_on(mkt, fill_pos - 1)


# ----------------------------------------------------------------------------
# Runner (tournament run_discrete / v3 run_breakout semantics + regime gate)
# ----------------------------------------------------------------------------

def run_breakout_regime(mkt, style_name, gate=True, placebo_schedule=None):
    pf = T.Portfolio(style_name)
    pending_entries = []
    pending_exits = []
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

        # 2) entries at today's open
        if placebo_schedule is not None:
            candidates = list(placebo_schedule.get(d, []))
        else:
            candidates = list(pending_entries)
        pending_entries = []
        for sym in candidates:
            if pf.shares_of(sym) > 0 or len(pf.held_symbols()) >= 2:
                continue
            eq_open = pf.equity(mkt.open_map(pos))
            pf.buy(d, pos, sym, mkt.price(sym, pos, "open"),
                   0.5 * eq_open, "entry")

        # 3) intraday -8% stop, stop-first (gap fills at the open)
        for sym in list(pf.held_symbols()):
            entry = pf.weighted_entry_price(sym)
            if entry is None:
                continue
            o = mkt.price(sym, pos, "open")
            low = mkt.price(sym, pos, "low")
            stop_px = entry * (1 - 0.08)
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

        # 5) schedule MA exits for tomorrow's open
        for sym in list(pf.held_symbols()):
            ma = mkt.frames[sym]["sma20"].iloc[pos]
            if not np.isnan(ma) and mkt.price(sym, pos, "close") < ma:
                pending_exits.append((sym, "ma-exit"))

        # 6) generate tomorrow's entries from today's close signals
        if placebo_schedule is None:
            if gate and not regime_on(mkt, pos):
                continue
            for sym in UNIVERSE:
                if pf.shares_of(sym) > 0:
                    continue
                if T.sig_breakout52(mkt, sym, pos):
                    pending_entries.append(sym)
    return pf


def count_signals(mkt):
    """Raw breakout signals vs gate-passing signals over the window."""
    raw = gated = 0
    for t, d in enumerate(mkt.test_dates[:-1]):
        pos = mkt.test_pos[t]
        on = regime_on(mkt, pos)
        for sym in UNIVERSE:
            if T.sig_breakout52(mkt, sym, pos):
                raw += 1
                if on:
                    gated += 1
    return {"raw_breakout_signals": raw, "gate_passing_signals": gated}


# ----------------------------------------------------------------------------
# Placebo: random entries, per-year filled-count matched, gate-open days only
# ----------------------------------------------------------------------------

def entries_by_year(pf):
    out = {}
    for tr in pf.trades:
        if tr["side"] == "buy":
            y = int(tr["date"][:4])
            out[y] = out.get(y, 0) + 1
    return out


def run_placebo_matched(mkt, target_by_year, seed=PLACEBO_SEED):
    """Random (day, symbol) entry attempts on gate-open days only, topped up
    iteratively until FILLED entries match the real gated strategy's
    per-year counts. A day already carrying 2 scheduled attempts rolls to
    the next gate-open day. Deterministic given the seed."""
    rng = np.random.default_rng(seed)
    test_dates = mkt.test_dates
    test_pos = mkt.test_pos

    elig_all = []          # gate-open fill days, in order
    elig_by_year = {}
    for t, d in enumerate(test_dates[:-1]):  # never enter on the final day
        if gate_open_for_fill(mkt, test_pos[t]):
            elig_all.append(d)
            elig_by_year.setdefault(d.year, []).append(d)
    elig_pos = {d: i for i, d in enumerate(elig_all)}
    schedule = {}

    def add_attempts(year, n):
        days = elig_by_year.get(year, [])
        if not days:
            return
        for _ in range(n):
            d = days[int(rng.integers(0, len(days)))]
            j = elig_pos[d]
            while len(schedule.get(d, [])) >= 2 and j < len(elig_all) - 1:
                j += 1
                d = elig_all[j]
            sym = UNIVERSE[int(rng.integers(0, len(UNIVERSE)))]
            schedule.setdefault(d, []).append(sym)

    for year, target in sorted(target_by_year.items()):
        add_attempts(year, target)

    pf, actual = None, {}
    for _ in range(60):
        pf = run_breakout_regime(mkt, "breakout_regime_placebo",
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
                "target_by_year": target_by_year, "actual_by_year": actual,
                "gate_open_days_by_year": {y: len(v)
                                           for y, v in elig_by_year.items()}}


# ----------------------------------------------------------------------------
# Scaled-pot configuration (same approach as the v3 validation)
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
# Per-year table (full run)
# ----------------------------------------------------------------------------

def per_year_table(frames, mkt, pf, start_cash):
    spy_df = frames["SPY"]
    spy_close = {d: float(c) for d, c in zip(spy_df["date"], spy_df["close"])}
    spy_open_first = float(spy_df["open"].iloc[mkt.test_pos[0]])
    curve = list(pf.equity_curve)
    rows = []
    prev_eq, prev_spy_px = start_cash, spy_open_first
    for year in range(2016, 2027):
        in_year = [(d, e) for d, e in curve if d.year == year]
        if not in_year:
            continue
        end_eq = in_year[-1][1]
        spy_end = spy_close[in_year[-1][0]]
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

def run_window(frames, window, style, gate=True, placebo_schedule=None):
    mkt = make_market(frames, window)
    pf = run_breakout_regime(mkt, style, gate=gate,
                             placebo_schedule=placebo_schedule)
    r = T.score(pf, mkt.test_dates[0])
    g, n = T.spy_benchmark(mkt)
    return pf, r, g, n


def main():
    print("Loading data (tournament cache)...")
    frames = build_frames()
    results = {}

    for size, cfg in POT_CONFIGS.items():
        tag = f"start{size}"
        results[tag] = {}
        with pot_config(**cfg):
            # (A) full continuous run, gated
            mkt_full = make_market(frames, FULL)
            pf_full = run_breakout_regime(mkt_full, "breakout_regime")
            r_full = T.score(pf_full, mkt_full.test_dates[0])
            g_full, n_full = T.spy_benchmark(mkt_full)
            results[tag]["full"] = {
                "strategy": r_full, "spy_gross": g_full, "spy_net": n_full,
                "per_year": per_year_table(frames, mkt_full, pf_full,
                                           cfg["start_cash"]),
                "signals": count_signals(mkt_full),
            }
            print(f"[{tag}] FULL gated: ${r_full['final']:,.2f} "
                  f"({r_full['total_pct']:+.1f}%) vs SPY net ${n_full:,.2f}, "
                  f"halt {r_full['halt_date'] or '-'}")

            # engine sanity / control: ungated full at $100 must reproduce
            # the tournament's $383.36
            if size == 100:
                _, r_ctl, _, n_ctl = run_window(frames, FULL,
                                                "breakout_ungated_control",
                                                gate=False)
                results[tag]["full_ungated_control"] = {
                    "strategy": r_ctl, "spy_net": n_ctl}
                print(f"[{tag}] FULL ungated control: ${r_ctl['final']:,.2f} "
                      f"(tournament/v3 said $383.36)")

            # (B) design vs validation, gated + ungated control
            for name, window in (("design", DESIGN),
                                 ("validation", VALIDATION)):
                _, r_g, g_g, n_g = run_window(frames, window,
                                              "breakout_regime", gate=True)
                _, r_u, _, _ = run_window(frames, window,
                                          "breakout_ungated_control",
                                          gate=False)
                mkt_w = make_market(frames, window)
                results[tag][name] = {
                    "gated": r_g, "ungated": r_u,
                    "spy_gross": g_g, "spy_net": n_g,
                    "signals": count_signals(mkt_w),
                }
                print(f"[{tag}] {name.upper()} gated: ${r_g['final']:,.2f} "
                      f"({r_g['total_pct']:+.1f}%) vs SPY net ${n_g:,.2f}, "
                      f"halt {r_g['halt_date'] or '-'} | ungated: "
                      f"${r_u['final']:,.2f}, halt {r_u['halt_date'] or '-'}")

            # (C) placebo on validation, matched to the gated strategy
            mkt_val = make_market(frames, VALIDATION)
            real_val = run_breakout_regime(mkt_val, "breakout_regime")
            target = entries_by_year(real_val)
            ppf, meta = run_placebo_matched(mkt_val, target)
            r_p = T.score(ppf, mkt_val.test_dates[0])
            results[tag]["placebo_validation"] = {"placebo": r_p, **meta}
            print(f"[{tag}] PLACEBO validation: ${r_p['final']:,.2f}, "
                  f"halt {r_p['halt_date'] or '-'} (attempts "
                  f"{meta['attempts']}, target {meta['target_by_year']}, "
                  f"actual {meta['actual_by_year']})")

    out = os.path.join(HERE, "breakout-regime-results.json")
    with open(out, "w") as fh:
        json.dump(results, fh, indent=2, default=str)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
