#!/usr/bin/env python3
"""
Gap-up continuation (v2 tournament style G) — v10 GREAT RETEST engine.

Self-contained. The Portfolio, data alignment, gap signal, intraday
stop/target logic, time exit, scoring and placebo-schedule code are copied
from backtests/v2/tournament.py (style G form) so the integrity run is a
true reproduction; the cadence filter and the v9 protection state machine
are the only additions, and both are switchable:

  - protection="ladder"  -> original tournament floor (85, ladder to 100 at
    a $125 close, 125 at a $150 close; a touch liquidates at the next open
    and ENDS the run). Used ONLY for the integrity reproduction.
  - protection="v9"      -> SPEC v9 rules: plain -15% floor from the
    episode's starting balance, no ladder; first halt liquidates at the
    next open, cash for 90 calendar days, restart at the next cadence date
    on/after the wait, episode-2 floor -15% from the restart balance;
    second halt ends the run.

CADENCE TREATMENT (uniform SPEC definition, stated precisely):
  - Cadence dates: daily = every trading day; weekly = first trading day
    of each ISO week; biweekly = first trading day of every second week
    (anchored on the first test week); monthly = first trading day of each
    month; quarterly = first trading day of each calendar quarter;
    semi-annual = first trading day of each half-year; annual = first
    trading day of each year.
  - Entries: the published gap gate (today's open > 3% above yesterday's
    close AND yesterday's volume > 1.5x the mean volume of the 20 sessions
    ending two sessions ago) is evaluated ONLY at the open of cadence
    dates; fills at that open. Max 2 positions, 50% of open equity each
    (tournament sizing, unchanged).
  - Exits: reviewed ONLY on cadence dates. On a cadence date, after
    entries, the -4% stop / +8% target are checked against that day's bar
    with the tournament's stop-first / gap-through-at-open rules; then the
    3-trading-day time exit fires at that day's close if the position has
    been held >= 3 trading days (at any cadence slower than daily the next
    cadence date is always >= 3 trading days later, so in practice a
    position exits at the first cadence date after entry at the latest).
  - The v9 floor is a protection overlay, not a strategy decision: it is
    marked at every close and liquidates at the next open in every cell
    (identical across cadences); only the RESTART waits for a cadence
    date, per the SPEC ("restart at the strategy's next regular decision
    point").

Data: split-adjusted daily bars read READ-ONLY from the tournament's own
cache, backtests/v2/tournament-data/*.csv (the exact bars the original
tournament ran on). Universe = the tournament STOCK_UNIVERSE (10 names).
Costs: 0.10% per side + $0.01 per sell order (tournament conventions).
Window: DECADE 2016-11-21 -> 2026-11-20 (the tournament window itself).

Simulation only. No broker orders are placed by this script.
"""

import json
import os
from datetime import date, timedelta

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_CACHE = os.path.join(HERE, "..", "..", "v2", "tournament-data")

TEST_START = date(2016, 11, 21)
TEST_END = date(2026, 11, 20)

STOCK_UNIVERSE = ["SPY", "QQQ", "NVDA", "TSLA", "AAPL",
                  "MSFT", "AMZN", "META", "AMD", "AVGO"]

START_CASH = 100.0
COST_RATE = 0.001                 # 0.10% per side
SELL_FEE = 0.01                   # per sell order

STOP_PCT = 0.04
TARGET_PCT = 0.08
TIME_EXIT_DAYS = 3
MAX_POSITIONS = 2
FRAC = 0.5

CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]


# ----------------------------------------------------------------------------
# Data loading (copied from tournament.py: _fallback-free cache read +
# align_frames + the vol_base indicator the gap rule needs)
# ----------------------------------------------------------------------------

def load_symbol(symbol):
    cache_path = os.path.join(SRC_CACHE, f"{symbol}.csv")
    df = pd.read_csv(cache_path)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def add_indicators(df):
    v = df["volume"].astype(float)
    # Volume baseline for the gap rule: mean volume of the 20 sessions ending
    # two sessions ago (tournament definition, verbatim).
    df["vol_base"] = v.shift(2).rolling(20).mean()
    return df


