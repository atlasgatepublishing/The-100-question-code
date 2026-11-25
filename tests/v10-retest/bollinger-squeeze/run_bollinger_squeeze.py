#!/usr/bin/env python3
"""
THE GREAT RETEST (v10) - bollinger-squeeze (tournament style E).

Strategy (v2 tournament form, frozen): buy the first close above the upper
Bollinger band (20, 2) after bandwidth sat at a 6-month (126-session) low;
fill at the next open; max 2 positions, 50% of equity each; exit on a close
below the 20-day average (executed at the next open) or an intraday -8% stop
(stop-first rule). Universe: the tournament STOCK_UNIVERSE (10 names).

Modes:
  integrity  - the ORIGINAL tournament engine, copied verbatim below
               (Portfolio / Market / run_discrete / sig_squeeze / score),
               ladder-era floor ($85, rising to $100 at a $125 close and
               $125 at a $150 close; a close at/below the floor liquidates
               at the next open and ENDS the run). Target: final $154.47,
               max DD 13.4%, 72 orders, 36 closed trades, costs $4.96,
               never halted (backtests/v2/tournament.md).
  selfcheck  - the cadence engine below at cadence=daily with the ladder
               floor must reproduce the integrity run exactly; this proves
               the cadence gating is a no-op at the native daily tempo.
  sweep      - DECADE 2016-11-21 -> 2026-11-20 at 7 cadences under the
               SPEC's uniform cadence definition (signal evaluation,
               entries, MA-exit checks and -8% stop checks happen ONLY on
               cadence dates; fills at the cadence date's open from the
               previous cadence date's close signals) with v9 protections:
               plain -15% floor from the episode's starting balance
               (floor = round(0.85 * episode start, 2)); a close at/below
               the floor liquidates everything at the next open; on the
               first halt the pot sits in cash 90 calendar days and
               restarts at the next cadence date on/after liquidation+90d
               under an episode-2 floor of -15% from the restart balance;
               a second halt ends the run. The floor itself is a
               protection, not a signal: it is checked at every close.
               Plus 20-seed random-entry placebos per cell (identical
               exits / sizing / costs / protections; entry count matched
               to the real run's buy count; seeds 91001..91020).

Data: split-adjusted Yahoo daily bars, NOT dividend-adjusted - the exact
tournament convention. Bars are the tournament's own cache, copied into
this folder's data/ from backtests/v2/tournament-data/ (read-only source).
SPY dividend-adjusted decade final is computed separately from the
adjclose payload in backtests/v7/long-hold/data/pxfull_SPY.json
(read-only) using the long-run plumbing's bars_adj convention
(open/close scaled by adjclose/close), program costs applied.

Simulation only. No broker orders are placed by this script.
"""

import json
import math
import os
import sys
from datetime import date

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
CELLS_DIR = os.path.join(HERE, "cells")
SPY_ADJ_PAYLOAD = os.path.join(
    HERE, "..", "..", "v7", "long-hold", "data", "pxfull_SPY.json")

TEST_START = date(2016, 11, 21)
TEST_END = date(2026, 11, 20)

STOCK_UNIVERSE = ["SPY", "QQQ", "NVDA", "TSLA", "AAPL",
                  "MSFT", "AMZN", "META", "AMD", "AVGO"]

START_CASH = 100.0
COST_RATE = 0.001                 # 0.10% per side
SELL_FEE = 0.01                   # per sell order

CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]
PLACEBO_SEEDS = [91000 + s for s in range(1, 21)]   # 91001..91020


# ----------------------------------------------------------------------------
# Data loading (tournament.py, adapted only to read this folder's data/)
# ----------------------------------------------------------------------------

