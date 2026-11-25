#!/usr/bin/env python3
"""
Deep validation of the tournament winner: C. 52-week-high breakout
(Terry's AI stock app, v3 track). Simulation only - no broker orders.

The tournament (../v2/tournament.py) ran this style at $100 -> $383.36 over
2016-11-21 -> 2026-11-20, beating SPY net ($314.10) and its random placebo
($126.60) - but on ONE 10-year path, with a survivorship-flattered universe,
and with a placebo that only filled 40 of its 140 target entries.

This script re-checks the winner six ways, importing the tournament module
itself so the Portfolio / cost / floor machinery is byte-for-byte the same:

  1. Per-year table over the full 10 years (pot vs SPY, same years).
  2. Design (2016-11-21 -> 2022-12-31) vs validation (2023-01-01 -> 2026-11-20)
     split, fresh $100 pots: does it beat SPY net in the VALIDATION years?
  3. FIXED placebo: random entries with the same NUMBER of entries per year
     as the real strategy (iterative top-up until the filled counts match;
     busy slots roll to the next available day). Full window + validation.
  4. Cost stress: full 10 years at 2x costs (0.20%/side + $0.02/sell).
  5. Parameter neighbors: lookback {200, 252, 300}-day high x MA exit
     {20-day, 50-day} x stop {-8%, -10%} on the full 10 years.
  6. Deflated Sharpe (Bailey & Lopez de Prado) with stated assumptions and a
     sensitivity table over trial count N and cross-trial Sharpe dispersion.

Original rules (exact): buy at next open when a name closes above its highest
close of the prior 252 sessions; max 2 positions, 50% of equity each; exit at
next open after a close below the 20-day average; -8% intraday stop (gap fills
at the open, honestly); costs 0.10%/side + $0.01/sell; Terry's floor ($85,
rising to $100 at a $125 close, $125 at a $150 close; a close at/below the
floor liquidates at the next open and ends the run). Universe: SPY QQQ NVDA
TSLA AAPL MSFT AMZN META AMD AVGO (today's famous names - survivorship tilt
applies to every number here). Data: Yahoo daily bars cached by the
tournament (split-adjusted, NOT dividend-adjusted).

Outputs: breakout-validation-results.json next to this script, plus a console
summary. The .md report is written from those results.
"""

import contextlib
import json
import math
import os
import sys
from datetime import date
from statistics import NormalDist

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
# v9 copy lives in backtests/v9-muse-rules/breakout-validation/; the v2
# tournament engine it imports is at backtests/v2/.
V2_DIR = os.path.join(HERE, "..", "..", "v2")
sys.path.insert(0, V2_DIR)

import tournament as T  # the exact tournament engine

UNIVERSE = T.STOCK_UNIVERSE
FULL = (date(2016, 11, 21), date(2026, 11, 20))
DESIGN = (date(2016, 11, 21), date(2022, 12, 31))
VALIDATION = (date(2023, 1, 1), date(2026, 11, 20))
PLACEBO_SEED = 90210
EULER_GAMMA = 0.5772156649015329
ND = NormalDist()


# ----------------------------------------------------------------------------
# Data / market construction
# ----------------------------------------------------------------------------

def build_frames():
    raw = {sym: T.load_symbol(sym) for sym in T.ALL_SYMBOLS}
    frames = T.align_frames(raw)
    for sym, df in frames.items():
        c = df["close"]
        df["prior200_high_close"] = c.shift(1).rolling(200).max()
        df["prior300_high_close"] = c.shift(1).rolling(300).max()
    return frames


def make_market(frames, window):
    T.TEST_START, T.TEST_END = window
    return T.Market(frames)


# ----------------------------------------------------------------------------
# Breakout runner (tournament run_discrete semantics, parameterized)
# ----------------------------------------------------------------------------

def breakout_signal(mkt, sym, pos, lookback):
    df = mkt.frames[sym]
    if pos < lookback + 1:
        return False
    prior_high = df[f"prior{lookback}_high_close"].iloc[pos]
    if np.isnan(prior_high):
        return False
    return bool(df["close"].iloc[pos] > prior_high)


def run_breakout(mkt, style_name, lookback=252, ma_col="sma20", stop_pct=0.08,
                 placebo_schedule=None):
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

        # 3) intraday stop, stop-first semantics identical to the tournament
        if stop_pct is not None:
            for sym in list(pf.held_symbols()):
                entry = pf.weighted_entry_price(sym)
                if entry is None:
                    continue
                o = mkt.price(sym, pos, "open")
                low = mkt.price(sym, pos, "low")
                stop_px = entry * (1 - stop_pct)
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
            ma = mkt.frames[sym][ma_col].iloc[pos]
            if not np.isnan(ma) and mkt.price(sym, pos, "close") < ma:
                pending_exits.append((sym, "ma-exit"))

        # 6) generate tomorrow's entries from today's close signals
        if placebo_schedule is None:
            for sym in UNIVERSE:
                if pf.shares_of(sym) > 0:
                    continue
                if breakout_signal(mkt, sym, pos, lookback):
                    pending_entries.append(sym)
    return pf


