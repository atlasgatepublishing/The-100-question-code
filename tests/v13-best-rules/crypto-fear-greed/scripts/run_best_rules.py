#!/usr/bin/env python3
"""
CRYPTO-FEAR-GREED — V13 BEST-RULES RUN.
Frozen form: see ../BEST-RULES-SPEC.md (HOLD-PLUS-VETO).
Reads v12/v4 caches READ-ONLY. Writes only inside this v13 folder.

Form: start 100% BTC; target 50% while lagged F&G >= 76, else 100%.
No floor. Costs 0.60%/side. Close execution. Lag: value dated D first
traded on D+1 (signal for day t = last F&G value published < t).
Roads: FULL / DESIGN / VALIDATION (v12 exact windows) + frozen
confirmation folds A-D. Placebos: 20 circularly shifted index seeds.
"""
import csv, json, os, random
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
FAM = os.path.dirname(HERE)
ROOT = os.path.join(FAM, "..", "..")
V12 = os.path.join(ROOT, "v12-completions", "crypto-fear-greed")
V4 = os.path.join(ROOT, "v4")
POT = 100.0
COST = 0.006
TRIM = 0.50
EG = 76
WINDOWS = {"full": ("2018-02-01", "2026-11-20"),
           "design": ("2018-02-01", "2022-12-31"),
           "validation": ("2023-01-01", "2026-11-20")}
FOLDS = {"fold_a": ("2018-02-01", "2020-12-31"),
         "fold_b": ("2021-01-01", "2022-12-31"),
         "fold_c": ("2023-01-01", "2024-12-31"),
         "fold_d": ("2025-01-01", "2026-11-20")}

def load_fng():
    with open(os.path.join(V12, "data", "fng_api_full.json")) as f:
        raw = json.load(f)["data"]
    out = {}
    for x in raw:
        d = datetime.utcfromtimestamp(int(x["timestamp"])).strftime("%Y-%m-%d")
        out[d] = int(x["value"])
    return out

def load_btc():
    rows = []
    with open(os.path.join(V4, "crypto-trend-data", "BTC-USD.csv")) as f:
        for r in csv.DictReader(f):
            rows.append((r["date"], float(r["close"])))
    return rows

def signal_series(cal, fng):
    sig, last = [], None
    fi = sorted(fng.items())
    j = 0
    for d in cal:
        while j < len(fi) and fi[j][0] < d:
            last = fi[j][1]; j += 1
        sig.append(last)
    return sig

def veto_targets(sig):
    return [1.0 if (v is None or v < EG) else TRIM for v in sig]

def max_dd(curve):
    peak, mdd = -1e18, 0.0
    for v in curve:
        peak = max(peak, v); mdd = min(mdd, v / peak - 1.0)
    return mdd

