#!/usr/bin/env python3
"""
v10 GREAT RETEST -- v0-lottery DECADE CADENCE SWEEP.

Strategy: the ORIGINAL v0 penny-lottery book (see orig/week/lottery.py and
orig/year/lottery-year.py, reproduced exactly in the integrity gate):
  * Candidate pool: the v0 fixed list of 69 well-known listed names
    (assembled Nov 2026 -- survivorship tilt, stated, same as the original).
  * Monthly point-in-time screen (v0-year form): on the last trading day of
    the prior month -- US exchange-listed EQUITY (feed metadata), close
    < $5.00, trailing-20-day average daily dollar volume > $5,000,000.
  * Entry ranking: score = day % gain x volume spike (day volume /
    trailing-20-day average volume); positive scores only; held excluded.
  * Buy at next open, max 20% of pot equity per name, max 5 positions,
    fractional shares, no averaging down / no adding.
  * Exits: stop -10% from entry (gap-down open fills at the open), take-
    profit +25% sells ALL (fill at the +25% level), stop first if both
    touched. Anything held at run end sells at the final close.
  * Costs (the engine's own cost code, unchanged): 2.0% of trade value on
    EVERY buy and EVERY sell (the v0 spread+slippage model for sub-$5
    names) + $0.01 per sell order. The 2% part is reported separately as
    the spread/slippage component.

SWEEP TREATMENT (SPEC uniform cadence definition):
  * Road: DECADE 2016-11-21 -> 2026-11-20, $100 per cell.
  * Cadence governs the screen/review rhythm: entries AND the stop/
    take-profit exit checks happen ONLY on cadence dates (ranking on the
    cadence date's completed bar, buys at the next trading day's open;
    exits judged on the cadence date's bar). The monthly universe screen
    stays monthly in every cell (it is part of the strategy's definition,
    not its trading tempo -- stated substitution).
  * Protection: v9 rules substituted for the v0 ladder -- plain -15% floor
    from the episode's starting balance, checked on EVERY daily close
    (protection is not cadence-gated); on a breach, liquidate at the next
    open, sit in cash 90 calendar days, restart at the next cadence
    decision point under an episode-2 floor of -15% from the restart
    balance; a second halt ends the run. NOTE: in a penny book the -15%
    floor is a TARGET, not a guarantee -- exits are only checked on
    cadence dates and penny names gap, so a breach can be recognised late
    and filled worse than the floor level.
  * Placebos: per cell, 20 seeded twins that pass the same screen and, on
    each cadence date, buy a RANDOM ordering of the same eligible
    positive-score names (same slot/size/exit/floor rules).
  * SPY decade: dividend-adjusted (Yahoo adjclose), close-to-close.

Outputs: cells/<cadence>.json per cell + results.json (SPEC sweep format).
"""
import json, math, os, random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data_decade")
CELLS = os.path.join(HERE, "cells")
os.makedirs(CELLS, exist_ok=True)
ET = ZoneInfo("America/New_York")

RUN_START, RUN_END = "2016-11-21", "2026-11-20"
START_CASH = 100.00
MAX_POSITIONS, MAX_PER_NAME_FRAC = 5, 0.20
STOP_FRAC, TP_FRAC = 0.10, 0.25
COST_RATE, SELL_ORDER_FEE = 0.02, 0.01
SCREEN_MAX_PRICE, SCREEN_MIN_ADV = 5.00, 5_000_000
LISTED_EXCHANGES = {"NMS", "NGM", "NCM", "NYQ", "ASE", "AMX"}
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]

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

