#!/usr/bin/env python3
"""v13 BEST RULES — hunt-reserve-risk RR-DIAL (BEST-RULES-SPEC.md, frozen before run).
Log dial between published Glassnode anchors 0.0026 (full) and 0.0200 (out);
weekly rebalance check (every 7th step); 0.10 rebalance band; 0.60%/side on
traded notional; signal at close t earns t->t+1; NO floor; final liquidation
at 0.60%. Data: v12 cache (read-only) — BGeometrics reserve-risk + CoinMetrics
PriceUSD aligned by date. Placebos: 20 seeds, both anchors x U[0.75,1.33].
Labels: NO PUBLISHED VINTAGE POLICY (provider-constructed CDD/HODL Bank)."""
import json, os, random, statistics, math

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/hunt-reserve-risk/data")
COST = 0.006
START = 100.0
LO, HI = 0.0026, 0.0200

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

def target(rr, lo=LO, hi=HI):
    if rr <= lo: return 1.0
    if rr >= hi: return 0.0
    return 1.0 - math.log(rr / lo) / math.log(hi / lo)

def dial(dates, prices, sig, start, end, lo=LO, hi=HI):
    idx = [i for i, d in enumerate(dates) if start <= d <= end]
    eq = START; expo = 0.0; curve = []; rebalances = 0; turnover = 0.0; expo_days = []
    for k, i in enumerate(idx):
        if k > 0: eq *= (1 + expo * (prices[i] / prices[idx[k-1]] - 1))
        if k % 7 == 0:
            t = target(sig[i], lo, hi)
            d = abs(t - expo)
            if d >= 0.10:
                eq *= (1 - COST * d); turnover += d; rebalances += 1; expo = t
        expo_days.append(expo)
        curve.append((dates[i], round(eq, 4)))
    if expo > 0:
        eq *= (1 - COST * expo); curve[-1] = (curve[-1][0], round(eq, 4))
    return {"final": round(eq, 2), "curve": curve, "rebalances": rebalances,
            "turnover_total": round(turnover, 3),
            "avg_exposure": round(statistics.mean(expo_days), 4) if expo_days else 0.0,
            "min_exposure": round(min(expo_days), 4) if expo_days else 0.0,
            "maxdd_pct": max_dd(curve), "periods_monthly": period_stats(curve)}

def bh(dates, prices, start, end):
    idx = [i for i, d in enumerate(dates) if start <= d <= end]
    fin = 100 * (1 - COST) * prices[idx[-1]] / prices[idx[0]] * (1 - COST)
    curve = [(dates[i], round(100 * (1 - COST) * prices[i] / prices[idx[0]], 4)) for i in idx]
    curve[-1] = (curve[-1][0], round(fin, 4))
    return {"final": round(fin, 2), "curve": curve, "maxdd_pct": max_dd(curve),
            "periods_monthly": period_stats(curve)}

def main():
    rr = {r["d"]: float(r["reserveRisk"]) for r in json.load(open(f"{SRC}/bgeo_reserve_risk.json"))}
    cm = {r["time"][:10]: float(r["PriceUSD"]) for r in json.load(open(f"{SRC}/cm_btc.json"))}
    dates = sorted(d for d in rr if d in cm and cm[d] > 0)
    prices = [cm[d] for d in dates]; sig = [rr[d] for d in dates]
    END = dates[-1]
    res = {"family": "hunt-reserve-risk", "form": "v13-rr-dial-weekly-nofloor",
           "labels": "NO PUBLISHED VINTAGE POLICY / provider-constructed CDD-HODL Bank",
           "signal_range_window": [min(sig), max(sig)],
           "published_best_v12": {"FULL-TRUNC_open_position": 369.52},
           "roads": {}, "curves": {}}
    windows = {"FULL-TRUNC": (dates[0], END), "CONFIRM": ("2023-01-01", END)}
    for wname, (s, e) in windows.items():
        d = dial(dates, prices, sig, s, e); b = bh(dates, prices, s, e)
        res["roads"][wname] = {"window": [s, e],
            "dial_final": d["final"], "buyhold_final": b["final"],
            "dial_maxdd_pct": d["maxdd_pct"], "buyhold_maxdd_pct": b["maxdd_pct"],
            "rebalances": d["rebalances"], "turnover_total": d["turnover_total"],
            "avg_exposure": d["avg_exposure"], "min_exposure": d["min_exposure"],
            "periods_monthly_dial": d["periods_monthly"],
            "periods_monthly_buyhold": b["periods_monthly"]}
        res["curves"][wname] = {"dial": d["curve"], "buyhold": b["curve"]}
        finals = []
        for seed in range(1, 21):
            rng = random.Random(seed)
            f = rng.uniform(0.75, 1.33)
            finals.append(dial(dates, prices, sig, s, e, LO * f, HI * f)["final"])
        res["roads"][wname]["placebos_shifted_anchors"] = {
            "median": round(statistics.median(finals), 2),
            "n_beaten_by_dial": sum(1 for x in finals if d["final"] > x), "finals": finals}
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    for w, r in res["roads"].items():
        print(w, r["window"], "dial", r["dial_final"], "dd", r["dial_maxdd_pct"],
              "| bh", r["buyhold_final"], "dd", r["buyhold_maxdd_pct"],
              "| rebal", r["rebalances"], "avgExpo", r["avg_exposure"], "minExpo", r["min_exposure"],
              "| placebo med", r["placebos_shifted_anchors"]["median"],
              "beaten", r["placebos_shifted_anchors"]["n_beaten_by_dial"], "/20")
    print("signal range", res["signal_range_window"])

if __name__ == "__main__":
    main()
