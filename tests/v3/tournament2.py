#!/usr/bin/env python3
"""
Strategy Tournament ROUND 2 - Terry's AI stock app (v3 track).

Five NEW strategy families (Round 1's seven chart styles live in ../v2), each
on its own $100 pot, run on the same 10 years of daily data, same costs, same
floor rules:

  F1  Dual momentum (GEM-style)      - monthly, SPY / IEFA / AGG / SHY
  F2  Donchian trend basket          - 55-day breakout / 20-day exit, 9 ETFs
  F3  Low volatility                 - monthly, calmest 2 of SPY QQQ IWM GLD TLT
  F4  Overnight effect               - SPY bought at every close, sold next open
  F5  Turn of month                  - SPY held only around the month turn

Windows:
  FULL       2016-11-21 -> 2026-11-20 (per-year table)
  DESIGN     2016-11-21 -> 2022-12-31 (fresh $100)
  VALIDATION 2023-01-01 -> 2026-11-20 (fresh $100)

Shared rules:
  - Long only, fractional shares.
  - Costs: 0.10% of trade value on every buy and every sell, plus $0.01 per
    sell order.
  - No look-ahead: signals computed from closes up to and including day t;
    executions at day t+1's open, EXCEPT families defined on closes
    (F4 overnight, F5 turn-of-month) which trade at the close itself, and the
    monthly families (F1/F3) whose month-end-close decisions execute at the
    next open.
  - Terry's floor: floor starts at $85; a closing pot value of $125+ raises it
    to $100; $150+ raises it to $125. A close at or below the floor liquidates
    everything at the next open and ENDS the run (halt date recorded).
  - At the end of a window any open position is liquidated at the last close
    (sell costs charged) so the final balance is cash.

Data: free Yahoo Finance chart API (split-adjusted OHLC, NOT dividend
adjusted), cached under tournament2-data/. Caches left by the v2 tracks are
reused when present. Simulation only - no broker orders.
"""

import json
import os
import time
import urllib.request
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, "tournament2-data")
os.makedirs(CACHE_DIR, exist_ok=True)
V2_TOURNAMENT_DATA = os.path.join(HERE, "..", "v2", "tournament-data")
V2_DATA = os.path.join(HERE, "..", "v2", "data")

FETCH_START = date(2015, 1, 1)
FETCH_END = date(2026, 11, 21)

SYMBOLS = ["SPY", "IEFA", "AGG", "SHY", "QQQ", "IWM", "EEM",
           "GLD", "TLT", "VNQ", "DBC"]

START_CASH = 100.0
COST_RATE = 0.001          # 0.10% per side
SELL_FEE = 0.01            # per sell order

WINDOWS = {
    "full":       (date(2016, 11, 21), date(2026, 11, 20)),
    "design":     (date(2016, 11, 21), date(2022, 12, 31)),
    "validation": (date(2023, 1, 1),   date(2026, 11, 20)),
}


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
        o, h, l, c, v = (q["open"][i], q["high"][i], q["low"][i],
                         q["close"][i], q["volume"][i])
        if None in (o, h, l, c) or c <= 0:
            continue
        rows.append((d, o, h, l, c, v or 0))
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    return df.drop_duplicates("date").sort_values("date").reset_index(drop=True)


def _read_csv(path):
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df[["date", "open", "high", "low", "close", "volume"]] \
        .drop_duplicates("date").sort_values("date").reset_index(drop=True)


def load_symbol(symbol):
    cache_path = os.path.join(CACHE_DIR, f"{symbol}.csv")
    if os.path.exists(cache_path):
        return _read_csv(cache_path)
    for alt in (os.path.join(V2_TOURNAMENT_DATA, f"{symbol}.csv"),
                os.path.join(V2_DATA, f"{symbol}.csv")):
        if os.path.exists(alt):
            df = _read_csv(alt)
            if df["date"].min() <= date(2015, 6, 1) and df["date"].max() >= date(2026, 11, 1):
                df.to_csv(cache_path, index=False)
                return df
    df = None
    for attempt in range(3):
        try:
            df = _yahoo_fetch(symbol)
            break
        except Exception as exc:  # noqa: BLE001
            print(f"fetch {symbol} attempt {attempt + 1} failed: {exc}")
            time.sleep(2 * (attempt + 1))
    if df is None or df.empty:
        raise RuntimeError(f"could not load data for {symbol}")
    df.to_csv(cache_path, index=False)
    return df


