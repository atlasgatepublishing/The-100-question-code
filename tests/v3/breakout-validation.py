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
V2_DIR = os.path.join(HERE, "..", "v2")
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
    print("Loading data (tournament cache)...")
    frames = build_frames()
    results = {}

    # ---- full window, original rules -------------------------------------
    mkt_full = make_market(frames, FULL)
    pf_full = run_breakout(mkt_full, "c_breakout52")
    r_full = brief(pf_full, mkt_full)
    spy_g, spy_n = T.spy_benchmark(mkt_full)
    results["full"] = {"strategy": r_full, "spy_gross": spy_g, "spy_net": spy_n}
    print(f"FULL: strategy ${r_full['final']:,.2f} vs SPY net ${spy_n:,.2f} "
          f"(sanity: tournament said $383.36 / $314.10)")

    # ---- 1. per-year table -------------------------------------------------
    spy_df = frames["SPY"]
    spy_close = {d: float(c) for d, c in zip(spy_df["date"], spy_df["close"])}
    spy_open_first = float(spy_df["open"].iloc[mkt_full.test_pos[0]])
    curve = list(pf_full.equity_curve)
    per_year = []
    prev_eq, prev_spy_px = T.START_CASH, spy_open_first
    for year in range(2016, 2027):
        in_year = [(d, e) for d, e in curve if d.year == year]
        if not in_year:
            continue
        end_eq = in_year[-1][1]
        last_day = in_year[-1][0]
        spy_end = spy_close[last_day]
        per_year.append({
            "year": year, "start": prev_eq, "end": end_eq,
            "pot_ret_pct": (end_eq / prev_eq - 1) * 100,
            "spy_ret_pct": (spy_end / prev_spy_px - 1) * 100,
        })
        prev_eq, prev_spy_px = end_eq, spy_end
    results["per_year"] = per_year

    # ---- 2. design vs validation -------------------------------------------
    for name, window in (("design", DESIGN), ("validation", VALIDATION)):
        mkt = make_market(frames, window)
        pf = run_breakout(mkt, "c_breakout52")
        r = brief(pf, mkt)
        g, n_ = T.spy_benchmark(mkt)
        results[name] = {"strategy": r, "spy_gross": g, "spy_net": n_}
        print(f"{name.upper()}: strategy ${r['final']:,.2f} vs SPY net "
              f"${n_:,.2f} (gross ${g:,.2f}), halt {r['halt_date'] or '-'}")

    # ---- 3. fixed placebos ---------------------------------------------------
    for name, window in (("full", FULL), ("validation", VALIDATION)):
        mkt = make_market(frames, window)
        real = run_breakout(mkt, "c_breakout52")
        target = entries_by_year(real)
        ppf, meta = run_placebo_matched(mkt, target)
        pr = brief(ppf, mkt)
        results[f"placebo_{name}"] = {"placebo": pr, **meta}
        print(f"PLACEBO {name.upper()}: ${pr['final']:,.2f} "
              f"(attempts {meta['attempts']}, target {meta['target_by_year']}, "
              f"actual {meta['actual_by_year']})")

    # ---- 4. cost stress 2x ---------------------------------------------------
    T.COST_RATE, T.SELL_FEE = 0.002, 0.02
    try:
        mkt = make_market(frames, FULL)
        pf2x = run_breakout(mkt, "c_breakout52")
        r2x = brief(pf2x, mkt)
    finally:
        T.COST_RATE, T.SELL_FEE = 0.001, 0.01
    results["cost2x"] = {"strategy": r2x, "spy_net_1x": spy_n}
    print(f"COST 2x: strategy ${r2x['final']:,.2f} (costs "
          f"${r2x['total_costs']:,.2f}) vs SPY net 1x ${spy_n:,.2f}")

    # ---- 4b. $50 starting pot (Terry's rule change) --------------------------
    s50 = {}
    with pot_config(50.0, 42.50, 62.50, 50.0, 75.0, 62.50):
        for name, window in (("full", FULL), ("validation", VALIDATION)):
            mkt = make_market(frames, window)
            pf50 = run_breakout(mkt, "c_breakout52_50")
            r50 = brief(pf50, mkt)
            g50, n50 = T.spy_benchmark(mkt)
            s50[name] = {"strategy": r50, "spy_gross": g50, "spy_net": n50,
                         "costs_pct_of_pot": r50["total_costs"] / 50.0 * 100}
            print(f"$50 {name.upper()}: strategy ${r50['final']:,.2f} "
                  f"({r50['total_pct']:+.1f}%) vs SPY net ${n50:,.2f}, "
                  f"costs ${r50['total_costs']:,.2f} "
                  f"({s50[name]['costs_pct_of_pot']:.1f}% of pot), "
                  f"halt {r50['halt_date'] or '-'}")
    results["start50"] = s50
    results["full"]["costs_pct_of_pot"] = r_full["total_costs"] / 100.0 * 100
    results["validation"]["costs_pct_of_pot"] = \
        results["validation"]["strategy"]["total_costs"] / 100.0 * 100

    # ---- 5. parameter neighbors ----------------------------------------------
    grid = []
    for lookback in (200, 252, 300):
        for ma_col in ("sma20", "sma50"):
            for stop in (0.08, 0.10):
                mkt = make_market(frames, FULL)
                gpf = run_breakout(mkt, "c_breakout52_grid", lookback=lookback,
                                   ma_col=ma_col, stop_pct=stop)
                gr = brief(gpf, mkt)
                grid.append({"lookback": lookback,
                             "ma_exit": 20 if ma_col == "sma20" else 50,
                             "stop_pct": stop * 100, "final": gr["final"],
                             "total_pct": gr["total_pct"],
                             "max_dd_pct": gr["max_dd_pct"],
                             "closed_trades": gr["closed_trades"],
                             "total_costs": gr["total_costs"],
                             "halt_date": gr["halt_date"],
                             "beat_spy_net": gr["final"] > spy_n})
                print(f"GRID lb={lookback} ma={grid[-1]['ma_exit']} "
                      f"stop={stop:.0%}: ${gr['final']:,.2f} "
                      f"(DD {gr['max_dd_pct']:.1f}%, halt "
                      f"{gr['halt_date'] or '-'})")
    results["grid"] = grid

    # ---- 6. Sharpe / deflated Sharpe ------------------------------------------
    ss = sharpe_stats(pf_full)
    dsr_table = []
    for n_trials in (17, 30, 50):
        for disp in (0.30, 0.40, 0.50):
            d = deflated_sharpe(ss["sr_daily"], ss["skew"], ss["kurtosis"],
                                ss["n_days"], n_trials, disp)
            dsr_table.append({"n_trials": n_trials,
                              "trial_sr_std_annual": disp, **d})
    results["sharpe"] = {**ss, "dsr_table": dsr_table}
    print(f"SHARPE: daily {ss['sr_daily']:.4f}, annual {ss['sr_annual']:.3f}, "
          f"skew {ss['skew']:.2f}, kurt {ss['kurtosis']:.2f}, "
          f"n={ss['n_days']}")
    for row in dsr_table:
        print(f"  DSR N={row['n_trials']} disp={row['trial_sr_std_annual']}: "
              f"SR0 ann {row['sr0_annual']:.3f}, DSR {row['dsr']:.4f}")

    out = os.path.join(HERE, "breakout-validation-results.json")
    with open(out, "w") as fh:
        json.dump(results, fh, indent=2, default=str)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
