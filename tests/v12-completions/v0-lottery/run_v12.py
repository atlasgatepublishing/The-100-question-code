#!/usr/bin/env python3
"""
v12 -- v0-lottery: the frozen ORIGINAL v0 penny-lottery spec, re-run on the
program roads. NO spec changes, NO tuning (see CONSTRUCTION-SPEC.md).

This engine is a faithful port of the original year script
(backtests/2025-11-21-year/lottery-year.py, read-only): same monthly
point-in-time screen, same evening ranking (score = day % gain x volume
spike, positive only), same entries (next open, max 20% of equity per name,
max 5 positions, fractional, no averaging down), same exits (-10% stop with
gap-down fills at the open, +25% take-profit sells all, stop first), same
costs (2.0% of trade value on every buy and sell + $0.01 per sell order),
same floor ladder ($85; close >= $125 -> $100; close >= $150 -> $125; a close
at/below the floor liquidates at the next open and ENDS the run).

Per road: (a) program-cost run, (b) ZERO-COST TWIN (identical, costs 0 --
the family's friction measurement), (c) 20 seeded placebo twins under
program costs (random ordering of the same eligible positive-score names
each evening; v10 placebo convention, seeds 1..20).

Roads (all ending 2026-11-20, the last day of the original record):
  LONG   first trading day on/after 2010-01-01
  CONT   first trading day on/after 2019-01-01
  VAL    first trading day on/after 2023-01-01
  DECADE 2016-11-21 (the v10 decade start)

Data: Yahoo Finance chart API daily OHLCV, cached in ./data_long/
(2009-06-01 -> 2026-11-20) by download_long.py. Prices as reported
(split-adjusted, not dividend-adjusted), exactly the v0 channel/convention.

Ranking/screen arithmetic is precomputed per symbol with bisect over sorted
bar dates; the formulas are the originals, unchanged (verified: this engine
reproduces the original year window's $84.04 / $122.82 before any road runs
-- see verify mode in main()).

Outputs: results.json (equity curves for costed + zero-cost per road,
placebo finals, SPY per road), trades_<road>.csv (costed run).
"""

import bisect
import csv
import json
import os
import random
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data_long")
ET = ZoneInfo("America/New_York")

START_CASH = 100.00
FLOOR_START = 85.00
FLOOR_STEPS = [(150.00, 125.00), (125.00, 100.00)]  # (close >=, floor ->)
MAX_POSITIONS = 5
MAX_PER_NAME_FRAC = 0.20
STOP_FRAC = 0.10
TP_FRAC = 0.25
COST_RATE = 0.02
SELL_ORDER_FEE = 0.01
SCREEN_MAX_PRICE = 5.00
SCREEN_MIN_AVG_DOLLAR_VOL = 5_000_000
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

ROADS = {
    "LONG":   "2010-01-01",
    "CONT":   "2019-01-01",
    "VAL":    "2023-01-01",
    "DECADE": "2016-11-21",
}
RUN_END = "2026-11-20"
DATA_FLOOR = "2009-06-01"


# --------------------------------------------------------------------------
# Data loading (original parse, verbatim semantics)
# --------------------------------------------------------------------------

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


ALL_BARS, ALL_META = {}, {}
FAILED = []
for s in CANDIDATES + ["SPY"]:
    m, b = load(s)
    ALL_META[s], ALL_BARS[s] = m, b
    if not b:
        FAILED.append(s)

TRADING_DAYS = sorted(d for d in ALL_BARS["SPY"] if DATA_FLOOR <= d <= RUN_END)
DAY_IDX = {d: i for i, d in enumerate(TRADING_DAYS)}

# Per-symbol sorted bar dates + prefix data for exact original arithmetic.
SYM_DAYS = {s: sorted(ALL_BARS[s]) for s in CANDIDATES}


def trailing_avg(bars_days, bars, end_date, n, field):
    """Mean of `field` over the n bars ending on end_date inclusive
    (original trailing() semantics; returns (count, mean))."""
    i = bisect.bisect_right(bars_days, end_date)
    seg = bars_days[max(0, i - n):i]
    if not seg:
        return 0, 0.0
    return len(seg), sum(bars[d][field] for d in seg) / len(seg)


