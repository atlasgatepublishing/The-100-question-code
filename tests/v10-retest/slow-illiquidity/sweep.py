#!/usr/bin/env python3
"""
SLOW ILLIQUIDITY -- v10 GREAT RETEST cadence sweep.

Simulation only. No broker orders (real or paper) are placed.

Engine: the v9 slow-illiquidity engine (itself the v4 original with ONLY
the protection module swapped) with exactly two mechanical changes, both
mandated by the v10 SPEC's uniform cadence definition:

  1. CADENCE: signal evaluation, selection (N3 quiet-gainer ranking),
     entries, and exit checks (the +60% target and the 60-trading-day
     time exit) happen ONLY on cadence dates -- the first trading day
     of each week / second week / month / quarter / half-year / year
     (daily = every trading day). The monthly point-in-time screen is
     refreshed on the screen cadence: monthly for the daily..monthly
     cadences (the original design), and at the cadence itself for
     quarterly / semi-annual / annual. The v9 protection module (plain
     -15% floor on closes, liquidate next open, 90 calendar days in
     cash, restart at the next regular decision point -- here: the
     next cadence date on/after day 90 -- under an episode-2 floor of
     -15% from the restart balance; second halt ends the run) is NOT
     cadence-governed and is unchanged.

  2. PLACEBO MODE (optional): on each entry decision, instead of the
     N3 smallest-gain-first ranking, pick uniformly at random (seeded)
     from the SAME eligible set (current screen universe, up on the
     signal day, not held). 20 seeds per cell.

Everything else is the frozen original design: lottery cost model
(2.0% of trade value per side + $0.01 per sell order), max 3 positions
at 20% of equity, no averaging down, no per-trade stop, minimum hold
40 trading days, +60% target live from day 40, time exit at 60 trading
days, $100 start. Zero-cost twins run beside every costed run.

Modes:
  crosscheck  -- original cache, daily cadence, design+validation
                 windows, v9 protection; must reproduce the v9 finals
                 ($158.63 / $219.29 / $93.38 / $105.32).
  sweep       -- DECADE 2016-11-21..2026-11-20, 7 cadences, costed +
                 zero-cost twin + 20 placebo seeds per cadence.
                 Writes cells/<cadence>.json and sweep_raw.json.

Data: decade mode downloads Yahoo Finance chart API daily OHLCV from
2016-09-01 (screen warm-up) through 2026-11-20 into
data_cache_decade/ inside this folder. Prices split-adjusted, not
dividend-adjusted (SPY benchmark is additionally computed on adjclose
for the dividend-adjusted figure). The candidate list is the original
Nov-2026-assembled lottery list -- survivorship tilt documented in
RESULTS.md, unchanged from the original study.
"""

import bisect
import json
import os
import random
import sys
import time
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
ORIG_CACHE = "/home/hatch/workspace/stock-app/backtests/v3/data_cache"
DECADE_CACHE = os.path.join(HERE, "data_cache_decade")
ET = ZoneInfo("America/New_York")

COST_RATE = 0.02
SELL_ORDER_FEE = 0.01
SCREEN_MAX_PRICE = 5.00
SCREEN_MIN_AVG_DOLLAR_VOL = 20_000_000
MAX_POSITIONS = 3
MAX_PER_NAME_FRAC = 0.20
MIN_HOLD_DAYS = 40
MAX_HOLD_DAYS = 60
TARGET = 0.60
START = 100.00

DECADE_START, DECADE_END = "2016-11-21", "2026-11-20"
DESIGN_START, DESIGN_END = "2022-11-21", "2025-11-20"
VALID_START, VALID_END = "2025-11-21", "2026-11-20"