def prepare(df):
    """Add indicators; index rows by date for O(1) lookup."""
    df = df.copy()
    df["ma200"] = df["close"].rolling(200).mean()
    df["ret252"] = df["close"] / df["close"].shift(252) - 1.0
    df["high55_prev"] = df["high"].rolling(55).max().shift(1)
    df["low20_prev"] = df["low"].rolling(20).min().shift(1)
    df["vol20"] = df["close"].pct_change().rolling(20).std()
    df.attrs["pos"] = {d: i for i, d in enumerate(df["date"])}
    df.attrs["dates"] = df["date"].tolist()
    return df


DATA = {}
CAL = None  # master calendar = SPY trading days


def bar(sym, d, field):
    df = DATA[sym]
    i = df.attrs["pos"].get(d)
    if i is None:
        return None
    v = df[field].iloc[i]
    return None if (v is None or (isinstance(v, float) and np.isnan(v))) else float(v)


def last_close(sym, d):
    """Most recent close on or before date d (for marking / fallback fills)."""
    import bisect
    df = DATA[sym]
    j = bisect.bisect_right(df.attrs["dates"], d) - 1
    if j < 0:
        return None
    return float(df["close"].iloc[j])


# ----------------------------------------------------------------------------
# Portfolio
# ----------------------------------------------------------------------------

