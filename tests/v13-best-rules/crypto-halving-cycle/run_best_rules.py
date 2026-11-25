#!/usr/bin/env python3
"""
V13 BEST RULES — crypto-halving-cycle (BTC only), frozen in BEST-RULES-SPEC.md
before this run. Simulation only.

Rules: buy all-in at open of H-500 for each BTC halving; sell 50% of units at
open of H+500; remaining 50% sells at next open after the first close below the
200-day SMA of closes on/after H+500, hard cap open of H+650. No floor.
Costs 0.60%/side primary; finals also at 0.40/0.80.
Placebos: 20 phase shifts (same RNG construction as v12), full rule set.
Data read-only: backtests/v4/crypto-basket-pit-data/y_BTC-USD.json
Native comparator read from v12 results.json (not re-derived).
"""
import bisect, json, os, random
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "..", "v4", "crypto-basket-pit-data")
V12 = os.path.join(HERE, "..", "..", "v12-completions", "crypto-halving-cycle", "results.json")
POT = 100.0
COST = 0.006
HALVINGS = ["2016-07-09", "2020-05-11", "2024-04-20"]

def dparse(s):
    y, m, d = map(int, s.split("-"))
    return date(y, m, d)

def load(sym="BTC"):
    with open(os.path.join(DATA, f"y_{sym}-USD.json")) as f:
        rows = json.load(f)
    bars = [(dparse(r["d"]), float(r["o"]), float(r["c"])) for r in rows]
    bars.sort()
    return bars

def run_best(bars, halvings, cost=COST):
    """Full best-rules machine. halvings: list of date objects (possibly shifted)."""
    dates = [b[0] for b in bars]
    closes = [b[2] for b in bars]
    # 200-day SMA of closes (needs >=200 closes up to and incl. day i)
    sma = [None] * len(bars)
    run_sum = 0.0
    for i, c in enumerate(closes):
        run_sum += c
        if i >= 200:
            run_sum -= closes[i - 200]
        if i >= 199:
            sma[i] = run_sum / 200.0

    def on_or_after(d):
        i = bisect.bisect_left(dates, d)
        return i if i < len(bars) else None

    windows = []
    for h in halvings:
        windows.append({
            "halving": h,
            "buy_i": on_or_after(h - timedelta(days=500)),
            "a_i": on_or_after(h + timedelta(days=500)),    # tranche A sell
            "cap_i": on_or_after(h + timedelta(days=650)),  # tranche B hard cap
        })
    start_i = windows[0]["buy_i"]
    cash = POT
    units_a = 0.0   # tranche destined for H+500 sale
    units_b = 0.0   # trend-tail tranche
    trades = []
    curve = []
    tail_pending = False
    invested_days = 0
    total_days = 0
    peak = POT
    maxdd = 0.0
    per_window = []   # standalone tracking filled from trade log below
    for i in range(start_i, len(bars)):
        d, o, c = bars[i]
        total_days += 1
        # --- open actions ---
        if tail_pending and units_b > 0:
            proceeds = units_b * o * (1 - cost)
            trades.append({"date": str(d), "side": "SELL-B-TREND", "price": o,
                           "proceeds": round(proceeds, 2)})
            cash += proceeds
            units_b = 0.0
            tail_pending = False
        for w in windows:
            if w["cap_i"] == i and units_b > 0:
                proceeds = units_b * o * (1 - cost)
                trades.append({"date": str(d), "side": "SELL-B-CAP", "price": o,
                               "proceeds": round(proceeds, 2), "halving": str(w["halving"])})
                cash += proceeds
                units_b = 0.0
                tail_pending = False
            if w["a_i"] == i and units_a > 0:
                proceeds = units_a * o * (1 - cost)
                trades.append({"date": str(d), "side": "SELL-A", "price": o,
                               "proceeds": round(proceeds, 2), "halving": str(w["halving"])})
                cash += proceeds
                units_a = 0.0
            if w["buy_i"] == i and units_a == 0 and units_b == 0 and cash > 0:
                spend = cash
                total_units = spend * (1 - cost) / o
                units_a = total_units / 2.0
                units_b = total_units / 2.0
                trades.append({"date": str(d), "side": "BUY", "price": o,
                               "spent": round(spend, 2), "halving": str(w["halving"])})
                cash = 0.0
        # --- mark on close ---
        equity = cash + (units_a + units_b) * c
        if units_a + units_b > 0:
            invested_days += 1
        curve.append([str(d), round(equity, 4)])
        peak = max(peak, equity)
        maxdd = min(maxdd, equity / peak - 1.0)
        # --- tail trigger: close below SMA200 on/after this window's H+500 bar ---
        if units_b > 0 and sma[i] is not None:
            for w in windows:
                if w["a_i"] is not None and i >= w["a_i"] and (w["cap_i"] is None or i < w["cap_i"]):
                    # units_b belonging to this window only (windows never overlap)
                    if c < sma[i]:
                        tail_pending = True
    final = curve[-1][1] if curve else POT
    return {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 1),
            "trades": trades, "n_trades": len(trades),
            "exposure_pct": round(100.0 * invested_days / max(total_days, 1), 1),
            "curve": curve}