def last_close_on_or_before(sym, day):
    days = SYM_DAYS[sym]
    i = bisect.bisect_right(days, day)
    return ALL_BARS[sym][days[i - 1]]["close"] if i else None


# --------------------------------------------------------------------------
# Monthly point-in-time screens (original screen_for_month, verbatim rules)
# --------------------------------------------------------------------------

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


def screen_for_month(mk):
    first_of_month = mk + "-01"
    j = bisect.bisect_left(TRADING_DAYS, first_of_month)
    if j == 0:
        return None, []
    screen_date = TRADING_DAYS[j - 1]
    passed = []
    for sym in CANDIDATES:
        bars = ALL_BARS[sym]
        bar = bars.get(screen_date)
        if bar is None:
            continue
        days = SYM_DAYS[sym]
        i = bisect.bisect_right(days, screen_date)
        seg = days[max(0, i - 20):i]
        if len(seg) < 20:
            continue
        avg_dv = sum(bars[d]["close"] * bars[d]["volume"] for d in seg) / 20
        meta = ALL_META[sym]
        if (meta.get("exchangeName") in LISTED_EXCHANGES
                and meta.get("instrumentType") == "EQUITY"
                and bar["close"] < SCREEN_MAX_PRICE
                and avg_dv > SCREEN_MIN_AVG_DOLLAR_VOL):
            passed.append(sym)
    return screen_date, sorted(passed)


# --------------------------------------------------------------------------
# Ranking (original rank_evening, verbatim formula)
# --------------------------------------------------------------------------

def rank_evening(universe, day, held, rng=None):
    ranked = []
    for s in universe:
        if s in held:
            continue
        bars = ALL_BARS[s]
        today = bars.get(day)
        days = SYM_DAYS[s]
        i = bisect.bisect_left(days, day)
        if not today or i == 0:
            continue
        prev_close = bars[days[i - 1]]["close"]
        if prev_close <= 0:
            continue
        gain_pct = (today["close"] / prev_close - 1) * 100
        seg = days[max(0, i + 1 - 20):i + 1]
        avg_vol = (sum(bars[d]["volume"] for d in seg) / len(seg)
                   if seg else 0)
        spike = (today["volume"] / avg_vol) if avg_vol else 0.0
        score = gain_pct * spike
        if score > 0:
            ranked.append((score, s))
    ranked.sort(reverse=True)
    out = [s for _, s in ranked]
    if rng is not None:
        rng.shuffle(out)
    return out


# --------------------------------------------------------------------------
# Simulation -- ported line-for-line from the original year script's
# simulate(), plus: road window parameters, optional placebo rng, and the
# daily equity curve in the result.
# --------------------------------------------------------------------------

