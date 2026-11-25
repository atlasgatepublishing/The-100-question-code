#!/usr/bin/env python3
"""Overnight Effect -- V13 BEST RULES run. Implements BEST-RULES-SPEC.md
exactly (frozen before this run):

MY FORM ("hold-through"): SPY, buy at the road's first close with the
whole $100 pot, hold through every night AND every day, sell at the
road's last close. One round trip per road. No floor, no rebalancing.
Program costs at full weight: 0.10%/side + $0.01 per sell order.

CONTROL (labeled, not a candidate): the v12 CONSTRUCTED overnight form
-- buy every close, sell next open -- re-run on identical data/costs so
the comparison table is self-contained.

Placebos: 20 seeds, uniformly random entry day in the road, buy at that
close, hold to the last close, same costs.
SPY buy-hold: program convention (buy at first open), same costs.
Data: shared SPY bars, read-only, lr_common convention (open scaled by
adjclose/close, close = adjclose). Simulation only."""
import json, os, random, time
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
PX = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
COST = 0.001; SELL_FEE = 0.01; START = 100.0

def load():
    j = json.load(open(PX))
    r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i, t in enumerate(ts):
        if q["open"][i] is None or q["close"][i] is None or adj[i] is None:
            continue
        ratio = adj[i] / q["close"][i]
        bars.append({"date": time.strftime("%Y-%m-%d", time.gmtime(t)),
                     "open": q["open"][i] * ratio, "close": adj[i]})
    return bars

def road_idx(bars, start, end):
    return [i for i, b in enumerate(bars) if start <= b["date"] <= end]

def hold_form(bars, idx, entry_pos=0):
    """Buy at close of idx[entry_pos], hold, sell at close of idx[-1].
    Returns final, costs, daily equity curve (marked at each close;
    days before entry are cash at START)."""
    ei = idx[entry_pos]
    buy_px = bars[ei]["close"]
    notional = START / (1.0 + COST)
    shares = notional / buy_px
    buy_cost = notional * COST
    curve = []
    for i in idx:
        if i < ei:
            curve.append({"date": bars[i]["date"], "equity": round(START, 4)})
        elif i < idx[-1]:
            curve.append({"date": bars[i]["date"], "equity": round(shares * bars[i]["close"], 4)})
        else:
            gross = shares * bars[i]["close"]
            curve.append({"date": bars[i]["date"], "equity": round(gross, 4)})  # pre-sale mark
    gross_final = shares * bars[idx[-1]]["close"]
    sell_cost = gross_final * COST + SELL_FEE
    final = gross_final - sell_cost
    curve[-1] = {"date": bars[idx[-1]]["date"], "equity": round(final, 4)}
    return final, buy_cost + sell_cost, curve

def max_dd(curve):
    peak = START; mdd = 0.0
    for pt in curve:
        peak = max(peak, pt["equity"])
        if peak > 0: mdd = max(mdd, (peak - pt["equity"]) / peak)
    return round(mdd * 100, 2)

def longest_underwater_days(curve):
    """Longest stretch (calendar days) between new equity highs."""
    peak = START; peak_date = curve[0]["date"]; worst = 0
    for pt in curve:
        if pt["equity"] >= peak:
            peak = pt["equity"]; peak_date = pt["date"]
        d0 = date.fromisoformat(peak_date); d1 = date.fromisoformat(pt["date"])
        worst = max(worst, (d1 - d0).days)
    return worst