# ----------------------------------------------------------------------------
# Fixed placebo: match the real strategy's filled entries, per year
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
    number of FILLED entries matches the real strategy's per-year counts.
    A day that already carries 2 scheduled attempts rolls to the next
    trading day. Deterministic given the seed."""
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
            while len(schedule.get(d, [])) >= 2 and i < len(test_dates) - 1:
                i += 1
                d = test_dates[i]
            sym = UNIVERSE[rng.integers(0, len(UNIVERSE))]
            schedule.setdefault(d, []).append(sym)

    for year, target in sorted(target_by_year.items()):
        add_attempts(year, target)

    pf, actual = None, {}
    for _ in range(60):
        pf = run_breakout(mkt, "c_breakout52_placebo_fixed",
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
# Scaled-pot configuration (Terry's $50 rule change)
# ----------------------------------------------------------------------------

@contextlib.contextmanager
def pot_config(start_cash, floor0, lad1_at, lad1_to, lad2_at, lad2_to):
    """Temporarily rescale the tournament Portfolio to a different starting
    pot with a proportionally scaled floor/ladder. For $50: floor $42.50,
    ladder to $50 at a $62.50 close, to $62.50 at a $75 close."""
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
# CLAUDE-RULES PROTECTION SPEC v9 (the ONLY change vs the original script)
#
# Reading applied: the ENTIRE original protection module (plain $85 floor
# PLUS the $125/$150 profit ladder) is replaced by:
#   - Episode 1: plain floor = -15% from the pot's start balance
#     ($85.00 on $100; $42.50 on the scaled $50 pot). NO ladder.
#   - On FIRST halt: liquidate exactly as the original engine does
#     (next open, original cost schedule), sit in cash 90 calendar days,
#     then RESTART with the remaining cash; breakout signals resume from
#     closes after day 90 (entries are generated fresh from the restart
#     day's close onward, exactly the strategy's own signal cadence).
#   - Episode 2: floor = -15% from the RESTART balance. On SECOND halt
#     the run ends permanently.
#   - If the 90-day sit-out runs past the window end, the run ends with
#     the liquidation cash (no restart day exists in the window).
# Everything else — signals, parameters, costs, liquidation mechanics —
# is byte-identical to the original engine above.
# ----------------------------------------------------------------------------

from datetime import timedelta


def plain_floor_check(self, d, equity_close):
    """v9 floor test: plain -15% floor only, no ladder raises."""
    if equity_close <= self.floor:
        self.halt_pending = True
        self.halt_trigger_date = d
        return True
    return False


@contextlib.contextmanager
def v9_pot_config(start_cash, floor0):
    """Scaled-pot setup for v9: same START_CASH / initial-floor rescaling
    as the original pot_config, but the floor check is the plain v9 one
    (the original pot_config's scaled_floor_check carried the ladder)."""
    orig_start = T.START_CASH
    orig_init = T.Portfolio.__init__
    orig_fc = T.Portfolio.floor_check

    def scaled_init(self, style_name):
        orig_init(self, style_name)
        self.floor = floor0

    T.START_CASH = start_cash
    T.Portfolio.__init__ = scaled_init
    T.Portfolio.floor_check = plain_floor_check
    try:
        yield
    finally:
        T.START_CASH = orig_start
        T.Portfolio.__init__ = orig_init
        T.Portfolio.floor_check = orig_fc


def run_breakout_v9(mkt, style_name, lookback=252, ma_col="sma20",
                    stop_pct=0.08):
    """run_breakout with ONLY the protection module swapped to spec v9.
    Loop body is the original's, restructured from for/enumerate to an
    index while-loop so a first halt can jump forward 90 calendar days."""
    pf = T.Portfolio(style_name)
    pending_entries = []
    pending_exits = []
    last_t = len(mkt.test_dates) - 1
    episode = 1
    restarts = []
    halt_events = []

    t = 0
    while t <= last_t:
        d = mkt.test_dates[t]
        pos = mkt.test_pos[t]
        if pf.halt_pending:
            pf.liquidate_all(d, pos, mkt.open_map(pos), "floor-liquidation")
            pf.halted = True
            pf.halt_date = d
            pf.equity_curve.append((d, pf.equity(mkt.close_map(pos))))
            halt_events.append({
                "episode": episode,
                "trigger_date": (pf.halt_trigger_date.isoformat()
                                 if pf.halt_trigger_date else None),
                "liquidation_date": d.isoformat(),
                "cash_after_liquidation": round(pf.cash, 2),
            })
            if episode == 2:
                break
            # Episode 1 halt -> cash sit-out of 90 calendar days, restart
            # at the first test day on/after halt_date + 90 days.
            restart_balance = pf.cash
            resume_on_or_after = d + timedelta(days=90)
            j = t + 1
            while j <= last_t and mkt.test_dates[j] < resume_on_or_after:
                pf.equity_curve.append((mkt.test_dates[j], restart_balance))
                j += 1
            if j > last_t:
                restarts.append({
                    "halt_trigger_date": halt_events[-1]["trigger_date"],
                    "liquidation_date": d.isoformat(),
                    "restart_date": None,
                    "restart_balance": round(restart_balance, 2),
                    "note": "90-day sit-out runs past the window end; "
                            "run ends with the liquidation cash.",
                })
                break
            pf.floor = 0.85 * restart_balance
            pf.halt_pending = False
            pf.halted = False
            pf.halt_date = None
            pf.halt_trigger_date = None
            pending_entries = []
            pending_exits = []
            episode = 2
            restarts.append({
                "halt_trigger_date": halt_events[-1]["trigger_date"],
                "liquidation_date": d.isoformat(),
                "restart_date": mkt.test_dates[j].isoformat(),
                "restart_balance": round(restart_balance, 2),
                "episode2_floor": round(pf.floor, 2),
            })
            t = j
            continue

        # 1) close-signal exits scheduled yesterday fill at today's open
        for sym, reason in pending_exits:
            if pf.shares_of(sym) > 0:
                pf.sell(d, pos, sym, mkt.price(sym, pos, "open"), reason)
        pending_exits = []

        # 2) entries at today's open
        candidates = list(pending_entries)
        pending_entries = []
        for sym in candidates:
            if pf.shares_of(sym) > 0 or len(pf.held_symbols()) >= 2:
                continue
            eq_open = pf.equity(mkt.open_map(pos))
            pf.buy(d, pos, sym, mkt.price(sym, pos, "open"),
                   0.5 * eq_open, "entry")

        # 3) intraday stop, stop-first semantics identical to the original
        if stop_pct is not None:
            for sym in list(pf.held_symbols()):
                entry = pf.weighted_entry_price(sym)
                if entry is None:
                    continue
                o = mkt.price(sym, pos, "open")
                low = mkt.price(sym, pos, "low")
                stop_px = entry * (1 - stop_pct)
                fill, reason = None, None
                if o <= stop_px:
                    fill, reason = o, "stop-gap"
                elif low <= stop_px:
                    fill, reason = stop_px, "stop"
                if fill is not None:
                    pf.sell(d, pos, sym, fill, reason)

        # 4) mark to close, v9 plain floor test (floor_check is patched)
        eq_close = pf.equity(mkt.close_map(pos))
        pf.equity_curve.append((d, eq_close))
        touched = pf.floor_check(d, eq_close)
        if touched and t == last_t:
            pf.halted = True
            pf.halt_date = d
            halt_events.append({
                "episode": episode,
                "trigger_date": d.isoformat(),
                "liquidation_date": None,
                "cash_after_liquidation": round(pf.cash, 2),
                "note": "floor touched on the final day; original engine "
                        "ends the run here (no next open to liquidate at).",
            })
            break
        if t == last_t:
            break

        # 5) schedule MA exits for tomorrow's open
        for sym in list(pf.held_symbols()):
            ma = mkt.frames[sym][ma_col].iloc[pos]
            if not np.isnan(ma) and mkt.price(sym, pos, "close") < ma:
                pending_exits.append((sym, "ma-exit"))

        # 6) generate tomorrow's entries from today's close signals
        for sym in UNIVERSE:
            if pf.shares_of(sym) > 0:
                continue
            if breakout_signal(mkt, sym, pos, lookback):
                pending_entries.append(sym)
        t += 1

    pf.v9_restarts = restarts
    pf.v9_halt_events = halt_events
    return pf


# ----------------------------------------------------------------------------
# Sharpe / deflated Sharpe
# ----------------------------------------------------------------------------

def sharpe_stats(pf):
    eq = [T.START_CASH] + [e for _, e in pf.equity_curve]
    rets = np.diff(np.array(eq)) / np.array(eq[:-1])
    n = len(rets)
    mu, sd = float(rets.mean()), float(rets.std(ddof=1))
    sr_d = mu / sd if sd > 0 else 0.0
    z = (rets - mu) / sd
    skew = float((z ** 3).mean())
    kurt = float((z ** 4).mean())  # raw kurtosis (normal = 3)
    return {"n_days": n, "sr_daily": sr_d,
            "sr_annual": sr_d * math.sqrt(252),
            "skew": skew, "kurtosis": kurt}


def deflated_sharpe(sr_daily, skew, kurt, n_obs, n_trials, trial_sr_std_annual):
    """Bailey & Lopez de Prado DSR. trial_sr_std_annual = assumed standard
    deviation of annualized Sharpe ratios across the trials run in the
    program (stated assumption - the true cross-trial dispersion is not
    observable from one winner's curve)."""
    var_daily = (trial_sr_std_annual ** 2) / 252.0
    z1 = ND.inv_cdf(1 - 1 / n_trials)
    z2 = ND.inv_cdf(1 - 1 / (n_trials * math.e))
    sr0 = math.sqrt(var_daily) * ((1 - EULER_GAMMA) * z1 + EULER_GAMMA * z2)
    denom = math.sqrt(max(1 - skew * sr_daily
                          + (kurt - 1) / 4 * sr_daily ** 2, 1e-12))
    dsr = ND.cdf((sr_daily - sr0) * math.sqrt(n_obs - 1) / denom)
    return {"sr0_daily": sr0, "sr0_annual": sr0 * math.sqrt(252), "dsr": dsr}


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def brief(pf, mkt):
    r = T.score(pf, mkt.test_dates[0])
    return r


def main():
    """v9 driver: ONLY the runs whose ranked pot halted under his rules
    are re-run (validation $100 and validation $50). All other original
    runs never halted, so under a floor that is never higher than his
    (plain $85 vs his $85 + ladder raises) their trajectories are
    unchanged -- see the report. Placebos are not re-run (ranked pots
    only). His-mode replication runs first and must reproduce the
    recorded finals/halts before any v9 number is trusted."""
    print("Loading data (tournament cache)...")
    frames = build_frames()
    out = {"replication_his_mode": {}, "v9": {}}

    mkt = make_market(frames, VALIDATION)

    # ---- replication, his rules exactly as recorded -------------------
    pf = run_breakout(mkt, "c_breakout52")
    r = brief(pf, mkt)
    out["replication_his_mode"]["validation_100"] = r
    print(f"HIS replication VALIDATION $100: ${r['final']:,.2f} "
          f"halt {r['halt_date'] or '-'} (recorded: $124.82, 2026-08-14)")
    with pot_config(50.0, 42.50, 62.50, 50.0, 75.0, 62.50):
        pf50 = run_breakout(mkt, "c_breakout52_50")
        r50 = brief(pf50, mkt)
    out["replication_his_mode"]["validation_50"] = r50
    print(f"HIS replication VALIDATION $50: ${r50['final']:,.2f} "
          f"halt {r50['halt_date'] or '-'} (recorded: $62.25, 2026-08-13)")

    # ---- v9 runs --------------------------------------------------------
    orig_fc = T.Portfolio.floor_check
    T.Portfolio.floor_check = plain_floor_check
    try:
        pf_v9 = run_breakout_v9(mkt, "c_breakout52")
    finally:
        T.Portfolio.floor_check = orig_fc
    r_v9 = brief(pf_v9, mkt)
    curve = [(VALIDATION[0], 100.0)] + list(pf_v9.equity_curve)
    worst = min(e for _, e in curve)
    out["v9"]["validation_100"] = {
        "stats": r_v9, "restarts": pf_v9.v9_restarts,
        "halt_events": pf_v9.v9_halt_events,
        "worst_total_loss_pct": round((worst / 100.0 - 1) * 100, 2),
        "min_equity": round(worst, 2),
    }
    print(f"V9 VALIDATION $100: ${r_v9['final']:,.2f} "
          f"halt {r_v9['halt_date'] or '-'} restarts {pf_v9.v9_restarts}")

    with v9_pot_config(50.0, 42.50):
        pf50_v9 = run_breakout_v9(mkt, "c_breakout52_50")
        r50_v9 = brief(pf50_v9, mkt)
    curve50 = [(VALIDATION[0], 50.0)] + list(pf50_v9.equity_curve)
    worst50 = min(e for _, e in curve50)
    out["v9"]["validation_50"] = {
        "stats": r50_v9, "restarts": pf50_v9.v9_restarts,
        "halt_events": pf50_v9.v9_halt_events,
        "worst_total_loss_pct": round((worst50 / 50.0 - 1) * 100, 2),
        "min_equity": round(worst50, 2),
    }
    print(f"V9 VALIDATION $50: ${r50_v9['final']:,.2f} "
          f"halt {r50_v9['halt_date'] or '-'} restarts {pf50_v9.v9_restarts}")

    path = os.path.join(HERE, "v9-driver-results.json")
    with open(path, "w") as fh:
        json.dump(out, fh, indent=2, default=str)
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