CANDIDATES = [
    "PLUG", "FCEL", "BLDP", "SNDL", "ACB", "CGC", "TLRY", "OGI", "CRON",
    "BYND", "GERN", "IOVA", "RXRX", "PACB", "DNA", "EDIT", "OCGN", "SAVA",
    "BTBT", "SDIG", "GREE", "CAN", "EBON", "SOS", "MULN", "FFAI", "NKLA",
    "GOEV", "WKHS", "BLNK", "EVGO", "CHPT", "SPCE", "JBLU", "ULCC", "AMC",
    "BB", "NOK", "KOSS", "VFS", "PSNY", "NIO", "GRAB", "FINV", "NNDM",
    "DDD", "EXK", "FSM", "HYMC", "TEF", "BBAI", "OPEN", "PTON", "TDOC",
    "LCID", "CLOV", "ACHR", "CIFR", "AGEN", "INO", "NVAX", "LX", "IQ",
    "TUYA", "NGD", "BTG", "DNN", "CLNE", "GEVO",
]
LISTED_EXCHANGES = {"NMS", "NGM", "NCM", "NYQ", "ASE", "AMX"}
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def fetch_chart(symbol, cache, fetch_start, fetch_end):
    path = os.path.join(cache, f"{symbol}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    p1 = int(fetch_start.timestamp())
    p2 = int(fetch_end.timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?period1={p1}&period2={p2}&interval=1d")
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    os.makedirs(cache, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)
    time.sleep(0.3)
    return data


def parse_bars(symbol, cache, fetch_start, fetch_end):
    data = fetch_chart(symbol, cache, fetch_start, fetch_end)
    result = data.get("chart", {}).get("result")
    if not result:
        return {}, {}, {}
    r = result[0]
    meta = r.get("meta", {})
    ts = r.get("timestamp", []) or []
    q = r.get("indicators", {}).get("quote", [{}])[0]
    adj = (r.get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose") or []
    bars, adjc = {}, {}
    for i, t in enumerate(ts):
        d = datetime.fromtimestamp(t, tz=ET).strftime("%Y-%m-%d")
        try:
            bar = {"open": q["open"][i], "high": q["high"][i],
                   "low": q["low"][i], "close": q["close"][i],
                   "volume": q["volume"][i]}
        except (KeyError, IndexError, TypeError):
            continue
        if None in bar.values():
            continue
        bars[d] = bar
        if i < len(adj) and adj[i]:
            adjc[d] = adj[i]
    return meta, bars, adjc


class Data:
    """Bars + precomputed sorted day lists (bisect lookups; semantics
    identical to the original engine's sorted() helpers)."""

    def __init__(self, cache, fetch_start, fetch_end):
        self.bars, self.meta, self.adj = {}, {}, {}
        self.failed = []
        for sym in CANDIDATES + ["SPY"]:
            try:
                meta, bars, adjc = parse_bars(sym, cache, fetch_start,
                                              fetch_end)
            except Exception:
                meta, bars, adjc = {}, {}, {}
            self.meta[sym], self.bars[sym], self.adj[sym] = meta, bars, adjc
            if not bars:
                self.failed.append(sym)
        self.days = {s: sorted(b) for s, b in self.bars.items()}
        self.trading_days = self.days["SPY"]

    def last_close_on_or_before(self, sym, day):
        ds = self.days[sym]
        i = bisect.bisect_right(ds, day) - 1
        return self.bars[sym][ds[i]]["close"] if i >= 0 else None

    def trailing(self, sym, end_date, n):
        ds = self.days[sym]
        i = bisect.bisect_right(ds, end_date)
        return [(d, self.bars[sym][d]) for d in ds[max(0, i - n):i]]

    def prev_day(self, day):
        i = bisect.bisect_left(self.trading_days, day)
        return self.trading_days[i - 1] if i > 0 else None


# ---------------------------------------------------------------------------
# Screens (identical rule to the original engine, explicit screen date)
# ---------------------------------------------------------------------------

def screen_on(data, screen_date):
    passed = []
    for sym in CANDIDATES:
        meta, bars = data.meta[sym], data.bars[sym]
        bar = bars.get(screen_date)
        if bar is None:
            continue
        last20 = data.trailing(sym, screen_date, 20)
        if len(last20) < 20:
            continue
        avg_dv = sum(b["close"] * b["volume"] for _, b in last20) / 20
        if (meta.get("exchangeName") in LISTED_EXCHANGES
                and meta.get("instrumentType") == "EQUITY"
                and bar["close"] < SCREEN_MAX_PRICE
                and avg_dv > SCREEN_MIN_AVG_DOLLAR_VOL):
            passed.append(sym)
    return sorted(passed)


def period_key(date_str, cadence):
    y, m = int(date_str[:4]), int(date_str[5:7])
    if cadence == "monthly":
        return (y, m)
    if cadence == "quarterly":
        return (y, (m - 1) // 3)
    if cadence == "semiannual":
        return (y, (m - 1) // 6)
    if cadence == "annual":
        return (y,)
    raise ValueError(cadence)


def period_start_str(key, cadence):
    if cadence == "monthly":
        return f"{key[0]:04d}-{key[1]:02d}-01"
    if cadence == "quarterly":
        return f"{key[0]:04d}-{key[1] * 3 + 1:02d}-01"
    if cadence == "semiannual":
        return f"{key[0]:04d}-{key[1] * 6 + 1:02d}-01"
    return f"{key[0]:04d}-01-01"


def build_universes(data, run_days, screen_cadence):
    """Universe in force per period: screen as of the last trading day
    before the period start (the original engine's construction)."""
    universes = {}
    for d in run_days:
        key = period_key(d, screen_cadence)
        if key not in universes:
            pstart = period_start_str(key, screen_cadence)
            prior = [x for x in data.trading_days if x < pstart]
            sdate = prior[-1] if prior else None
            universes[key] = (screen_on(data, sdate) if sdate else [])
    return universes


def decision_dates(run_days, cadence):
    if cadence == "daily":
        return set(run_days)
    out = set()
    if cadence in ("weekly", "biweekly"):
        weeks, order = {}, []
        for d in run_days:
            dt = datetime.strptime(d, "%Y-%m-%d").date()
            wk = dt.isocalendar()[:2]
            if wk not in weeks:
                weeks[wk] = d
                order.append(wk)
        chosen = order if cadence == "weekly" else order[::2]
        out = {weeks[w] for w in chosen}
    else:
        seen = set()
        for d in run_days:
            key = period_key(d, cadence)
            if key not in seen:
                seen.add(key)
                out.add(d)
    return out


# ---------------------------------------------------------------------------
# Ranking (N3) and placebo ranking
# ---------------------------------------------------------------------------

def eligible_evening(data, universe, day, held):
    rows = []
    for s in universe:
        if s in held:
            continue
        bars = data.bars[s]
        today = bars.get(day)
        if not today:
            continue
        ds = data.days[s]
        i = bisect.bisect_left(ds, day)
        if i == 0:
            continue
        prev_close = bars[ds[i - 1]]["close"]
        if prev_close <= 0:
            continue
        gain_pct = (today["close"] / prev_close - 1) * 100
        if gain_pct > 0:
            rows.append((gain_pct, s))
    return rows


def pick_candidate(data, universes, screen_cadence, signal_day, for_day,
                   held, rng):
    universe = universes[period_key(for_day, screen_cadence)]
    rows = eligible_evening(data, universe, signal_day, held)
    if not rows:
        return None
    if rng is not None:  # placebo: uniform random from the same set
        return rng.choice(sorted(s for _, s in rows))
    rows.sort(key=lambda x: (x[0], x[1]))
    return rows[0][1]


# ---------------------------------------------------------------------------
# Simulation (v9 engine logic; cadence gates decisions, v9 protection)
# ---------------------------------------------------------------------------

def simulate(data, run_days, cadence, costed, rng=None, label=""):
    screen_cadence = cadence if cadence in ("quarterly", "semiannual",
                                            "annual") else "monthly"
    universes = build_universes(data, run_days, screen_cadence)
    decide = decision_dates(run_days, cadence)
    cost_rate = COST_RATE if costed else 0.0
    sell_fee = SELL_ORDER_FEE if costed else 0.0
    trading_days = data.trading_days

    res = {"label": label, "trades": [], "total_costs": 0.0,
           "round_trips": [], "daily": [], "halted": False,
           "halt_date": None, "final_balance": None,
           "v9_halts": [], "v9_restarts": [], "notes": []}
    trades = res["trades"]
    cash = START
    positions = {}
    floor = 0.85 * START
    halt_pending = False
    episode = 1
    cash_until = None

    def record(date, sym, side, price, shares, reason):
        trades.append({"date": date, "ticker": sym, "side": side,
                       "price": round(price, 4),
                       "shares": round(shares, 6),
                       "value": round(price * shares, 2),
                       "reason": reason})

    def do_buy(date, sym, price, amount, reason):
        shares = amount / (price * (1 + cost_rate))
        res["total_costs"] += amount - shares * price
        record(date, sym, "buy", price, shares, reason)
        return shares

    def do_sell(date, sym, price, shares, reason):
        gross = shares * price
        res["total_costs"] += gross * cost_rate + sell_fee
        record(date, sym, "sell", price, shares, reason)
        return gross * (1 - cost_rate) - sell_fee

    def close_position(date, sym, price, reason, exit_idx):
        nonlocal cash
        p = positions.pop(sym)
        proceeds = do_sell(date, sym, price, p["shares"], reason)
        cash += proceeds
        res["round_trips"].append(
            {"ticker": sym, "entry_date": p["entry_date"],
             "exit_date": date, "hold_days": exit_idx - p["entry_idx"],
             "entry": p["entry"], "exit": price,
             "pnl": round(proceeds - p["outlay"], 2),
             "ret_pct": round((proceeds / p["outlay"] - 1) * 100, 2),
             "reason": reason})

    def equity(day, field):
        eq = cash
        for s, p in positions.items():
            b = data.bars[s].get(day)
            if b:
                eq += p["shares"] * b[field]
            else:
                c = data.last_close_on_or_before(s, day)
                eq += p["shares"] * (c if c else p["entry"])
        return eq

    start_idx = trading_days.index(run_days[0])
    end_idx = trading_days.index(run_days[-1])
    pending = None
    if run_days[0] in decide:
        pending = pick_candidate(data, universes, screen_cadence,
                                 trading_days[start_idx - 1], run_days[0],
                                 set(positions), rng)

    i = start_idx
    while i <= end_idx:
        day = trading_days[i]
        is_last = (i == end_idx)

        if halt_pending:
            for s in list(positions):
                b = data.bars[s].get(day)
                if b:
                    close_position(day, s, b["open"],
                                   "FLOOR liquidation at open (prior "
                                   "close touched the floor)", i)
            res["daily"].append((day, round(cash, 2)))
            res["v9_halts"].append({"date": day,
                                    "balance": round(cash, 2),
                                    "episode": episode})
            if episode >= 2:
                res["halted"] = True
                res["halt_date"] = day
                res["final_balance"] = cash
                return res
            cash_until = (datetime.strptime(day, "%Y-%m-%d")
                          + __import__("datetime").timedelta(days=90)
                          ).strftime("%Y-%m-%d")
            episode = 2
            floor = 0.85 * cash
            halt_pending = False
            res["notes"].append(
                f"V9 RESTART PENDING: first halt on {day} at "
                f"${cash:.2f}; cash until {cash_until}, episode-2 "
                f"floor ${floor:.2f}.")
            i += 1
            continue
        if cash_until is not None:
            if day < cash_until or day not in decide:
                res["daily"].append((day, round(cash, 2)))
                i += 1
                continue
            res["v9_restarts"].append({"date": day,
                                       "balance": round(cash, 2),
                                       "episode2_floor": round(floor, 2)})
            res["notes"].append(
                f"V9 RESTART: resumed {day} with ${cash:.2f}; "
                f"episode-2 floor ${floor:.2f}.")
            cash_until = None
            pending = pick_candidate(data, universes, screen_cadence,
                                     trading_days[i - 1], day,
                                     set(positions), rng)

        # Entry at the open, cadence dates only: at most one, slot free.
        if day in decide and pending is not None:
            s = pending
            if s not in positions and len(positions) < MAX_POSITIONS:
                b = data.bars[s].get(day)
                if b and b["open"] > 0:
                    amount = min(MAX_PER_NAME_FRAC * equity(day, "open"),
                                 cash)
                    if amount >= 1.00:
                        shares = do_buy(day, s, b["open"], amount,
                                        "entry: top of N3 quiet-gainer "
                                        "ranking from prior evening")
                        cash -= amount
                        positions[s] = {"shares": shares,
                                        "entry": b["open"],
                                        "outlay": amount,
                                        "entry_idx": i,
                                        "entry_date": day}
        pending = None

        # Exits, cadence dates only. NO per-trade stop; nothing exits
        # before MIN_HOLD_DAYS except the floor. +60% target intraday
        # from day 40; time exit at close at MAX_HOLD_DAYS.
        if day in decide:
            for s in list(positions):
                b = data.bars[s].get(day)
                if not b:
                    continue
                p = positions[s]
                if i - p["entry_idx"] < MIN_HOLD_DAYS:
                    continue
                tp = p["entry"] * (1 + TARGET)
                if b["open"] >= tp:
                    close_position(day, s, b["open"],
                                   "take-profit +60% from entry "
                                   "(gapped above target; filled at "
                                   "open)", i)
                elif b["high"] >= tp:
                    close_position(day, s, tp,
                                   "take-profit +60% from entry "
                                   "(limit fill at target)", i)
            for s in list(positions):
                p = positions[s]
                if i - p["entry_idx"] >= MAX_HOLD_DAYS:
                    b = data.bars[s].get(day)
                    price = b["close"] if b else \
                        data.last_close_on_or_before(s, day)
                    if price:
                        close_position(day, s, price,
                                       "time exit: 60 trading days "
                                       "held, target never hit", i)

        if is_last:
            for s in list(positions):
                b = data.bars[s].get(day)
                price = b["close"] if b else \
                    data.last_close_on_or_before(s, day)
                if price:
                    close_position(day, s, price,
                                   "end-of-run exit at final close", i)

        eq_close = equity(day, "close") if positions else cash
        if is_last:
            eq_close = cash
        res["daily"].append((day, round(eq_close, 2)))

        if eq_close <= floor:
            if is_last:
                res["halted"] = True
                res["halt_date"] = day
                res["final_balance"] = cash
                res["notes"].append(
                    f"FLOOR: pot closed at ${eq_close:.2f} on {day}, "
                    f"at/below the ${floor:.2f} floor, on the final day.")
                return res
            halt_pending = True
            res["notes"].append(
                f"FLOOR: pot closed at ${eq_close:.2f} on {day}, "
                f"at/below the ${floor:.2f} floor. All positions "
                f"liquidate at the next open.")
            i += 1
            continue

        if not is_last:
            nxt = trading_days[i + 1]
            if nxt in decide and i + 1 <= end_idx:
                pending = pick_candidate(data, universes, screen_cadence,
                                         day, nxt, set(positions), rng)
        i += 1

    res["final_balance"] = cash
    return res


def stats_of(res):
    series = [START] + [eq for _, eq in res["daily"]]
    peak, max_dd = series[0], 0.0
    for v in series:
        peak = max(peak, v)
        max_dd = min(max_dd, v / peak - 1)
    days = (datetime.strptime(res["daily"][-1][0], "%Y-%m-%d")
            - datetime.strptime(res["daily"][0][0], "%Y-%m-%d")).days
    years = days / 365.25
    final = res["final_balance"]
    return {"final": round(final, 2),
            "cagr_pct": round(((final / START) ** (1 / years) - 1) * 100, 2)
            if final > 0 else -100.0,
            "max_dd_pct": round(max_dd * 100, 2),
            "costs": round(res["total_costs"], 2),
            "orders": len(res["trades"]),
            "round_trips": len(res["round_trips"]),
            "halts": res["v9_halts"],
            "restarts": res["v9_restarts"],
            "second_halt": bool(res["halted"] and len(res["v9_halts"]) >= 2),
            "equity_curve": [[d, v] for d, v in res["daily"]],
            "round_trip_list": res["round_trips"],
            "notes": res["notes"]}


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

def crosscheck():
    fs = datetime(2022, 6, 1, tzinfo=timezone.utc)
    fe = datetime(2026, 11, 22, tzinfo=timezone.utc)
    data = Data(ORIG_CACHE, fs, fe)
    td = data.trading_days
    for name, s, e in (("design", DESIGN_START, DESIGN_END),
                       ("validation", VALID_START, VALID_END)):
        days = [d for d in td if s <= d <= e]
        for costed in (True, False):
            res = simulate(data, days, "daily", costed,
                           label=f"{name} {'costed' if costed else 'zero'}")
            st = stats_of(res)
            print(f"crosscheck {name} {'costed' if costed else 'ZERO-COST'}:"
                  f" final ${st['final']:.2f} orders {st['orders']} "
                  f"halts {len(st['halts'])}")
    print("expected v9: design costed 158.63, design zero 219.29, "
          "validation costed 93.38, validation zero 105.32")


def sweep():
    fs = datetime(2016, 9, 1, tzinfo=timezone.utc)
    fe = datetime(2026, 11, 22, tzinfo=timezone.utc)
    data = Data(DECADE_CACHE, fs, fe)
    td = data.trading_days
    run_days = [d for d in td if DECADE_START <= d <= DECADE_END]
    print(f"decade days {run_days[0]}..{run_days[-1]} ({len(run_days)}); "
          f"fetch failures: {sorted(set(data.failed))}", flush=True)

    spy = data.bars["SPY"]
    spy_price = START * spy[run_days[-1]]["close"] / spy[run_days[0]]["open"]
    a0, a1 = data.adj["SPY"].get(run_days[0]), data.adj["SPY"].get(run_days[-1])
    spy_adj = START * a1 / a0 if a0 and a1 else None
    print(f"SPY decade price-only ${spy_price:.2f}; dividend-adjusted "
          f"${spy_adj:.2f}" if spy_adj else "SPY adj n/a", flush=True)

    out = {"window": [run_days[0], run_days[-1]],
           "spy_price_only_final": round(spy_price, 2),
           "spy_dividend_adj_final": round(spy_adj, 2) if spy_adj else None,
           "fetch_failures": sorted(set(data.failed)), "cells": {}}
    os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)
    for cadence in CADENCES:
        cell = {}
        res = simulate(data, run_days, cadence, True, label=f"{cadence} costed")
        cell["costed"] = stats_of(res)
        resz = simulate(data, run_days, cadence, False,
                        label=f"{cadence} zero-cost")
        cell["zero_cost"] = stats_of(resz)
        placebo_finals = []
        for seed in range(20):
            rng = random.Random(1000 + seed)
            resp = simulate(data, run_days, cadence, True, rng=rng,
                            label=f"{cadence} placebo {seed}")
            placebo_finals.append(round(resp["final_balance"], 2))
        beaten = sum(1 for f in placebo_finals if cell["costed"]["final"] > f)
        cell["placebo_finals"] = placebo_finals
        cell["placebo_beaten"] = beaten
        with open(os.path.join(HERE, "cells", f"{cadence}.json"), "w") as f:
            json.dump({"slug": "slow-illiquidity", "cadence": cadence,
                       "window": out["window"], **cell}, f)
        out["cells"][cadence] = {
            "final": cell["costed"]["final"],
            "cagr_pct": cell["costed"]["cagr_pct"],
            "max_dd_pct": cell["costed"]["max_dd_pct"],
            "costs": cell["costed"]["costs"],
            "orders": cell["costed"]["orders"],
            "halts": len(cell["costed"]["halts"]),
            "restart": bool(cell["costed"]["restarts"]),
            "second_halt": cell["costed"]["second_halt"],
            "zero_cost_final": cell["zero_cost"]["final"],
            "placebo_beaten": beaten,
            "placebo_finals": placebo_finals}
        print(f"{cadence}: costed ${cell['costed']['final']:.2f} "
              f"zero ${cell['zero_cost']['final']:.2f} "
              f"placebo beaten {beaten}/20 orders "
              f"{cell['costed']['orders']} costs "
              f"${cell['costed']['costs']:.2f} maxDD "
              f"{cell['costed']['max_dd_pct']:.2f}%", flush=True)
    with open(os.path.join(HERE, "sweep_raw.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("sweep done")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "sweep"
    if mode == "crosscheck":
        crosscheck()
    else:
        sweep()