class Portfolio:
    def __init__(self, window, family):
        self.window = window
        self.family = family
        self.cash = START_CASH
        self.pos = {}            # sym -> {"shares", "basis", "proceeds"}
        self.trades = []         # order rows
        self.trips = []          # closed-trip P&Ls
        self.total_costs = 0.0
        self.orders = 0
        self.floor = 85.0
        self.halt_trigger = None
        self.halt_date = None
        self.equity_series = []  # (date, close equity)

    # -- trading ------------------------------------------------------------
    def buy(self, d, sym, price, notional, reason):
        """Buy `notional` dollars of shares; cost charged on top from cash."""
        if price is None or price <= 0 or notional <= 0:
            return 0.0
        cost = notional * COST_RATE
        if notional + cost > self.cash:
            notional = self.cash / (1.0 + COST_RATE)
            cost = notional * COST_RATE
        if notional < 0.01:
            return 0.0
        shares = notional / price
        self.cash -= notional + cost
        p = self.pos.setdefault(sym, {"shares": 0.0, "basis": 0.0, "proceeds": 0.0})
        p["shares"] += shares
        p["basis"] += notional + cost
        self.total_costs += cost
        self.orders += 1
        self.trades.append([self.window, self.family, d.isoformat(), sym, "BUY",
                            round(price, 4), round(shares, 6), round(notional, 2),
                            round(cost, 4), reason])
        return shares

    def sell(self, d, sym, price, shares=None, reason=""):
        if price is None or price <= 0 or sym not in self.pos:
            return 0.0
        p = self.pos[sym]
        if shares is None or shares >= p["shares"]:
            shares = p["shares"]
            full = True
        else:
            full = False
        if shares <= 0:
            return 0.0
        value = shares * price
        cost = value * COST_RATE + SELL_FEE
        net = value - cost
        self.cash += net
        p["shares"] -= shares
        p["proceeds"] += net
        self.total_costs += cost
        self.orders += 1
        self.trades.append([self.window, self.family, d.isoformat(), sym, "SELL",
                            round(price, 4), round(shares, 6), round(value, 2),
                            round(cost, 4), reason])
        if full or p["shares"] <= 1e-9:
            self.trips.append(p["proceeds"] - p["basis"])
            del self.pos[sym]
        return net

    def sell_value(self, d, sym, price, value, reason):
        if price is None or price <= 0:
            return 0.0
        return self.sell(d, sym, price, shares=value / price, reason=reason)

    # -- valuation ------------------------------------------------------------
    def equity_close(self, d):
        eq = self.cash
        for sym, p in self.pos.items():
            c = bar(sym, d, "close")
            if c is None:
                c = last_close(sym, d)
            eq += p["shares"] * c
        return eq

    def equity_at_open(self, d):
        eq = self.cash
        for sym, p in self.pos.items():
            o = bar(sym, d, "open")
            if o is None:
                o = last_close(sym, d)
            eq += p["shares"] * o
        return eq

    def position_value_open(self, sym, d):
        if sym not in self.pos:
            return 0.0
        o = bar(sym, d, "open")
        if o is None:
            o = last_close(sym, d)
        return self.pos[sym]["shares"] * o

    # -- floor ------------------------------------------------------------------
    def record_close(self, d):
        eq = self.equity_close(d)
        self.equity_series.append((d, eq))
        if eq >= 150.0:
            self.floor = max(self.floor, 125.0)
        elif eq >= 125.0:
            self.floor = max(self.floor, 100.0)
        if eq <= self.floor and self.halt_trigger is None:
            self.halt_trigger = d
        return eq

    def liquidate(self, d, at_open, reason):
        for sym in list(self.pos.keys()):
            px = bar(sym, d, "open") if at_open else bar(sym, d, "close")
            if px is None:
                px = last_close(sym, d)
            self.sell(d, sym, px, reason=reason)

    def finalize(self, days):
        """End-of-window: liquidate at last close; return results dict."""
        last = days[-1]
        if self.pos:
            self.liquidate(last, at_open=False, reason="end of window liquidation")
        final = self.cash
        if self.equity_series and self.equity_series[-1][0] == last:
            self.equity_series[-1] = (last, final)
        else:
            self.equity_series.append((last, final))
        return self.results(final, days)

    def results(self, final, days):
        eqs = [START_CASH] + [e for _, e in self.equity_series]
        peak, maxdd = eqs[0], 0.0
        for e in eqs:
            peak = max(peak, e)
            if peak > 0:
                maxdd = max(maxdd, (peak - e) / peak)
        span_days = (days[-1] - days[0]).days
        years = span_days / 365.25 if span_days > 0 else 0.0
        cagr = (final / START_CASH) ** (1.0 / years) - 1.0 if years > 0 and final > 0 else float("nan")
        wins = sum(1 for t in self.trips if t > 0)
        return {
            "final": final,
            "total_pct": (final / START_CASH - 1.0) * 100.0,
            "cagr_pct": cagr * 100.0,
            "orders": self.orders,
            "trips": len(self.trips),
            "win_rate": (100.0 * wins / len(self.trips)) if self.trips else float("nan"),
            "maxdd_pct": maxdd * 100.0,
            "costs": self.total_costs,
            "halt_date": self.halt_date,
            "halt_trigger": self.halt_trigger,
        }


def window_days(start, end):
    return [d for d in CAL if start <= d <= end]


def month_end_days(days):
    out = []
    for i, d in enumerate(days):
        if i == len(days) - 1 or (days[i + 1].year, days[i + 1].month) != (d.year, d.month):
            out.append(d)
    return out


def run_with_floor(pf, days, day_fn):
    """Generic daily loop: day_fn(i, d) acts during day d (opens/closes as the
    family defines); closes are recorded and the floor enforced here."""
    for i, d in enumerate(days):
        if pf.halt_trigger is not None:
            # liquidate at today's open and end the run
            pf.liquidate(d, at_open=True, reason="floor halt liquidation")
            pf.halt_date = d
            pf.equity_series.append((d, pf.cash))
            break
        day_fn(i, d)
        if pf.halt_trigger is None:
            pf.record_close(d)
    return pf, pf.finalize(days)