def period_stats(curve, monthly_dates=None):
    rets = [curve[i] / curve[i-1] - 1.0 for i in range(1, len(curve))]
    if not rets: return {}
    srt = sorted(rets); n = len(rets)
    med = srt[n // 2] if n % 2 else 0.5 * (srt[n//2 - 1] + srt[n//2])
    longest_loss, run = 0, 0
    for r in rets:
        run = run + 1 if r < 0 else 0
        longest_loss = max(longest_loss, run)
    peak_i, longest_uw = 0, 0
    for i, v in enumerate(curve):
        if v >= curve[peak_i]: peak_i = i
        longest_uw = max(longest_uw, i - peak_i)
    st = {"periods": n, "share_positive": round(sum(1 for r in rets if r > 0) / n, 4),
          "median_period": round(med, 6), "mean_period_secondary": round(sum(rets) / n, 6),
          "best_period": round(max(rets), 6), "worst_period": round(min(rets), 6),
          "longest_losing_run": longest_loss, "longest_between_new_highs": longest_uw}
    if monthly_dates is not None:
        # month-end equity -> monthly returns
        me, last_m = [], None
        for i, d in enumerate(monthly_dates):
            if d[:7] != last_m:
                if me: me[-1] = curve[i-1] if False else me[-1]
                me.append(curve[i]); last_m = d[:7]
            else:
                me[-1] = curve[i]
        mr = [me[i] / me[i-1] - 1.0 for i in range(1, len(me))]
        if mr:
            ms = sorted(mr); m = len(mr)
            mmed = ms[m // 2] if m % 2 else 0.5 * (ms[m//2 - 1] + ms[m//2])
            run = ll = 0
            for r in mr:
                run = run + 1 if r < 0 else 0
                ll = max(ll, run)
            st["monthly"] = {"periods": m,
                             "share_positive": round(sum(1 for r in mr if r > 0) / m, 4),
                             "median_period": round(mmed, 6),
                             "best_period": round(max(mr), 6),
                             "worst_period": round(min(mr), 6),
                             "longest_losing_run_months": ll}
    return st

def simulate(dates, prices, tgts):
    cash, units = POT, 0.0
    curve, expo = [], []
    trades, turnover = 0, 0.0
    for i in range(len(dates)):
        p = prices[i]
        eq = cash + units * p
        desired = tgts[i] * eq
        cur = units * p
        delta = desired - cur
        if abs(delta) > 1e-9:
            cost = abs(delta) * COST
            units = desired / p if p > 0 else 0.0
            cash = eq - desired - cost
            trades += 1; turnover += abs(delta)
        eq = cash + units * p
        curve.append(eq)
        expo.append((units * p / eq) if eq > 0 else 0.0)
    return {"final": round(curve[-1], 2), "max_dd": round(max_dd(curve), 4),
            "trades": trades, "turnover": round(turnover, 2),
            "avg_exposure": round(sum(expo) / len(expo), 4),
            "curve": [round(v, 4) for v in curve],
            "period_stats": period_stats(curve, dates)}

def buy_hold(dates, prices):
    units = POT * (1 - COST) / prices[0]
    curve = [units * p for p in prices]
    curve[-1] = units * prices[-1] * (1 - COST)
    return {"final": round(curve[-1], 2), "max_dd": round(max_dd(curve), 4),
            "curve": [round(v, 4) for v in curve],
            "period_stats": period_stats(curve, dates)}

def main():
    fng = load_fng()
    btc = load_btc()
    cal = [d for d, _ in btc]
    ci = {d: i for i, d in enumerate(cal)}
    closes = [c for _, c in btc]
    sig = signal_series(cal, fng)
    tg = veto_targets(sig)

    out = {"form": "hold-plus-veto (target 50% while lagged F&G>=76 else 100%, no floor)",
           "cost_per_side": COST, "windows": WINDOWS, "folds": FOLDS,
           "cells": {}, "placebos": {}}

    def run_window(wmap, store):
        for wname, (ws, we) in wmap.items():
            i0, i1 = ci[ws], ci[we]
            dates = cal[i0:i1+1]; prices = closes[i0:i1+1]
            bh = buy_hold(dates, prices)
            r = simulate(dates, prices, tg[i0:i1+1])
            store[wname] = {
                "hold_plus_veto": {k: r[k] for k in ("final", "max_dd", "trades",
                                   "turnover", "avg_exposure", "period_stats")},
                "btc_hold": {"final": bh["final"], "max_dd": bh["max_dd"],
                             "period_stats": bh["period_stats"]},
                "curves": {"hold_plus_veto": r["curve"], "btc_hold": bh["curve"]},
                "dates": dates}
    roads, folds = {}, {}
    run_window(WINDOWS, roads)
    run_window(FOLDS, folds)
    out["cells"] = roads
    out["confirmation_folds"] = folds

    # placebos: circularly shifted F&G, same form, full + validation
    span_dates = [d for d in cal if WINDOWS["full"][0] <= d <= "2026-11-21"]
    span_vals, last = [], None
    for d in span_dates:
        if d in fng: last = fng[d]
        span_vals.append(last)
    N = len(span_dates)
    for wname in ("full", "validation"):
        ws, we = WINDOWS[wname]
        i0, i1 = ci[ws], ci[we]
        dates = cal[i0:i1+1]; prices = closes[i0:i1+1]
        real = roads[wname]["hold_plus_veto"]["final"]
        finals = []
        for seed in range(1, 21):
            rng = random.Random(seed)
            k = rng.randint(30, N - 30)
            shifted = {}
            for j, d in enumerate(span_dates):
                shifted[d] = span_vals[(j - k) % N]
            st = veto_targets(signal_series(cal, shifted))[i0:i1+1]
            finals.append(simulate(dates, prices, st)["final"])
        fs = sorted(finals)
        out["placebos"][wname] = {
            "real_final": real,
            "placebo_finals": [round(x, 2) for x in finals],
            "placebo_median": round(fs[10], 2), "placebo_max": round(fs[-1], 2),
            "n_placebos_ge_real": sum(1 for x in finals if x >= real)}

    with open(os.path.join(FAM, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("done")
    for src, store in (("ROAD", roads), ("FOLD", folds)):
        for k, c in store.items():
            print(src, k, "veto", c["hold_plus_veto"]["final"],
                  "dd", c["hold_plus_veto"]["max_dd"],
                  "| hold", c["btc_hold"]["final"], "dd", c["btc_hold"]["max_dd"],
                  "| trades", c["hold_plus_veto"]["trades"],
                  "avg_expo", c["hold_plus_veto"]["avg_exposure"])
    for k, p in out["placebos"].items():
        print("PLACEBO", k, "real", p["real_final"], "median", p["placebo_median"],
              "max", p["placebo_max"], "n_ge_real", p["n_placebos_ge_real"])

if __name__ == "__main__":
    main()