def load_symbol(symbol):
    cache_path = os.path.join(DATA_DIR, f"{symbol}.csv")
    df = pd.read_csv(cache_path)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def add_indicators(df):
    c = df["close"]
    v = df["volume"].astype(float)
    df["sma20"] = c.rolling(20).mean()
    df["sma50"] = c.rolling(50).mean()
    df["sma200"] = c.rolling(200).mean()
    # Wilder RSI(2)
    delta = c.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / 2, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 2, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi2"] = 100 - 100 / (1 + rs)
    df.loc[(avg_loss == 0) & (avg_gain > 0), "rsi2"] = 100.0
    df.loc[(avg_gain == 0) & (avg_loss > 0), "rsi2"] = 0.0
    # Bollinger bands (20, 2) and bandwidth
    mid = c.rolling(20).mean()
    sd = c.rolling(20).std(ddof=0)
    df["bb_mid"] = mid
    df["bb_upper"] = mid + 2 * sd
    df["bb_lower"] = mid - 2 * sd
    df["bb_bw"] = (df["bb_upper"] - df["bb_lower"]) / mid
    # Highest close of the prior 252 sessions (for the 52-week-high breakout)
    df["prior252_high_close"] = c.shift(1).rolling(252).max()
    # Volume baseline for the gap rule
    df["vol_base"] = v.shift(2).rolling(20).mean()
    return df


# ----------------------------------------------------------------------------
# Portfolio (VERBATIM from backtests/v2/tournament.py)
# ----------------------------------------------------------------------------

class Portfolio:
    def __init__(self, style_name):
        self.style = style_name
        self.cash = START_CASH
        self.lots = {}            # symbol -> list of lot dicts
        self.trades = []          # order records
        self.round_trips = []     # closed-lot P&L records
        self.total_costs = 0.0
        self.floor = 85.0
        self.halt_pending = False
        self.halted = False
        self.halt_trigger_date = None
        self.halt_date = None     # liquidation date (or trigger date if no next day)
        self.equity_curve = []    # (date, equity)

    def held_symbols(self):
        return [s for s, lots in self.lots.items() if sum(l["shares"] for l in lots) > 1e-12]

    def shares_of(self, symbol):
        return sum(l["shares"] for l in self.lots.get(symbol, []))

    def position_value(self, symbol, price):
        return self.shares_of(symbol) * price

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
            "cost": round(cost, 4), "reason": reason,
            "pnl": "",
        })
        return True

    def liquidate_all(self, d, pos, price_map, reason):
        for sym in list(self.held_symbols()):
            px = price_map.get(sym)
            if px is not None:
                self.sell(d, pos, sym, px, reason)

    def floor_check(self, d, equity_close):
        """LADDER-era floor (integrity mode only)."""
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
# Market data container (VERBATIM from tournament.py)
# ----------------------------------------------------------------------------

class Market:
    def __init__(self, frames):
        self.frames = frames                       # symbol -> DataFrame
        spy = frames["SPY"]
        self.dates = list(spy["date"])             # master calendar
        self.pos_of = {d: i for i, d in enumerate(self.dates)}
        self.test_dates = [d for d in self.dates if TEST_START <= d <= TEST_END]
        self.test_pos = [self.pos_of[d] for d in self.test_dates]

    def row(self, symbol, pos):
        df = self.frames[symbol]
        if pos < 0 or pos >= len(df):
            return None
        return df.iloc[pos]

    def price(self, symbol, pos, field="close"):
        df = self.frames[symbol]
        if pos < 0 or pos >= len(df):
            return None
        return float(df[field].iloc[pos])

    def close_map(self, pos):
        return {s: self.price(s, pos, "close") for s in self.frames}

    def open_map(self, pos):
        return {s: self.price(s, pos, "open") for s in self.frames}


def align_frames(raw):
    """VERBATIM from tournament.py."""
    spy_dates = raw["SPY"]["date"]
    frames = {}
    for sym, df in raw.items():
        df = df.set_index("date").reindex(spy_dates)
        real = df["close"].notna()
        df[["open", "high", "low", "close"]] = df[["open", "high", "low", "close"]].ffill()
        df["volume"] = df["volume"].fillna(0)
        df = add_indicators(df.reset_index().rename(columns={"index": "date"}))
        df["real"] = real.values
        frames[sym] = df
    return frames


# ----------------------------------------------------------------------------
# Signal (VERBATIM from tournament.py)
# ----------------------------------------------------------------------------