def align_frames(raw):
    """Reindex every symbol onto SPY's calendar (tournament, verbatim)."""
    spy_dates = raw["SPY"]["date"]
    frames = {}
    for sym, df in raw.items():
        df = df.set_index("date").reindex(spy_dates)
        real = df["close"].notna()
        df[["open", "high", "low", "close"]] = \
            df[["open", "high", "low", "close"]].ffill()
        df["volume"] = df["volume"].fillna(0)
        df = add_indicators(df.reset_index().rename(columns={"index": "date"}))
        df["real"] = real.values
        frames[sym] = df
    return frames


class Market:
    def __init__(self, frames):
        self.frames = frames
        spy = frames["SPY"]
        self.dates = list(spy["date"])
        self.pos_of = {d: i for i, d in enumerate(self.dates)}
        self.test_dates = [d for d in self.dates if TEST_START <= d <= TEST_END]
        self.test_pos = [self.pos_of[d] for d in self.test_dates]

    def price(self, symbol, pos, field="close"):
        df = self.frames[symbol]
        if pos < 0 or pos >= len(df):
            return None
        return float(df[field].iloc[pos])

    def close_map(self, pos):
        return {s: self.price(s, pos, "close") for s in self.frames}

    def open_map(self, pos):
        return {s: self.price(s, pos, "open") for s in self.frames}


# ----------------------------------------------------------------------------
# Portfolio (copied from tournament.py; floor ladder kept for integrity mode)
# ----------------------------------------------------------------------------

class Portfolio:
    def __init__(self, style_name):
        self.style = style_name
        self.cash = START_CASH
        self.lots = {}
        self.trades = []
        self.round_trips = []
        self.total_costs = 0.0
        self.floor = 85.0
        self.halt_pending = False
        self.halted = False
        self.halt_trigger_date = None
        self.halt_date = None
        self.equity_curve = []

    def held_symbols(self):
        return [s for s, lots in self.lots.items()
                if sum(l["shares"] for l in lots) > 1e-12]

    def shares_of(self, symbol):
        return sum(l["shares"] for l in self.lots.get(symbol, []))

    def equity(self, price_map):
        total = self.cash
        for sym in self.held_symbols():
            px = price_map.get(sym)
            if px is not None:
                total += self.shares_of(sym) * px
        return total

    def weighted_entry_price(self, symbol):
        lots = self.lots.get(symbol, [])
        sh = sum(l["shares"] for l in lots)
        if sh <= 0:
            return None
        return sum(l["shares"] * l["entry_price"] for l in lots) / sh

    def entry_pos(self, symbol):
        lots = self.lots.get(symbol, [])
        if not lots:
            return None
        return min(l["entry_pos"] for l in lots)

    def buy(self, d, pos, symbol, price, target_value, reason):
        if price is None or price <= 0 or target_value <= 0:
            return False
        value = min(target_value, self.cash / (1 + COST_RATE))
        if value < 1.0:
            return False
        cost = COST_RATE * value
        shares = value / price
        self.cash -= value + cost
        self.total_costs += cost
        self.lots.setdefault(symbol, []).append({
            "shares": shares, "entry_price": price, "entry_pos": pos,
            "entry_date": d, "buy_cost": cost, "realized": 0.0,
        })
        self.trades.append({
            "style": self.style, "date": d.isoformat(), "symbol": symbol,
            "side": "buy", "price": round(price, 4), "shares": round(shares, 6),
            "value": round(value, 2), "cost": round(cost, 4),
            "reason": reason, "pnl": "",
        })
        return True

    def sell(self, d, pos, symbol, price, reason, shares_to_sell=None):
        held = self.shares_of(symbol)
        if held <= 1e-12 or price is None or price <= 0:
            return False
        if shares_to_sell is None:
            shares_to_sell = held
        shares_to_sell = min(shares_to_sell, held)
        value = shares_to_sell * price
        cost = COST_RATE * value + SELL_FEE
        proceeds = value - cost
        self.cash += proceeds
        self.total_costs += cost
        remaining = shares_to_sell
        lots = self.lots.get(symbol, [])
        while remaining > 1e-12 and lots:
            lot = lots[0]
            take = min(lot["shares"], remaining)
            frac = take / lot["shares"] if lot["shares"] > 0 else 0
            basis = take * lot["entry_price"] + lot["buy_cost"] * frac
            lot_proceeds = proceeds * (take / shares_to_sell)
            lot["realized"] += lot_proceeds - basis
            lot["shares"] -= take
            lot["buy_cost"] -= lot["buy_cost"] * frac
            remaining -= take
            if lot["shares"] <= 1e-12:
                self.round_trips.append({
                    "symbol": symbol, "entry_date": lot["entry_date"].isoformat(),
                    "exit_date": d.isoformat(), "pnl": lot["realized"],
                    "reason": reason,
                })
                lots.pop(0)
        if not lots:
            self.lots.pop(symbol, None)
        self.trades.append({
            "style": self.style, "date": d.isoformat(), "symbol": symbol,
            "side": "sell", "price": round(price, 4),
            "shares": round(shares_to_sell, 6), "value": round(value, 2),
            "cost": round(cost, 4), "reason": reason, "pnl": "",
        })
        return True

    def liquidate_all(self, d, pos, price_map, reason):
        for sym in list(self.held_symbols()):
            px = price_map.get(sym)
            if px is not None:
                self.sell(d, pos, sym, px, reason)

    def floor_check_ladder(self, d, equity_close):
        """Tournament-era ladder floor (integrity mode only)."""
        if equity_close >= 150.0:
            self.floor = max(self.floor, 125.0)
        elif equity_close >= 125.0:
            self.floor = max(self.floor, 100.0)
        if equity_close <= self.floor:
            self.halt_pending = True
            self.halt_trigger_date = d
            return True
        return False


