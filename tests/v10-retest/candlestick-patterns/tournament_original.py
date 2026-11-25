#!/usr/bin/env python3
"""
Strategy Tournament - Terry's AI stock app (v2 track).

Seven pre-specified trading styles, each with its own $100 pot, run head-to-head
on the same 10 years of daily data (first trading day on/after 2016-11-21 through
2026-11-20), same costs, same floor rules. Three styles also get a random-entry
placebo twin so a lucky style cannot fool us.

Rules shared by every pot:
  - Long only, fractional shares.
  - Costs: 0.10% of trade value on every buy and every sell, plus $0.01 per sell order.
  - No look-ahead: signals are computed from closes up to and including day t and
    filled at day t+1's open. Intraday stop/target checks use the stop-first rule
    (if a day's range touches both stop and target, the stop fills first; if the
    day opens beyond the stop, the fill is the open - gaps fill worse, honestly).
  - Terry's floor: floor starts at $85. If a pot's closing value reaches $125 the
    floor rises to $100; at $150 it rises to $125. If a closing value is at or
    below the current floor, everything is liquidated at the next open and that
    pot's run ENDS (the halt is part of the score - no restarts).
  - Indicator-based exits that are only knowable at the close (RSI, close below a
    moving average, golden-cross state) are executed at the NEXT open. Pure
    time-based exits (hold N trading days) are executed at the close of the Nth
    day, because the exit date is known in advance (market-on-close is fair).

Data: free Yahoo Finance chart API (split-adjusted OHLC, not dividend-adjusted),
cached under tournament-data/. Existing caches in ../v2/data are used as a
fallback for SPY/QQQ (CSV) and the stock universe (raw Yahoo JSON).

Simulation only. No broker orders are placed by this script.
"""

import json
import math
import os
import time
import urllib.request
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, "tournament-data")
os.makedirs(CACHE_DIR, exist_ok=True)

FETCH_START = "2015-01-01"
FETCH_END = "2026-11-21"          # exclusive-ish; last bar wanted is 2026-11-20
TEST_START = date(2016, 11, 21)   # first trading day on/after this date
TEST_END = date(2026, 11, 20)

STOCK_UNIVERSE = ["SPY", "QQQ", "NVDA", "TSLA", "AAPL",
                  "MSFT", "AMZN", "META", "AMD", "AVGO"]
SECTOR_UNIVERSE = ["XLK", "XLF", "XLE", "XLV", "XLI",
                   "XLY", "XLP", "XLU", "XLB", "XLRE"]
ALL_SYMBOLS = sorted(set(STOCK_UNIVERSE + SECTOR_UNIVERSE))

START_CASH = 100.0
COST_RATE = 0.001                 # 0.10% per side
SELL_FEE = 0.01                   # per sell order


# ----------------------------------------------------------------------------
# Data loading
# ----------------------------------------------------------------------------

def _yahoo_fetch(symbol):
    p1 = int(datetime(2015, 1, 1, tzinfo=timezone.utc).timestamp())
    p2 = int(datetime(2026, 11, 22, tzinfo=timezone.utc).timestamp())
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
           f"{symbol}?period1={p1}&period2={p2}&interval=1d&events=div,splits")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    result = payload["chart"]["result"][0]
    ts = result["timestamp"]
    q = result["indicators"]["quote"][0]
    rows = []
    for i, t in enumerate(ts):
        d = datetime.fromtimestamp(t, tz=timezone.utc).date()
        o, h, l, c, v = q["open"][i], q["high"][i], q["low"][i], q["close"][i], q["volume"][i]
        if None in (o, h, l, c) or c <= 0:
            continue
        rows.append((d, o, h, l, c, v or 0))
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    return df.drop_duplicates("date").sort_values("date").reset_index(drop=True)