def buyhold(bars, start_date, cost=COST):
    dates = [b[0] for b in bars]
    i = bisect.bisect_left(dates, start_date)
    units = POT * (1 - cost) / bars[i][1]
    curve = []
    peak = POT
    maxdd = 0.0
    for j in range(i, len(bars)):
        eq = units * bars[j][2]
        curve.append([str(bars[j][0]), round(eq, 4)])
        peak = max(peak, eq)
        maxdd = min(maxdd, eq / peak - 1.0)
    return {"final": round(curve[-1][1], 2), "max_dd_pct": round(maxdd * 100, 1), "curve": curve}

def window_buyhold_final(bars, buy_d, sell_d, cost=COST):
    dates = [b[0] for b in bars]
    bi = bisect.bisect_left(dates, buy_d)
    si = bisect.bisect_left(dates, sell_d)
    if si >= len(bars):
        # sell at last close, no terminal cost convention not used here; cap at last bar open
        si = len(bars) - 1
    units = POT * (1 - cost) / bars[bi][1]
    return round(units * bars[si][1] * (1 - cost), 2)

def period_stats(curve, boundaries):
    """Period = halving cycle (sell boundary to sell boundary), from curve values."""
    vals = dict(curve)
    dates_sorted = [d for d, _ in curve]
    def val_at_or_before(dstr):
        i = bisect.bisect_right(dates_sorted, dstr) - 1
        return curve[i][1]
    periods = []
    prev_date = dates_sorted[0]
    prev_val = POT  # value just before first buy bar's close mark; use curve start approx via POT
    # period return: value at cycle exit-complete date / value at previous cycle exit-complete date
    prev_val = 100.0
    for b in boundaries:
        v = val_at_or_before(b)
        periods.append(v / prev_val - 1.0)
        prev_val = v
    return periods