# ----------------------------------------------------------------------------
# F1 - Dual momentum (GEM-style)
# ----------------------------------------------------------------------------

def run_f1(window, days):
    pf = Portfolio(window, "F1 Dual momentum (GEM)")
    assets = ["SPY", "IEFA"]
    decisions = {}  # execution day -> target symbol
    med = set(month_end_days(days))
    for i, d in enumerate(days):
        if d in med and i + 1 < len(days):
            rets = {}
            ok = True
            for s in assets + ["SHY"]:
                r = bar(s, d, "ret252")
                if r is None:
                    ok = False
                    break
                rets[s] = r
            if not ok:
                continue
            best = max(assets, key=lambda s: rets[s])
            target = best if rets[best] > rets["SHY"] else "AGG"
            decisions[days[i + 1]] = target

    def day_fn(i, d):
        if d in decisions:
            target = decisions[d]
            held = list(pf.pos.keys())
            if held != [target]:
                for s in held:
                    pf.sell(d, s, bar(s, d, "open"), reason="GEM monthly switch out")
                o = bar(target, d, "open")
                if o:
                    pf.buy(d, target, o, pf.cash / (1.0 + COST_RATE),
                           reason="GEM monthly switch in")

    return run_with_floor(pf, days, day_fn)


# ----------------------------------------------------------------------------
# F2 - Donchian trend basket
# ----------------------------------------------------------------------------

def run_f2(window, days):
    pf = Portfolio(window, "F2 Donchian trend basket")
    universe = ["SPY", "QQQ", "IWM", "IEFA", "EEM", "GLD", "TLT", "VNQ", "DBC"]
    pending_exits, pending_entries = [], []

    def day_fn(i, d):
        # execute yesterday's signals at today's open
        for s in pending_exits:
            if s in pf.pos:
                pf.sell(d, s, bar(s, d, "open"), reason="Donchian 20-day low exit")
        exited = set(pending_exits)
        if pending_entries:
            eq = pf.equity_at_open(d)
            slice_val = eq / 5.0
            for s in pending_entries:
                if len(pf.pos) >= 5 or s in pf.pos or s in exited:
                    continue
                o = bar(s, d, "open")
                if o:
                    pf.buy(d, s, o, slice_val, reason="Donchian 55-day high entry")
        pending_exits.clear()
        pending_entries.clear()
        # compute today's signals from closes
        for s in universe:
            c = bar(s, d, "close")
            if c is None:
                continue
            if s in pf.pos:
                lo = bar(s, d, "low20_prev")
                if lo is not None and c < lo:
                    pending_exits.append(s)
            else:
                hi = bar(s, d, "high55_prev")
                if hi is not None and c > hi:
                    pending_entries.append(s)

    return run_with_floor(pf, days, day_fn)


# ----------------------------------------------------------------------------
# F3 - Low volatility
# ----------------------------------------------------------------------------

def run_f3(window, days):
    pf = Portfolio(window, "F3 Low volatility")
    universe = ["SPY", "QQQ", "IWM", "GLD", "TLT"]
    decisions = {}
    med = set(month_end_days(days))
    for i, d in enumerate(days):
        if d in med and i + 1 < len(days):
            elig = []
            for s in universe:
                c, ma, v = bar(s, d, "close"), bar(s, d, "ma200"), bar(s, d, "vol20")
                if c is not None and ma is not None and v is not None and c > ma:
                    elig.append((v, s))
            elig.sort()
            decisions[days[i + 1]] = [s for _, s in elig[:2]]

    def day_fn(i, d):
        if d in decisions:
            targets = decisions[d]
            for s in list(pf.pos.keys()):
                if s not in targets:
                    pf.sell(d, s, bar(s, d, "open"), reason="low-vol monthly drop")
            if targets:
                eq = pf.equity_at_open(d)
                tgt_val = eq / len(targets)
                for s in targets:
                    o = bar(s, d, "open")
                    if o is None:
                        continue
                    cur = pf.position_value_open(s, d)
                    delta = tgt_val - cur
                    if delta > 0.25:
                        pf.buy(d, s, o, delta, reason="low-vol monthly rebalance buy")
                    elif delta < -0.25:
                        pf.sell_value(d, s, o, -delta, reason="low-vol monthly rebalance trim")

    return run_with_floor(pf, days, day_fn)