def _fallback_cache(symbol):
    """Reuse caches left by the sibling v2 tracks, if present."""
    csv_path = os.path.join(HERE, "data", f"{symbol}.csv")
    if os.path.exists(csv_path):
        df = pd.read_csv(csv_path)
        df["date"] = pd.to_datetime(df["date"]).dt.date
        return df[["date", "open", "high", "low", "close", "volume"]]
    json_path = os.path.join(HERE, "data", f"{symbol}.json")
    if os.path.exists(json_path):
        payload = json.load(open(json_path))
        result = payload["chart"]["result"][0]
        ts = result["timestamp"]
        q = result["indicators"]["quote"][0]
        rows = []
        for i, t in enumerate(ts):
            d = datetime.fromtimestamp(t, tz=timezone.utc).date()
            o, h, l, c, v = q["open"][i], q["high"][i], q["low"][i], q["close"][i], q["volume"][i]
            if None in (o, h, l, c) or c <= 0:
                continue
            rows.append((d, o, h, l, c, v or 0))
        df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
        return df.drop_duplicates("date").sort_values("date").reset_index(drop=True)
    return None


def load_symbol(symbol):
    cache_path = os.path.join(CACHE_DIR, f"{symbol}.csv")
    if os.path.exists(cache_path):
        df = pd.read_csv(cache_path)
        df["date"] = pd.to_datetime(df["date"]).dt.date
        return df
    df = None
    try:
        df = _yahoo_fetch(symbol)
        print(f"  fetched {symbol} from Yahoo ({len(df)} bars)")
    except Exception as exc:  # fall back to sibling caches
        print(f"  Yahoo fetch failed for {symbol} ({exc}); trying local caches")
        df = _fallback_cache(symbol)
    if df is None or len(df) < 300:
        raise RuntimeError(f"Could not obtain usable data for {symbol}")
    df = df[(df["date"] >= date(2015, 1, 1)) & (df["date"] <= date(2026, 11, 20))]
    df.to_csv(cache_path, index=False)
    time.sleep(0.3)
    return df.reset_index(drop=True)


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
    # Volume baseline for the gap rule: mean volume of the 20 sessions ending
    # two sessions ago (so 'prior-day volume vs its 20-day average' compares
    # yesterday's volume against the 20 days before it).
    df["vol_base"] = v.shift(2).rolling(20).mean()
    return df


# ----------------------------------------------------------------------------
# Portfolio
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

    # -- helpers -------------------------------------------------------------
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

    # -- trading -------------------------------------------------------------
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
        # FIFO lot closing
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
            "pnl": "",  # per-lot P&L lives in round_trips
        })
        return True

    def liquidate_all(self, d, pos, price_map, reason):
        for sym in list(self.held_symbols()):
            px = price_map.get(sym)
            if px is not None:
                self.sell(d, pos, sym, px, reason)

    # -- floor ---------------------------------------------------------------
    def floor_check(self, d, equity_close):
        """Update the profit ladder, then test the floor. Returns True if the
        floor was touched at this close."""
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
# Market data container
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
        # frames are aligned to the master calendar by construction below
        return float(df[field].iloc[pos])

    def close_map(self, pos):
        return {s: self.price(s, pos, "close") for s in self.frames}

    def open_map(self, pos):
        return {s: self.price(s, pos, "open") for s in self.frames}


def align_frames(raw):
    """Reindex every symbol onto SPY's calendar. Bars missing on a day where
    SPY traded (rare for these liquid names) are forward-filled for valuation
    only and flagged untradeable via the 'real' mask."""
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
# Signal definitions (all evaluated on data through the close of day `pos`)
# ----------------------------------------------------------------------------

