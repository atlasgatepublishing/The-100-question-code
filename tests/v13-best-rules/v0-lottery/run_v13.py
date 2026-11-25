#!/usr/bin/env python3
"""
V13 BEST RULES -- v0-lottery (original v0 penny/lottery sprint pot).

Implements BEST-RULES-SPEC.md exactly as frozen in this folder:
quarterly decisions (first trading day of Jan/Apr/Jul/Oct), universe =
the family's own monthly PIT screen (69-name candidate list, listed
EQUITY only, close < $5, trailing-20d avg dollar volume > $5M),
entry ranking = trailing-20-trading-day momentum through the prior
close, positive momentum only, target book = top 5, entrants sized to
1/5 of pot equity at the decision open, trade ONLY on membership
change, NO stop, NO target, NO floor/halt/restart. Costs: 2.0% of
trade value on every buy and sell + $0.01 per sell order. $100 pots.

Roads: LONG 2010-01-04->2026-11-20, DECADE 2016-11-21->2026-11-20,
CONT 2019-01-02->2026-11-20, VAL 2023-01-03->2026-11-20.

Placebos: 20 seeded random-rank twins per road (seeds 1..20) --
identical screens, decision dates, eligibility (screened, momentum>0),
target size, sizing, membership-change trading and costs; only the
ranking is random.

Data: v12-completions/v0-lottery/data_long/ Yahoo chart-API cache
(2009-06 -> 2026-11, split-adjusted, not dividend-adjusted), read-only.
Screen arithmetic is the v12 engine's, unchanged.

Confirmation (frozen in the spec): if the real form beats the V+M
champion on any road -- fresh $100 calendar-year folds 2010-2026
(compounded must beat $100 and compounded SPY folds) plus half-window
runs 2010-2017 / 2018-2026 (each must beat the published form's final
for that road) -- before any BEATS WHAT WE HAVE claim.
"""

import bisect
import json
import os
import random
from datetime import datetime
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "..", "..", "v12-completions", "v0-lottery",
                     "data_long")
ET = ZoneInfo("America/New_York")

START_CASH = 100.00
COST_RATE = 0.02
SELL_ORDER_FEE = 0.01
TARGET_N = 5
MOM_DAYS = 20
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
    "LONG":   ("2010-01-04", "2026-11-20"),
    "DECADE": ("2016-11-21", "2026-11-20"),
    "CONT":   ("2019-01-02", "2026-11-20"),
    "VAL":    ("2023-01-03", "2026-11-20"),
}
SPY_REF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
CHAMPION = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
PUBLISHED = {"LONG": 84.21, "DECADE": 83.99, "CONT": 83.28, "VAL": 81.78}
LOTTERY_V13 = {"LONG": 171.29, "DECADE": 120.31, "CONT": 125.60, "VAL": 121.18}
LOTTERY_V2_V13 = {"LONG": None, "DECADE": 264.67, "CONT": 304.33, "VAL": 98.09}


def load(symbol):
    path = os.path.join(CACHE, f"{symbol}.json")
    if not os.path.exists(path):
        return {}, {}
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


ALL_BARS, ALL_META, FAILED = {}, {}, []
for s in CANDIDATES + ["SPY"]:
    m, b = load(s)
    ALL_META[s], ALL_BARS[s] = m, b
    if not b:
        FAILED.append(s)
SYM_DAYS = {s: sorted(ALL_BARS[s]) for s in CANDIDATES + ["SPY"]}
TRADING_DAYS = sorted(d for d in ALL_BARS["SPY"] if d <= "2026-11-20")


def last_close_on_or_before(sym, day):
    days = SYM_DAYS[sym]
    i = bisect.bisect_right(days, day)
    return ALL_BARS[sym][days[i - 1]]["close"] if i else None


def screen_for_month(mk):
    """v12 engine's monthly PIT screen, verbatim rules."""
    j = bisect.bisect_left(TRADING_DAYS, mk + "-01")
    if j == 0:
        return []
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
    return sorted(passed)