# ----------------------------------------------------------------------------
# Gap signal (tournament, verbatim)
# ----------------------------------------------------------------------------

def gap_signal_at_open(mkt, sym, pos):
    """Evaluated at the open of day `pos`: gap vs prior close, prior-day
    volume vs the 20 sessions before it."""
    df = mkt.frames[sym]
    if pos < 22:
        return False
    o = df["open"].iloc[pos]
    pc = df["close"].iloc[pos - 1]
    pv = df["volume"].iloc[pos - 1]
    base = df["vol_base"].iloc[pos]
    if pc <= 0 or np.isnan(base) or base <= 0:
        return False
    return bool(o / pc - 1 > 0.03 and pv > 1.5 * base)


# ----------------------------------------------------------------------------
# Cadence calendars
# ----------------------------------------------------------------------------

def cadence_dates(test_dates, cadence):
    if cadence == "daily":
        return set(test_dates)
    out = []
    seen = set()
    if cadence == "weekly":
        for d in test_dates:
            key = (d.isocalendar()[0], d.isocalendar()[1])
            if key not in seen:
                seen.add(key)
                out.append(d)
    elif cadence == "biweekly":
        weeks = []
        seen_w = set()
        for d in test_dates:
            key = (d.isocalendar()[0], d.isocalendar()[1])
            if key not in seen_w:
                seen_w.add(key)
                weeks.append(d)
        out = weeks[::2]
    elif cadence == "monthly":
        for d in test_dates:
            key = (d.year, d.month)
            if key not in seen:
                seen.add(key)
                out.append(d)
    elif cadence == "quarterly":
        for d in test_dates:
            key = (d.year, (d.month - 1) // 3)
            if key not in seen:
                seen.add(key)
                out.append(d)
    elif cadence == "semiannual":
        for d in test_dates:
            key = (d.year, (d.month - 1) // 6)
            if key not in seen:
                seen.add(key)
                out.append(d)
    elif cadence == "annual":
        for d in test_dates:
            if d.year not in seen:
                seen.add(d.year)
                out.append(d)
    else:
        raise ValueError(cadence)
    return set(out)


# ----------------------------------------------------------------------------
# Runner — style G under a cadence + a protection regime
# ----------------------------------------------------------------------------

def run_gap(mkt, style_name, cadence="daily", protection="v9",
            placebo_schedule=None):
    """Returns (portfolio, events) where events records halts/restarts."""
    pf = Portfolio(style_name)
    cad = cadence_dates(mkt.test_dates, cadence)
    last_t = len(mkt.test_dates) - 1
    events = {"halts": [], "restart_date": None, "second_halt": False}

    # v9 state
    episode_floor = 0.85 * START_CASH
    state = "active"            # active | waiting
    halt_count = 0
    restart_eligible = None     # first date the 90-day wait is over
    pending_halt_idx = None     # index into events["halts"] awaiting liq.

    for t, d in enumerate(mkt.test_dates):
        pos = mkt.test_pos[t]

        # --- pending floor liquidation fills at today's open ---------------
        if pf.halt_pending:
            n_before = len(pf.trades)
            pf.liquidate_all(d, pos, mkt.open_map(pos), "floor-liquidation")
            if pending_halt_idx is not None:
                events["halts"][pending_halt_idx]["liquidation_date"] = \
                    d.isoformat()
                events["halts"][pending_halt_idx]["positions_liquidated"] = \
                    len(pf.trades) - n_before
                pending_halt_idx = None
            pf.halt_date = d
            pf.halt_pending = False
            eq = pf.equity(mkt.close_map(pos))
            pf.equity_curve.append((d, eq))
            if protection == "ladder" or halt_count >= 2:
                pf.halted = True
                if halt_count >= 2:
                    events["second_halt"] = True
                break
            # v9 first halt: sit in cash 90 calendar days
            state = "waiting"
            restart_eligible = d + timedelta(days=90)
            continue

        # --- v9 cash wait ---------------------------------------------------
        if protection == "v9" and state == "waiting":
            if d in cad and d >= restart_eligible:
                state = "active"
                episode_floor = 0.85 * pf.cash
                events["restart_date"] = d.isoformat()
                # fall through and trade on this cadence date
            else:
                pf.equity_curve.append((d, pf.cash))
                continue

        # --- strategy decisions: cadence dates only -------------------------
        if d in cad:
            # entries at today's open
            if placebo_schedule is not None:
                candidates = list(placebo_schedule.get(d, []))
            else:
                candidates = [s for s in STOCK_UNIVERSE
                              if gap_signal_at_open(mkt, s, pos)]
            for sym in candidates:
                if pf.shares_of(sym) > 0 or \
                        len(pf.held_symbols()) >= MAX_POSITIONS:
                    continue
                eq_open = pf.equity(mkt.open_map(pos))
                pf.buy(d, pos, sym, mkt.price(sym, pos, "open"),
                       FRAC * eq_open, "entry")

            # intraday stop / target, stop-first (tournament, verbatim logic)
            for sym in list(pf.held_symbols()):
                entry = pf.weighted_entry_price(sym)
                if entry is None:
                    continue
                o = mkt.price(sym, pos, "open")
                h = mkt.price(sym, pos, "high")
                l = mkt.price(sym, pos, "low")
                stop_px = entry * (1 - STOP_PCT)
                tgt_px = entry * (1 + TARGET_PCT)
                fill, reason = None, None
                if o <= stop_px:
                    fill, reason = o, "stop-gap"
                elif o >= tgt_px:
                    fill, reason = o, "target-gap"
                elif l <= stop_px and h >= tgt_px:
                    fill, reason = stop_px, "stop-first"
                elif l <= stop_px:
                    fill, reason = stop_px, "stop"
                elif h >= tgt_px:
                    fill, reason = tgt_px, "target"
                if fill is not None:
                    pf.sell(d, pos, sym, fill, reason)

            # time exit at the close of the Nth trading day
            for sym in list(pf.held_symbols()):
                ep = pf.entry_pos(sym)
                if ep is not None and pos - ep >= TIME_EXIT_DAYS:
                    pf.sell(d, pos, sym, mkt.price(sym, pos, "close"),
                            "time-exit")

        # --- mark to close, floor test --------------------------------------
        eq_close = pf.equity(mkt.close_map(pos))
        pf.equity_curve.append((d, eq_close))
        if protection == "ladder":
            touched = pf.floor_check_ladder(d, eq_close)
        else:
            touched = eq_close <= episode_floor
            if touched:
                pf.halt_pending = True
                pf.halt_trigger_date = d
                halt_count += 1
                events["halts"].append({
                    "n": halt_count,
                    "trigger_date": d.isoformat(),
                    "floor": round(episode_floor, 2),
                    "equity_at_trigger": round(eq_close, 2),
                })
                pending_halt_idx = len(events["halts"]) - 1
        if touched and t == last_t:
            pf.halted = True
            pf.halt_date = d
            if protection == "v9" and halt_count >= 2:
                events["second_halt"] = True
            # record liquidation date as the trigger date when no next day
            if events["halts"]:
                events["halts"][-1]["liquidation_date"] = d.isoformat()
            break

    return pf, events


# ----------------------------------------------------------------------------
# Placebo schedules (tournament generator, verbatim draw pattern)
# ----------------------------------------------------------------------------

def make_placebo_schedule(pool_dates, universe, n_entries, seed):
    rng = np.random.default_rng(seed)
    schedule = {}
    for _ in range(n_entries):
        d = pool_dates[rng.integers(0, len(pool_dates))]
        sym = universe[rng.integers(0, len(universe))]
        schedule.setdefault(d, []).append(sym)
    return schedule


# ----------------------------------------------------------------------------
# Scoring (tournament, verbatim)
# ----------------------------------------------------------------------------

def score(pf, start_date):
    curve = [(start_date, START_CASH)] + list(pf.equity_curve)
    final = curve[-1][1]
    end_date = curve[-1][0]
    peak, max_dd = START_CASH, 0.0
    for _, eq in curve:
        peak = max(peak, eq)
        if peak > 0:
            max_dd = max(max_dd, (peak - eq) / peak)
    years = max((end_date - start_date).days, 1) / 365.25
    cagr = (final / START_CASH) ** (1 / years) - 1 if final > 0 else -1.0
    rts = pf.round_trips
    wins = [r for r in rts if r["pnl"] > 0]
    buys = sum(1 for tr in pf.trades if tr["side"] == "buy")
    return {
        "style": pf.style,
        "final": final,
        "total_pct": (final / START_CASH - 1) * 100,
        "cagr_pct": cagr * 100,
        "orders": len(pf.trades),
        "entries": buys,
        "closed_trades": len(rts),
        "win_rate": (100 * len(wins) / len(rts)) if rts else None,
        "max_dd_pct": max_dd * 100,
        "total_costs": pf.total_costs,
        "halt_date": (pf.halt_date.isoformat() if pf.halted and pf.halt_date
                      else None),
        "end_date": end_date.isoformat(),
        "open_positions": pf.held_symbols(),
    }


def spy_benchmark_price_only(mkt):
    """Tournament convention: buy at first test open, sell at last close."""
    first_pos, last_pos = mkt.test_pos[0], mkt.test_pos[-1]
    o = mkt.price("SPY", first_pos, "open")
    c = mkt.price("SPY", last_pos, "close")
    gross_final = START_CASH / o * c
    buy_value = START_CASH / (1 + COST_RATE)
    shares = buy_value / o
    sell_value = shares * c
    net_final = sell_value - (COST_RATE * sell_value + SELL_FEE)
    return gross_final, net_final


def build_market():
    raw = {sym: load_symbol(sym) for sym in STOCK_UNIVERSE}
    frames = align_frames(raw)
    return Market(frames)