def simulate(run_days, universes, cost_rate, sell_fee, rng=None):
    res = {
        "trades": [], "total_costs": 0.0, "round_trips": [],
        "daily": [], "halted": False, "halt_date": None,
        "halt_trigger_close": None, "final_balance": None,
        "worst_intraday": (START_CASH, None), "intraday_floor_dips": [],
        "gap_through_stops": 0, "floor_history": [(None, FLOOR_START)],
        "notes": [],
    }
    trades = res["trades"]
    cash = START_CASH
    positions = {}
    floor = FLOOR_START
    halt_pending = False

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

    def close_position(date, sym, price, reason):
        nonlocal cash
        p = positions.pop(sym)
        proceeds = do_sell(date, sym, price, p["shares"], reason)
        cash += proceeds
        res["round_trips"].append(
            {"ticker": sym, "exit_date": date,
             "pnl": proceeds - p["outlay"], "outlay": p["outlay"]})

    def equity(day, field):
        eq = cash
        for s, p in positions.items():
            b = ALL_BARS[s].get(day)
            if b:
                eq += p["shares"] * b[field]
            else:
                c = last_close_on_or_before(s, day)
                eq += p["shares"] * (c if c else p["entry"])
        return eq

    start_idx = DAY_IDX[run_days[0]]
    end_idx = DAY_IDX[run_days[-1]]

    pending = rank_evening(universes[month_key(run_days[0])],
                           TRADING_DAYS[start_idx - 1], set(), rng)

    i = start_idx
    while i <= end_idx:
        day = TRADING_DAYS[i]
        is_last = (i == end_idx)

        if halt_pending:
            for s in list(positions):
                b = ALL_BARS[s].get(day)
                if b:
                    close_position(day, s, b["open"],
                                   "FLOOR liquidation at open (prior close "
                                   "touched the floor); run ends")
            res["daily"].append((day, cash))
            res["halted"] = True
            res["halt_date"] = day
            res["final_balance"] = cash
            return res

        for s in pending:
            if s in positions or len(positions) >= MAX_POSITIONS:
                continue
            b = ALL_BARS[s].get(day)
            if not b or b["open"] <= 0:
                continue
            amount = min(MAX_PER_NAME_FRAC * equity(day, "open"), cash)
            if amount < 1.00:
                continue
            shares = do_buy(day, s, b["open"], amount,
                            "entry: top momentum x volume rank from prior "
                            "evening")
            cash -= amount
            positions[s] = {"shares": shares, "entry": b["open"],
                            "outlay": amount}
        pending = []

        low_eq = equity(day, "low")
        if low_eq < res["worst_intraday"][0]:
            res["worst_intraday"] = (low_eq, day)

        for s in list(positions):
            b = ALL_BARS[s].get(day)
            if not b:
                continue
            entry = positions[s]["entry"]
            stop, tp = entry * (1 - STOP_FRAC), entry * (1 + TP_FRAC)
            if b["low"] <= stop:
                if b["open"] < stop:
                    res["gap_through_stops"] += 1
                    fill = b["open"]
                else:
                    fill = stop
                close_position(day, s, fill, "stop-loss -10% from entry")
            elif b["high"] >= tp:
                close_position(day, s, tp,
                               "take-profit +25% from entry (sold all)")

        if is_last:
            for s in list(positions):
                b = ALL_BARS[s].get(day)
                price = b["close"] if b else last_close_on_or_before(s, day)
                if price:
                    close_position(day, s, price,
                                   "end-of-run exit at final close")

        eq_close = equity(day, "close") if positions else cash
        if is_last:
            eq_close = cash
        res["daily"].append((day, eq_close))

        if low_eq < floor and eq_close > floor:
            res["intraday_floor_dips"].append((day, low_eq, floor))

        if eq_close <= floor:
            if is_last:
                res["halted"] = True
                res["halt_date"] = day
                res["halt_trigger_close"] = eq_close
                res["final_balance"] = cash
                return res
            halt_pending = True
            res["halt_trigger_close"] = eq_close
            i += 1
            continue
        for threshold, new_floor in FLOOR_STEPS:
            if eq_close >= threshold and new_floor > floor:
                floor = new_floor
                res["floor_history"].append((day, floor))
                break

        if not is_last:
            nxt = TRADING_DAYS[i + 1]
            pending = rank_evening(universes[month_key(nxt)], day,
                                   set(positions), rng)
        i += 1

    res["final_balance"] = cash
    return res


# --------------------------------------------------------------------------
# Stats + main
# --------------------------------------------------------------------------

def stats(res):
    series = [START_CASH] + [eq for _, eq in res["daily"]]
    peak, max_dd = series[0], 0.0
    for v in series:
        peak = max(peak, v)
        max_dd = min(max_dd, v / peak - 1)
    rts = res["round_trips"]
    wins = sum(1 for r in rts if r["pnl"] > 0)
    return {
        "final": round(res["final_balance"], 2),
        "return_pct": round((res["final_balance"] / START_CASH - 1) * 100, 2),
        "halted": res["halted"],
        "halt_date": res["halt_date"],
        "halt_trigger_close": (round(res["halt_trigger_close"], 2)
                               if res["halt_trigger_close"] else None),
        "days_recorded": len(res["daily"]),
        "n_trades": len(res["trades"]),
        "round_trips": len(rts),
        "wins": wins, "losses": len(rts) - wins,
        "win_rate_pct": round(wins / len(rts) * 100, 1) if rts else 0.0,
        "total_costs": round(res["total_costs"], 2),
        "max_dd_pct": round(max_dd * 100, 2),
        "worst_intraday": [round(res["worst_intraday"][0], 2),
                           res["worst_intraday"][1]],
        "gap_through_stops": res["gap_through_stops"],
        "intraday_floor_dips": len(res["intraday_floor_dips"]),
        "floor_history": [[d, f] for d, f in res["floor_history"]],
        "curve": [[d, round(eq, 4)] for d, eq in res["daily"]],
    }