def momentum(sym, signal_day):
    days = SYM_DAYS[sym]
    k = bisect.bisect_right(days, signal_day)
    if k < MOM_DAYS + 1:
        return None
    c_now = ALL_BARS[sym][days[k - 1]]["close"]
    c_then = ALL_BARS[sym][days[k - 1 - MOM_DAYS]]["close"]
    if c_then <= 0:
        return None
    return c_now / c_then - 1


def quarter_key(d):
    return (int(d[:4]), (int(d[5:7]) - 1) // 3)


def simulate(run_days, universes, mode, seed=None):
    rng = random.Random(seed) if mode == "RANDOM" else None
    res = {"trades": [], "total_costs": 0.0, "rate_costs": 0.0,
           "fee_costs": 0.0, "round_trips": [], "daily": [],
           "final_balance": None, "n_decisions": 0}
    cash = START_CASH
    positions = {}

    decision_set = set()
    seen_q = set()
    for d in run_days:
        qk = quarter_key(d)
        if qk not in seen_q:
            seen_q.add(qk)
            decision_set.add(d)

    def price_at(sym, day, field):
        b = ALL_BARS[sym].get(day)
        if b:
            return b[field]
        return last_close_on_or_before(sym, day)

    def equity(day, field):
        eq = cash
        for s, p in positions.items():
            px = price_at(s, day, field)
            if px:
                eq += p["shares"] * px
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

    def do_sell(date, sym, price):
        nonlocal cash
        p = positions.pop(sym)
        gross = p["shares"] * price
        res["total_costs"] += gross * COST_RATE + SELL_ORDER_FEE
        res["rate_costs"] += gross * COST_RATE
        res["fee_costs"] += SELL_ORDER_FEE
        res["trades"].append({"date": date, "ticker": sym, "side": "sell",
                              "price": round(price, 4),
                              "shares": round(p["shares"], 6),
                              "value": round(gross, 2)})
        proceeds = gross * (1 - COST_RATE) - SELL_ORDER_FEE
        cash += proceeds
        res["round_trips"].append(
            {"ticker": sym, "exit_date": date,
             "pnl": round(proceeds - p["outlay"], 2),
             "outlay": p["outlay"]})

    start_idx = TRADING_DAYS.index(run_days[0])
    end_idx = TRADING_DAYS.index(run_days[-1])

    for i in range(start_idx, end_idx + 1):
        day = TRADING_DAYS[i]
        is_last = (i == end_idx)

        if day in decision_set and i > 0:
            res["n_decisions"] += 1
            signal_day = TRADING_DAYS[i - 1]
            universe = universes[day[:7]]
            elig = []
            for s in universe:
                m = momentum(s, signal_day)
                if m is not None and m > 0:
                    elig.append((m, s))
            if mode == "MOMENTUM":
                elig.sort(key=lambda x: (-x[0], x[1]))
                target = [s for _, s in elig[:TARGET_N]]
            else:
                syms = [s for _, s in elig]
                rng.shuffle(syms)
                target = syms[:TARGET_N]
            target_set = set(target)
            for s in list(positions):
                if s not in target_set:
                    px = price_at(s, day, "open")
                    if px:
                        do_sell(day, s, px)
            eq_open = equity(day, "open")
            for s in target:
                if s in positions:
                    continue
                b = ALL_BARS[s].get(day)
                if not b or b["open"] <= 0:
                    continue
                amount = min(eq_open / TARGET_N, cash)
                if amount >= 1.00:
                    shares = do_buy(day, s, b["open"], amount)
                    cash -= amount
                    positions[s] = {"shares": shares, "entry": b["open"],
                                    "outlay": amount}

        if is_last:
            for s in list(positions):
                px = price_at(s, day, "close")
                if px:
                    do_sell(day, s, px)
            res["daily"].append((day, round(cash, 4)))
        else:
            res["daily"].append((day, round(equity(day, "close"), 4)))

    res["final_balance"] = cash
    return res


def period_stats(res):
    q_end = {}
    for d, v in res["daily"]:
        q_end[quarter_key(d)] = v
    keys = sorted(q_end)
    rets, prev = [], START_CASH
    for k in keys:
        rets.append(q_end[k] / prev - 1)
        prev = q_end[k]
    if not rets:
        return {}
    srt = sorted(rets)
    n = len(srt)
    median = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2
    longest_loss = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0
        longest_loss = max(longest_loss, cur)
    series = [START_CASH] + [q_end[k] for k in keys]
    peak, since, longest = series[0], 0, 0
    for v in series[1:]:
        if v >= peak:
            peak, since = v, 0
        else:
            since += 1
            longest = max(longest, since)
    return {"periods": n,
            "median_pct": round(median * 100, 2),
            "pct_positive": round(sum(1 for r in rets if r > 0) / n * 100, 1),
            "best_pct": round(max(rets) * 100, 2),
            "worst_pct": round(min(rets) * 100, 2),
            "mean_pct_secondary": round(sum(rets) / n * 100, 2),
            "longest_losing_streak": longest_loss,
            "longest_between_highs_periods": longest}


def stats_of(res, span_days):
    series = [START_CASH] + [eq for _, eq in res["daily"]]
    peak, max_dd = series[0], 0.0
    for v in series:
        peak = max(peak, v)
        max_dd = min(max_dd, v / peak - 1)
    final = res["final_balance"]
    years = span_days / 365.25
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
            "win_rate_pct": round(len(wins) / len(rts) * 100, 1) if rts else 0.0,
            "n_decisions": res["n_decisions"]}