def sig_squeeze(mkt, sym, pos):
    df = mkt.frames[sym]
    if pos < 130:
        return False
    bw = df["bb_bw"]
    if np.isnan(bw.iloc[pos - 1]):
        return False
    window = bw.iloc[pos - 126:pos]          # 126 sessions ending yesterday
    if window.isna().any():
        return False
    squeeze_yesterday = bw.iloc[pos - 1] <= window.min() + 1e-12
    breakout = (df["close"].iloc[pos] > df["bb_upper"].iloc[pos]
                and df["close"].iloc[pos - 1] <= df["bb_upper"].iloc[pos - 1])
    return bool(squeeze_yesterday and breakout)


# ----------------------------------------------------------------------------
# Original discrete runner (VERBATIM from tournament.py) - integrity mode
# ----------------------------------------------------------------------------

def run_discrete(mkt, style_name, universe, signal_fn=None, entry_mode="next_open",
                 stop_pct=None, target_pct=None, time_exit_days=None,
                 ma_exit=False, max_positions=2, frac=0.5,
                 placebo_schedule=None):
    pf = Portfolio(style_name)
    pending_entries = []
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

        # 2) entries at today's open
        candidates = []
        if placebo_schedule is not None:
            candidates = list(placebo_schedule.get(d, []))
        elif entry_mode == "next_open":
            candidates = list(pending_entries)
        pending_entries = []
        for sym in candidates:
            if pf.shares_of(sym) > 0 or len(pf.held_symbols()) >= max_positions:
                continue
            eq_open = pf.equity(mkt.open_map(pos))
            pf.buy(d, pos, sym, mkt.price(sym, pos, "open"),
                   frac * eq_open, "entry")

        # 3) intraday stop / target, stop-first
        if stop_pct is not None or target_pct is not None:
            for sym in list(pf.held_symbols()):
                entry = pf.weighted_entry_price(sym)
                if entry is None:
                    continue
                o = mkt.price(sym, pos, "open")
                h = mkt.price(sym, pos, "high")
                l = mkt.price(sym, pos, "low")
                stop_px = entry * (1 - stop_pct) if stop_pct is not None else None
                tgt_px = entry * (1 + target_pct) if target_pct is not None else None
                fill, reason = None, None
                if stop_px is not None and o <= stop_px:
                    fill, reason = o, "stop-gap"
                elif tgt_px is not None and o >= tgt_px:
                    fill, reason = o, "target-gap"
                elif stop_px is not None and l <= stop_px and tgt_px is not None and h >= tgt_px:
                    fill, reason = stop_px, "stop-first"
                elif stop_px is not None and l <= stop_px:
                    fill, reason = stop_px, "stop"
                elif tgt_px is not None and h >= tgt_px:
                    fill, reason = tgt_px, "target"
                if fill is not None:
                    pf.sell(d, pos, sym, fill, reason)

        # 4) time exit at the close of the Nth trading day
        if time_exit_days is not None:
            for sym in list(pf.held_symbols()):
                ep = pf.entry_pos(sym)
                if ep is not None and pos - ep >= time_exit_days:
                    pf.sell(d, pos, sym, mkt.price(sym, pos, "close"), "time-exit")

        # 5) mark to close, floor ladder + floor test
        eq_close = pf.equity(mkt.close_map(pos))
        pf.equity_curve.append((d, eq_close))
        touched = pf.floor_check(d, eq_close)
        if touched and t == last_t:
            pf.halted = True
            pf.halt_date = d
            break
        if t == last_t:
            break

        # 6) schedule moving-average exits for tomorrow's open
        if ma_exit:
            for sym in list(pf.held_symbols()):
                sma20 = mkt.frames[sym]["sma20"].iloc[pos]
                if not np.isnan(sma20) and mkt.price(sym, pos, "close") < sma20:
                    pending_exits.append((sym, "ma-exit"))

        # 7) generate tomorrow's entries from today's close signals
        if placebo_schedule is None and entry_mode == "next_open" and signal_fn is not None:
            for sym in universe:
                if pf.shares_of(sym) > 0:
                    continue
                if signal_fn(mkt, sym, pos):
                    pending_entries.append(sym)

    return pf