def build_universes(first_day, last_day):
    universes, screens = {}, {}
    for mk in run_months(first_day, last_day):
        sdate, passed = screen_for_month(mk)
        universes[mk] = passed
        screens[mk] = {"screen_date": sdate, "n_passed": len(passed),
                       "passed": passed}
    return universes, screens


def main():
    out = {
        "family": "v0-lottery",
        "spec": "frozen original v0 (year form), unmodified rules",
        "costs": {"rate_per_side": COST_RATE, "sell_order_fee": SELL_ORDER_FEE},
        "data_failed_symbols": FAILED,
        "verification": {},
        "roads": {},
    }

    # ---- verification: original year window through THIS engine ----------
    v_first = next(d for d in TRADING_DAYS if d >= "2025-11-21")
    v_days = [d for d in TRADING_DAYS if v_first <= d <= RUN_END]
    v_univ, _ = build_universes(v_days[0], v_days[-1])
    vc = simulate(v_days, v_univ, COST_RATE, SELL_ORDER_FEE)
    vf = simulate(v_days, v_univ, 0.0, 0.0)
    out["verification"] = {
        "window": [v_days[0], v_days[-1]],
        "recorded": {"costed_final": 84.04, "zero_cost_final": 122.82,
                     "costs": 23.36, "halt_liquidation": "2026-03-13"},
        "this_engine": {"costed_final": round(vc["final_balance"], 2),
                        "zero_cost_final": round(vf["final_balance"], 2),
                        "costs": round(vc["total_costs"], 2),
                        "halt_date": vc["halt_date"]},
    }
    print("VERIFY year window:", out["verification"], flush=True)

    spy = ALL_BARS["SPY"]
    for road, start in ROADS.items():
        first = next(d for d in TRADING_DAYS if d >= start)
        run_days = [d for d in TRADING_DAYS if first <= d <= RUN_END]
        universes, screens = build_universes(run_days[0], run_days[-1])

        costed = simulate(run_days, universes, COST_RATE, SELL_ORDER_FEE)
        free = simulate(run_days, universes, 0.0, 0.0)
        placebo_finals = []
        for seed in range(1, 21):
            rng = random.Random(seed)
            pr = simulate(run_days, universes, COST_RATE, SELL_ORDER_FEE,
                          rng=rng)
            placebo_finals.append(round(pr["final_balance"], 2))
        beaten = sum(1 for x in placebo_finals
                     if costed["final_balance"] > x)

        spy_final = 100.0 * spy[run_days[-1]]["close"] / spy[run_days[0]]["open"]

        cs, fs = stats(costed), stats(free)
        out["roads"][road] = {
            "window": [run_days[0], run_days[-1]],
            "trading_days": len(run_days),
            "spy_gross_final": round(spy_final, 2),
            "costed": cs,
            "zero_cost": {k: v for k, v in fs.items() if k != "curve"},
            "zero_cost_curve": fs["curve"],
            "friction_gap_final": round(free["final_balance"]
                                        - costed["final_balance"], 2),
            "placebos_costed": {"finals": placebo_finals,
                                "beaten": beaten, "of": 20,
                                "median": sorted(placebo_finals)[10]},
            "screens": screens,
        }
        with open(os.path.join(HERE, f"trades_{road}.csv"), "w",
                  newline="") as f:
            w = csv.DictWriter(f, fieldnames=["date", "ticker", "side",
                                              "price", "shares", "value",
                                              "reason"])
            w.writeheader()
            w.writerows(costed["trades"])
        print(f"{road}: costed ${cs['final']:.2f} (halted={cs['halted']} "
              f"{cs['halt_date']}, trades={cs['n_trades']}, costs="
              f"${cs['total_costs']:.2f}) | zero-cost ${fs['final']:.2f} "
              f"(halted={fs['halted']} {fs['halt_date']}) | SPY "
              f"${spy_final:.2f} | placebo beaten {beaten}/20", flush=True)

    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("Wrote results.json")


if __name__ == "__main__":
    main()