def sig_candlestick(mkt, sym, pos):
    df = mkt.frames[sym]
    if pos < 51:
        return False
    c, o = df["close"].iloc[pos], df["open"].iloc[pos]
    sma50 = df["sma50"].iloc[pos]
    if np.isnan(sma50) or c <= sma50:
        return False
    pc, po = df["close"].iloc[pos - 1], df["open"].iloc[pos - 1]
    ph, pl = df["high"].iloc[pos - 1], df["low"].iloc[pos - 1]
    h, l = df["high"].iloc[pos], df["low"].iloc[pos]
    # Bullish engulfing: prior red candle, current green candle whose body
    # fully covers the prior body.
    engulfing = (pc < po and c > o and o <= pc and c >= po)
    # Hammer: long lower shadow (>=2x body), tiny upper shadow, body at top.
    body = abs(c - o)
    rng = h - l
    lower_shadow = min(o, c) - l
    upper_shadow = h - max(o, c)
    hammer = (rng > 0 and c >= o and lower_shadow >= 2 * max(body, 1e-9)
              and upper_shadow <= 0.1 * rng)
    return bool(engulfing or hammer)


def sig_breakout52(mkt, sym, pos):
    df = mkt.frames[sym]
    if pos < 253:
        return False
    prior_high = df["prior252_high_close"].iloc[pos]
    if np.isnan(prior_high):
        return False
    return bool(df["close"].iloc[pos] > prior_high)


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
# Generic runner for the discrete stock styles (a, c, e, g + their placebos)
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
        elif entry_mode == "gap_open":
            candidates = [s for s in universe if gap_signal_at_open(mkt, s, pos)]
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
# (b) RSI(2) mean reversion on SPY / QQQ
# ----------------------------------------------------------------------------

def run_rsi2(mkt):
    pf = Portfolio("b_rsi2_mean_reversion")
    universe = ["SPY", "QQQ"]
    pending_entries, pending_exits = [], []
    last_t = len(mkt.test_dates) - 1

    for t, d in enumerate(mkt.test_dates):
        pos = mkt.test_pos[t]
        if pf.halt_pending:
            pf.liquidate_all(d, pos, mkt.open_map(pos), "floor-liquidation")
            pf.halted = True
            pf.halt_date = d
            pf.equity_curve.append((d, pf.equity(mkt.close_map(pos))))
            break
        for sym, reason in pending_exits:
            if pf.shares_of(sym) > 0:
                pf.sell(d, pos, sym, mkt.price(sym, pos, "open"), reason)
        pending_exits = []
        for sym in pending_entries:
            if pf.shares_of(sym) > 0:
                continue
            eq_open = pf.equity(mkt.open_map(pos))
            pf.buy(d, pos, sym, mkt.price(sym, pos, "open"), 0.5 * eq_open, "entry")
        pending_entries = []

        # time exit: at the close of the 5th trading day
        for sym in list(pf.held_symbols()):
            ep = pf.entry_pos(sym)
            if ep is not None and pos - ep >= 5:
                pf.sell(d, pos, sym, mkt.price(sym, pos, "close"), "time-exit")

        eq_close = pf.equity(mkt.close_map(pos))
        pf.equity_curve.append((d, eq_close))
        touched = pf.floor_check(d, eq_close)
        if touched and t == last_t:
            pf.halted = True
            pf.halt_date = d
            break
        if t == last_t:
            break

        for sym in universe:
            df = mkt.frames[sym]
            rsi = df["rsi2"].iloc[pos]
            if pf.shares_of(sym) > 0:
                if not np.isnan(rsi) and rsi > 70:
                    pending_exits.append((sym, "rsi-exit"))
            else:
                sma200 = df["sma200"].iloc[pos]
                if (not np.isnan(rsi) and not np.isnan(sma200)
                        and rsi < 10 and df["close"].iloc[pos] > sma200):
                    pending_entries.append(sym)
    return pf


# ----------------------------------------------------------------------------
# (d) Golden-cross timing on SPY
# ----------------------------------------------------------------------------