# ----------------------------------------------------------------------------
# Scoring (VERBATIM from tournament.py) + SPY benchmark (VERBATIM)
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
    losses = [r for r in rts if r["pnl"] <= 0]
    buys = sum(1 for tr in pf.trades if tr["side"] == "buy")
    return {
        "style": pf.style,
        "final": final,
        "total_pct": (final / START_CASH - 1) * 100,
        "cagr_pct": cagr * 100,
        "orders": len(pf.trades),
        "entries": buys,
        "closed_trades": len(rts),
        "win_rate": (100 * len(wins) / len(rts)) if rts else float("nan"),
        "avg_win": float(np.mean([r["pnl"] for r in wins])) if wins else float("nan"),
        "avg_loss": float(np.mean([r["pnl"] for r in losses])) if losses else float("nan"),
        "max_dd_pct": max_dd * 100,
        "total_costs": pf.total_costs,
        "halt_date": (pf.halt_date.isoformat() if pf.halted and pf.halt_date else None),
        "end_date": end_date.isoformat(),
        "open_positions": pf.held_symbols(),
    }


def spy_benchmark(mkt):
    first_pos, last_pos = mkt.test_pos[0], mkt.test_pos[-1]
    o = mkt.price("SPY", first_pos, "open")
    c = mkt.price("SPY", last_pos, "close")
    gross_final = START_CASH / o * c
    buy_value = START_CASH / (1 + COST_RATE)
    shares = buy_value / o
    sell_value = shares * c
    net_final = sell_value - (COST_RATE * sell_value + SELL_FEE)
    return gross_final, net_final