def spy_fold_final(run_days):
    first = ALL_BARS["SPY"][run_days[0]]["open"]
    last = ALL_BARS["SPY"][run_days[-1]]["close"]
    return round(100.0 * last / first, 2)


def main():
    print(f"data: failed/no-data symbols = {sorted(set(FAILED))}")
    months = []
    y, m = 2009, 12
    while (y, m) <= (2026, 11):
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    universes = {mk: screen_for_month(mk) for mk in months}
    nonempty = {k: v for k, v in universes.items() if v}
    print(f"screens: {len(nonempty)} non-empty months of {len(months)}; "
          f"2010-01={universes.get('2010-01')} 2023-01={universes.get('2023-01')}")

    roads_out = {}
    beat_champion_roads = []
    for road, (start, end) in ROADS.items():
        run_days = [d for d in TRADING_DAYS if start <= d <= end]
        span_days = (datetime.strptime(end, "%Y-%m-%d")
                     - datetime.strptime(start, "%Y-%m-%d")).days
        res = simulate(run_days, universes, "MOMENTUM")
        st = stats_of(res, span_days)
        placebo_finals = []
        for seed in range(1, 21):
            pres = simulate(run_days, universes, "RANDOM", seed=seed)
            placebo_finals.append(round(pres["final_balance"], 2))
        beaten = sum(1 for f in placebo_finals if st["final"] > f)
        if st["final"] > CHAMPION[road]:
            beat_champion_roads.append(road)
        roads_out[road] = {
            "window": [start, end], **st,
            "period_stats": period_stats(res),
            "placebo_beaten": beaten,
            "placebo_finals": placebo_finals,
            "placebo_median": round(sorted(placebo_finals)[9:11][0] * 0 +
                                    (sorted(placebo_finals)[9] +
                                     sorted(placebo_finals)[10]) / 2, 2),
            "placebo_min": min(placebo_finals),
            "placebo_max": max(placebo_finals),
            "spy_ref": SPY_REF[road], "champion_vm": CHAMPION[road],
            "published_form_v12": PUBLISHED[road],
            "lottery_v13": LOTTERY_V13[road],
            "lottery_v2_v13": LOTTERY_V2_V13[road],
            "equity_curve": [[d, v] for d, v in res["daily"]],
            "trades": res["trades"],
            "round_trips_detail": res["round_trips"],
        }
        print(f"ROAD {road}: final ${st['final']:.2f} CAGR "
              f"{st['cagr_pct']:+.2f}% DD {st['max_dd_pct']:.2f}% costs "
              f"${st['costs']:.2f} orders {st['orders']} RT "
              f"{st['round_trips']} win {st['win_rate_pct']}% placebo "
              f"{beaten}/20 median ${roads_out[road]['placebo_median']:.2f}")

    confirmation = None
    if beat_champion_roads:
        print(f"CHAMPION BEATEN on {beat_champion_roads} -- running frozen "
              f"confirmation: yearly folds + half-windows")
        folds, spy_folds = {}, {}
        for year in range(2010, 2027):
            run_days = [d for d in TRADING_DAYS
                        if f"{year}-01-01" <= d <= f"{year}-12-31"]
            if len(run_days) < 50:
                continue
            folds[str(year)] = round(
                simulate(run_days, universes, "MOMENTUM")["final_balance"], 2)
            spy_folds[str(year)] = spy_fold_final(run_days)
        comp = spy_comp = 100.0
        for yr in sorted(folds):
            comp *= folds[yr] / 100.0
            spy_comp *= spy_folds[yr] / 100.0
        halves = {}
        for label, (hs, he) in {"2010-2017": ("2010-01-01", "2017-12-31"),
                                "2018-2026": ("2018-01-01", "2026-11-20")}.items():
            run_days = [d for d in TRADING_DAYS if hs <= d <= he]
            halves[label] = round(
                simulate(run_days, universes, "MOMENTUM")["final_balance"], 2)
        confirmation = {
            "trigger_roads": beat_champion_roads,
            "folds_fresh_100_per_year": folds,
            "spy_folds_fresh_100_per_year": spy_folds,
            "fold_compounded_final": round(comp, 2),
            "spy_fold_compounded_final": round(spy_comp, 2),
            "fold_bar_pass": bool(comp > 100.0 and comp > spy_comp),
            "half_windows": halves,
            "half_window_bar": "each half must beat the published form's "
                               "final for the triggered road",
        }
        print(f"confirmation: folds compounded ${comp:.2f} vs SPY folds "
              f"${spy_comp:.2f}; halves {halves}")

    results = {
        "family": "v0-lottery",
        "program": "v13-best-rules",
        "spec": "BEST-RULES-SPEC.md (frozen before the run)",
        "form": "Quarterly momentum basket on the v0 pond: monthly PIT "
                "screen (69-name list, listed sub-$5, >$5M trailing-20d "
                "avg dollar volume); rank by trailing-20d momentum, "
                "positive only; top 5 equal-weight at entry (1/5 of "
                "equity); trade only on membership change; no "
                "stop/target/floor/halt; costs 2.0%/side + $0.01/sell "
                "order; $100 pots.",
        "habitat_fences": "Exchange-listed sub-$5 ONLY (OTC impossible "
                "on the free broker); fills at daily-bar prints only; "
                "candidate list assembled Nov 2026 = survivorship tilt "
                "flattering every number by an unknown amount; NO floor "
                "in this form -- the published form's -15% floor was a "
                "target, not a guarantee (gaps/no-bid jump through it); "
                "the loss is capped only by the $100 in the pot.",
        "failed_symbols": sorted(set(FAILED)),
        "roads": roads_out,
        "beat_champion_roads": beat_champion_roads,
        "confirmation": confirmation,
        "verdict_ceiling": "CANDIDATE -- every road seen before; the "
                           "forward paper trial is the only promotion "
                           "court.",
    }
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("Wrote results.json")


if __name__ == "__main__":
    main()
