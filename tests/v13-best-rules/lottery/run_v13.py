#!/usr/bin/env python3
"""
V13 BEST RULES -- lottery (penny-stock lottery pot).

Implements BEST-RULES-SPEC.md exactly as frozen in this folder:
quarterly decisions (first trading day of Jan/Apr/Jul/Oct), universe =
the unchanged monthly PIT screen (listed sub-$5, trailing-20d avg dollar
volume > $20M, v3 73-name candidate list), entry ranking = trailing-20-
trading-day momentum through the prior close with a positive-momentum
eligibility gate, target book = top 5, entrants sized to 1/5 of pot
equity at the decision open, trade ONLY on membership change, NO stop,
NO target, NO floor/halt/sit-out/restart. Costs: 2.0% of trade value on
every buy and sell + $0.01 per sell order. $100 pots.

Roads: LONG 2010-01-04->2026-11-20, DECADE 2016-11-21->2026-11-20,
CONT 2019-01-02->2026-11-20, VAL 2023-01-03->2026-11-20.

Placebos: 20 seeded random-rank twins per road (seeds 1..20) --
identical screens, decision dates, eligibility (screened, momentum>0),
target size, sizing, membership-change trading and costs; only the
ranking is random.

Data: the v12-completions lottery folder's Yahoo chart-API cache
(2009-11 -> 2026-11, split-adjusted, not dividend-adjusted), read-only.
Screens/Store are the v10-retest lottery module's, imported unchanged
(read-only). This folder's outputs only: results.json.

Confirmation (PROGRAM.md): if the real form beats the V+M champion on
any road, fresh $100 calendar-year folds of the real form are run as
the different-years re-run before the verdict counts.
"""

import bisect
import importlib.util
import json
import os
import random
from datetime import datetime
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
V12_CACHE = os.path.join(
    HERE, "..", "..", "v12-completions", "lottery", "data_cache")
V10_PATH = os.path.join(
    HERE, "..", "..", "v10-retest", "lottery", "run_v10.py")
spec = importlib.util.spec_from_file_location("lottery_v10", V10_PATH)
v10 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v10)

ET = ZoneInfo("America/New_York")
START_CASH = 100.00
COST_RATE = 0.02
SELL_ORDER_FEE = 0.01
TARGET_N = 5
MOM_DAYS = 20

ROADS = {
    "LONG":   ("2010-01-04", "2026-11-20"),
    "DECADE": ("2016-11-21", "2026-11-20"),
    "CONT":   ("2019-01-02", "2026-11-20"),
    "VAL":    ("2023-01-03", "2026-11-20"),
}
SPY_REF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
CHAMPION = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
PUBLISHED = {"LONG": 71.53, "DECADE": 67.05, "CONT": 66.87, "VAL": 69.88}


def parse_bars_cached(symbol):
    """Read-only parse of the v12 folder's Yahoo cache files."""
    path = os.path.join(V12_CACHE, f"{symbol}.json")
    if not os.path.exists(path):
        return {}, {}
    with open(path) as f:
        data = json.load(f)
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


def momentum(store, sym, signal_day):
    """Trailing MOM_DAYS-trading-day return through signal_day's close.
    None if fewer than MOM_DAYS+1 bars exist up to signal_day."""
    days = store.days[sym]
    k = bisect.bisect_right(days, signal_day)
    if k < MOM_DAYS + 1:
        return None
    c_now = store.bars[sym][days[k - 1]]["close"]
    c_then = store.bars[sym][days[k - 1 - MOM_DAYS]]["close"]
    if c_then <= 0:
        return None
    return c_now / c_then - 1