def spy_dividend_adjusted():
    """SPY buy-and-hold on dividend-adjusted bars (long-run plumbing's
    bars_adj convention: open/close scaled by adjclose/close), program
    costs, bought at the first test-window open, sold at the last close."""
    import time as _time
    with open(SPY_ADJ_PAYLOAD, "rb") as fh:
        payload = json.loads(fh.read())
    res = payload["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = _time.strftime("%Y-%m-%d", _time.gmtime(t))
        o, c = q["open"][i], q["close"][i]
        if c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        bars.append((d, (o * ratio if o else a), a))
    bars.sort()
    win = [b for b in bars if "2016-11-21" <= b[0] <= "2026-11-20"]
    o0, cN = win[0][1], win[-1][2]
    buy_value = START_CASH / (1 + COST_RATE)
    shares = buy_value / o0
    sell_value = shares * cN
    net_final = sell_value - (COST_RATE * sell_value + SELL_FEE)
    return {"first_date": win[0][0], "last_date": win[-1][0],
            "open_first": o0, "close_last": cN, "net_final": net_final}


# ----------------------------------------------------------------------------
# Cadence machinery (SPEC uniform definition)
# ----------------------------------------------------------------------------

def cadence_date_set(test_dates, cadence):
    """Set of test-window indices t that ARE cadence dates.
    daily = every trading day; weekly = first trading day of each ISO week;
    biweekly = first trading day of every second week (weeks counted from
    the week containing the window's first date, index 0 = that week);
    monthly = first trading day of each month; quarterly = first trading
    day of each calendar quarter; semiannual = first trading day of each
    half-year; annual = first trading day of each year."""
    out = set()
    if cadence == "daily":
        return set(range(len(test_dates)))
    seen = set()
    week_index = {}
    for t, d in enumerate(test_dates):
        iso = d.isocalendar()
        wk = (iso[0], iso[1])
        if wk not in week_index:
            week_index[wk] = len(week_index)
        if cadence == "weekly":
            key = wk
        elif cadence == "biweekly":
            if week_index[wk] % 2 != 0:
                continue
            key = ("bi", week_index[wk])
        elif cadence == "monthly":
            key = (d.year, d.month)
        elif cadence == "quarterly":
            key = (d.year, (d.month - 1) // 3)
        elif cadence == "semiannual":
            key = (d.year, (d.month - 1) // 6)
        elif cadence == "annual":
            key = (d.year,)
        else:
            raise ValueError(cadence)
        if key not in seen:
            seen.add(key)
            out.add(t)
    return out


def make_placebo_schedule_cadence(test_dates, cad_idx, universe, n_entries, seed):
    """Tournament placebo design, cadence-gated: n_entries random
    (cadence date, symbol) picks; entries never scheduled on the final
    cadence date (mirrors the tournament's 'never enter on the final day')."""
    rng = np.random.default_rng(seed)
    pool = [test_dates[t] for t in sorted(cad_idx)[:-1]]
    schedule = {}
    for _ in range(n_entries):
        d = pool[rng.integers(0, len(pool))]
        sym = universe[rng.integers(0, len(universe))]
        schedule.setdefault(d, []).append(sym)
    return schedule


# ----------------------------------------------------------------------------
# Cadence engine: tournament style-E mechanics gated to cadence dates,
# with switchable protection (ladder for the self-check, v9 for the sweep).
# ----------------------------------------------------------------------------

def run_cadence(mkt, cadence, protection="v9", placebo_schedule=None,
                sig_cache=None):
    """sig_cache: {symbol: {pos: bool}} precomputed sig_squeeze values
    (identical semantics to calling sig_squeeze live)."""
    pf = Portfolio(f"bollinger-squeeze@{cadence}")
    dates = mkt.test_dates
    poss = mkt.test_pos
    cad_idx = cadence_date_set(dates, cadence)
    last_t = len(dates) - 1

    episode = 1
    floor = round(0.85 * START_CASH, 2) if protection == "v9" else pf.floor
    active = True
    ended = False
    halt_pending = False
    halt_trigger_date = None
    restart_not_before = None       # ordinal; episode-2 restart threshold
    halts = []                      # {episode, trigger_date, liquidation_date, floor}
    restarts = []                   # {date, balance, episode2_floor}
    pending_entries, pending_exits = [], []

    for t, d in enumerate(dates):
        pos = poss[t]

        # --- floor liquidation at today's open (engine's own behavior) ---
        if halt_pending:
            pf.liquidate_all(d, pos, mkt.open_map(pos), "floor-liquidation")
            liq_equity = pf.equity(mkt.close_map(pos))
            halts.append({
                "episode": episode,
                "trigger_date": halt_trigger_date.isoformat(),
                "liquidation_date": d.isoformat(),
                "floor": floor,
                "cash_after_liquidation": round(pf.cash, 4),
            })
            halt_pending = False
            pending_entries, pending_exits = [], []
            pf.equity_curve.append((d, liq_equity))
            if protection == "ladder" or episode == 2:
                ended = True
                # pot is all cash now; curve stays flat to the window end
                for t2 in range(t + 1, len(dates)):
                    pf.equity_curve.append((dates[t2], pf.cash))
                break
            # v9 first halt: sit in cash 90 calendar days
            active = False
            restart_not_before = d.toordinal() + 90
            continue

        # --- episode-2 restart at the next cadence date >= liq + 90d ---
        if (not active and not ended and protection == "v9"
                and t in cad_idx and d.toordinal() >= restart_not_before):
            active = True
            episode = 2
            floor = round(0.85 * pf.cash, 2)
            restarts.append({
                "date": d.isoformat(),
                "restart_balance": round(pf.cash, 4),
                "episode2_floor": floor,
            })

        if active and not ended and t in cad_idx:
            # 1) close-signal exits scheduled at the previous cadence close
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

            # 3) intraday -8% stop, stop-first (cadence dates only)
            for sym in list(pf.held_symbols()):
                entry = pf.weighted_entry_price(sym)
                if entry is None:
                    continue
                o = mkt.price(sym, pos, "open")
                l = mkt.price(sym, pos, "low")
                stop_px = entry * (1 - 0.08)
                fill, reason = None, None
                if o <= stop_px:
                    fill, reason = o, "stop-gap"
                elif l <= stop_px:
                    fill, reason = stop_px, "stop"
                if fill is not None:
                    pf.sell(d, pos, sym, fill, reason)

        # 4) mark to close
        eq_close = pf.equity(mkt.close_map(pos))
        pf.equity_curve.append((d, eq_close))

        # 5) floor test at the close (protection: checked every close)
        if active and not ended:
            if protection == "ladder":
                touched = pf.floor_check(d, eq_close)
                floor = pf.floor
            else:
                touched = eq_close <= floor
            if touched:
                if t == last_t:
                    halts.append({
                        "episode": episode,
                        "trigger_date": d.isoformat(),
                        "liquidation_date": None,
                        "floor": floor,
                        "cash_after_liquidation": None,
                    })
                    ended = True
                    break
                halt_pending = True
                halt_trigger_date = d
                continue

        if t == last_t:
            break

        # 6) on cadence closes: schedule MA exits + entries for next cadence open
        if active and not ended and t in cad_idx:
            for sym in list(pf.held_symbols()):
                sma20 = mkt.frames[sym]["sma20"].iloc[pos]
                if not np.isnan(sma20) and mkt.price(sym, pos, "close") < sma20:
                    pending_exits.append((sym, "ma-exit"))
            if placebo_schedule is None:
                for sym in STOCK_UNIVERSE:
                    if pf.shares_of(sym) > 0:
                        continue
                    sig = (sig_cache[sym][pos] if sig_cache is not None
                           else sig_squeeze(mkt, sym, pos))
                    if sig:
                        pending_entries.append(sym)

    return pf, halts, restarts, ended


def summarize_run(pf, halts, restarts, start_date, end_date):
    curve = [(start_date, START_CASH)] + list(pf.equity_curve)
    final = curve[-1][1]
    peak, max_dd = START_CASH, 0.0
    for _, eq in curve:
        peak = max(peak, eq)
        if peak > 0:
            max_dd = max(max_dd, (peak - eq) / peak)
    years = max((end_date - start_date).days, 1) / 365.25
    cagr = (final / START_CASH) ** (1 / years) - 1 if final > 0 else -1.0
    return {
        "final": round(final, 2),
        "cagr_pct": round(cagr * 100, 2),
        "max_dd_pct": round(max_dd * 100, 2),
        "costs": round(pf.total_costs, 2),
        "orders": len(pf.trades),
        "entries": sum(1 for tr in pf.trades if tr["side"] == "buy"),
        "closed_trades": len(pf.round_trips),
        "halts": len(halts),
        "halt_records": halts,
        "restart": bool(restarts),
        "restart_records": restarts,
        "second_halt": any(h["episode"] == 2 for h in halts),
        "equity_curve": [[d.isoformat(), round(v, 4)] for d, v in pf.equity_curve],
    }


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def build_market():
    raw = {sym: load_symbol(sym) for sym in STOCK_UNIVERSE}
    frames = align_frames(raw)
    return Market(frames)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    os.makedirs(CELLS_DIR, exist_ok=True)
    mkt = build_market()
    start_date, end_date = mkt.test_dates[0], mkt.test_dates[-1]
    print(f"Window: {start_date} -> {end_date} ({len(mkt.test_dates)} trading days)")

    spy_gross, spy_net = spy_benchmark(mkt)
    print(f"SPY price-only: gross ${spy_gross:,.2f} / net ${spy_net:,.2f}")
    spy_adj = spy_dividend_adjusted()
    print(f"SPY dividend-adjusted: net ${spy_adj['net_final']:,.2f} "
          f"({spy_adj['first_date']} open {spy_adj['open_first']:.4f} -> "
          f"{spy_adj['last_date']} close {spy_adj['close_last']:.4f})")

    # ---------------- integrity: original engine, ladder floor --------------
    print("\n--- INTEGRITY (original tournament engine, ladder floor) ---")
    pf0 = run_discrete(mkt, "e_bollinger_squeeze", STOCK_UNIVERSE,
                       signal_fn=sig_squeeze, entry_mode="next_open",
                       stop_pct=0.08, ma_exit=True)
    r0 = score(pf0, start_date)
    print(f"final ${r0['final']:,.2f} | CAGR {r0['cagr_pct']:+.2f}% | "
          f"maxDD {r0['max_dd_pct']:.1f}% | orders {r0['orders']} | "
          f"closed {r0['closed_trades']} | win {r0['win_rate']:.1f}% | "
          f"costs ${r0['total_costs']:.2f} | halt {r0['halt_date']}")
    published = {"final": 154.47, "max_dd_pct": 13.4, "orders": 72,
                 "closed_trades": 36, "costs": 4.96, "halt_date": None}
    ok = (abs(r0["final"] - published["final"]) < 0.005
          and abs(r0["max_dd_pct"] - published["max_dd_pct"]) < 0.05
          and r0["orders"] == published["orders"]
          and r0["closed_trades"] == published["closed_trades"]
          and abs(r0["total_costs"] - published["costs"]) < 0.005
          and r0["halt_date"] == published["halt_date"])
    print("INTEGRITY:", "REPRODUCED" if ok else "MISMATCH - see output above")
    integrity = {
        "status": "reproduced" if ok else "FAILED",
        "original_form": "v2 tournament style E via run_discrete verbatim, "
                         "ladder-era floor ($85 -> $100 at $125 close -> $125 "
                         "at $150 close; close at/below floor liquidates at "
                         "next open and ends the run), split-adjusted bars, "
                         "no restarts",
        "published": published,
        "reproduced": {
            "final": round(r0["final"], 2), "cagr_pct": round(r0["cagr_pct"], 2),
            "max_dd_pct": round(r0["max_dd_pct"], 2), "orders": r0["orders"],
            "entries": r0["entries"], "closed_trades": r0["closed_trades"],
            "win_rate_pct": round(r0["win_rate"], 1),
            "avg_win": round(r0["avg_win"], 2), "avg_loss": round(r0["avg_loss"], 2),
            "costs": round(r0["total_costs"], 2), "halt_date": r0["halt_date"],
        },
        "placebo_note": "The original tournament ran NO placebo for style E "
                        "(placebos were run only for styles A, C and G). "
                        "The sweep placebos below are built fresh.",
        "equity_curve": [[d.isoformat(), round(v, 4)] for d, v in pf0.equity_curve],
    }
    with open(os.path.join(CELLS_DIR, "integrity.json"), "w") as fh:
        json.dump(integrity, fh, indent=1)
    if mode == "integrity":
        return

    # ---------------- self-check: cadence engine @daily + ladder ------------
    print("\n--- SELF-CHECK (cadence engine, daily, ladder floor) ---")
    print("precomputing squeeze signals...")
    sig_cache = {sym: {} for sym in STOCK_UNIVERSE}
    for sym in STOCK_UNIVERSE:
        df = mkt.frames[sym]
        bw = df["bb_bw"]
        for pos in mkt.test_pos:
            sig_cache[sym][pos] = sig_squeeze(mkt, sym, pos)
    pf_sc, halts_sc, _, _ = run_cadence(mkt, "daily", protection="ladder",
                                        sig_cache=sig_cache)
    r_sc = score(pf_sc, start_date)
    match = abs(r_sc["final"] - r0["final"]) < 1e-9 and r_sc["orders"] == r0["orders"]
    print(f"cadence-daily/ladder final ${r_sc['final']:,.2f} vs integrity "
          f"${r0['final']:,.2f} -> {'MATCH' if match else 'MISMATCH'}")
    if not match:
        print("SELF-CHECK FAILED - sweep results would not be trustworthy.")
        sys.exit(2)
    if mode == "selfcheck":
        return

    # ---------------- sweep: 7 cadences, v9 protections ---------------------
    print("\n--- SWEEP (DECADE, v9 protections) ---")
    cells = {}
    for cadence in CADENCES:
        pf, halts, restarts, _ = run_cadence(mkt, cadence, protection="v9",
                                             sig_cache=sig_cache)
        s = summarize_run(pf, halts, restarts, start_date, end_date)
        n_entries = s["entries"]
        cad_idx = cadence_date_set(mkt.test_dates, cadence)
        placebo_finals = []
        for seed in PLACEBO_SEEDS:
            sched = make_placebo_schedule_cadence(
                mkt.test_dates, cad_idx, STOCK_UNIVERSE, n_entries, seed)
            ppf, phalts, prestarts, _ = run_cadence(
                mkt, cadence, protection="v9", placebo_schedule=sched,
                sig_cache=sig_cache)
            ps = summarize_run(ppf, phalts, prestarts, start_date, end_date)
            placebo_finals.append(round(ps["final"], 2))
        beaten = sum(1 for f in placebo_finals if s["final"] > f)
        s["placebo_finals"] = placebo_finals
        s["placebo_beaten"] = beaten
        s["placebo_seeds"] = PLACEBO_SEEDS
        s["cadence_dates"] = len(cad_idx)
        cells[cadence] = s
        with open(os.path.join(CELLS_DIR, f"{cadence}.json"), "w") as fh:
            json.dump({"slug": "bollinger-squeeze", "cadence": cadence,
                       "window": {"start": start_date.isoformat(),
                                  "end": end_date.isoformat()},
                       "start_cash": START_CASH,
                       "protection": "v9: plain -15% floor per episode; first "
                                     "halt liquidates at next open, 90 calendar "
                                     "days cash, restart at next cadence date "
                                     "under episode-2 floor -15% from restart "
                                     "balance; second halt ends the run",
                       **s}, fh, indent=1)
        print(f"{cadence:11s} final ${s['final']:>8,.2f} | CAGR "
              f"{s['cagr_pct']:+6.2f}% | maxDD {s['max_dd_pct']:5.1f}% | "
              f"orders {s['orders']:>3} | costs ${s['costs']:>5.2f} | "
              f"halts {s['halts']} restart {s['restart']} | "
              f"placebo beaten {beaten}/20")

    spy_adj_final = round(spy_adj["net_final"], 2)
    money = [c for c in CADENCES
             if cells[c]["final"] > spy_adj_final and cells[c]["placebo_beaten"] == 20]
    money_relaxed = [c for c in CADENCES
                     if cells[c]["final"] > spy_adj_final
                     and cells[c]["placebo_beaten"] is not None
                     and cells[c]["placebo_beaten"] >= 11]
    results = {
        "slug": "bollinger-squeeze",
        "area": "Short-cycle daily price style (W9): a Bollinger squeeze "
                "breakout day-trading-style rule, cycled and compounded over "
                "the full decade road",
        "area_source": "v10 SPEC W9 assignment + CADENCE GRID (bollinger-"
                       "squeeze native cadence = daily)",
        "cadence": "daily",
        "native_cadence": "daily",
        "original_cadence_foreign": False,
        "original_cadence_note": "The original tournament test ran the style "
                                 "at its native daily cadence; not foreign.",
        "native_change": "none - original form was native (daily signals, "
                         "next-open fills, MA exit + -8% stop). The sweep "
                         "changes only the protection (v9 plain floor + "
                         "90-day restart replaces the ladder-era floor) and "
                         "gates signal/exit evaluation to cadence dates at "
                         "slower tempos per the SPEC's uniform definition.",
        "integrity": {k: v for k, v in integrity.items() if k != "equity_curve"},
        "decade_spy_final": spy_adj_final,
        "decade_spy": {
            "dividend_adjusted_net": spy_adj_final,
            "price_only_net_tournament": round(spy_net, 2),
            "price_only_gross_tournament": round(spy_gross, 2),
            "note": "Tournament benchmark was price-only (no dividends). "
                    "Dividend-adjusted figure computed in this plumbing from "
                    "the v7 long-hold adjclose payload, program costs.",
        },
        "champion_decade_reference": {
            "final": 65.89,
            "note": "Champion (value+momentum) DECADE $65.89 after two halts "
                    "(lazy-quarterly test) - its crown rests on the 2010 and "
                    "2019 roads; the decade caveat applies.",
        },
        "cells": {
            c: {k: cells[c][k] for k in
                ("final", "cagr_pct", "max_dd_pct", "halts", "restart",
                 "second_halt", "costs", "orders", "placebo_beaten")}
            | {"placebo_note": "20 random-entry twins (seeds 91001-91020), "
                               "identical exits/sizing/costs/v9 protections, "
                               "entry count matched to the real run"}
            for c in CADENCES
        },
        "money_cadences": money,
        "money_cadences_majority_placebo": money_relaxed,
        "verdict_area": None,   # filled in RESULTS.md / by coordinator review
    }
    with open(os.path.join(HERE, "results.json"), "w") as fh:
        json.dump(results, fh, indent=1)
    print("\nmoney cadences (beat SPY-adj AND all 20 placebos):", money or "none")
    print("Wrote cells/*.json and results.json")


if __name__ == "__main__":
    main()