# ----------------------------------------------------------------------------
# F4 - Overnight effect (SPY only)
# ----------------------------------------------------------------------------

def run_f4(window, days):
    pf = Portfolio(window, "F4 Overnight effect (SPY)")

    def day_fn(i, d):
        last_day = i == len(days) - 1
        # sell at the open whatever was bought at yesterday's close
        if "SPY" in pf.pos:
            pf.sell(d, "SPY", bar("SPY", d, "open"), reason="overnight: sell at open")
        if pf.halt_trigger is not None or last_day:
            return
        c = bar("SPY", d, "close")
        if c:
            pf.buy(d, "SPY", c, pf.cash / (1.0 + COST_RATE),
                   reason="overnight: buy at close")

    # custom loop: floor checked on close equity (cash after the open sale on
    # most days; position value on the final day is handled by finalize)
    for i, d in enumerate(days):
        if pf.halt_trigger is not None:
            pf.liquidate(d, at_open=True, reason="floor halt liquidation")
            pf.halt_date = d
            pf.equity_series.append((d, pf.cash))
            break
        day_fn(i, d)
        if pf.halt_trigger is None:
            pf.record_close(d)
    return pf, pf.finalize(days)


# ----------------------------------------------------------------------------
# F5 - Turn of month (SPY only)
# ----------------------------------------------------------------------------

def run_f5(window, days):
    pf = Portfolio(window, "F5 Turn of month (SPY)")
    # Build hold schedule from the master calendar (needs days just outside the
    # window too, so use the full SPY calendar around the window).
    buys, sells = set(), set()
    by_month = {}
    for d in CAL:
        by_month.setdefault((d.year, d.month), []).append(d)
    months = sorted(by_month.keys())
    for k, ym in enumerate(months[:-1]):
        mdays = by_month[ym]
        nm = by_month[months[k + 1]]
        if len(mdays) >= 2 and len(nm) >= 3:
            b, s = mdays[-2], nm[2]
            if days[0] <= b and s <= days[-1]:
                buys.add(b)
                sells.add(s)

    def day_fn(i, d):
        if d in sells and "SPY" in pf.pos:
            pf.sell(d, "SPY", bar("SPY", d, "close"), reason="turn-of-month: exit at close")
        if d in buys and "SPY" not in pf.pos:
            c = bar("SPY", d, "close")
            if c:
                pf.buy(d, "SPY", c, pf.cash / (1.0 + COST_RATE),
                       reason="turn-of-month: enter at close")

    return run_with_floor(pf, days, day_fn)


FAMILIES = [
    ("F1 Dual momentum (GEM)", run_f1),
    ("F2 Donchian trend basket", run_f2),
    ("F3 Low volatility", run_f3),
    ("F4 Overnight effect (SPY)", run_f4),
    ("F5 Turn of month (SPY)", run_f5),
]


# ----------------------------------------------------------------------------
# Benchmark
# ----------------------------------------------------------------------------

def spy_benchmark(days):
    o = bar("SPY", days[0], "open")
    c = bar("SPY", days[-1], "close")
    gross = START_CASH / o * c
    sh = (START_CASH / (1.0 + COST_RATE)) / o
    net = sh * c * (1.0 - COST_RATE) - SELL_FEE
    return gross, net


# ----------------------------------------------------------------------------
# Reporting
# ----------------------------------------------------------------------------

