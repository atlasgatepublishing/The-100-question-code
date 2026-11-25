#!/usr/bin/env python3
"""CBBI-ACCUM — frozen construction (SPEC-FROZEN.md). CONSTRUCTED-RECONSTRUCTION.
Vendored algorithm: github.com/Zaczero/CBBI @ 31e4b869d1ecd425040885b820cb75e39a879299,
run by cbbi_driver.py -> cbbi_series.json. 8 of 9 published metrics computed
(PiCycle, RUPL, RHODL, Puell, 2YMA, Trolololo, ReserveRisk, Woobull);
MVRV-Z dropped: its _calculate raised and the code's own cbbi.info fallback
returned a 42,820-row non-daily series that cannot align — the code's
mean_horizontal averaging-over-available behavior drops it (logged).
State machine: enter long on close with CBBI <= 10; exit to cash on close
with CBBI >= 70; hold prior state between; starts in cash. Costs 0.60%/side,
price = CoinMetrics PriceUSD (as fetched by the vendored code).
NATIVE no floor; V9 = -15% plain floor (daily-close check, run stops).
Windows: FULL = first score -> 2026-11-20; VALIDATION = 2023-01-01 ->
2026-11-20 (the only verdict window per spec); POSTLAUNCH = 2022-01-01 ->
2026-11-20 (launch-era split stated here: the index launched in 2021;
2022-01-01 is the first full calendar year after launch).
Bar: BTC buy-hold net of one 0.60% buy + one 0.60% sell.
Placebos (VALIDATION): 20 seeds, buy line U[5,20], sell line U[60,85].
Labels: CONSTRUCTED-RECONSTRUCTION / CALIBRATION-LOOKAHEAD / NO-VINTAGE-ARCHIVE."""
import json, os, random, statistics, sys
sys.path.insert(0, "/tmp/hs2")
from common import period_stats, max_dd

HERE = os.path.dirname(os.path.abspath(__file__))
COST = 0.006
END = "2026-11-20"

def run_state(dates, prices, score, buy_thr, sell_thr, start, end, floor=False):
    idx = [i for i, d in enumerate(dates) if start <= d <= end]
    if not idx: return None
    eq = 100.0; curve = []; prev = 0; ep = 100.0; dead = False; trades = 0
    for k, i in enumerate(idx):
        if k > 0 and prev == 1: eq *= prices[i] / prices[idx[k-1]]
        s = score[i]
        des = prev
        if s is not None:
            if prev == 0 and s <= buy_thr: des = 1
            elif prev == 1 and s >= sell_thr: des = 0
        if dead: des = 0
        if des != prev:
            eq *= (1 - COST)
            if des == 0: trades += 1
            prev = des
        if floor and prev == 1 and eq < 0.85 * ep:
            eq *= (1 - COST); prev = 0; trades += 1; dead = True
        curve.append((dates[i], round(eq, 4)))
    if prev == 1:
        eq *= (1 - COST); curve[-1] = (curve[-1][0], round(eq, 4))
    return {"final": round(eq, 2), "curve": curve, "trades": trades}

def bh(dates, prices, start, end):
    idx = [i for i, d in enumerate(dates) if start <= d <= end]
    fin = 100 * (1 - COST) * prices[idx[-1]] / prices[idx[0]] * (1 - COST)
    curve = [(dates[i], round(100 * (1 - COST) * prices[i] / prices[idx[0]], 4)) for i in idx]
    curve[-1] = (curve[-1][0], round(fin, 4))
    return {"final": round(fin, 2), "curve": curve}

def main():
    blob = json.load(open(os.path.join(HERE, "cbbi_series.json")))
    series = blob["series"]
    dates = sorted(d for d in series if series[d]["cbbi"] is not None or True)
    dates = [d for d in sorted(series) if d <= END]
    prices = [series[d]["price"] for d in dates]
    score = [series[d]["cbbi"] for d in dates]
    first = next(d for d in dates if series[d]["cbbi"] is not None)
    res = {"family": "hunt-cbbi", "commit": blob["commit"], "availability": blob["availability"],
           "metric_columns": blob["metric_columns"], "first_score": first,
           "labels": "CONSTRUCTED-RECONSTRUCTION / CALIBRATION-LOOKAHEAD / NO-VINTAGE-ARCHIVE"}
    windows = {"FULL": (first, END), "VALIDATION": ("2023-01-01", END), "POSTLAUNCH": ("2022-01-01", END),
               "DESIGN": (first, "2022-12-31")}
    curves = {}
    for wname, (s, e) in windows.items():
        nat = run_state(dates, prices, score, 10, 70, s, e, floor=False)
        v9 = run_state(dates, prices, score, 10, 70, s, e, floor=True)
        b = bh(dates, prices, s, e)
        res[wname] = {"native_final": nat["final"], "v9_final": v9["final"], "buyhold_final": b["final"],
                      "trades": nat["trades"], "maxdd_pct": max_dd(nat["curve"]),
                      "periods_monthly_native": period_stats(nat["curve"], "monthly")}
        curves[wname] = nat["curve"]
    res["curves"] = curves
    finals = []
    s, e = windows["VALIDATION"]
    for seed in range(1, 21):
        rng = random.Random(seed * 17)
        bt, st_ = rng.uniform(5, 20), rng.uniform(60, 85)
        finals.append(run_state(dates, prices, score, bt, st_, s, e, floor=False)["final"])
    res["placebos_VALIDATION"] = {"median": round(statistics.median(finals), 2),
        "n_beaten_by_native": sum(1 for f in finals if res["VALIDATION"]["native_final"] > f), "finals": finals}
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print({w: {k: res[w][k] for k in ("native_final", "v9_final", "buyhold_final", "trades")} for w in windows})
    print("placebos VAL:", res["placebos_VALIDATION"]["median"], res["placebos_VALIDATION"]["n_beaten_by_native"])

if __name__ == "__main__": main()