def run_golden_cross(mkt):
    pf = Portfolio("d_golden_cross_spy")
    df = mkt.frames["SPY"]
    pending_switch = None       # True = go long, False = go to cash
    # state from the close before the test window opens
    first_pos = mkt.test_pos[0]
    s50 = df["sma50"].iloc[first_pos - 1]
    s200 = df["sma200"].iloc[first_pos - 1]
    pending_switch = bool(s50 > s200)
    last_t = len(mkt.test_dates) - 1

    for t, d in enumerate(mkt.test_dates):
        pos = mkt.test_pos[t]
        if pf.halt_pending:
            pf.liquidate_all(d, pos, mkt.open_map(pos), "floor-liquidation")
            pf.halted = True
            pf.halt_date = d
            pf.equity_curve.append((d, pf.equity(mkt.close_map(pos))))
            break
        if pending_switch is True and pf.shares_of("SPY") <= 0:
            eq_open = pf.equity(mkt.open_map(pos))
            pf.buy(d, pos, "SPY", mkt.price("SPY", pos, "open"), eq_open, "cross-up")
        elif pending_switch is False and pf.shares_of("SPY") > 0:
            pf.sell(d, pos, "SPY", mkt.price("SPY", pos, "open"), "cross-down")
        pending_switch = None

        eq_close = pf.equity(mkt.close_map(pos))
        pf.equity_curve.append((d, eq_close))
        touched = pf.floor_check(d, eq_close)
        if touched and t == last_t:
            pf.halted = True
            pf.halt_date = d
            break
        if t == last_t:
            break
        s50 = df["sma50"].iloc[pos]
        s200 = df["sma200"].iloc[pos]
        if np.isnan(s50) or np.isnan(s200):
            continue
        desired_long = bool(s50 > s200)
        currently_long = pf.shares_of("SPY") > 0
        if desired_long != currently_long:
            pending_switch = desired_long
    return pf


# ----------------------------------------------------------------------------
# (f) Sector rotation, monthly
# ----------------------------------------------------------------------------

def run_sector_rotation(mkt):
    pf = Portfolio("f_sector_rotation")
    selections = []             # (date, [(symbol, ret63), ...], picks)
    last_t = len(mkt.test_dates) - 1
    rebalance_positions = set()
    seen_months = set()
    for t, d in enumerate(mkt.test_dates):
        key = (d.year, d.month)
        if key not in seen_months:
            seen_months.add(key)
            rebalance_positions.add(t)

    for t, d in enumerate(mkt.test_dates):
        pos = mkt.test_pos[t]
        if pf.halt_pending:
            pf.liquidate_all(d, pos, mkt.open_map(pos), "floor-liquidation")
            pf.halted = True
            pf.halt_date = d
            pf.equity_curve.append((d, pf.equity(mkt.close_map(pos))))
            break

        if t in rebalance_positions:
            prev = pos - 1
            scored = []
            for sym in SECTOR_UNIVERSE:
                df = mkt.frames[sym]
                if prev - 63 < 0:
                    continue
                c_prev = df["close"].iloc[prev]
                sma200 = df["sma200"].iloc[prev]
                c_63 = df["close"].iloc[prev - 63]
                if np.isnan(sma200) or c_63 <= 0:
                    continue
                if c_prev > sma200:
                    scored.append((sym, c_prev / c_63 - 1))
            scored.sort(key=lambda x: -x[1])
            picks = [s for s, _ in scored[:2]]
            selections.append((d, scored, picks))
            eq_open = pf.equity(mkt.open_map(pos))
            target_each = eq_open / len(picks) if picks else 0.0
            # sell anything not picked
            for sym in list(pf.held_symbols()):
                if sym not in picks:
                    pf.sell(d, pos, sym, mkt.price(sym, pos, "open"), "rotation-out")
            # trim overweight picks
            for sym in picks:
                cur = pf.position_value(sym, mkt.price(sym, pos, "open"))
                if cur > target_each + 0.5:
                    excess_shares = (cur - target_each) / mkt.price(sym, pos, "open")
                    pf.sell(d, pos, sym, mkt.price(sym, pos, "open"),
                            "rotation-trim", shares_to_sell=excess_shares)
            # buy up to target
            for sym in picks:
                cur = pf.position_value(sym, mkt.price(sym, pos, "open"))
                deficit = target_each - cur
                if deficit > 0.5:
                    pf.buy(d, pos, sym, mkt.price(sym, pos, "open"),
                           deficit, "rotation-in")

        eq_close = pf.equity(mkt.close_map(pos))
        pf.equity_curve.append((d, eq_close))
        touched = pf.floor_check(d, eq_close)
        if touched and t == last_t:
            pf.halted = True
            pf.halt_date = d
            break
    return pf, selections