def main():
    bars = load()
    halvings = [dparse(h) for h in HALVINGS]
    best = run_best(bars, halvings)
    best_040 = run_best(bars, halvings, cost=0.004)
    best_080 = run_best(bars, halvings, cost=0.008)
    first_buy = halvings[0] - timedelta(days=500)
    bh = buyhold(bars, first_buy)

    # placebos: same RNG construction as v12
    rng = random.Random(20261122)
    placebo_finals = []
    for seed in range(20):
        shift = rng.choice([-1, 1]) * rng.randint(60, 730)
        shifted = [h + timedelta(days=shift) for h in halvings]
        pr = run_best(bars, shifted)
        placebo_finals.append(pr["final"])
    pf_sorted = sorted(placebo_finals)
    placebo = {"seeds": 20, "median_final": pf_sorted[10], "min_final": pf_sorted[0],
               "max_final": pf_sorted[-1],
               "strategy_percentile": sum(1 for f in placebo_finals if f < best["final"]) / 20 * 100,
               "finals": placebo_finals}

    # per-cycle standalone runs ($100 fresh per cycle) + chained early/late confirmation
    per_cycle = []
    for h in halvings:
        r = run_best(bars, [h])
        # window buy&hold over the strategy's own span: buy at H-500 open, value at strategy's last sell
        last_sell_date = dparse(r["trades"][-1]["date"]) if r["trades"] else None
        wb = window_buyhold_final(bars, h - timedelta(days=500), last_sell_date) if last_sell_date else None
        per_cycle.append({"halving": str(h), "strategy_final": r["final"],
                          "strategy_max_dd_pct": r["max_dd_pct"],
                          "trades": r["trades"],
                          "buyhold_own_span_final": wb})
    early = run_best(bars, halvings[:2])
    # early-span buy&hold: buy at first buy open, sell at early run's last sell open
    early_bh = window_buyhold_final(bars, first_buy, dparse(early["trades"][-1]["date"]))
    late = per_cycle[2]

    # per-period distribution from the chained curve: period ends when a cycle fully exits
    # cycle exit-complete dates = last SELL date of each cycle in the chained trade log
    sells = [t for t in best["trades"] if t["side"].startswith("SELL")]
    # group sells by halving order: A sells in order; cycle complete at its B sell (or A if B same)
    exit_dates = []
    a_dates = [t["date"] for t in sells if t["side"] == "SELL-A"]
    b_dates = [t["date"] for t in sells if t["side"].startswith("SELL-B")]
    for k in range(len(halvings)):
        cand = [x for x in ([a_dates[k]] if k < len(a_dates) else []) + ([b_dates[k]] if k < len(b_dates) else [])]
        exit_dates.append(max(cand))
    periods = period_stats(best["curve"], exit_dates)
    # longest stretch between new highs + calendar-year returns from curve
    peak = 0.0; peak_date = None; longest_gap = 0; last_high_date = None
    curve_dates = [dparse(d) for d, _ in best["curve"]]
    for (dstr, v), dd_ in zip(best["curve"], curve_dates):
        if v >= peak:
            if last_high_date is not None:
                longest_gap = max(longest_gap, (dd_ - last_high_date).days)
            peak = v; last_high_date = dd_
    if last_high_date is not None:
        longest_gap = max(longest_gap, (curve_dates[-1] - last_high_date).days)
    year_ret = {}
    by_year = {}
    for dstr, v in best["curve"]:
        by_year.setdefault(dstr[:4], []).append((dstr, v))
    years_sorted = sorted(by_year)
    prev_end = POT
    for y in years_sorted:
        end_v = by_year[y][-1][1]
        year_ret[y] = round((end_v / prev_end - 1.0) * 100, 1)
        prev_end = end_v

    with open(V12) as f:
        v12 = json.load(f)
    native = v12["coins"]["BTC"]["native"]
    native_bh = v12["coins"]["BTC"]["buyhold_same_span"]

    out = {
        "spec": "V13 BEST RULES crypto-halving-cycle, frozen BEST-RULES-SPEC.md 2026-11-22",
        "pot": POT, "cost_primary_per_side": COST,
        "window": [best["curve"][0][0], best["curve"][-1][0]],
        "best_rules": {k: v for k, v in best.items() if k != "curve"},
        "best_rules_cost_040_final": best_040["final"],
        "best_rules_cost_080_final": best_080["final"],
        "buyhold_same_span": {k: v for k, v in bh.items() if k != "curve"},
        "native_v12_reference": {"final": native["final"], "max_dd_pct": native["max_dd_pct"],
                                  "exposure_pct": native["exposure_pct"], "n_trades": native["n_trades"]},
        "placebo_phase_shift": placebo,
        "per_cycle_standalone": per_cycle,
        "confirmation": {
            "early_cycles_chained_2016_2020": {"strategy_final": early["final"],
                                                "strategy_max_dd_pct": early["max_dd_pct"],
                                                "buyhold_same_span_final": early_bh,
                                                "last_sell": early["trades"][-1]["date"]},
            "late_cycle_2024_standalone": {"strategy_final": late["strategy_final"],
                                            "strategy_max_dd_pct": late["strategy_max_dd_pct"],
                                            "buyhold_own_span_final": late["buyhold_own_span_final"]},
        },
        "period_distribution": {
            "periods_cycle_returns_pct": [round(p * 100, 1) for p in periods],
            "cycle_exit_dates": exit_dates,
            "longest_stretch_between_new_highs_days": longest_gap,
            "calendar_year_returns_pct": year_ret,
        },
        "curves": {"best_rules": best["curve"], "buyhold": bh["curve"],
                    "native_v12": v12["coins"]["BTC"]["curves"]["native"]},
    }
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("BEST", best["final"], "DD", best["max_dd_pct"], "trades", best["n_trades"], "exposure", best["exposure_pct"])
    print("cost040", best_040["final"], "cost080", best_080["final"])
    print("BH", bh["final"], bh["max_dd_pct"], "| native v12", native["final"], native["max_dd_pct"])
    print("placebo median", placebo["median_final"], "pct", placebo["strategy_percentile"], "min/max", placebo["min_final"], placebo["max_final"])
    for t in best["trades"]:
        print(t)
    print("per cycle:", [(c["halving"], c["strategy_final"], c["buyhold_own_span_final"]) for c in per_cycle])
    print("early", early["final"], "vs BH", early_bh, "| late", late["strategy_final"], "vs BH own span", late["buyhold_own_span_final"])
    print("periods %", out["period_distribution"]["periods_cycle_returns_pct"], "new-high gap days", longest_gap)
    print("years", year_ret)

if __name__ == "__main__":
    main()
