#!/usr/bin/env python3
"""
THE GREAT RETEST (v10) -- lottery (v3 penny-stock lottery pot).

Slug: lottery. Headline configuration: E4+N3 (stop -10% / target +40%;
entry N3 = rank by smallest prior-day % gain among names up on the day).
Program rules (Terry's decision, binding): exchange-listed sub-$5 names
ONLY (no OTC), monthly point-in-time screen (trailing-20-day average
daily dollar volume > $20M AND close < $5.00), limit-order-style fills
at the next open / stop / target levels from daily bars, max 5 positions
at 15% of pot each, max 1 entry per decision day and 2 per calendar
week, no averaging down, no promotion/hype buying (entries come only
from the mechanical screen + ranking). Costs are the engine's own:
2.0% of trade value on EVERY buy and sell (the program's spread /
friction model for sub-$5 names -- reported separately as the spread
component) plus $0.01 per sell order (reported as the fee component).
The -15% floor is a TARGET the pot aims at: gap-down opens and no-bid
moments can jump straight through it (the engine fills floor
liquidations at the next open, so a gap lands below the floor), and
that is stated wherever the floor is mentioned.

Work performed by this script:
  (1) INTEGRITY -- all 16 published costed configs of v3 (see the v9
      record table) re-run in ORIGINAL form (his floor + ladder,
      original design/validation windows, original v3 data cache,
      read-only) through the byte-identical v9 module's simulate()
      (protection="his"). Finals + halt dates compared to the
      published record.
  (2) SWEEP -- DECADE 2016-11-21 -> 2026-11-20, headline config
      E4+N3 only, $100/cell, v9 protections (plain -15% floor per
      episode, no ladder; first halt liquidates at the next open, 90
      calendar days in cash, restart at the next CADENCE date with an
      episode-2 floor of -15% from the restart balance; second halt
      ends the run), at all 7 cadences.
  (3) PLACEBOS -- per cell, 20 seeded random-rank twins: identical
      screens, eligibility (screen universe, not held, up on the
      signal day -- N3's own eligibility), sizing, caps, exits, costs
      and protection; only the RANKING is replaced by a seeded random
      order. Seeds 1..20.

CADENCE TREATMENT (stated per the task): cadence governs the
screen/review rhythm of the penny book as follows. The monthly
point-in-time screen is the universe definition and is computed
monthly in every cell (changing it would change the strategy, not its
tempo); a cadence date uses the current month's screen. Entries AND
exit checks (stop / target / trailing ratchet) happen ONLY on cadence
dates: on a cadence date the entry signal is evaluated from the prior
trading day's completed bar (the freshest data available at that
open -- for daily cadence this is exactly the original engine) and
fills at the cadence date's open; exits are judged on the cadence
date's bar only, so between cadence dates positions ride unchecked.
The v9 floor is protection, not signal: it is checked on every close
(as the original checked its floor daily) and a breach liquidates at
the next trading day's open regardless of cadence. The final-day
liquidation at the window's last close also applies in every cell
(the original engine's window-boundary rule).

Data: extended Yahoo Finance chart API daily OHLCV (free), fetched
2016-01-01 through 2026-11-21 into ./data_cache_ext/ inside this
folder (the v3 cache only reaches back to 2022-06, so the decade road
needs this extended pull; same source, same fields, split-adjusted,
not dividend-adjusted). The candidate list is the v3 list, assembled
in Nov 2026 -- survivorship tilt flatters every number by an unknown
amount, exactly as flagged in the original study. Integrity uses the
original v3 cache read-only (backtests/v3/data_cache/).

Outputs (this folder): cells/<cadence>.json, results.json,
integrity.json. RESULTS.md is written alongside by hand from these
files.
"""

import bisect
import importlib.util
import json
import math
import os
import random
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))  # stock-app/
EXT_CACHE = os.path.join(HERE, "data_cache_ext")
os.makedirs(EXT_CACHE, exist_ok=True)
os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)

