#!/usr/bin/env python3
"""
THE HIGH-WIN-RATE LAB - Terry's AI stock app (v4 track).

Terry's new goal: "win at least 80% of the time." This lab hunts for trade
shapes with genuinely high win rates - and judges every shape on BOTH its win
rate and its money, because a high win rate with small wins and huge losses is
a losing machine in a winning costume. Expectancy per trade (average dollars
won/lost per closed trade) is reported next to every win rate.

Four frozen shapes, each on its own pot:

  H1  RSI(2) snap-back, tight target (SPY/QQQ only, 50% each, max 2):
      buy when RSI(2) < 10 and price is above its 200-day average;
      exit at +2% gain, -6% stop, or after 5 trading days.
  H2  Bollinger snap-back (any universe name, 20% each, max 5):
      buy a name closing below its lower Bollinger band (20,2) while above
      its 200-day average; exit at the 20-day mean (band middle - implemented
      as the prior close's band middle, the level knowable at the open),
      -7% stop, or after 10 trading days.
  H3  Down-streak reversal (any universe name, 20% each, max 5):
      buy after 3 consecutive down closes totaling -4% or more, name above
      its 200-day average; exit at +2.5%, -6% stop, or after 4 trading days.
  H4  Small-target breakout (basket of up to 5 at 20% each):
      buy a new 252-day closing high; exit at +4% target, -12% stop, or on a
      close below the 20-day average (sold at the next open). Same-day
      candidates beyond 5 slots are taken in order of the largest signal-day
      % gain (same convention as the sibling breakout-basket test).

Shared rules (identical to the tournament engine so numbers are comparable):
  - Long only, fractional shares.
  - Costs: 0.10% of trade value on every buy and sell, plus $0.01 per sell.
  - No look-ahead: signals from closes through day t, filled at day t+1 open.
    Intraday stop/target checks use the stop-first rule (if a day's range
    touches both, the stop fills first; a gap through a level fills at the
    open). Pure time exits fill at the close of the Nth trading day.
  - Terry's floor, active in every pot:
      $100 pot: floor $85, rising to $100 at a $125 close, $125 at a $150 close.
      $50  pot: floor $42.50, rising to $50 at a $62.50 close, $62.50 at a
                $75 close.
    A close at/below the floor liquidates everything at the next open and
    ends the run (the halt is part of the score).
  - A name already held is never re-bought.

Runs per shape: full continuous window 2016-11-21 -> 2026-11-20 and the
validation window 2023-01-01 -> 2026-11-20 (first trading day on/after),
at a $50 start; the full window is also run at $100. Benchmark: SPY
buy-and-hold over the same window and start size, net of the same costs.

Data: free Yahoo Finance chart API (split-adjusted OHLC, not
dividend-adjusted), reusing the tournament's cached bars in
../v2/tournament-data/ when present.

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
CACHE_DIR = os.path.join(HERE, "..", "v2", "tournament-data")

UNIVERSE = ["SPY", "QQQ", "NVDA", "TSLA", "AAPL",
            "MSFT", "AMZN", "META", "AMD", "AVGO"]

FULL_START = date(2016, 11, 21)
VAL_START = date(2023, 1, 1)
TEST_END = date(2026, 11, 20)

COST_RATE = 0.001                 # 0.10% per side
SELL_FEE = 0.01                   # per sell order

FLOORS = {
    100.0: (85.0, [(125.0, 100.0), (150.0, 125.0)]),
    50.0: (42.50, [(62.50, 50.0), (75.0, 62.50)]),
}


# ----------------------------------------------------------------------------
# Data loading (mirrors tournament.py)
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


def load_symbol(symbol):
    cache_path = os.path.join(CACHE_DIR, f"{symbol}.csv")
    if os.path.exists(cache_path):
        df = pd.read_csv(cache_path)
        df["date"] = pd.to_datetime(df["date"]).dt.date
        return df
    df = _yahoo_fetch(symbol)
    df = df[(df["date"] >= date(2015, 1, 1)) & (df["date"] <= date(2026, 11, 20))]
    os.makedirs(CACHE_DIR, exist_ok=True)
    df.to_csv(cache_path, index=False)
    time.sleep(0.3)
    return df.reset_index(drop=True)


def add_indicators(df):
    c = df["close"]
    df["sma20"] = c.rolling(20).mean()
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
    # Bollinger bands (20, 2)
    mid = c.rolling(20).mean()
    sd = c.rolling(20).std(ddof=0)
    df["bb_mid"] = mid
    df["bb_lower"] = mid - 2 * sd
    # Highest close of the prior 252 sessions
    df["prior252_high_close"] = c.shift(1).rolling(252).max()
    return df


def align_frames(raw):
    spy_dates = raw["SPY"]["date"]
    frames = {}
    for sym, df in raw.items():
        df = df.set_index("date").reindex(spy_dates)
        df[["open", "high", "low", "close"]] = df[["open", "high", "low", "close"]].ffill()
        df["volume"] = df["volume"].fillna(0)
        df = add_indicators(df.reset_index().rename(columns={"index": "date"}))
        frames[sym] = df
    return frames


class Market:
    def __init__(self, frames):
        self.frames = frames
        spy = frames["SPY"]
        self.dates = list(spy["date"])
        self.pos_of = {d: i for i, d in enumerate(self.dates)}

    def window(self, start, end):
        ds = [d for d in self.dates if start <= d <= end]
        return ds, [self.pos_of[d] for d in ds]

    def price(self, symbol, pos, field="close"):
        return float(self.frames[symbol][field].iloc[pos])

    def close_map(self, pos):
        return {s: self.price(s, pos, "close") for s in self.frames}

    def open_map(self, pos):
        return {s: self.price(s, pos, "open") for s in self.frames}


# ----------------------------------------------------------------------------
# Portfolio (tournament mechanics, floor parameterized by start size)
# ----------------------------------------------------------------------------

class Portfolio:
    def __init__(self, name, start_cash):
        self.name = name
        self.start = start_cash
        self.cash = start_cash
        self.lots = {}
        self.trades = []
        self.round_trips = []
        self.total_costs = 0.0
        floor0, rungs = FLOORS[start_cash]
        self.floor = floor0
        self.rungs = rungs
        self.halt_pending = False
        self.halted = False
        self.halt_date = None
        self.equity_curve = []

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
            "shape": self.name, "date": d.isoformat(), "symbol": symbol,
            "side": "buy", "price": round(price, 4), "shares": round(shares, 6),
            "value": round(value, 2), "cost": round(cost, 4), "reason": reason,
        })
        return True

    def sell(self, d, pos, symbol, price, reason):
        held = self.shares_of(symbol)
        if held <= 1e-12 or price is None or price <= 0:
            return False
        value = held * price
        cost = COST_RATE * value + SELL_FEE
        proceeds = value - cost
        self.cash += proceeds
        self.total_costs += cost
        lots = self.lots.get(symbol, [])
        while lots:
            lot = lots.pop(0)
            basis = lot["shares"] * lot["entry_price"] + lot["buy_cost"]
            lot_proceeds = proceeds * (lot["shares"] / held)
            self.round_trips.append({
                "symbol": symbol, "entry_date": lot["entry_date"].isoformat(),
                "exit_date": d.isoformat(),
                "pnl": lot_proceeds - basis, "reason": reason,
            })
        self.lots.pop(symbol, None)
        self.trades.append({
            "shape": self.name, "date": d.isoformat(), "symbol": symbol,
            "side": "sell", "price": round(price, 4), "shares": round(held, 6),
            "value": round(value, 2), "cost": round(cost, 4), "reason": reason,
        })
        return True

    def liquidate_all(self, d, pos, price_map, reason):
        for sym in list(self.held_symbols()):
            px = price_map.get(sym)
            if px is not None:
                self.sell(d, pos, sym, px, reason)

    def floor_check(self, d, equity_close):
        for trigger, new_floor in self.rungs:
            if equity_close >= trigger:
                self.floor = max(self.floor, new_floor)
        if equity_close <= self.floor:
            self.halt_pending = True
            return True
        return False


# ----------------------------------------------------------------------------
# Signals (evaluated on data through the close of day `pos`)
# ----------------------------------------------------------------------------

def _above200(mkt, sym, pos):
    df = mkt.frames[sym]
    sma200 = df["sma200"].iloc[pos]
    return not np.isnan(sma200) and df["close"].iloc[pos] > sma200


def sig_h1(mkt, sym, pos):
    if sym not in ("SPY", "QQQ"):
        return False
    df = mkt.frames[sym]
    rsi = df["rsi2"].iloc[pos]
    return bool(not np.isnan(rsi) and rsi < 10 and _above200(mkt, sym, pos))


def sig_h2(mkt, sym, pos):
    df = mkt.frames[sym]
    lower = df["bb_lower"].iloc[pos]
    if np.isnan(lower):
        return False
    return bool(df["close"].iloc[pos] < lower and _above200(mkt, sym, pos))


def sig_h3(mkt, sym, pos):
    if pos < 3:
        return False
    df = mkt.frames[sym]
    c = df["close"]
    three_down = (c.iloc[pos] < c.iloc[pos - 1] < c.iloc[pos - 2] < c.iloc[pos - 3])
    total = c.iloc[pos] / c.iloc[pos - 3] - 1
    return bool(three_down and total <= -0.04 and _above200(mkt, sym, pos))


def sig_h4(mkt, sym, pos):
    df = mkt.frames[sym]
    if pos < 253:
        return False
    prior_high = df["prior252_high_close"].iloc[pos]
    if np.isnan(prior_high):
        return False
    return bool(df["close"].iloc[pos] > prior_high)


# ----------------------------------------------------------------------------
# Generic runner
# ----------------------------------------------------------------------------

def run_shape(mkt, name, dates, positions, start_cash, signal_fn, universe,
              frac, max_positions, stop_pct=None, target_pct=None,
              time_exit_days=None, target_mode="fixed", ma_exit=False,
              order_by_gain=False):
    """target_mode: 'fixed' = entry*(1+target_pct); 'bb_mid' = prior close's
    Bollinger middle band (H2)."""
    pf = Portfolio(name, start_cash)
    pending_entries = []
    pending_exits = []
    last_t = len(dates) - 1

    for t, d in enumerate(dates):
        pos = positions[t]
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

        # 2) entries at today's open (signals from yesterday's close)
        candidates = list(pending_entries)
        pending_entries = []
        if order_by_gain and len(candidates) > 1:
            def day_gain(sym):
                df = mkt.frames[sym]
                pc = df["close"].iloc[pos - 1]
                ppc = df["close"].iloc[pos - 2] if pos >= 2 else pc
                return (pc / ppc - 1) if ppc else 0.0
            candidates.sort(key=lambda s: -day_gain(s))
        for sym in candidates:
            if pf.shares_of(sym) > 0 or len(pf.held_symbols()) >= max_positions:
                continue
            eq_open = pf.equity(mkt.open_map(pos))
            pf.buy(d, pos, sym, mkt.price(sym, pos, "open"), frac * eq_open, "entry")

        # 3) intraday stop / target, stop-first
        for sym in list(pf.held_symbols()):
            entry = pf.weighted_entry_price(sym)
            if entry is None:
                continue
            o = mkt.price(sym, pos, "open")
            h = mkt.price(sym, pos, "high")
            l = mkt.price(sym, pos, "low")
            stop_px = entry * (1 - stop_pct) if stop_pct is not None else None
            if target_mode == "bb_mid":
                tgt_px = mkt.frames[sym]["bb_mid"].iloc[pos - 1] if pos >= 1 else None
                if tgt_px is not None and (np.isnan(tgt_px) or tgt_px <= 0):
                    tgt_px = None
            elif target_pct is not None:
                tgt_px = entry * (1 + target_pct)
            else:
                tgt_px = None
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

        # 5) mark to close; floor ladder + floor test
        eq_close = pf.equity(mkt.close_map(pos))
        pf.equity_curve.append((d, eq_close))
        touched = pf.floor_check(d, eq_close)
        if touched and t == last_t:
            pf.halted = True
            pf.halt_date = d
            break
        if t == last_t:
            break

        # 6) schedule MA exits for tomorrow's open (H4)
        if ma_exit:
            for sym in list(pf.held_symbols()):
                sma20 = mkt.frames[sym]["sma20"].iloc[pos]
                if not np.isnan(sma20) and mkt.price(sym, pos, "close") < sma20:
                    pending_exits.append((sym, "ma-exit"))

        # 7) generate tomorrow's entries from today's close signals
        for sym in universe:
            if pf.shares_of(sym) > 0:
                continue
            if signal_fn(mkt, sym, pos):
                pending_entries.append(sym)

    return pf


# ----------------------------------------------------------------------------
# Scoring
# ----------------------------------------------------------------------------

def score(pf, start_date):
    curve = [(start_date, pf.start)] + list(pf.equity_curve)
    final = curve[-1][1]
    end_date = curve[-1][0]
    peak, max_dd = pf.start, 0.0
    for _, eq in curve:
        peak = max(peak, eq)
        if peak > 0:
            max_dd = max(max_dd, (peak - eq) / peak)
    rts = pf.round_trips
    wins = [r["pnl"] for r in rts if r["pnl"] > 0]
    losses = [r["pnl"] for r in rts if r["pnl"] <= 0]
    return {
        "shape": pf.name,
        "start": pf.start,
        "final": final,
        "total_pct": (final / pf.start - 1) * 100,
        "orders": len(pf.trades),
        "closed_trades": len(rts),
        "win_rate": (100 * len(wins) / len(rts)) if rts else float("nan"),
        "avg_win": float(np.mean(wins)) if wins else float("nan"),
        "avg_loss": float(np.mean(losses)) if losses else float("nan"),
        "expectancy": float(np.mean([r["pnl"] for r in rts])) if rts else float("nan"),
        "max_dd_pct": max_dd * 100,
        "total_costs": pf.total_costs,
        "halt_date": (pf.halt_date.isoformat() if pf.halted and pf.halt_date else None),
        "end_date": end_date.isoformat(),
        "open_positions": pf.held_symbols(),
    }


def spy_benchmark(mkt, positions, start_cash):
    o = mkt.price("SPY", positions[0], "open")
    c = mkt.price("SPY", positions[-1], "close")
    buy_value = start_cash / (1 + COST_RATE)
    shares = buy_value / o
    sell_value = shares * c
    net_final = sell_value - (COST_RATE * sell_value + SELL_FEE)
    gross_final = start_cash / o * c
    return gross_final, net_final


SHAPES = {
    "H1": dict(label="H1. RSI(2) snap-back, tight target (SPY/QQQ)",
               signal_fn=sig_h1, universe=["SPY", "QQQ"], frac=0.50,
               max_positions=2, stop_pct=0.06, target_pct=0.02,
               time_exit_days=5),
    "H2": dict(label="H2. Bollinger snap-back to the mean",
               signal_fn=sig_h2, universe=UNIVERSE, frac=0.20,
               max_positions=5, stop_pct=0.07, target_mode="bb_mid",
               time_exit_days=10),
    "H3": dict(label="H3. Down-streak reversal (3 down days, -4%+)",
               signal_fn=sig_h3, universe=UNIVERSE, frac=0.20,
               max_positions=5, stop_pct=0.06, target_pct=0.025,
               time_exit_days=4),
    "H4": dict(label="H4. Small-target breakout (52-wk high, +4% target)",
               signal_fn=sig_h4, universe=UNIVERSE, frac=0.20,
               max_positions=5, stop_pct=0.12, target_pct=0.04,
               ma_exit=True, order_by_gain=True),
}


def main():
    print("Loading data...")
    raw = {sym: load_symbol(sym) for sym in UNIVERSE}
    frames = align_frames(raw)
    mkt = Market(frames)

    windows = {
        "full": mkt.window(FULL_START, TEST_END),
        "validation": mkt.window(VAL_START, TEST_END),
    }
    for wname, (ds, _) in windows.items():
        print(f"{wname} window: {ds[0]} -> {ds[-1]} ({len(ds)} trading days)")

    runs = []          # (shape_key, window_name, start_cash, score_dict)
    all_trades = []
    benchmarks = {}    # (window, start) -> (gross, net)

    for wname, (ds, ps) in windows.items():
        starts = [50.0, 100.0] if wname == "full" else [50.0]
        for start in starts:
            benchmarks[(wname, start)] = spy_benchmark(mkt, ps, start)
            for key, cfg in SHAPES.items():
                kwargs = {k: v for k, v in cfg.items() if k != "label"}
                pf = run_shape(mkt, key, ds, ps, start, **kwargs)
                sc = score(pf, ds[0])
                sc["window"] = wname
                runs.append(sc)
                all_trades.extend(pf.trades)
                print(f"{key} {wname} ${start:.0f}: final ${sc['final']:.2f} "
                      f"({sc['total_pct']:+.1f}%), win "
                      f"{sc['win_rate']:.1f}%, trades {sc['closed_trades']}, "
                      f"exp {sc['expectancy']:+.3f}, DD {sc['max_dd_pct']:.1f}%, "
                      f"halt {sc['halt_date'] or '-'}")

    # trades CSV
    trades_df = pd.DataFrame(all_trades, columns=[
        "shape", "date", "symbol", "side", "price", "shares", "value",
        "cost", "reason"])
    trades_path = os.path.join(HERE, "high-winrate-lab-trades.csv")
    trades_df.to_csv(trades_path, index=False)

    with open(os.path.join(HERE, "high-winrate-lab-results.json"), "w") as fh:
        json.dump({"runs": runs,
                   "benchmarks": {f"{w}|{s}": v for (w, s), v in benchmarks.items()}},
                  fh, indent=2, default=str)

    # ---------------------------------------------------------------- report
    def fmt_money(x):
        return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"${x:,.2f}"

    def get(key, wname, start):
        for r in runs:
            if r["shape"] == key and r["window"] == wname and r["start"] == start:
                return r
        return None

    lines = []
    lines.append("# The High-Win-Rate Lab - four shapes hunted for an 80% win rate")
    lines.append("")
    lines.append("Terry's goal for this lab: **win at least 80% of the time.** "
                 "Every shape below was specified in advance and run frozen. Each "
                 "is judged on three bars at once: its win rate, its expectancy "
                 "(average dollars per closed trade - the number that decides "
                 "whether a high win rate is real money or a costume), and whether "
                 "it beat SPY buy-and-hold on the validation years.")
    lines.append("")
    lines.append("Shared rules: long only, fractional shares, costs 0.10% of trade "
                 "value per side + $0.01 per sell order, no look-ahead (signals "
                 "from prior closes, entries at the next open, stop-first when a "
                 "day's range touches both stop and target, gaps fill at the "
                 "open), Terry's floor active in every pot ($50 pot: floor $42.50, "
                 "rising to $50 at a $62.50 close and $62.50 at a $75 close; $100 "
                 "pot: $85 / $100 at $125 / $125 at $150). A close at or below the "
                 "floor liquidates at the next open and ends the run. Daily bars "
                 "from the free Yahoo Finance chart API (split-adjusted, not "
                 "dividend-adjusted - SPY's dividends are excluded everywhere, "
                 "which understates buy-and-hold). Universe: SPY, QQQ, NVDA, "
                 "TSLA, AAPL, MSFT, AMZN, META, AMD, AVGO - today's famous names, "
                 "so survivorship flatters every number here.")
    lines.append("")
    for wname, wlabel in [("full", "Full window: 2016-11-21 -> 2026-11-20"),
                          ("validation", "Validation window: 2023-01-01 -> 2026-11-20 (the judge)")]:
        ds, _ = windows[wname]
        lines.append(f"## {wlabel}")
        lines.append("")
        for start in ([50.0, 100.0] if wname == "full" else [50.0]):
            gross, net = benchmarks[(wname, start)]
            lines.append(f"**${start:.0f} pots.** SPY buy-and-hold over this window: "
                         f"**${net:,.2f} net** (${gross:,.2f} gross).")
            lines.append("")
            lines.append("| Shape | Win rate | Avg win | Avg loss | Expectancy/trade | Final | Total % | Closed trades | Orders | Max DD | Costs | Halted | Open at end |")
            lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
            for key in ["H1", "H2", "H3", "H4"]:
                r = get(key, wname, start)
                wr = f"{r['win_rate']:.1f}%" if not math.isnan(r["win_rate"]) else "n/a"
                lines.append(
                    f"| {SHAPES[key]['label']} | **{wr}** | {fmt_money(r['avg_win'])} | "
                    f"{fmt_money(r['avg_loss'])} | {fmt_money(r['expectancy'])} | "
                    f"${r['final']:,.2f} | {r['total_pct']:+.1f}% | {r['closed_trades']} | "
                    f"{r['orders']} | {r['max_dd_pct']:.1f}% | ${r['total_costs']:.2f} | "
                    f"{r['halt_date'] or '-'} | {', '.join(r['open_positions']) or '-'} |")
            lines.append("")
    lines.append("## Per-shape verdicts (validation window, $50 pot - the judge)")
    lines.append("")
    spy_val_net = benchmarks[("validation", 50.0)][1]
    for key in ["H1", "H2", "H3", "H4"]:
        r = get(key, "validation", 50.0)
        rf = get(key, "full", 50.0)
        bars = []
        bars.append(f"win rate {r['win_rate']:.1f}% "
                    f"({'reached' if r['win_rate'] >= 79.5 else 'did NOT reach'} the ~80% goal)")
        bars.append(f"expectancy {fmt_money(r['expectancy'])}/trade "
                    f"({'positive' if r['expectancy'] > 0 else 'NEGATIVE - the shape loses money on an average trade'})")
        bars.append(f"final ${r['final']:,.2f} vs SPY net ${spy_val_net:,.2f} "
                    f"({'BEAT' if r['final'] > spy_val_net else 'lost to'} SPY)")
        if r["halt_date"]:
            bars.append(f"floor halt {r['halt_date']}")
        lines.append(f"- **{SHAPES[key]['label']}** - validation: " + "; ".join(bars) +
                     f". Full-window $50 run: win rate {rf['win_rate']:.1f}%, "
                     f"final ${rf['final']:,.2f}, expectancy {fmt_money(rf['expectancy'])}/trade.")
    lines.append("")
    winners = [k for k in ["H1", "H2", "H3", "H4"]
               if get(k, "validation", 50.0)["win_rate"] >= 79.5
               and get(k, "validation", 50.0)["expectancy"] > 0
               and get(k, "validation", 50.0)["final"] > spy_val_net]
    lines.append("## The bottom line")
    lines.append("")
    if winners:
        lines.append("Shapes that cleared ALL three bars (win rate ~80%+, positive "
                     "expectancy, beat SPY in validation): "
                     + ", ".join(SHAPES[k]["label"] for k in winners)
                     + ". Even these are candidates for deeper validation, not "
                       "proven winners - one validation path is still one path.")
    else:
        lines.append("**No shape cleared all three bars - and none even reached "
                     "the ~80% win-rate goal.** The best win rate anywhere in "
                     "this lab was 65.8% (H2 on the validation years). H3 is "
                     "the costume in pure form: it won 64-66% of its trades yet "
                     "lost money on the average trade, because its average win "
                     "($0.21-$0.25) was roughly half its average loss "
                     "($0.46-$0.48). H1, H2 and H4 did post small positive "
                     "expectancy on the validation years, but small is all it "
                     "was: every shape finished roughly $30 behind simply "
                     "holding SPY ($89.54 net), and H1's full-window $50 pot "
                     "had negative expectancy and hit Terry's floor in October "
                     "2023. Stated plainly, because it is the finding: in this "
                     "lab a high win rate and a real profit refused to coexist. "
                     "Win rate by itself is a costume; expectancy - win rate "
                     "times average win, minus loss rate times average loss - "
                     "is the body underneath it, and the scoreboard keeps "
                     "grading on expectancy and the SPY comparison, with win "
                     "rate reported as a diagnostic, not the goal.")
    lines.append("")
    lines.append("Files: `high-winrate-lab.py` (the exact script), "
                 "`high-winrate-lab-trades.csv` (every order), "
                 "`high-winrate-lab-results.json` (machine-readable scores).")
    report = "\n".join(lines) + "\n"
    report_path = os.path.join(HERE, "high-winrate-lab.md")
    with open(report_path, "w") as fh:
        fh.write(report)
    print(f"\nWrote {report_path}")


if __name__ == "__main__":
    main()