# ----------------------------------------------------------------------------
# Placebo schedules
# ----------------------------------------------------------------------------

def make_placebo_schedule(mkt, universe, n_entries, seed):
    rng = np.random.default_rng(seed)
    pool = mkt.test_dates[:-1]           # never enter on the final day
    schedule = {}
    for _ in range(n_entries):
        d = pool[rng.integers(0, len(pool))]
        sym = universe[rng.integers(0, len(universe))]
        schedule.setdefault(d, []).append(sym)
    return schedule


# ----------------------------------------------------------------------------
# Scoring
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


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

STYLE_LABELS = {
    "a_candlestick": "A. Candlestick (engulfing/hammer above 50-day avg)",
    "b_rsi2_mean_reversion": "B. RSI(2) mean reversion (SPY/QQQ)",
    "c_breakout52": "C. 52-week-high breakout",
    "d_golden_cross_spy": "D. Golden-cross timing (SPY)",
    "e_bollinger_squeeze": "E. Bollinger squeeze breakout",
    "f_sector_rotation": "F. Sector rotation (monthly, top-2 of 10 ETFs)",
    "g_gap_up": "G. Gap-up continuation",
    "a_candlestick_placebo": "A-placebo. Random entries, candlestick exits",
    "c_breakout52_placebo": "C-placebo. Random entries, breakout exits",
    "g_gap_up_placebo": "G-placebo. Random entries, gap exits",
}

PLACEBO_SEEDS = {"a_candlestick": 42101, "c_breakout52": 42103, "g_gap_up": 42107}