def period_distribution(curve):
    """Periods = calendar years. Return per year from year-end marks."""
    years = {}
    for pt in curve:
        years.setdefault(pt["date"][:4], []).append(pt)
    marks = []
    prev = START
    for y in sorted(years):
        end_eq = years[y][-1]["equity"]
        marks.append({"year": y, "start_equity": round(prev, 2), "end_equity": round(end_eq, 2),
                      "return_pct": round(100.0 * (end_eq / prev - 1.0), 2) if prev > 0 else None})
        prev = end_eq
    rets = [m["return_pct"] for m in marks if m["return_pct"] is not None]
    srt = sorted(rets)
    median = srt[len(srt) // 2] if len(srt) % 2 else round((srt[len(srt) // 2 - 1] + srt[len(srt) // 2]) / 2, 2)
    streak = 0; worst_streak = 0
    for r in rets:
        streak = streak + 1 if r < 0 else 0
        worst_streak = max(worst_streak, streak)
    return {"periods": marks, "n_periods": len(rets), "median_period_pct": median,
            "share_positive_pct": round(100.0 * sum(1 for r in rets if r > 0) / len(rets), 1) if rets else None,
            "best_period_pct": max(rets) if rets else None, "worst_period_pct": min(rets) if rets else None,
            "longest_losing_streak_periods": worst_streak}

# ---- CONTROL: v12 overnight machinery (identical to v12 script) ----
def run_sequence(segs, with_costs=True):
    cash = START; costs = 0.0; died = False; death_date = None
    for d, m in segs:
        if died: continue
        if with_costs:
            notional = cash / (1.0 + COST); c1 = notional * COST
            value = notional * m
            c2 = value * COST + SELL_FEE
            cash = value - c2; costs += c1 + c2
            if cash <= 0: cash = 0.0; died = True; death_date = d
        else:
            cash = cash * m
    return cash, costs, died, death_date

def control_overnight(bars, start, end):
    idx = road_idx(bars, start, end)
    segs = [(bars[idx[k]]["date"], bars[idx[k + 1]]["open"] / bars[idx[k]]["close"])
            for k in range(len(idx) - 1)]
    final, costs, died, death_date = run_sequence(segs, with_costs=True)
    gross, _, _, _ = run_sequence(segs, with_costs=False)
    return {"final": round(final, 2), "gross_final_no_costs": round(gross, 2),
            "costs": round(costs, 2), "round_trips": len(segs),
            "pot_died": died, "death_segment_date": death_date}

def buyhold_open(bars, idx):
    sh = (START * (1 - COST)) / bars[idx[0]]["open"]
    gross = sh * bars[idx[-1]]["close"]
    return round(gross - gross * COST - SELL_FEE, 2)

def main():
    bars = load()
    roads = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
             "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
    champions = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
    spy_ref = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
    prior_best = {"LONG": 0.00, "DECADE": 71.57, "CONT": 0.00, "VAL": 17.15}  # v12 net / v10 DECADE
    out = {"family": "overnight-effect", "program": "v13-best-rules",
           "form": "hold-through: buy SPY at first close, hold every night and day, sell at last close; no floor",
           "roads": {}, "roads_meta": roads}
    for name, (s, e) in roads.items():
        idx = road_idx(bars, s, e)
        final, costs, curve = hold_form(bars, idx, entry_pos=0)
        # placebos: 20 seeded random entry days, hold to end
        twins = []
        for seed in range(20):
            rng = random.Random(41000 + seed)
            pos = rng.randrange(len(idx) - 1)  # not the last day (nothing to hold)
            tf, _, _ = hold_form(bars, idx, entry_pos=pos)
            twins.append(round(tf, 2))
        ctrl = control_overnight(bars, s, e)
        r = {"final": round(final, 2), "costs": round(costs, 2), "orders": 2,
             "max_dd_pct": max_dd(curve),
             "longest_stretch_between_new_highs_days": longest_underwater_days(curve),
             "spy_buyhold_computed": buyhold_open(bars, idx),
             "spy_reference_program": spy_ref[name],
             "champion_reference": champions[name],
             "family_prior_best_net": prior_best[name],
             "control_v12_overnight_daily": ctrl,
             "placebo_finals_random_entry": twins,
             "placebos_beaten": sum(1 for t in twins if final > t),
             "beats_champion": final > champions[name],
             "beats_spy_computed": final > buyhold_open(bars, idx),
             "beats_family_prior_best": final > prior_best[name],
             "period_distribution": period_distribution(curve),
             "equity_curve": curve}
        out["roads"][name] = r
        print(name, "MY", r["final"], "DD", r["max_dd_pct"], "costs", r["costs"],
              "SPYbh", r["spy_buyhold_computed"], "ctrl", ctrl["final"],
              "placebo", r["placebos_beaten"], "/20",
              "medianYr", r["period_distribution"]["median_period_pct"],
              "pos%", r["period_distribution"]["share_positive_pct"],
              "underwaterDays", r["longest_stretch_between_new_highs_days"])
    # context folds (also the frozen confirmation machinery, if ever triggered)
    folds = {}
    for y in range(2010, 2027):
        s = f"{y}-01-01"; e = f"{y}-12-31" if y < 2026 else "2026-11-20"
        idx = road_idx(bars, s, e)
        if len(idx) < 10: continue
        f, c, _ = hold_form(bars, idx, entry_pos=0)
        folds[str(y)] = {"final": round(f, 2), "costs": round(c, 2)}
    out["year_folds_context"] = folds
    print("folds", {k: v["final"] for k, v in folds.items()})
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("wrote results.json")

if __name__ == "__main__":
    main()
