#!/usr/bin/env python3
"""F-7 Pivots BEST-RULES (v13). Implements BEST-RULES-SPEC.md exactly:
SPY, monthly classic pivots from prior month, entry at first open of new
month when prior close > P, exit only when prior close < S1 (ladder
dead-band), long/cash, NO floor, program costs. Placebos: same machinery
on levels from a wrong prior month (seeded). Reference twin: house form
(entry+exit at P, -15% floor) for integrity reproduction only.
Simulation only. Daily-bar chassis: pivots used as a slow bias line only;
the intraday habitat cannot be captured (see spec)."""
import json, os, time, random, statistics
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
PX = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
COST = 0.001; SELL_FEE = 0.01; START = 100.0

def load():
    j = json.load(open(PX))
    r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i, t in enumerate(ts):
        if q["close"][i] is None or adj[i] is None or q["high"][i] is None or q["low"][i] is None:
            continue
        ratio = adj[i] / q["close"][i]
        bars.append({"date": time.strftime("%Y-%m-%d", time.gmtime(t)),
                     "open": q["open"][i] * ratio, "high": q["high"][i] * ratio,
                     "low": q["low"][i] * ratio, "close": adj[i]})
    return bars

def monthly(bars):
    """month key 'YYYY-MM' -> {H,L,C} in chronological order."""
    m = OrderedDict()
    for b in bars:
        k = b["date"][:7]
        if k not in m: m[k] = {"H": b["high"], "L": b["low"], "C": b["close"]}
        else:
            m[k]["H"] = max(m[k]["H"], b["high"]); m[k]["L"] = min(m[k]["L"], b["low"]); m[k]["C"] = b["close"]
    return m

def pivots(mo):
    P = (mo["H"] + mo["L"] + mo["C"]) / 3.0
    return P, 2 * P - mo["H"]  # P, S1

def run(bars, months, mkeys, start, end, placebo_seed=None, house=False):
    cash = START; shares = 0.0; costs = 0.0; trades = 0; halted = False
    rng = random.Random(31000 + placebo_seed) if placebo_seed is not None else None
    curve = []; months_long = 0; decisions = 0; cur_long_month = False
    days = [b for b in bars if start <= b["date"] <= end]
    prev_month = None
    for di, b in enumerate(days):
        mk = b["date"][:7]
        first_of_month = (mk != prev_month)
        if first_of_month:
            prev_month = mk
            # decision uses the month just ended (the calendar month before mk)
            if mk in mkeys and mkeys.index(mk) >= 1:
                pass
            # source month = previous key in mkeys
            try: si = mkeys.index(mk) - 1
            except ValueError: si = -1
            if si >= 0:
                if placebo_seed is None:
                    src = months[mkeys[si]]
                else:
                    off = rng.randint(1, 12)  # wrong month: 1..12 months older than true source
                    src = months[mkeys[max(0, si - off)]]
                P, S1 = pivots(src)
                close_prev = months[mkeys[si]]["C"]  # real prior close always (only levels are wronged)
                decisions += 1
                exit_line = P if house else S1
                if not halted:
                    if shares == 0 and close_prev > P:
                        fee = cash * COST; shares = (cash - fee) / b["open"]; costs += fee; cash = 0.0; trades += 1
                    elif shares > 0 and close_prev < exit_line:
                        gross = shares * b["open"]; fee = gross * COST + SELL_FEE
                        cash = gross - fee; costs += fee; shares = 0.0; trades += 1
            cur_long_month = shares > 0
        if shares > 0: months_long += 0  # counted per-day below instead
        eq = cash + shares * b["close"]
        # house floor: checked on daily closes, liquidate next open, then halted
        if house and shares > 0 and eq <= 85.0 and di + 1 < len(days):
            nb = days[di + 1]
            gross = shares * nb["open"]; fee = gross * COST + SELL_FEE
            cash = gross - fee; costs += fee; shares = 0.0; trades += 1; halted = True
            curve.append({"date": b["date"], "equity": round(eq, 4)})
            continue
        curve.append({"date": b["date"], "equity": round(eq, 4)})
    # exposure: share of road days long (from final state reconstruction is complex; use trade log proxy below)
    if shares > 0:  # liquidate at final close
        gross = shares * days[-1]["close"]; fee = gross * COST + SELL_FEE
        cash = gross - fee; costs += fee; shares = 0.0; trades += 1
        curve[-1] = {"date": days[-1]["date"], "equity": round(cash, 4)}
    peak = -1; mdd = 0.0
    for pt in curve:
        peak = max(peak, pt["equity"]); mdd = max(mdd, (peak - pt["equity"]) / peak if peak > 0 else 0)
    return {"final": round(cash, 2), "max_dd_pct": round(mdd * 100, 2), "costs": round(costs, 2),
            "switch_trades": trades, "decisions": decisions, "equity_curve": curve}

