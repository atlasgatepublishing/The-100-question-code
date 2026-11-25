#!/usr/bin/env python3
"""v13 BEST RULES — hunt-cbbi DIAL form (BEST-RULES-SPEC.md, frozen before run).
Target exposure = clamp((100 - CBBI)/100, 0, 1); weekly rebalance (every 7th
step, first day included); turnover charged 0.60% on |dExposure| x equity;
signal at close t earns t->t+1; no floor; final exposure liquidated at 0.60%.
Series: v12 frozen cbbi_series.json (read-only shared input).
Placebos: 20 seeds, daily scores permuted within window (timing destroyed).
Labels: CONSTRUCTED-RECONSTRUCTION / CALIBRATION-LOOKAHEAD / NO-VINTAGE-ARCHIVE."""
import json, os, random, statistics

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/hunt-cbbi/cbbi_series.json")
COST = 0.006
END = "2026-11-20"
START = 100.0

def max_dd(curve):
    peak = -1e18; dd = 0.0
    for _, eq in curve:
        peak = max(peak, eq)
        if peak > 0: dd = max(dd, (peak - eq) / peak)
    return round(-dd * 100, 2)

def period_stats(curve):
    months = {}
    for d, eq in curve: months[d[:7]] = eq
    ks = sorted(months); rets = []; prev = START
    for k in ks:
        rets.append(months[k] / prev - 1 if prev > 0 else 0.0); prev = months[k]
    if not rets: return {}
    pos = sum(1 for r in rets if r > 0)
    streak = worst = 0
    for r in rets:
        streak = streak + 1 if r < 0 else 0; worst = max(worst, streak)
    vals = [START] + [months[k] for k in ks]
    peak = vals[0]; since = longest = 0
    for v in vals:
        if v >= peak: peak = v; since = 0
        else: since += 1; longest = max(longest, since)
    return {"tempo": "monthly", "n_periods": len(rets),
            "share_positive_pct": round(pos / len(rets) * 100, 1),
            "median_pct": round(statistics.median(rets) * 100, 3),
            "best_pct": round(max(rets) * 100, 3), "worst_pct": round(min(rets) * 100, 3),
            "longest_losing_streak": worst, "longest_between_highs_periods": longest,
            "average_pct_secondary": round(statistics.mean(rets) * 100, 3)}

def dial(dates, prices, score, start, end):
    idx = [i for i, d in enumerate(dates) if start <= d <= end]
    eq = START; expo = 0.0; curve = []; rebalances = 0; turnover = 0.0; expo_days = []
    last_target = 0.0
    for k, i in enumerate(idx):
        if k > 0: eq *= (1 + expo * (prices[i] / prices[idx[k-1]] - 1))
        if score[i] is not None:
            last_target = min(1.0, max(0.0, (100.0 - score[i]) / 100.0))
        if k % 7 == 0:
            d = abs(last_target - expo)
            if d > 1e-9:
                eq *= (1 - COST * d); turnover += d; rebalances += 1; expo = last_target
        expo_days.append(expo)
        curve.append((dates[i], round(eq, 4)))
    if expo > 0:  # final liquidation
        eq *= (1 - COST * expo); curve[-1] = (curve[-1][0], round(eq, 4))
    return {"final": round(eq, 2), "curve": curve, "rebalances": rebalances,
            "turnover_total": round(turnover, 3),
            "avg_exposure": round(statistics.mean(expo_days), 4) if expo_days else 0.0,
            "maxdd_pct": max_dd(curve), "periods_monthly": period_stats(curve)}

def bh(dates, prices, start, end):
    idx = [i for i, d in enumerate(dates) if start <= d <= end]
    fin = 100 * (1 - COST) * prices[idx[-1]] / prices[idx[0]] * (1 - COST)
    curve = [(dates[i], round(100 * (1 - COST) * prices[i] / prices[idx[0]], 4)) for i in idx]
    curve[-1] = (curve[-1][0], round(fin, 4))
    return {"final": round(fin, 2), "curve": curve, "maxdd_pct": max_dd(curve),
            "periods_monthly": period_stats(curve)}

def main():
    blob = json.load(open(SRC))
    series = blob["series"]
    dates = [d for d in sorted(series) if d <= END]
    prices = [series[d]["price"] for d in dates]
    score = [series[d]["cbbi"] for d in dates]
    first = next(d for d in dates if series[d]["cbbi"] is not None)
    res = {"family": "hunt-cbbi", "form": "v13-dial-weekly-nofloor",
           "commit": blob["commit"], "availability": blob["availability"],
           "first_score": first,
           "labels": "CONSTRUCTED-RECONSTRUCTION / CALIBRATION-LOOKAHEAD / NO-VINTAGE-ARCHIVE",
           "published_best_v12": {"VALIDATION": 308.45, "POSTLAUNCH": 264.84, "FULL_fenced": 574230.23}}
    windows = {"FULL": (first, END), "VALIDATION": ("2023-01-01", END),
               "POSTLAUNCH": ("2022-01-01", END), "DESIGN": (first, "2022-12-31")}
    curves = {}
    for wname, (s, e) in windows.items():
        d = dial(dates, prices, score, s, e)
        b = bh(dates, prices, s, e)
        res[wname] = {"dial_final": d["final"], "buyhold_final": b["final"],
                      "dial_maxdd_pct": d["maxdd_pct"], "buyhold_maxdd_pct": b["maxdd_pct"],
                      "rebalances": d["rebalances"], "turnover_total": d["turnover_total"],
                      "avg_exposure": d["avg_exposure"],
                      "periods_monthly_dial": d["periods_monthly"],
                      "periods_monthly_buyhold": b["periods_monthly"]}
        curves[wname] = {"dial": d["curve"], "buyhold": b["curve"]}
    res["curves"] = curves
    s, e = windows["VALIDATION"]
    vidx = [i for i, dd in enumerate(dates) if s <= dd <= e]
    vscore = [score[i] for i in vidx]
    finals = []
    for seed in range(1, 21):
        rng = random.Random(seed * 31)
        sh = vscore[:]; rng.shuffle(sh)
        sc = score[:]
        for j, i in enumerate(vidx): sc[i] = sh[j]
        finals.append(dial(dates, prices, sc, s, e)["final"])
    res["placebos_VALIDATION_shuffled_score"] = {
        "median": round(statistics.median(finals), 2),
        "n_beaten_by_dial": sum(1 for f in finals if res["VALIDATION"]["dial_final"] > f),
        "finals": finals}
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    for w in windows:
        r = res[w]
        print(w, "dial", r["dial_final"], "dd", r["dial_maxdd_pct"], "| bh", r["buyhold_final"],
              "dd", r["buyhold_maxdd_pct"], "| rebal", r["rebalances"], "avgExpo", r["avg_exposure"])
    print("placebos VAL median", res["placebos_VALIDATION_shuffled_score"]["median"],
          "beaten", res["placebos_VALIDATION_shuffled_score"]["n_beaten_by_dial"], "/20")

if __name__ == "__main__": main()