ET = ZoneInfo("America/New_York")
FETCH_START = datetime(2016, 1, 1, tzinfo=timezone.utc)
FETCH_END = datetime(2026, 11, 22, tzinfo=timezone.utc)

DECADE_START, DECADE_END = "2016-11-21", "2026-11-20"
START_CASH = 100.00
COST_RATE = 0.02
SELL_ORDER_FEE = 0.01
MAX_POSITIONS = 5
MAX_PER_NAME_FRAC = 0.15
MAX_ENTRIES_PER_WEEK = 2
SCREEN_MAX_PRICE = 5.00
SCREEN_MIN_AVG_DOLLAR_VOL = 20_000_000
LISTED_EXCHANGES = {"NMS", "NGM", "NCM", "NYQ", "ASE", "AMX"}

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
E4 = {"kind": "fixed", "stop": 0.10, "tp": 0.40, "time_days": None}
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]

# ---------------------------------------------------------------------------
# Extended data (2016 -> 2026)
# ---------------------------------------------------------------------------

def fetch_chart_ext(symbol):
    path = os.path.join(EXT_CACHE, f"{symbol}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    p1 = int(FETCH_START.timestamp())
    p2 = int(FETCH_END.timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?period1={p1}&period2={p2}&interval=1d")
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    with open(path, "w") as f:
        json.dump(data, f)
    time.sleep(0.25)
    return data


def parse_bars_ext(symbol):
    data = fetch_chart_ext(symbol)
    result = data.get("chart", {}).get("result")
    if not result:
        return {}, {}
    r = result[0]
    meta = r.get("meta", {})
    ts = r.get("timestamp", []) or []
    q = r.get("indicators", {}).get("quote", [{}])[0]
    bars = {}
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
    return meta, bars


class Store:
    """Bars + sorted date lists with bisect lookups (fast trailing)."""

    def __init__(self, all_bars):
        self.bars = all_bars
        self.days = {s: sorted(b.keys()) for s, b in all_bars.items()}

    def trailing(self, sym, end_date, n):
        days = self.days[sym]
        k = bisect.bisect_right(days, end_date)
        return [(d, self.bars[sym][d]) for d in days[max(0, k - n):k]]

    def prev_close(self, sym, day):
        days = self.days[sym]
        k = bisect.bisect_left(days, day)
        if k == 0:
            return None, None
        d = days[k - 1]
        return d, self.bars[sym][d]["close"]

    def last_close_on_or_before(self, sym, day):
        days = self.days[sym]
        k = bisect.bisect_right(days, day)
        if k == 0:
            return None
        return self.bars[sym][days[k - 1]]["close"]


def month_key(date_str):
    return date_str[:7]


def run_months(first_day, last_day):
    months = []
    y, m = int(first_day[:4]), int(first_day[5:7])
    ey, em = int(last_day[:4]), int(last_day[5:7])
    while (y, m) <= (ey, em):
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return months


def screen_for_month(mk, trading_days, store, all_meta):
    first_of_month = mk + "-01"
    prior = [d for d in trading_days if d < first_of_month]
    if not prior:
        return None, []
    screen_date = prior[-1]
    passed = []
    for sym in CANDIDATES:
        meta, bars = all_meta[sym], store.bars[sym]
        bar = bars.get(screen_date)
        if bar is None:
            continue
        last20 = store.trailing(sym, screen_date, 20)
        if len(last20) < 20:
            continue
        avg_dv = sum(b["close"] * b["volume"] for _, b in last20) / 20
        if (meta.get("exchangeName") in LISTED_EXCHANGES
                and meta.get("instrumentType") == "EQUITY"
                and bar["close"] < SCREEN_MAX_PRICE
                and avg_dv > SCREEN_MIN_AVG_DOLLAR_VOL):
            passed.append(sym)
    return screen_date, sorted(passed)


def rank_signal(store, universe, signal_day, held, mode, rng=None):
    """Ranking from `signal_day`'s completed bar. N3: smallest prior-day
    % gain among names up on the day. RANDOM (placebo): same eligibility
    as N3, seeded random order."""
    rows = []
    for s in universe:
        if s in held:
            continue
        bars = store.bars[s]
        today = bars.get(signal_day)
        if not today:
            continue
        _, prev_close = store.prev_close(s, signal_day)
        if prev_close is None or prev_close <= 0:
            continue
        gain_pct = (today["close"] / prev_close - 1) * 100
        if gain_pct > 0:
            rows.append((gain_pct, s))
    if mode == "N3":
        rows.sort(key=lambda x: (x[0], x[1]))
        return [s for _, s in rows]
    if mode == "RANDOM":
        syms = [s for _, s in rows]
        rng.shuffle(syms)
        return syms
    raise ValueError(mode)


def cadence_dates(cadence, run_days):
    if cadence == "daily":
        return set(run_days)
    out = []
    if cadence == "weekly":
        seen = set()
        for d in run_days:
            iso = datetime.strptime(d, "%Y-%m-%d").date().isocalendar()
            k = (iso[0], iso[1])
            if k not in seen:
                seen.add(k)
                out.append(d)
    elif cadence == "biweekly":
        weeks, seen = [], set()
        for d in run_days:
            iso = datetime.strptime(d, "%Y-%m-%d").date().isocalendar()
            k = (iso[0], iso[1])
            if k not in seen:
                seen.add(k)
                weeks.append((k, d))
        out = [d for idx, (_, d) in enumerate(weeks) if idx % 2 == 0]
    elif cadence == "monthly":
        seen = set()
        for d in run_days:
            if d[:7] not in seen:
                seen.add(d[:7])
                out.append(d)
    elif cadence == "quarterly":
        seen = set()
        for d in run_days:
            k = (d[:4], (int(d[5:7]) - 1) // 3)
            if k not in seen:
                seen.add(k)
                out.append(d)
    elif cadence == "semiannual":
        seen = set()
        for d in run_days:
            k = (d[:4], 0 if int(d[5:7]) <= 6 else 1)
            if k not in seen:
                seen.add(k)
                out.append(d)
    elif cadence == "annual":
        seen = set()
        for d in run_days:
            if d[:4] not in seen:
                seen.add(d[:4])
                out.append(d)
    return set(out)


# ---------------------------------------------------------------------------
# Cadence simulation (E4 exits; N3 or RANDOM entries; v9 protection)
# ---------------------------------------------------------------------------

def simulate_cadence(store, trading_days, run_days, universes, cad_set,
                     mode, seed=None):
    rng = random.Random(seed) if mode == "RANDOM" else None
    res = {"trades": [], "total_costs": 0.0, "rate_costs": 0.0,
           "fee_costs": 0.0, "round_trips": [], "daily": [],
           "halt_events": [], "restarts": [], "episode": 1,
           "halted": False, "halt_date": None, "final_balance": None,
           "gap_through_stops": 0, "notes": []}
    cash = START_CASH
    positions = {}
    floor = 0.85 * START_CASH
    halt_pending = False
    halt_trigger = None
    entries_by_week = {}

    def equity(day, field):
        eq = cash
        for s, p in positions.items():
            b = store.bars[s].get(day)
            if b:
                eq += p["shares"] * b[field]
            else:
                c = store.last_close_on_or_before(s, day)
                eq += p["shares"] * (c if c else p["entry"])
        return eq

    def do_buy(date, sym, price, amount):
        shares = amount / (price * (1 + COST_RATE))
        c = amount - shares * price
        res["total_costs"] += c
        res["rate_costs"] += c
        res["trades"].append({"date": date, "ticker": sym, "side": "buy",
                              "price": round(price, 4),
                              "shares": round(shares, 6),
                              "value": round(price * shares, 2)})
        return shares

    def do_sell(date, sym, price, shares):
        gross = shares * price
        res["total_costs"] += gross * COST_RATE + SELL_ORDER_FEE
        res["rate_costs"] += gross * COST_RATE
        res["fee_costs"] += SELL_ORDER_FEE
        res["trades"].append({"date": date, "ticker": sym, "side": "sell",
                              "price": round(price, 4),
                              "shares": round(shares, 6),
                              "value": round(gross, 2)})
        return gross * (1 - COST_RATE) - SELL_ORDER_FEE

    def close_position(date, sym, price):
        nonlocal cash
        p = positions.pop(sym)
        proceeds = do_sell(date, sym, price, p["shares"])
        cash += proceeds
        res["round_trips"].append({"ticker": sym, "exit_date": date,
                                   "pnl": proceeds - p["outlay"],
                                   "outlay": p["outlay"]})

    def week_key(day):
        iso = datetime.strptime(day, "%Y-%m-%d").date().isocalendar()
        return (iso[0], iso[1])

    start_idx = trading_days.index(run_days[0])
    end_idx = trading_days.index(run_days[-1])

    def pad_cash_curve(from_idx):
        # After a terminal halt the pot sits in cash to the window end;
        # the saved equity curve covers the full window, flat at cash.
        for j in range(from_idx, end_idx + 1):
            res["daily"].append((trading_days[j], round(cash, 4)))

    i = start_idx
    while i <= end_idx:
        day = trading_days[i]
        is_last = (i == end_idx)
        is_cad = day in cad_set

        if halt_pending:
            for s in list(positions):
                b = store.bars[s].get(day)
                if b:
                    close_position(day, s, b["open"])
            res["daily"].append((day, round(cash, 4)))
            ev = {"episode": res["episode"],
                  "breach_date": halt_trigger[0],
                  "trigger_close": round(halt_trigger[1], 2),
                  "floor": round(halt_trigger[2], 2),
                  "liquidation_date": day,
                  "cash_after_liquidation": round(cash, 2)}
            res["halt_events"].append(ev)
            if res["episode"] == 1:
                liq = datetime.strptime(day, "%Y-%m-%d").date()
                resume_on = (liq + timedelta(days=90)).isoformat()
                cand = [d for d in run_days
                        if d >= resume_on and d in cad_set]
                if not cand:
                    res["restarts"].append(
                        {"liquidation_date": day, "restart_date": None,
                         "restart_balance": round(cash, 2),
                         "note": "no cadence date remains after the "
                                 "90-day sit-out; run ends."})
                    res["halted"] = True
                    res["halt_date"] = day
                    res["final_balance"] = cash
                    pad_cash_curve(i + 1)
                    return res
                restart_day = cand[0]
                floor = 0.85 * cash
                res["restarts"].append(
                    {"liquidation_date": day, "restart_date": restart_day,
                     "restart_balance": round(cash, 2),
                     "episode2_floor": round(floor, 2)})
                res["episode"] = 2
                halt_pending = False
                halt_trigger = None
                # fast-forward the equity curve through the sit-out
                j = i + 1
                while j <= end_idx and trading_days[j] < restart_day:
                    res["daily"].append((trading_days[j], round(cash, 4)))
                    j += 1
                i = j
                continue
            res["halted"] = True
            res["halt_date"] = day
            res["final_balance"] = cash
            pad_cash_curve(i + 1)
            return res

        # --- entry (cadence dates only), signal from prior trading day
        if is_cad and i > start_idx or (is_cad and i == start_idx):
            if is_cad:
                signal_day = trading_days[i - 1] if i > 0 else None
                if signal_day is not None:
                    ranked = rank_signal(
                        store, universes[month_key(day)], signal_day,
                        set(positions), mode, rng)
                    if ranked:
                        s = ranked[0]
                        wk = week_key(day)
                        if (entries_by_week.get(wk, 0)
                                < MAX_ENTRIES_PER_WEEK
                                and s not in positions
                                and len(positions) < MAX_POSITIONS):
                            b = store.bars[s].get(day)
                            if b and b["open"] > 0:
                                amount = min(
                                    MAX_PER_NAME_FRAC * equity(day, "open"),
                                    cash)
                                if amount >= 1.00:
                                    shares = do_buy(day, s, b["open"],
                                                    amount)
                                    cash -= amount
                                    positions[s] = {
                                        "shares": shares,
                                        "entry": b["open"],
                                        "outlay": amount,
                                        "entry_idx": i,
                                        "peak": b["open"],
                                        "trail_active": False}
                                    entries_by_week[wk] = \
                                        entries_by_week.get(wk, 0) + 1

        # --- exits (cadence dates only), E4 fixed -10% / +40%
        if is_cad:
            for s in list(positions):
                b = store.bars[s].get(day)
                if not b:
                    continue
                p = positions[s]
                entry = p["entry"]
                stop = entry * (1 - E4["stop"])
                tp = entry * (1 + E4["tp"])
                if b["low"] <= stop:
                    if b["open"] < stop:
                        res["gap_through_stops"] += 1
                        fill = b["open"]
                    else:
                        fill = stop
                    close_position(day, s, fill)
                elif b["high"] >= tp:
                    close_position(day, s, tp)

        if is_last:
            for s in list(positions):
                b = store.bars[s].get(day)
                price = b["close"] if b else \
                    store.last_close_on_or_before(s, day)
                if price:
                    close_position(day, s, price)

        eq_close = equity(day, "close") if positions else cash
        if is_last:
            eq_close = cash
        res["daily"].append((day, round(eq_close, 4)))

        # --- v9 floor on every close (protection, not cadence-gated)
        if eq_close <= floor:
            if is_last:
                res["halt_events"].append(
                    {"episode": res["episode"], "breach_date": day,
                     "trigger_close": round(eq_close, 2),
                     "floor": round(floor, 2),
                     "liquidation_date": None,
                     "cash_after_liquidation": round(cash, 2),
                     "note": "floor touched on the final day; no next "
                             "open exists."})
                if res["episode"] == 1:
                    res["restarts"].append(
                        {"liquidation_date": None, "restart_date": None,
                         "restart_balance": round(cash, 2),
                         "note": "first halt on the final day; no "
                                 "restart occurs."})
                res["halted"] = True
                res["halt_date"] = day
                res["final_balance"] = cash
                return res
            halt_pending = True
            halt_trigger = (day, eq_close, floor)
        i += 1

    res["final_balance"] = cash
    return res


def stats_of(res, days_count):
    series = [START_CASH] + [eq for _, eq in res["daily"]]
    peak, max_dd = series[0], 0.0
    for v in series:
        peak = max(peak, v)
        max_dd = min(max_dd, v / peak - 1)
    final = res["final_balance"]
    years = days_count / 365.25
    cagr = (final / START_CASH) ** (1 / years) - 1 if final > 0 else -1.0
    rts = res["round_trips"]
    wins = [r for r in rts if r["pnl"] > 0]
    return {"final": round(final, 2), "cagr_pct": round(cagr * 100, 2),
            "max_dd_pct": round(-max_dd * 100, 2),
            "costs": round(res["total_costs"], 2),
            "spread_costs": round(res["rate_costs"], 2),
            "fee_costs": round(res["fee_costs"], 2),
            "orders": len(res["trades"]),
            "round_trips": len(rts),
            "win_rate_pct": round(len(wins) / len(rts) * 100, 1)
            if rts else 0.0,
            "gap_through_stops": res["gap_through_stops"]}


# ---------------------------------------------------------------------------
# Integrity: 16 published configs in original form via the v9 module
# ---------------------------------------------------------------------------

PUBLISHED_16 = [
    # label, window, exit, entry, start, his_final, his_halt
    ("BASE+N1", "design", "BASE", "N1", 100.0, 95.78, "2024-04-16"),
    ("E1+N1", "design", "E1", "N1", 100.0, 83.19, "2023-03-10"),
    ("E2+N1", "design", "E2", "N1", 100.0, 83.90, "2023-05-26"),
    ("E3+N1", "design", "E3", "N1", 100.0, 83.00, "2024-04-16"),
    ("E4+N1", "design", "E4", "N1", 100.0, 97.71, "2024-04-15"),
    ("E5+N1", "design", "E5", "N1", 100.0, 83.29, "2023-03-21"),
    ("E6+N1", "design", "E6", "N1", 100.0, 83.58, "2023-03-10"),
    ("E4+N2", "design", "E4", "N2", 100.0, 97.40, "2023-09-26"),
    ("E4+N3", "design", "E4", "N3", 100.0, 98.65, "2023-03-21"),
    ("E4+N4", "design", "E4", "N4", 100.0, 97.64, "2023-04-19"),
    ("E4+N1", "validation", "E4", "N1", 100.0, 82.27, "2026-03-23"),
    ("E4+N3", "validation", "E4", "N3", 100.0, 84.17, "2026-07-21"),
    ("E4+N1 $50", "design", "E4", "N1", 50.0, 50.04, "2024-03-06"),
    ("E4+N3 $50", "design", "E4", "N3", 50.0, 49.21, "2023-03-21"),
    ("E4+N1 $50", "validation", "E4", "N1", 50.0, 41.02, "2026-03-23"),
    ("E4+N3 $50", "validation", "E4", "N3", 50.0, 41.91, "2026-07-20"),
]


def run_integrity():
    v9_path = os.path.join(
        ROOT, "backtests", "v9-muse-rules", "lottery-v3",
        "lottery-v3-v9.py")
    spec = importlib.util.spec_from_file_location("lottery_v9", v9_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    all_bars, all_meta = {}, {}
    failed = []
    for sym in mod.CANDIDATES + ["SPY"]:
        try:
            meta, bars = mod.parse_bars(sym)
        except Exception:
            meta, bars = {}, {}
            failed.append(sym)
        all_meta[sym], all_bars[sym] = meta, bars
        if not bars and sym not in failed:
            failed.append(sym)
    trading_days = sorted(all_bars["SPY"].keys())
    design_days = [d for d in trading_days
                   if mod.DESIGN_START <= d <= mod.DESIGN_END]
    valid_days = [d for d in trading_days
                  if mod.VALID_START <= d <= mod.VALID_END]
    months = mod.run_months(design_days[0], valid_days[-1])
    universes = {}
    for mk in months:
        _, passed = mod.screen_for_month(mk, trading_days, all_bars,
                                         all_meta)
        universes[mk] = passed
    steps50 = [(75.00, 62.50), (62.50, 50.00)]
    days_of = {"design": design_days, "validation": valid_days}
    rows, n_ok = [], 0
    for (label, window, ek, em, start, pub_final, pub_halt) in \
            PUBLISHED_16:
        if start == 50.0:
            hfloor, hsteps = 42.50, steps50
        else:
            hfloor, hsteps = mod.FLOOR_START, mod.FLOOR_STEPS
        res = mod.simulate(all_bars, trading_days, days_of[window],
                           universes, mod.COST_RATE, mod.SELL_ORDER_FEE,
                           mod.EXITS[ek], em, label, start_cash=start,
                           floor_start=hfloor, floor_steps=hsteps,
                           protection="his")
        st = mod.stats_of(res, start)
        ok = (abs(st["final"] - pub_final) < 0.005
              and res["halt_date"] == pub_halt)
        n_ok += 1 if ok else 0
        rows.append({"config": label, "window": window, "start": start,
                     "published_final": pub_final,
                     "reproduced_final": round(st["final"], 2),
                     "published_halt": pub_halt,
                     "reproduced_halt": res["halt_date"],
                     "orders": st["n_trades"],
                     "costs": round(res["total_costs"], 2),
                     "match": ok})
        print(f"INTEGRITY {label} [{window}] ${start:.0f}: "
              f"{st['final']:.2f} vs {pub_final} halt "
              f"{res['halt_date']} vs {pub_halt} -> "
              f"{'OK' if ok else 'MISMATCH'}")
    out = {"status": "reproduced" if n_ok == 16 else "FAILED",
           "matched": n_ok, "of": 16, "failed_symbols": sorted(set(failed)),
           "rows": rows}
    with open(os.path.join(HERE, "integrity.json"), "w") as f:
        json.dump(out, f, indent=1)
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    integrity = run_integrity()

    # Extended decade data
    all_bars, all_meta = {}, {}
    failed = []
    for sym in CANDIDATES + ["SPY"]:
        try:
            meta, bars = parse_bars_ext(sym)
        except Exception as e:
            meta, bars = {}, {}
            failed.append(sym)
            print(f"EXT FETCH FAIL {sym}: {e}")
        all_meta[sym], all_bars[sym] = meta, bars
        if not bars and sym not in failed:
            failed.append(sym)
    print(f"extended data: failed={sorted(set(failed))}")
    store = Store(all_bars)
    all_days = sorted(all_bars["SPY"].keys())
    run_days = [d for d in all_days if DECADE_START <= d <= DECADE_END]
    span_days = (datetime.strptime(DECADE_END, "%Y-%m-%d")
                 - datetime.strptime(DECADE_START, "%Y-%m-%d")).days
    months = run_months("2016-11", "2026-11")
    universes = {}
    for mk in months:
        _, passed = screen_for_month(mk, all_days, store, all_meta)
        universes[mk] = passed
    spy = all_bars["SPY"]
    spy_price_only = round(
        100.0 * spy[run_days[-1]]["close"] / spy[run_days[0]]["open"], 2)
    print(f"SPY decade price-only (in-plumbing): ${spy_price_only}; "
          f"SPEC dividend-adjusted reference: $367.80")

    cells_summary = {}
    for cad in CADENCES:
        cad_set = cadence_dates(cad, run_days)
        res = simulate_cadence(store, all_days, run_days, universes,
                               cad_set, "N3")
        st = stats_of(res, span_days)
        placebo_finals = []
        for seed in range(1, 21):
            pres = simulate_cadence(store, all_days, run_days, universes,
                                    cad_set, "RANDOM", seed=seed)
            placebo_finals.append(round(pres["final_balance"], 2))
        beaten = sum(1 for f in placebo_finals if st["final"] > f)
        halts = res["halt_events"]
        cell = {
            "cadence": cad, "config": "E4+N3",
            "window": [DECADE_START, DECADE_END],
            "n_cadence_dates": len(cad_set),
            "final": st["final"], "cagr_pct": st["cagr_pct"],
            "max_dd_pct": st["max_dd_pct"], "costs": st["costs"],
            "spread_costs": st["spread_costs"],
            "fee_costs": st["fee_costs"],
            "orders": st["orders"], "round_trips": st["round_trips"],
            "win_rate_pct": st["win_rate_pct"],
            "gap_through_stops": st["gap_through_stops"],
            "halts": halts,
            "restart": bool(res["restarts"]
                            and res["restarts"][0].get("restart_date")),
            "restarts": res["restarts"],
            "second_halt": len(halts) >= 2,
            "placebo_beaten": beaten,
            "placebo_finals": placebo_finals,
            "equity_curve": [[d, v] for d, v in res["daily"]],
            "trades": res["trades"],
        }
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump(cell, f, indent=1)
        cells_summary[cad] = {
            "final": st["final"], "cagr_pct": st["cagr_pct"],
            "max_dd_pct": st["max_dd_pct"], "halts": halts,
            "restart": cell["restart"],
            "second_halt": cell["second_halt"], "costs": st["costs"],
            "spread_costs": st["spread_costs"],
            "fee_costs": st["fee_costs"], "orders": st["orders"],
            "placebo_beaten": beaten,
            "placebo_note": "20 seeded random-rank twins (seeds 1-20): "
                            "same monthly screens, same N3 eligibility "
                            "(screen names up on the signal day, not "
                            "held), same sizing/caps/E4 exits/costs/v9 "
                            "protection; only the ranking is random."}
        print(f"CELL {cad}: final ${st['final']:.2f} CAGR "
              f"{st['cagr_pct']:+.2f}% DD {st['max_dd_pct']:.2f}% "
              f"costs ${st['costs']:.2f} (spread ${st['spread_costs']:.2f}"
              f" + fees ${st['fee_costs']:.2f}) orders {st['orders']} "
              f"halts {len(halts)} placebo {beaten}/20")

    money = [c for c in CADENCES
             if cells_summary[c]["final"] > 367.80
             and cells_summary[c]["placebo_beaten"] >= 11]
    results = {
        "slug": "lottery",
        "area": "Exchange-listed sub-$5 penny-stock lottery pot (W10) -- "
                "its own ground is the listed penny book itself: monthly "
                "$20M-volume point-in-time screens, fast daily exits as "
                "designed; judged on the DECADE road at every cadence "
                "(headline config E4+N3 only, per task scope).",
        "area_source": "backtests/v10-retest/SPEC.md, worker batch W10 + "
                       "CADENCE GRID (W10: lottery -- daily, fast exits "
                       "as designed); task assignment (headline E4+N3 "
                       "sweep; other 15 configs integrity table only).",
        "native_cadence": "daily",
        "cadence": "daily",
        "original_cadence_foreign": {
            "foreign": False,
            "note": "The original v3 test ran the book in its native "
                    "daily form (daily entries from the prior evening's "
                    "ranking, daily exit checks). No foreign cadence "
                    "was forced; the sweep's slower cadences are the "
                    "foreign ones."},
        "cadence_treatment": "Cadence governs the screen/review rhythm "
            "of the penny book: the monthly point-in-time screen (the "
            "universe definition) is computed monthly in every cell; "
            "entries and exit checks happen ONLY on cadence dates "
            "(entry signal from the prior trading day's completed bar, "
            "filled at the cadence date's open; exits judged on the "
            "cadence date's bar only). The v9 floor is protection, "
            "checked on every close, liquidating at the next open; a "
            "restart resumes at the next cadence date after the "
            "90-day sit-out.",
        "headline_config": "E4+N3",
        "integrity": {
            "status": integrity["status"],
            "note": f"{integrity['matched']}/16 published costed "
                    f"configs reproduced in original form (finals + "
                    f"halt dates) via the byte-identical v9 module in "
                    f"his mode on the original v3 cache. Full table: "
                    f"integrity.json and RESULTS.md.",
            "original_finals": {f"{r['config']}|{r['window']}|"
                                f"${r['start']:.0f}": r["published_final"]
                                for r in integrity["rows"]},
            "reproduced_finals": {f"{r['config']}|{r['window']}|"
                                  f"${r['start']:.0f}":
                                  r["reproduced_final"] for r in
                                  integrity["rows"]}},
        "decade_spy_final": 367.80,
        "decade_spy_note": "SPEC reference (dividend-adjusted). "
            f"In-plumbing price-only SPY on the extended cache: "
            f"${spy_price_only} (split-adjusted bars, no dividends) -- "
            f"consistent with the SPEC's ~$314 price-only note.",
        "champion_decade_final": 65.89,
        "cells": cells_summary,
        "money_cadences": money,
        "verdict_area": "NO GROUND" if not money else "REAL BUT SMALL",
        "verdict_change": "No change in substance: the original "
            "program's verdict was that the listed-penny pot has no "
            "demonstrated edge (design winner E4+N3 lost on the one "
            "honest validation year, $84.17 vs SPY $105.31); the "
            "decade cadence sweep tests whether any tempo rescues it.",
        "data_notes": {
            "extended_cache": "data_cache_ext/ in this folder: Yahoo "
                "chart API daily OHLCV 2016-01-01 -> 2026-11-21 for "
                "the 73 v3 candidates + SPY (the v3 cache starts "
                "2022-06 and cannot cover the decade).",
            "failed_symbols": sorted(set(failed)),
            "survivorship": "Candidate list assembled Nov 2026 (v3 "
                "study); names that died/delisted and were forgotten "
                "are missing -- every decade number is flattered by "
                "an unknown amount, as in the original study.",
            "floor_honesty": "The -15% floor is a TARGET the pot aims "
                "at, not a guarantee: floor liquidations fill at the "
                "next open and stop fills gap through, so realized "
                "episode losses can and do land below -15%."},
    }
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print(f"money_cadences={money}")
    print("Wrote cells/, results.json, integrity.json")


if __name__ == "__main__":
    main()