def exposure_days(bars, months, mkeys, start, end):
    """Recompute state day-by-day (my rules) to report % of days long."""
    shares_long = False; days = [b for b in bars if start <= b["date"] <= end]
    prev_month = None; nlong = 0
    for b in days:
        mk = b["date"][:7]
        if mk != prev_month:
            prev_month = mk
            try: si = mkeys.index(mk) - 1
            except ValueError: si = -1
            if si >= 0:
                P, S1 = pivots(months[mkeys[si]]); cp = months[mkeys[si]]["C"]
                if not shares_long and cp > P: shares_long = True
                elif shares_long and cp < S1: shares_long = False
        if shares_long: nlong += 1
    return round(100.0 * nlong / len(days), 1) if days else None

def period_stats(curve):
    """Monthly periods from daily equity curve."""
    ends = OrderedDict()
    for pt in curve: ends[pt["date"][:7]] = pt["equity"]
    keys = list(ends); vals = [START] + [ends[k] for k in keys]
    chg = [(keys[i], round(vals[i + 1] - vals[i], 2)) for i in range(len(keys))]
    if not chg: return {}
    amounts = [c for _, c in chg]
    streak = mx = 0
    for a in amounts:
        streak = streak + 1 if a < 0 else 0; mx = max(mx, streak)
    # longest stretch between new highs (in months, month-end equity)
    last_high_i = 0; run_max = vals[0]; gap = mxgap = 0
    for i, v in enumerate(vals[1:], 1):
        if v > run_max: run_max = v; mxgap = max(mxgap, gap); gap = 0
        else: gap += 1
    mxgap = max(mxgap, gap)
    best = max(chg, key=lambda x: x[1]); worst = min(chg, key=lambda x: x[1])
    return {"periods": len(chg), "median_period": round(statistics.median(amounts), 2),
            "share_positive_pct": round(100 * sum(1 for a in amounts if a > 0) / len(amounts), 1),
            "best_period": {"month": best[0], "usd": best[1]}, "worst_period": {"month": worst[0], "usd": worst[1]},
            "longest_losing_streak_months": mx, "longest_stretch_between_new_highs_months": mxgap,
            "mean_period_secondary": round(statistics.mean(amounts), 2)}

def buyhold(bars, start, end):
    days = [b for b in bars if start <= b["date"] <= end]
    sh = (START * (1 - COST)) / days[0]["close"]
    gross = sh * days[-1]["close"]; return round(gross - gross * COST - SELL_FEE, 2)

def main():
    bars = load(); months = monthly(bars); mkeys = list(months.keys())
    roads = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
             "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
    house_ref = {"LONG": 221.91, "DECADE": 175.43, "CONT": 168.05, "VAL": 152.42}
    out = {"family": "folklore-f7-pivots",
           "form": "BEST-RULES v13: SPY monthly pivots, entry close>P, exit close<S1 (ladder dead-band), first-open execution, no floor, program costs",
           "chassis_fence": "Daily bars aggregated to monthly pivots; intraday pivot habitat (order of touches, reaction, flow) cannot be captured on this chassis.",
           "roads": {}}
    for name, (s, e) in roads.items():
        r = run(bars, months, mkeys, s, e)
        twins = [run(bars, months, mkeys, s, e, placebo_seed=seed)["final"] for seed in range(20)]
        h = run(bars, months, mkeys, s, e, house=True)
        r["spy_buyhold"] = buyhold(bars, s, e)
        r["placebo_finals"] = twins
        r["placebos_beaten"] = sum(1 for t in twins if r["final"] > t)
        r["placebo_median"] = round(statistics.median(twins), 2)
        r["exposure_pct_days_long"] = exposure_days(bars, months, mkeys, s, e)
        r["period_stats"] = period_stats(r["equity_curve"])
        r["house_twin"] = {"final": h["final"], "max_dd_pct": h["max_dd_pct"], "record": house_ref[name]}
        out["roads"][name] = r
        print(name, "MINE", r["final"], "DD", r["max_dd_pct"], "BH", r["spy_buyhold"],
              "house-twin", h["final"], "(record", house_ref[name], ") costs", r["costs"],
              "trades", r["switch_trades"], "exposure%", r["exposure_pct_days_long"],
              "placebo", r["placebos_beaten"], "/20 med", r["placebo_median"])
    folds = {}
    for y in range(2010, 2027):
        s = f"{y}-01-01"; e = f"{y}-12-31" if y < 2026 else "2026-11-20"
        folds[str(y)] = run(bars, months, mkeys, s, e)["final"]
    out["year_folds_mine"] = folds
    print("folds", folds)
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)

if __name__ == "__main__":
    main()