def per_year_table(pf, res):
    rows = []
    years = sorted({d.year for d, _ in pf.equity_series})
    if pf.halt_date:
        # after a halt the run is over; later "years" are just the frozen
        # final balance appended by finalize() - do not present them as years
        years = [y for y in years if y <= pf.halt_date.year]
    prev_eq = START_CASH
    for y in years:
        eqs = [e for d, e in pf.equity_series if d.year == y]
        if not eqs:
            continue
        end_eq = eqs[-1]
        ret = (end_eq / prev_eq - 1.0) * 100.0 if prev_eq > 0 else float("nan")
        orders_y = sum(1 for t in pf.trades if int(t[2][:4]) == y)
        costs_y = sum(t[8] for t in pf.trades if int(t[2][:4]) == y)
        halted_note = ""
        if pf.halt_date and pf.halt_date.year == y:
            halted_note = f" (HALTED {pf.halt_date.isoformat()})"
        rows.append(f"| {y} | ${prev_eq:,.2f} | ${end_eq:,.2f} | {ret:+.2f}% | "
                    f"{orders_y} | ${costs_y:,.2f}{halted_note} |")
        prev_eq = end_eq
    return rows


def fmt_pct(x):
    return "n/a" if x != x else f"{x:.1f}"


def verdict(fname, res_d, res_v, bench_d_net, bench_v_net):
    """Honest per-family verdict from the design/validation split."""
    beat_d = res_d["final"] > bench_d_net
    beat_v = res_v["final"] > bench_v_net
    lost_v = res_v["final"] < START_CASH
    halted = res_d["halt_date"] or res_v["halt_date"]
    if beat_v and beat_d and not halted:
        return ("EARNS FURTHER TESTING - beat SPY net in BOTH design and "
                "validation, no floor halt.")
    if beat_v and not halted:
        return ("PROMISING BUT UNPROVEN - beat SPY net in validation but not "
                "in design; inconsistent across periods, needs more evidence.")
    if beat_d and not beat_v:
        return ("SUSPECT - beat SPY in the design years only and failed in "
                "validation; the classic overfit signature. Culled unless "
                "re-proven on fresh data.")
    if lost_v:
        return "CULLED - lost money in the validation period."
    return "CULLED - made money in validation but still trailed SPY buy-and-hold net."