def quarter_key(d):
    return (int(d[:4]), (int(d[5:7]) - 1) // 3)


def simulate(store, all_days, run_days, universes, mode, seed=None):
    rng = random.Random(seed) if mode == "RANDOM" else None
    res = {"trades": [], "total_costs": 0.0, "rate_costs": 0.0,
           "fee_costs": 0.0, "round_trips": [], "daily": [],
           "final_balance": None, "n_decisions": 0}
    cash = START_CASH
    positions = {}  # sym -> {shares, entry, outlay}

    decision_dates = []
    seen_q = set()
    for d in run_days:
        qk = quarter_key(d)
        if qk not in seen_q:
            seen_q.add(qk)
            decision_dates.append(d)
    decision_set = set(decision_dates)

    def price_at(sym, day, field):
        b = store.bars[sym].get(day)
        if b:
            return b[field]
        return store.last_close_on_or_before(sym, day)

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

    start_idx = all_days.index(run_days[0])
    end_idx = all_days.index(run_days[-1])

    for i in range(start_idx, end_idx + 1):
        day = all_days[i]
        is_last = (i == end_idx)

        if day in decision_set and i > 0:
            res["n_decisions"] += 1
            signal_day = all_days[i - 1]
            universe = universes[day[:7]]
            elig = []
            for s in universe:
                m = momentum(store, s, signal_day)
                if m is not None and m > 0:
                    elig.append((m, s))
            if mode == "MOMENTUM":
                elig.sort(key=lambda x: (-x[0], x[1]))
                target = [s for _, s in elig[:TARGET_N]]
            else:  # RANDOM placebo: same eligibility, random order
                syms = [s for _, s in elig]
                rng.shuffle(syms)
                target = syms[:TARGET_N]
            target_set = set(target)
            # sell dropouts at the open
            for s in list(positions):
                if s not in target_set:
                    px = price_at(s, day, "open")
                    if px:
                        do_sell(day, s, px)
            # buy entrants at the open, 1/5 of equity each
            eq_open = equity(day, "open")
            for s in target:
                if s in positions:
                    continue
                b = store.bars[s].get(day)
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
    """Per-period (calendar quarter) distribution from the daily curve."""
    q_end = {}
    for d, v in res["daily"]:
        q_end[quarter_key(d)] = v  # last day in quarter wins
    keys = sorted(q_end)
    rets = []
    prev = START_CASH
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
    # longest stretch between new highs, in quarters (quarter-end series)
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


def main():
    all_bars, all_meta, failed = {}, {}, []
    for sym in v10.CANDIDATES + ["SPY"]:
        meta, bars = parse_bars_cached(sym)
        all_meta[sym], all_bars[sym] = meta, bars
        if not bars:
            failed.append(sym)
    print(f"data: failed/no-data symbols = {sorted(set(failed))}")
    store = v10.Store(all_bars)
    all_days = sorted(all_bars["SPY"].keys())

    months = v10.run_months("2009-12", "2026-11")
    universes = {}
    for mk in months:
        _, passed = v10.screen_for_month(mk, all_days, store, all_meta)
        universes[mk] = passed
    nonempty = {k: v for k, v in universes.items() if v}
    print(f"screens: {len(nonempty)} non-empty months; "
          f"sample 2010-01={universes.get('2010-01')}")

    roads_out = {}
    beat_champion_roads = []
    for road, (start, end) in ROADS.items():
        run_days = [d for d in all_days if start <= d <= end]
        span_days = (datetime.strptime(end, "%Y-%m-%d")
                     - datetime.strptime(start, "%Y-%m-%d")).days
        res = simulate(store, all_days, run_days, universes, "MOMENTUM")
        st = stats_of(res, span_days)
        placebo_finals = []
        for seed in range(1, 21):
            pres = simulate(store, all_days, run_days, universes,
                            "RANDOM", seed=seed)
            placebo_finals.append(round(pres["final_balance"], 2))
        beaten = sum(1 for f in placebo_finals if st["final"] > f)
        if st["final"] > CHAMPION[road]:
            beat_champion_roads.append(road)
        roads_out[road] = {
            "window": [start, end], **st,
            "period_stats": period_stats(res),
            "placebo_beaten": beaten,
            "placebo_finals": placebo_finals,
            "placebo_median": round(sorted(placebo_finals)[10], 2),
            "spy_ref": SPY_REF[road], "champion_vm": CHAMPION[road],
            "published_form_v12": PUBLISHED[road],
            "equity_curve": [[d, v] for d, v in res["daily"]],
            "trades": res["trades"],
            "round_trips_detail": res["round_trips"],
        }
        print(f"ROAD {road}: final ${st['final']:.2f} CAGR "
              f"{st['cagr_pct']:+.2f}% DD {st['max_dd_pct']:.2f}% costs "
              f"${st['costs']:.2f} (spread ${st['spread_costs']:.2f} + fees "
              f"${st['fee_costs']:.2f}) orders {st['orders']} RT "
              f"{st['round_trips']} win {st['win_rate_pct']}% placebo "
              f"{beaten}/20")

    confirmation = None
    if beat_champion_roads:
        print(f"CHAMPION BEATEN on {beat_champion_roads} -- running "
              f"confirmation folds (fresh $100 calendar years)")
        folds = {}
        for year in range(2010, 2027):
            ys, ye = f"{year}-01-01", f"{year}-12-31"
            run_days = [d for d in all_days if ys <= d <= ye]
            if len(run_days) < 50:
                continue
            res = simulate(store, all_days, run_days, universes, "MOMENTUM")
            folds[str(year)] = round(res["final_balance"], 2)
        comp = 100.0
        for y in sorted(folds):
            comp *= folds[y] / 100.0
        confirmation = {"folds_fresh_100_per_year": folds,
                        "fold_compounded_final": round(comp, 2),
                        "note": "Different-years re-run required by the "
                                "confirmation rule; verdict counts only "
                                "if the edge survives here."}
        print(f"confirmation folds compounded: ${comp:.2f}")

    results = {
        "family": "lottery",
        "program": "v13-best-rules",
        "spec": "BEST-RULES-SPEC.md (frozen before the run)",
        "form": "Quarterly momentum basket: monthly PIT screen (listed "
                "sub-$5, >$20M trailing-20d avg dollar volume); rank by "
                "trailing-20d momentum, positive only; top 5 equal-weight "
                "at entry (1/5 of equity); trade only on membership "
                "change; no stop/target/floor/halt; costs 2.0%/side + "
                "$0.01/sell order; $100 pots.",
        "habitat_fences": "Exchange-listed sub-$5 ONLY (OTC impossible "
                "on the free broker and unbuildable from free PIT data "
                "-- v12 hunt log); fills at daily-bar prints only; "
                "candidate list assembled Nov 2026 = survivorship tilt "
                "flattering every number by an unknown amount; NO floor "
                "in this form -- nothing pretends to protect the pot; "
                "the loss is capped only by the $100 in it.",
        "failed_symbols": sorted(set(failed)),
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