def main():
    print("Loading data...")
    raw = {sym: load_symbol(sym) for sym in ALL_SYMBOLS}
    frames = align_frames(raw)
    mkt = Market(frames)
    start_date = mkt.test_dates[0]
    end_date = mkt.test_dates[-1]
    print(f"Test window: {start_date} -> {end_date} ({len(mkt.test_dates)} trading days)")

    portfolios = {}

    # --- real styles ---------------------------------------------------------
    portfolios["a_candlestick"] = run_discrete(
        mkt, "a_candlestick", STOCK_UNIVERSE, signal_fn=sig_candlestick,
        entry_mode="next_open", stop_pct=0.05, target_pct=0.10,
        time_exit_days=10)
    portfolios["b_rsi2_mean_reversion"] = run_rsi2(mkt)
    portfolios["c_breakout52"] = run_discrete(
        mkt, "c_breakout52", STOCK_UNIVERSE, signal_fn=sig_breakout52,
        entry_mode="next_open", stop_pct=0.08, ma_exit=True)
    portfolios["d_golden_cross_spy"] = run_golden_cross(mkt)
    portfolios["e_bollinger_squeeze"] = run_discrete(
        mkt, "e_bollinger_squeeze", STOCK_UNIVERSE, signal_fn=sig_squeeze,
        entry_mode="next_open", stop_pct=0.08, ma_exit=True)
    sector_pf, selections = run_sector_rotation(mkt)
    portfolios["f_sector_rotation"] = sector_pf
    portfolios["g_gap_up"] = run_discrete(
        mkt, "g_gap_up", STOCK_UNIVERSE, entry_mode="gap_open",
        stop_pct=0.04, target_pct=0.08, time_exit_days=3)

    # --- placebos (matched entry counts, deterministic seeds) ----------------
    placebo_actual = {}
    for key, kwargs in {
        "a_candlestick": dict(signal_fn=sig_candlestick, entry_mode="next_open",
                              stop_pct=0.05, target_pct=0.10, time_exit_days=10),
        "c_breakout52": dict(signal_fn=sig_breakout52, entry_mode="next_open",
                             stop_pct=0.08, ma_exit=True),
        "g_gap_up": dict(entry_mode="gap_open", stop_pct=0.04,
                         target_pct=0.08, time_exit_days=3),
    }.items():
        real_pf = portfolios[key]
        n_entries = sum(1 for tr in real_pf.trades if tr["side"] == "buy")
        schedule = make_placebo_schedule(mkt, STOCK_UNIVERSE, n_entries,
                                         PLACEBO_SEEDS[key])
        kwargs.pop("signal_fn", None)
        kwargs.pop("entry_mode", None)
        pkey = key + "_placebo"
        ppf = run_discrete(mkt, pkey, STOCK_UNIVERSE,
                           placebo_schedule=schedule, **kwargs)
        portfolios[pkey] = ppf
        placebo_actual[key] = {
            "seed": PLACEBO_SEEDS[key], "target_entries": n_entries,
            "actual_entries": sum(1 for tr in ppf.trades if tr["side"] == "buy"),
        }

    # --- scoring --------------------------------------------------------------
    results = {k: score(pf, start_date) for k, pf in portfolios.items()}
    spy_gross, spy_net = spy_benchmark(mkt)
    spy_years = (end_date - start_date).days / 365.25
    spy_cagr = (spy_gross / START_CASH) ** (1 / spy_years) - 1

    # --- trades CSV -----------------------------------------------------------
    all_trades = []
    for pf in portfolios.values():
        all_trades.extend(pf.trades)
    trades_df = pd.DataFrame(all_trades, columns=[
        "style", "date", "symbol", "side", "price", "shares", "value",
        "cost", "reason", "pnl"])
    trades_path = os.path.join(HERE, "tournament-trades.csv")
    trades_df.sort_values(["style", "date"]).to_csv(trades_path, index=False)

    # --- verdicts ---------------------------------------------------------------
    def verdict(key):
        r = results[key]
        reasons = []
        if r["halt_date"]:
            reasons.append(f"floor halt on {r['halt_date']}")
        if r["final"] <= spy_net:
            reasons.append("did not beat SPY buy-and-hold (net)")
        pkey = key + "_placebo"
        if pkey in results and r["final"] <= results[pkey]["final"]:
            reasons.append("did not beat its random-entry placebo")
        return reasons

    real_keys = ["a_candlestick", "b_rsi2_mean_reversion", "c_breakout52",
                 "d_golden_cross_spy", "e_bollinger_squeeze",
                 "f_sector_rotation", "g_gap_up"]
    ranked = sorted(real_keys, key=lambda k: -results[k]["final"])
    verdicts = {k: verdict(k) for k in real_keys}
    survivors = [k for k in real_keys if not verdicts[k]]

    # --- report -------------------------------------------------------------------
    lines = []
    lines.append("# Strategy Tournament - 10 years, seven styles, three placebos")
    lines.append("")
    lines.append(f"Test window: **{start_date} to {end_date}** "
                 f"({len(mkt.test_dates)} trading days), each style on its own "
                 f"$100 pot. Daily bars from the free Yahoo Finance chart API "
                 f"(split-adjusted, not dividend-adjusted - so SPY's dividends "
                 f"are NOT counted in any number here, which slightly understates "
                 f"buy-and-hold and every style alike).")
    lines.append("")
    lines.append("Shared rules: long only, fractional shares, costs 0.10% of trade "
                 "value per side + $0.01 per sell order, no look-ahead (signals "
                 "from prior closes, entries at next open, stop-first on "
                 "stop/target days), Terry's floor active in every pot ($85, "
                 "rising to $100 at a $125 close and $125 at a $150 close; a close "
                 "at/below the floor liquidates at the next open and ends the run).")
    lines.append("")
    lines.append(f"**Benchmark:** $100 of SPY bought at the first open and sold at "
                 f"the last close = **${spy_gross:,.2f} gross / ${spy_net:,.2f} net** "
                 f"({(spy_gross / 100 - 1) * 100:+.1f}% total, {spy_cagr * 100:+.2f}% CAGR, "
                 f"price only, no dividends).")
    lines.append("")
    lines.append("## Ranked results (real styles)")
    lines.append("")
    lines.append("| Rank | Style | Final | Total % | CAGR % | Orders | Closed trades | Win % | Max DD % | Costs | Halted |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for i, k in enumerate(ranked, 1):
        r = results[k]
        wr = f"{r['win_rate']:.0f}" if not math.isnan(r["win_rate"]) else "-"
        lines.append(f"| {i} | {STYLE_LABELS[k]} | ${r['final']:,.2f} | "
                     f"{r['total_pct']:+.1f} | {r['cagr_pct']:+.2f} | {r['orders']} | "
                     f"{r['closed_trades']} | {wr} | {r['max_dd_pct']:.1f} | "
                     f"${r['total_costs']:.2f} | {r['halt_date'] or '-'} |")
    lines.append("")
    lines.append("## Placebo twins (random entries, identical exits/sizing/costs/floor)")
    lines.append("")
    lines.append("| Style | Seed | Target entries | Actual entries | Final | vs its real style |")
    lines.append("|---|---|---|---|---|---|")
    for key in ["a_candlestick", "c_breakout52", "g_gap_up"]:
        pkey = key + "_placebo"
        r, pr = results[key], results[pkey]
        pa = placebo_actual[key]
        diff = r["final"] - pr["final"]
        lines.append(f"| {STYLE_LABELS[pkey]} | {pa['seed']} | {pa['target_entries']} | "
                     f"{pa['actual_entries']} | ${pr['final']:,.2f} | "
                     f"real style {'ahead by' if diff >= 0 else 'BEHIND by'} ${abs(diff):,.2f} |")
    lines.append("")
    lines.append("## Per-style notes")
    lines.append("")
    notes = {
        "a_candlestick": "Bullish engulfing or hammer, only above the 50-day average; "
                         "-5% stop, +10% target, 10-trading-day time exit.",
        "b_rsi2_mean_reversion": "Buys SPY/QQQ dips (RSI(2) under 10) only in an "
                                 "uptrend (above the 200-day average); exits at RSI(2) "
                                 "over 70 or after 5 trading days.",
        "c_breakout52": "Buys new 252-day closing highs; exits on a close below the "
                        "20-day average or an -8% stop.",
        "d_golden_cross_spy": "All-in SPY while its 50-day average is above its "
                              "200-day average, cash otherwise. Fewest trades of any "
                              "style by construction.",
        "e_bollinger_squeeze": "Buys the first close above the upper Bollinger band "
                               "after bandwidth sat at a 6-month low; exits on a close "
                               "below the 20-day average or an -8% stop.",
        "f_sector_rotation": "Monthly: top 2 of 10 sector ETFs by trailing 63-day "
                             "return among those above their 200-day average, equal "
                             "weight; all cash if none qualify.",
        "g_gap_up": "Buys at the open after a >3% gap up on >1.5x volume; -4% stop, "
                    "+8% target, 3-trading-day time exit. The most cost-hungry style "
                    "here by design.",
    }
    for k in ranked:
        r = results[k]
        wr = f"{r['win_rate']:.1f}%" if not math.isnan(r["win_rate"]) else "n/a"
        aw = f"${r['avg_win']:.2f}" if not math.isnan(r["avg_win"]) else "n/a"
        al = f"${r['avg_loss']:.2f}" if not math.isnan(r["avg_loss"]) else "n/a"
        lines.append(f"- **{STYLE_LABELS[k]}** - {notes[k]} Finished "
                     f"${r['final']:,.2f} ({r['total_pct']:+.1f}%), "
                     f"{r['closed_trades']} closed trades, win rate {wr}, "
                     f"avg win {aw} vs avg loss {al}, max drawdown "
                     f"{r['max_dd_pct']:.1f}%, costs ${r['total_costs']:.2f}"
                     + (f", HALTED {r['halt_date']}." if r["halt_date"] else "."))
    lines.append("")
    lines.append("## The honest caution (read before believing the winner)")
    lines.append("")
    n_trials = len(portfolios)
    lines.append(f"This tournament ran **{n_trials} trials** (7 styles + 3 placebo "
                 f"twins), and the wider v2 program has tried more variants on top "
                 f"of these. When you test this many things on the same history, "
                 f"some of them will look good by pure chance - that is exactly "
                 f"what the placebos are for, and it is why a winner here has NOT "
                 f"proven an edge. Before any style is called real it must clear a "
                 f"higher bar than 'it made money': a t-statistic around 3 (not "
                 f"the usual 2), a deflated-Sharpe check that accounts for the "
                 f"number of trials, and survival on data it was not tuned on. "
                 f"One 10-year path is still one path: this decade contained a "
                 f"pandemic crash, a bear market, and a long bull run, in that "
                 f"order, once. A different decade can rank these styles "
                 f"differently. Yahoo's free bars also carry no dividends and "
                 f"the universe is today's famous names, so every result here "
                 f"is flattered by survivorship - treat all finals as upper bounds.")
    lines.append("")
    lines.append("## Verdict")
    lines.append("")
    lines.append("A style earns further testing only if it (1) finished above SPY "
                 "buy-and-hold net of costs, (2) never hit Terry's floor, and "
                 "(3) beat its random-entry placebo where one was run.")
    lines.append("")
    if survivors:
        for k in survivors:
            lines.append(f"- **EARNS FURTHER TESTING: {STYLE_LABELS[k]}** - "
                         f"finished ${results[k]['final']:,.2f} vs SPY net "
                         f"${spy_net:,.2f}, no halt"
                         + (f", beat its placebo (${results[k + '_placebo']['final']:,.2f})"
                            if k + "_placebo" in results else "")
                         + ". Next step for it: walk-forward folds and a "
                           "deflated-Sharpe check, not live paper trading yet.")
    else:
        lines.append("- **No style cleared all three bars.** That is a real result, "
                     "not a failed experiment: it is the tournament doing its job.")
    for k in ranked:
        if k not in survivors:
            lines.append(f"- **CULLED: {STYLE_LABELS[k]}** - "
                         + "; ".join(verdicts[k]) + ".")
    lines.append("")
    lines.append("Files: `tournament.py` (the exact script), "
                 "`tournament-trades.csv` (every order, all styles, with a style "
                 "column), cached bars in `tournament-data/`.")
    report = "\n".join(lines) + "\n"
    report_path = os.path.join(HERE, "tournament.md")
    with open(report_path, "w") as fh:
        fh.write(report)

    # --- console summary --------------------------------------------------------
    print("\n=== TOURNAMENT RESULTS ===")
    print(f"SPY buy-and-hold: gross ${spy_gross:,.2f} / net ${spy_net:,.2f}")
    for i, k in enumerate(ranked, 1):
        r = results[k]
        print(f"{i}. {k}: ${r['final']:,.2f} ({r['total_pct']:+.1f}%), "
              f"CAGR {r['cagr_pct']:+.2f}%, orders {r['orders']}, "
              f"closed {r['closed_trades']}, win "
              f"{r['win_rate']:.0f}%" if not math.isnan(r["win_rate"]) else
              f"{i}. {k}: ${r['final']:,.2f} ({r['total_pct']:+.1f}%), "
              f"CAGR {r['cagr_pct']:+.2f}%, orders {r['orders']}, "
              f"closed {r['closed_trades']}, win n/a")
        print(f"   maxDD {r['max_dd_pct']:.1f}%, costs ${r['total_costs']:.2f}, "
              f"halt {r['halt_date'] or '-'}")
    for key in ["a_candlestick", "c_breakout52", "g_gap_up"]:
        pr = results[key + "_placebo"]
        print(f"placebo {key}: ${pr['final']:,.2f} "
              f"(real ${results[key]['final']:,.2f})")
    print(f"Survivors: {survivors or 'none'}")
    print(f"Wrote {report_path} and {trades_path}")


if __name__ == "__main__":
    main()