def main():
    global CAL
    for sym in SYMBOLS:
        DATA[sym] = prepare(load_symbol(sym))
        print(f"loaded {sym}: {len(DATA[sym])} bars "
              f"{DATA[sym]['date'].iloc[0]} -> {DATA[sym]['date'].iloc[-1]}")
    CAL = DATA["SPY"]["date"].tolist()

    runs = {}      # (family, window) -> (pf, res)
    benches = {}   # window -> (gross, net)
    wdays = {}
    for wname, (ws, we) in WINDOWS.items():
        days = window_days(ws, we)
        wdays[wname] = days
        benches[wname] = spy_benchmark(days)
        print(f"\n== window {wname}: {days[0]} -> {days[-1]} ({len(days)} days) "
              f"SPY gross ${benches[wname][0]:.2f} net ${benches[wname][1]:.2f}")
        for fname, fn in FAMILIES:
            pf, res = fn(wname, days)
            runs[(fname, wname)] = (pf, res)
            print(f"  {fname}: final ${res['final']:.2f} "
                  f"({res['total_pct']:+.2f}%) CAGR {res['cagr_pct']:+.2f}% "
                  f"orders {res['orders']} trips {res['trips']} "
                  f"win {fmt_pct(res['win_rate'])}% DD {res['maxdd_pct']:.1f}% "
                  f"costs ${res['costs']:.2f} halt {res['halt_date']}")

    # ---- trades CSV ---------------------------------------------------------
    trades_path = os.path.join(HERE, "tournament2-trades.csv")
    rows = []
    for (fname, wname), (pf, _res) in runs.items():
        rows.extend(pf.trades)
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    pd.DataFrame(rows, columns=["window", "family", "date", "symbol", "side",
                                "price", "shares", "value", "cost", "reason"]) \
        .to_csv(trades_path, index=False)
    print(f"\nwrote {trades_path} ({len(rows)} orders)")

    # ---- markdown report ------------------------------------------------------
    fd = wdays["full"]
    lines = []
    lines.append("# Strategy Tournament Round 2 - five new families, 10 years")
    lines.append("")
    lines.append(f"Full window: **{fd[0].isoformat()} to {fd[-1].isoformat()}** "
                 f"({len(fd)} trading days), each family on its own $100 pot. "
                 "Daily bars from the free Yahoo Finance chart API "
                 "(split-adjusted, not dividend-adjusted - SPY's dividends are "
                 "NOT counted anywhere here, which understates buy-and-hold and "
                 "every family alike).")
    lines.append("")
    lines.append("Shared rules: long only, fractional shares, costs 0.10% of "
                 "trade value per side + $0.01 per sell order, no look-ahead "
                 "(signals from prior closes; monthly and Donchian families "
                 "execute at the next open; the overnight and turn-of-month "
                 "families are defined on closes and trade at the close), "
                 "Terry's floor active in every pot ($85, rising to $100 at a "
                 "$125 close and $125 at a $150 close; a close at/below the "
                 "floor liquidates at the next open and ends the run). Open "
                 "positions are liquidated at the last close of each window so "
                 "every final balance is cash.")
    lines.append("")
    lines.append("**Design vs validation:** every family also ran on two "
                 "sub-periods with a fresh $100 each - DESIGN "
                 f"{wdays['design'][0].isoformat()} to {wdays['design'][-1].isoformat()} "
                 "and VALIDATION "
                 f"{wdays['validation'][0].isoformat()} to {wdays['validation'][-1].isoformat()}. "
                 "A family that only looks good in the design years is treated "
                 "as suspect (overfit signature); the validation years are the "
                 "ones the rules were not chosen in.")
    lines.append("")
    g, n = benches["full"]
    lines.append(f"**Benchmark (full window):** $100 of SPY bought at the first "
                 f"open and sold at the last close = **${g:,.2f} gross / "
                 f"${n:,.2f} net** ({(g / 100 - 1) * 100:+.1f}% total, price "
                 "only, no dividends).")
    gd, nd = benches["design"]
    gv, nv = benches["validation"]
    lines.append(f"**Benchmark (design):** ${gd:,.2f} gross / ${nd:,.2f} net. "
                 f"**Benchmark (validation):** ${gv:,.2f} gross / ${nv:,.2f} net.")
    lines.append("")

    # ranked table (full window)
    ranked = sorted(FAMILIES, key=lambda f: -runs[(f[0], "full")][1]["final"])
    lines.append("## Ranked results - full 10 years")
    lines.append("")
    lines.append("| Rank | Family | Final | Total % | CAGR % | Orders | Closed "
                 "trades | Win % | Max DD % | Costs | Halted |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for rank, (fname, _fn) in enumerate(ranked, 1):
        _pf, r = runs[(fname, "full")]
        lines.append(f"| {rank} | {fname} | ${r['final']:,.2f} | "
                     f"{r['total_pct']:+.1f} | {r['cagr_pct']:+.2f} | "
                     f"{r['orders']} | {r['trips']} | {fmt_pct(r['win_rate'])} | "
                     f"{r['maxdd_pct']:.1f} | ${r['costs']:,.2f} | "
                     f"{r['halt_date'].isoformat() if r['halt_date'] else '-'} |")
    lines.append("")

    # design vs validation table
    lines.append("## Design vs validation (fresh $100 each)")
    lines.append("")
    lines.append("| Family | Design final | vs SPY net "
                 f"(${nd:,.2f}) | Validation final | vs SPY net (${nv:,.2f}) | "
                 "Validation max DD % | Validation costs | Halted (either) |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for fname, _fn in FAMILIES:
        rd = runs[(fname, "design")][1]
        rv = runs[(fname, "validation")][1]
        halts = [r["halt_date"].isoformat() for r in (rd, rv) if r["halt_date"]]
        lines.append(f"| {fname} | ${rd['final']:,.2f} | "
                     f"{'BEAT' if rd['final'] > nd else 'behind'} | "
                     f"${rv['final']:,.2f} | "
                     f"{'BEAT' if rv['final'] > nv else 'behind'} | "
                     f"{rv['maxdd_pct']:.1f} | ${rv['costs']:,.2f} | "
                     f"{', '.join(halts) if halts else '-'} |")
    lines.append("")

    # per-family sections with per-year tables
    lines.append("## Per-family detail (full window, year by year)")
    for fname, _fn in FAMILIES:
        pf, r = runs[(fname, "full")]
        rd = runs[(fname, "design")][1]
        rv = runs[(fname, "validation")][1]
        lines.append("")
        lines.append(f"### {fname}")
        lines.append("")
        lines.append(f"Full window: final ${r['final']:,.2f} "
                     f"({r['total_pct']:+.1f}%), CAGR {r['cagr_pct']:+.2f}%, "
                     f"{r['orders']} orders, {r['trips']} closed trades, win "
                     f"rate {fmt_pct(r['win_rate'])}%, max drawdown "
                     f"{r['maxdd_pct']:.1f}%, total costs ${r['costs']:,.2f}"
                     + (f", HALTED {r['halt_date'].isoformat()} "
                        f"(floor triggered at the {r['halt_trigger'].isoformat()} close)."
                        if r["halt_date"] else ", never halted."))
        if fname.startswith("F4"):
            lines.append("")
            lines.append(f"**Cost spotlight (the point of this test):** the "
                         f"overnight family paid **${r['costs']:,.2f} in total "
                         f"costs** over the full window on a $100 pot - "
                         f"{r['orders']} orders, i.e. a round trip every single "
                         "trading day. Whatever the overnight effect earns "
                         "gross, this is the friction it has to beat first.")
        lines.append("")
        lines.append("| Year | Start | End | Return | Orders | Costs |")
        lines.append("|---|---|---|---|---|---|")
        lines.extend(per_year_table(pf, r))
        lines.append("")
        lines.append(f"Design: ${rd['final']:,.2f} "
                     f"({'BEAT' if rd['final'] > nd else 'behind'} SPY net "
                     f"${nd:,.2f}); Validation: ${rv['final']:,.2f} "
                     f"({'BEAT' if rv['final'] > nv else 'behind'} SPY net "
                     f"${nv:,.2f}).")
        lines.append("")
        lines.append(f"**Verdict: {verdict(fname, rd, rv, nd, nv)}**")

    lines.append("")
    lines.append("## The honest caution (read before believing any winner)")
    lines.append("")
    lines.append("This round ran **5 families x 3 windows**, on top of Round "
                 "1's 10 trials and the rest of the v2 program. The "
                 "design/validation split is the guardrail this round adds: a "
                 "family had to hold up in 2023-2026, years its rules were not "
                 "chosen in, to earn a good verdict - and even that split is "
                 "only one cut of one decade (a long bull market with a "
                 "pandemic crash and one bear year). Yahoo's free bars carry "
                 "no dividends, so SPY buy-and-hold is understated by roughly "
                 "its dividend yield every year - beating the price-only "
                 "benchmark is a lower bar than beating a real index fund. "
                 "Families that trade ETFs (F1/F2/F3) have no survivorship "
                 "problem in their universe; families trading SPY alone have "
                 "none either. Treat every final as an upper bound, and any "
                 "family marked for further testing still owes walk-forward "
                 "folds, a deflated-Sharpe check across ALL trials run so far, "
                 "and a frozen paper trial before it is called real.")
    lines.append("")
    lines.append("Files: `tournament2.py` (the exact script), "
                 "`tournament2-trades.csv` (every order, all families, all "
                 "windows, with window and family columns), cached bars in "
                 "`tournament2-data/`.")

    report_path = os.path.join(HERE, "tournament2.md")
    with open(report_path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"wrote {report_path}")


if __name__ == "__main__":
    main()
