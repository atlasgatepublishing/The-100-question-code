#!/usr/bin/env python3
"""V11 NATIVE RUN — George & Hwang (2004) 52-week-high strategy, frozen spec.

Spec (see NATIVE-SPEC.md): monthly formation; rank the universe by
ratio = close / max(close over prior 252 trading sessions); long the top
tercile (10 of 30 pond names), equal weight; 6-month holding via six
overlapping monthly cohorts (Jegadeesh-Titman / George-Hwang methodology);
long-short tercile book computed as a supplementary series.
Costs: program standard 0.10% of notional per side + $0.01 per sell order.
No stop, no floor — the paper specifies none.
Data (read-only): backtests/v4/momentum-basket-honest-data/*.json (open/close
daily bars, 2015-01-02 onward). SPY excluded from the ranked universe, used
as benchmark only.
"""
import json, pathlib, random, sys

DATA = pathlib.Path.home() / "workspace/stock-app/backtests/v4/momentum-basket-honest-data"
START_CASH = 100.0
COST_RATE = 0.001
SELL_FEE = 0.01
LOOKBACK = 252
HOLD_MONTHS = 6
TOP_N = 10

def load():
    series = {}
    for f in sorted(DATA.glob("*.json")):
        rows = json.loads(f.read_text())
        series[f.stem] = rows
    return series

SERIES = load()
SYMS = [s for s in sorted(SERIES) if s != "SPY"]
DATES = [r["d"] for r in SERIES["SPY"]]
IDX = {d: i for i, d in enumerate(DATES)}
OPEN = {s: [r["o"] for r in SERIES[s]] for s in SERIES}
CLOSE = {s: [r["c"] for r in SERIES[s]] for s in SERIES}

def month_starts(start_i, end_i):
    out, seen = [], set()
    for i in range(start_i, end_i + 1):
        ym = DATES[i][:7]
        if ym not in seen:
            seen.add(ym); out.append(i)
    return out

def run(window_start, window_end, mode="long", seed=None):
    """mode: 'long' (top tercile), 'longshort' (top long / bottom short),
    'placebo' (random tercile, long). Returns dict with curve etc."""
    rng = random.Random(seed) if seed is not None else None
    s_i, e_i = IDX[window_start], IDX[window_end]
    forms = month_starts(s_i, e_i)
    cash = START_CASH
    cohorts = []  # each: {"shares": {sym: signed shares}, "age": int}
    costs = 0.0; orders = 0
    curve = []
    formations = 0
    for i in range(s_i, e_i + 1):
        if i in forms and i > 0:
            sig = i - 1  # signal from prior close
            # age cohorts, sell expired
            keep = []
            for c in cohorts:
                c["age"] += 1
                if c["age"] > HOLD_MONTHS:
                    for sym, sh in c["shares"].items():
                        px = OPEN[sym][i]
                        notional = abs(sh * px)
                        fee = notional * COST_RATE + (SELL_FEE if sh > 0 else 0.0)
                        # closing a long = sell (fee); closing a short = buy (no sell fee)
                        cash += sh * px - (notional * COST_RATE) - (SELL_FEE if sh > 0 else 0.0)
                        costs += notional * COST_RATE + (SELL_FEE if sh > 0 else 0.0)
                        orders += 1
                else:
                    keep.append(c)
            cohorts = keep
            # equity at open for sizing
            eq = cash + sum(sh * OPEN[s][i] for c in cohorts for s, sh in c["shares"].items())
            budget = eq / HOLD_MONTHS
            if sig >= LOOKBACK - 1:
                ratios = {}
                for s in SYMS:
                    hi = max(CLOSE[s][sig - LOOKBACK + 1: sig + 1])
                    if hi > 0:
                        ratios[s] = CLOSE[s][sig] / hi
                ranked = sorted(ratios, key=lambda s: -ratios[s])
                if mode == "placebo":
                    picks_long = rng.sample(sorted(ratios), TOP_N)
                    picks_short = []
                else:
                    picks_long = ranked[:TOP_N]
                    picks_short = ranked[-TOP_N:] if mode == "longshort" else []
                shares = {}
                per = budget / (TOP_N * (2 if mode == "longshort" else 1))
                for s in picks_long:
                    sh = per / OPEN[s][i]
                    fee = per * COST_RATE
                    cash -= per + fee; costs += fee; orders += 1
                    shares[s] = shares.get(s, 0.0) + sh
                for s in picks_short:
                    sh = per / OPEN[s][i]
                    fee = per * COST_RATE + SELL_FEE  # opening a short is a sell
                    cash += per - fee; costs += fee; orders += 1
                    shares[s] = shares.get(s, 0.0) - sh
                cohorts.append({"shares": shares, "age": 1})
                formations += 1
        eq_close = cash + sum(sh * CLOSE[s][i] for c in cohorts for s, sh in c["shares"].items())
        curve.append({"d": DATES[i], "eq": round(eq_close, 4)})
    # liquidate at end close
    final = curve[-1]["eq"] if curve else START_CASH
    peak, maxdd = START_CASH, 0.0
    for p in curve:
        peak = max(peak, p["eq"]); maxdd = max(maxdd, (peak - p["eq"]) / peak if peak else 0)
    yearly = {}
    for p in curve:
        yearly[p["d"][:4]] = p["eq"]
    return {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 2),
            "costs": round(costs, 2), "orders": orders, "formations": formations,
            "curve": curve, "year_end_equity": yearly}

def spy_bh(window_start, window_end):
    s_i, e_i = IDX[window_start], IDX[window_end]
    sh = START_CASH / OPEN["SPY"][s_i]
    return round(sh * CLOSE["SPY"][e_i] - (sh * CLOSE["SPY"][e_i]) * COST_RATE - SELL_FEE, 2)

WINDOWS = {"DECADE": ("2016-11-21", "2026-11-20"),
           "CONT": ("2019-01-02", "2026-11-20"),
           "VAL": ("2023-01-03", "2026-11-20")}

def main():
    out = {"strategy": "George-Hwang 2004 52-week-high, native long tercile + overlapping 6m cohorts",
           "universe": SYMS, "windows": {}}
    for name, (a, b) in WINDOWS.items():
        r = run(a, b, "long")
        ls = run(a, b, "longshort")
        twins = [run(a, b, "placebo", seed=7700 + k)["final"] for k in range(20)]
        beaten = sum(1 for t in twins if r["final"] > t)
        out["windows"][name] = {"window": [a, b], "long": r, "longshort_final": ls["final"],
                                "longshort_max_dd_pct": ls["max_dd_pct"],
                                "spy_buyhold_price_basis": spy_bh(a, b),
                                "placebo_beaten": f"{beaten}/20", "placebo_finals": twins}
        print(name, "long final", r["final"], "dd", r["max_dd_pct"], "costs", r["costs"],
              "orders", r["orders"], "| LS", ls["final"], "| SPY", spy_bh(a, b), "| placebo", beaten, "/20")
    pathlib.Path(__file__).with_name("gh_results.json").write_text(json.dumps(out, indent=1))
    print("saved gh_results.json")

if __name__ == "__main__":
    main()