# ---------------------------------------------------------------- load data
def load(symbol):
    path = os.path.join(CACHE, f"{symbol}.json")
    with open(path) as f:
        data = json.load(f)
    if "error" in data or not data.get("chart", {}).get("result"):
        return {}, {}
    r = data["chart"]["result"][0]
    meta = r.get("meta", {})
    ts = r.get("timestamp", []) or []
    q = r.get("indicators", {}).get("quote", [{}])[0]
    adj = (r.get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose")
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
        if adj and adj[i]:
            bar["adjclose"] = adj[i]
        bars[d] = bar
    return meta, bars

ALL_BARS, ALL_META = {}, {}
for s in CANDIDATES + ["SPY"]:
    ALL_META[s], ALL_BARS[s] = load(s)

SPY_DAYS = sorted(d for d in ALL_BARS["SPY"] if "2016-09-01" <= d <= RUN_END)
RUN_DAYS = [d for d in SPY_DAYS if RUN_START <= d <= RUN_END]
DAY_IDX = {d: i for i, d in enumerate(SPY_DAYS)}

# ------------------------------------------------- per-symbol derived series
# gain_pct[day], spike[day] computed on the symbol's own bar sequence.
DERIVED = {}
for s in CANDIDATES:
    bars = ALL_BARS[s]
    days = sorted(bars)
    gain, spike, adv20 = {}, {}, {}
    vols, dvols = [], []
    for i, d in enumerate(days):
        b = bars[d]
        vols.append(b["volume"]); dvols.append(b["close"] * b["volume"])
        if i > 0 and bars[days[i-1]]["close"] > 0:
            gain[d] = (b["close"] / bars[days[i-1]]["close"] - 1) * 100
        w = vols[-20:]
        avg_w = sum(w) / len(w) if w else 0.0
        spike[d] = b["volume"] / avg_w if avg_w else 0.0
        w2 = dvols[-20:]
        adv20[d] = sum(w2) / len(w2) if len(w2) == 20 else None
    DERIVED[s] = {"gain": gain, "spike": spike, "adv20": adv20}

# ------------------------------------------------------- monthly PIT screens
def month_key(d): return d[:7]

def screen_for_month(mk):
    first = mk + "-01"
    prior = [d for d in SPY_DAYS if d < first]
    if not prior:
        return []
    sd = prior[-1]
    passed = []
    for s in CANDIDATES:
        meta, bars = ALL_META[s], ALL_BARS[s]
        bar = bars.get(sd)
        if bar is None:
            continue
        adv = DERIVED[s]["adv20"].get(sd)
        if adv is None:
            continue
        if (meta.get("exchangeName") in LISTED_EXCHANGES
                and meta.get("instrumentType") == "EQUITY"
                and bar["close"] < SCREEN_MAX_PRICE and adv > SCREEN_MIN_ADV):
            passed.append(s)
    return sorted(passed)

MONTHS = sorted({month_key(d) for d in RUN_DAYS} |
                {month_key(RUN_DAYS[0])})
UNIVERSES = {mk: screen_for_month(mk) for mk in MONTHS}

# ------------------------------------------------------------ cadence dates
def cadence_dates(cadence):
    if cadence == "daily":
        return set(RUN_DAYS)
    out = set()
    if cadence in ("weekly", "biweekly"):
        weeks, seen = [], {}
        for d in RUN_DAYS:
            dt = datetime.strptime(d, "%Y-%m-%d").date()
            key = dt.isocalendar()[:2]
            if key not in seen:
                seen[key] = d; weeks.append(d)
        if cadence == "weekly":
            out = set(weeks)
        else:
            out = {weeks[i] for i in range(0, len(weeks), 2)}
    elif cadence == "monthly":
        seen = {}
        for d in RUN_DAYS:
            seen.setdefault(month_key(d), d)
        out = set(seen.values())
    elif cadence == "quarterly":
        seen = {}
        for d in RUN_DAYS:
            q = (int(d[:4]), (int(d[5:7]) - 1) // 3)
            seen.setdefault(q, d)
        out = set(seen.values())
    elif cadence == "semiannual":
        seen = {}
        for d in RUN_DAYS:
            h = (int(d[:4]), 0 if int(d[5:7]) <= 6 else 1)
            seen.setdefault(h, d)
        out = set(seen.values())
    elif cadence == "annual":
        seen = {}
        for d in RUN_DAYS:
            seen.setdefault(d[:4], d)
        out = set(seen.values())
    return out

# ---------------------------------------------------------------- simulator
def simulate(cadence, rng=None):
    dec = cadence_dates(cadence)
    cash = START_CASH
    positions = {}
    costs = spread_costs = fees = 0.0
    orders = 0
    curve = []
    halts = []            # {trigger_date, trigger_close, floor, liquidation_date, liquidation_balance}
    episode = 1
    ep_floor = START_CASH * 0.85
    state = "active"      # active | liquidate_at_open | cash_wait | ended
    restart_not_before = None
    pending = []
    trades = []

    def last_close(sym, day):
        days = [d for d in ALL_BARS[sym] if d <= day]
        return ALL_BARS[sym][days[-1]]["close"] if days else None

    def equity(day, field="close"):
        eq = cash
        for s, p in positions.items():
            b = ALL_BARS[s].get(day)
            if b:
                eq += p["shares"] * b[field]
            else:
                c = last_close(s, day)
                eq += p["shares"] * (c if c else p["entry"])
        return eq

    def do_buy(day, sym, price, amount):
        nonlocal cash, costs, spread_costs, orders
        shares = amount / (price * (1 + COST_RATE))
        c = amount - shares * price
        costs += c; spread_costs += c; orders += 1
        cash -= amount
        positions[sym] = {"shares": shares, "entry": price, "outlay": amount}
        trades.append([day, sym, "buy", round(price, 4)])

    def do_sell(day, sym, price, reason):
        nonlocal cash, costs, spread_costs, fees, orders
        p = positions.pop(sym)
        gross = p["shares"] * price
        c = gross * COST_RATE
        costs += c + SELL_ORDER_FEE; spread_costs += c; fees += SELL_ORDER_FEE
        orders += 1
        cash += gross * (1 - COST_RATE) - SELL_ORDER_FEE
        trades.append([day, sym, "sell", round(price, 4), reason])

    def rank(day, next_day, held):
        uni = UNIVERSES[month_key(next_day)]
        scored = []
        for s in uni:
            if s in held:
                continue
            g = DERIVED[s]["gain"].get(day)
            sp = DERIVED[s]["spike"].get(day)
            if g is None or sp is None:
                continue
            score = g * sp
            if score > 0:
                scored.append((score, s))
        if rng is not None:
            names = [s for _, s in scored]
            rng.shuffle(names)
            return names
        scored.sort(reverse=True)
        return [s for _, s in scored]

    n = len(RUN_DAYS)
    for i, day in enumerate(RUN_DAYS):
        is_last = (i == n - 1)
        next_day = RUN_DAYS[i + 1] if not is_last else None

        if state == "liquidate_at_open":
            for s in list(positions):
                b = ALL_BARS[s].get(day)
                if b:
                    do_sell(day, s, b["open"], "floor liquidation at open")
                else:
                    c = last_close(s, day)
                    if c:
                        do_sell(day, s, c, "floor liquidation (no bar; last close)")
            halts[-1]["liquidation_date"] = day
            halts[-1]["liquidation_balance"] = round(cash, 2)
            pending = []
            if episode >= 2:
                state = "ended"
                curve.append([day, round(cash, 4)])
                # fill remaining curve days in cash
                for d2 in RUN_DAYS[i + 1:]:
                    curve.append([d2, round(cash, 4)])
                break
            state = "cash_wait"
            restart_not_before = (datetime.strptime(day, "%Y-%m-%d").date()
                                  + timedelta(days=90)).strftime("%Y-%m-%d")
            curve.append([day, round(cash, 4)])
            continue

        if state == "cash_wait":
            if day in dec and day >= restart_not_before:
                episode = 2
                ep_floor = cash * 0.85
                state = "active"
                halts[-1]["restart_date"] = day
                halts[-1]["episode2_floor"] = round(ep_floor, 2)
                pending = rank(day, next_day, set()) if next_day else []
            curve.append([day, round(cash, 4)])
            continue

        # active: buys at the open from yesterday's ranking
        for s in pending:
            if s in positions or len(positions) >= MAX_POSITIONS:
                continue
            b = ALL_BARS[s].get(day)
            if not b or b["open"] <= 0:
                continue
            amount = min(MAX_PER_NAME_FRAC * equity(day, "open"), cash)
            if amount < 1.00:
                continue
            do_buy(day, s, b["open"], amount)
        pending = []

        # cadence-date processing: exit checks on today's bar, then ranking
        if day in dec:
            for s in list(positions):
                b = ALL_BARS[s].get(day)
                if not b:
                    continue
                entry = positions[s]["entry"]
                stop, tp = entry * (1 - STOP_FRAC), entry * (1 + TP_FRAC)
                if b["low"] <= stop:
                    fill = b["open"] if b["open"] < stop else stop
                    do_sell(day, s, fill, "stop-loss -10%")
                elif b["high"] >= tp:
                    do_sell(day, s, tp, "take-profit +25%")
            if next_day:
                pending = rank(day, next_day, set(positions))

        # end of run: liquidate at the final close
        if is_last:
            for s in list(positions):
                b = ALL_BARS[s].get(day)
                price = b["close"] if b else last_close(s, day)
                if price:
                    do_sell(day, s, price, "end-of-run exit at final close")
            curve.append([day, round(cash, 4)])
            break

        eq_close = equity(day, "close")
        curve.append([day, round(eq_close, 4)])

        # v9 floor check on the close (every day, not cadence-gated)
        if eq_close <= ep_floor:
            halts.append({"episode": episode,
                          "trigger_date": day,
                          "trigger_close": round(eq_close, 2),
                          "floor": round(ep_floor, 2)})
            state = "liquidate_at_open"

    final = cash
    series = [START_CASH] + [v for _, v in curve]
    peak, max_dd = series[0], 0.0
    for v in series:
        peak = max(peak, v)
        max_dd = min(max_dd, v / peak - 1)
    years = (datetime.strptime(RUN_END, "%Y-%m-%d")
             - datetime.strptime(RUN_START, "%Y-%m-%d")).days / 365.25
    cagr = (final / START_CASH) ** (1 / years) * 100 - 100 if final > 0 else -100.0
    return {
        "final": round(final, 2), "cagr_pct": round(cagr, 2),
        "max_dd_pct": round(max_dd * 100, 2),
        "costs": round(costs, 2), "spread_costs": round(spread_costs, 2),
        "sell_fees": round(fees, 2), "orders": orders,
        "halts": halts, "n_halts": len(halts),
        "restart": any("restart_date" in h for h in halts),
        "second_halt": len(halts) >= 2,
        "equity_curve": [[d, round(v, 2)] for d, v in curve],
        "trades": trades,
    }

def main():
    spy = ALL_BARS["SPY"]
    spy_final = 100.0 * spy[RUN_END]["adjclose"] / spy[RUN_START]["adjclose"]
    results = {"decade_spy_final": round(spy_final, 2), "cells": {}}
    for cad in CADENCES:
        r = simulate(cad)
        twins = []
        for seed in range(20):
            t = simulate(cad, rng=random.Random(1000 + seed))
            twins.append(t["final"])
        beaten = sum(1 for f in twins if r["final"] > f)
        cell = {
            "final": r["final"], "cagr_pct": r["cagr_pct"],
            "max_dd_pct": r["max_dd_pct"], "costs": r["costs"],
            "spread_costs": r["spread_costs"], "sell_fees": r["sell_fees"],
            "orders": r["orders"], "halts": r["n_halts"],
            "halt_events": r["halts"], "restart": r["restart"],
            "second_halt": r["second_halt"],
            "placebo_beaten": beaten, "placebo_twin_finals": twins,
            "equity_curve": r["equity_curve"], "trades": r["trades"],
        }
        with open(os.path.join(CELLS, f"{cad}.json"), "w") as f:
            json.dump(cell, f)
        results["cells"][cad] = {k: cell[k] for k in
            ("final", "cagr_pct", "max_dd_pct", "costs", "spread_costs",
             "orders", "halts", "restart", "second_halt", "placebo_beaten")}
        print(f"{cad:11s} final ${r['final']:8.2f}  CAGR {r['cagr_pct']:7.2f}%  "
              f"maxDD {r['max_dd_pct']:7.2f}%  costs ${r['costs']:7.2f} "
              f"(spread ${r['spread_costs']:.2f})  orders {r['orders']:4d}  "
              f"halts {r['n_halts']}  placebo beaten {beaten}/20", flush=True)
    print(f"SPY decade (dividend-adjusted): ${spy_final:.2f}")
    with open(os.path.join(HERE, "sweep_raw.json"), "w") as f:
        json.dump(results, f, indent=1)

if __name__ == "__main__":
    main()
