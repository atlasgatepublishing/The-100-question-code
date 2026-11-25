#!/usr/bin/env python3
"""CADENCE GRID (crypto timer families) — Second-Chance Protocol slice.
Usage: python3 run_cadence.py <family>
DECADE road 2016-11-21 -> 2026-11-20, intersected with each family's honest
data start (stated per family). $100 pot, native (no-floor) rule set — the
rule set of each family's primary record — crypto-realistic cost per side
(the family's own frozen cost). Cadence = signal-evaluation frequency
(v10 uniform definition): the target weight computed from the daily signal
is only ACTED ON at the first day of each cadence period; between cadence
dates the weight is held. Signal at close t applies to return t -> t+1.
Placebos: 20 seeds per cell — the target-weight series circularly shifted
by a seeded random offset (>=30 days), same cadence gating and costs.
BTC is the primary asset (each family's own primary); BTC buy-and-hold on
the same window is the bar.
"""
import csv, json, math, os, random, sys
from datetime import date, timedelta

FAMILY = sys.argv[1]
HERE = os.path.dirname(os.path.abspath(__file__))
V12 = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions")
V4 = os.path.expanduser("~/workspace/stock-app/backtests/v4")
START, END = "2016-11-21", "2026-11-20"
CONT = ("2019-01-02", "2026-11-20")
CADENCES = ["daily","weekly","biweekly","monthly","quarterly","semiannual","annual"]

def load_btc():
    rows = []
    with open(os.path.join(V4, "crypto-trend-data", "BTC-USD.csv")) as f:
        for r in csv.DictReader(f):
            rows.append((r["date"], float(r["close"])))
    rows.sort()
    return rows

def cadence_set(dates, cad):
    if cad == "daily": return set(dates)
    out, seen = set(), set()
    for d in dates:
        y, m = int(d[:4]), int(d[5:7])
        iso = date.fromisoformat(d).isocalendar()
        if cad == "weekly": k = (iso[0], iso[1])
        elif cad == "biweekly": k = (iso[0], iso[1] // 2)
        elif cad == "monthly": k = (y, m)
        elif cad == "quarterly":
            if m not in (1,4,7,10): continue
            k = (y, m)
        elif cad == "semiannual":
            if m not in (1,7): continue
            k = (y, m)
        elif cad == "annual":
            if m != 1: continue
            k = (y,)
        if k not in seen: seen.add(k); out.add(d)
    return out

def run(dates, closes, target, cad, cost):
    """target[i] = desired weight decided at close i (applies i -> i+1)."""
    ev = cadence_set(dates, cad)
    eq, w = 100.0, 0.0
    curve, costs, orders = [], 0.0, 0
    for i, d in enumerate(dates):
        if i > 0 and w:
            eq *= closes[i] / closes[i-1] if w == 1.0 else (1 + w * (closes[i]/closes[i-1] - 1))
        if d in ev and i < len(dates) - 1:
            tw = target[i]
            if tw != w:
                c = abs(tw - w) * eq * cost
                eq -= c; costs += c; orders += 1; w = tw
        curve.append((d, round(eq, 2)))
    peak, mdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0: mdd = max(mdd, (peak - v) / peak)
    return {"final": round(eq, 2), "costs": round(costs, 2), "orders": orders,
            "max_dd_pct": round(mdd * 100, 2), "curve": curve}

def period_stats(curve, cad):
    ev = sorted(cadence_set([d for d, _ in curve], cad))
    closes = dict(curve)
    pts = [(d, closes[d]) for d in ev if d in closes]
    if curve and (not pts or pts[-1][0] != curve[-1][0]): pts.append(curve[-1])
    if len(pts) < 2: return {"n_periods": 0}
    rets = [(d1, v1/v0-1) for (d0,v0),(d1,v1) in zip(pts, pts[1:]) if v0]
    n = len(rets); srt = sorted(r for _, r in rets)
    med = srt[n//2] if n % 2 else (srt[n//2-1]+srt[n//2])/2
    longest = cur = 0
    for _, r in rets:
        cur = cur+1 if r < 0 else 0; longest = max(longest, cur)
    peak, last_high, gap = -1, 0, 0
    for i, (d, v) in enumerate(pts):
        if v >= peak: peak, last_high = v, i
        gap = max(gap, i - last_high)
    return {"n_periods": n, "pct_profitable": round(100*sum(1 for _,r in rets if r>0)/n, 1),
            "median_period_pct": round(med*100, 3),
            "mean_period_pct_secondary": round(100*sum(r for _,r in rets)/n, 3),
            "best_period_pct": round(max(r for _,r in rets)*100, 2),
            "worst_period_pct": round(min(r for _,r in rets)*100, 2),
            "longest_losing_streak": longest, "longest_between_new_highs_periods": gap}

def grid(dates, closes, target, cost, native="daily", windows=((START, END),)):
    out = {}
    bh = round(100 * closes[-1] / closes[0], 2)
    for cad in CADENCES:
        r = run(dates, closes, target, cad, cost)
        pfin = []
        n = len(target)
        for seed in range(20):
            rng = random.Random(1000 + seed)
            off = rng.randrange(30, n - 30)
            shifted = target[off:] + target[:off]
            pfin.append(run(dates, closes, shifted, cad, cost)["final"])
        beaten = sum(1 for v in pfin if r["final"] > v)
        r.update({"placebo_beaten": beaten, "placebo_finals": pfin,
                  "placebo_median": sorted(pfin)[10],
                  "period_stats_at_this_cadence": period_stats(r["curve"], cad),
                  "btc_buyhold_same_window": bh})
        out[cad] = r
        print(f"{cad}: ${r['final']} DD {r['max_dd_pct']}% placebo {beaten}/20 (BH ${bh})", flush=True)
    return out

def slice_window(rows, start, end):
    return [(d, c) for d, c in rows if start <= d <= end]

# ------------------------------------------------------------- families
def fam_fear_greed():
    btc = load_btc()
    raw = json.load(open(os.path.join(V12, "crypto-fear-greed", "data", "fng_api_full.json")))["data"]
    fng = {}
    for r in raw:
        d = date.fromtimestamp(int(r["timestamp"])).isoformat()
        fng[d] = int(r["value"])
    rows = [(d, c) for d, c in btc if d in fng]
    # hysteresis target from LAGGED index (index of day t-1 decides close t)
    target, state = [], 0.0
    prev = None
    for d, c in rows:
        v = fng.get(prev) if prev else None
        if v is not None:
            if v <= 25: state = 1.0
            elif v >= 76: state = 0.0
        target.append(state)
        prev = d
    return rows, target, 0.006, "2018-02-01 (F&G index first publication; DECADE intersected)"

def fam_mayer(form):
    btc = [(d, c) for d, c in load_btc() if d >= "2015-01-01"]
    closes = [c for _, c in btc]
    target = []
    for i in range(len(closes)):
        if form == "W":
            if i + 1 < 1400: target.append(0.0)
            else:
                wma = sum(closes[i-1399:i+1]) / 1400
                target.append(1.0 if closes[i] <= wma else 0.0)
        else:
            if i + 1 < 200: target.append(0.0)
            else:
                mm = closes[i] / (sum(closes[i-199:i+1]) / 200)
                target.append(1.0 if mm < 2.4 else 0.0)
    rows = [(d, c) for (d, c) in btc if d >= "2018-10-31"]
    idx = [i for i, (d, c) in enumerate(btc) if d >= "2018-10-31"]
    return rows, [target[i] for i in idx], 0.004, "2018-10-31 (200-week warm-up complete on the family's 2015-start series, as in the primary record; DECADE intersected)"

def fam_pi():
    btc = load_btc()
    closes = [c for _, c in btc]
    def sma(i, n): return sum(closes[i-n+1:i+1]) / n if i + 1 >= n else None
    ema, k = [], 2 / 151
    for i, c in enumerate(closes):
        ema.append(c if i == 0 else c * k + ema[-1] * (1 - k))
    target, state = [], 1.0
    prev_top = prev_bot = None
    for i, (d, c) in enumerate(btc):
        s111, s350, s471 = sma(i, 111), sma(i, 350), sma(i, 471)
        if s111 and s350:
            line = 2 * s350
            cur = s111 > line
            if prev_top is not None and cur and not prev_top: state = 0.0  # top cross up -> exit
            prev_top = cur
        if s471:
            lineb = 0.745 * s471
            curb = ema[i] < lineb
            if prev_bot is not None and curb and not prev_bot: state = 1.0  # bottom cross down -> re-enter
            prev_bot = curb
        target.append(state)
    return btc, target, 0.006, "full DECADE (series from 2014-09-17; state carried into the window, as in the primary record)"

def fam_onchain():
    raw = json.load(open(os.path.join(V12, "crypto-onchain", "data", "cm_btc.json")))
    rows, target = [], []
    for r in raw:
        d = r["time"][:10]
        if r.get("PriceUSD") is None or r.get("CapMVRVCur") is None: continue
        rows.append((d, float(r["PriceUSD"])))
        target.append(0.0 if float(r["CapMVRVCur"]) >= 3.7 else 1.0)
    return rows, target, 0.006, "full DECADE (CoinMetrics BTC from 2010)"

BUILDERS = {"crypto-fear-greed": lambda: fam_fear_greed(),
            "crypto-mayer-200w-W": lambda: fam_mayer("W"),
            "crypto-mayer-200w-M": lambda: fam_mayer("M"),
            "crypto-pi-cycle": fam_pi,
            "crypto-onchain": fam_onchain}

def main():
    rows, target, cost, note = BUILDERS[FAMILY]()
    out = {"family": FAMILY, "window_requested": [START, END], "window_note": note,
           "ruleset": "native (no floor), family's frozen cost per side",
           "cost_per_side": cost, "placebo_design": "circular shift of the target-weight series, 20 seeds, same gating/costs",
           "cells": {}, "confirmation": {}}
    for (ws, we) in [(START, END)]:
        sel = [(d, c, t) for (d, c), t in zip(rows, target) if ws <= d <= we]
        dates = [d for d, _, _ in sel]; closes = [c for _, c, _ in sel]; tg = [t for _, _, t in sel]
        out["window_actual"] = [dates[0], dates[-1]]
        out["cells"] = grid(dates, closes, tg, cost)
    nat = out["cells"]["daily"]["final"]
    live = [c for c in CADENCES if c != "daily" and out["cells"][c]["final"] > nat]
    for cad in live:
        sel = [(d, c, t) for (d, c), t in zip(rows, target) if CONT[0] <= d <= CONT[1]]
        dates = [d for d, _, _ in sel]; closes = [c for _, c, _ in sel]; tg = [t for _, _, t in sel]
        conf = {}
        for cc in (cad, "daily"):
            r = run(dates, closes, tg, cc, cost)
            conf[cc] = {"final": r["final"], "max_dd_pct": r["max_dd_pct"]}
        out["confirmation"][cad] = {"window": list(CONT), "cells": conf,
                                     "beats_native_on_CONT": conf[cad]["final"] > conf["daily"]["final"]}
        print(f"CONFIRM {cad} on CONT: {conf[cad]['final']} vs daily {conf['daily']['final']}", flush=True)
    with open(os.path.join(HERE, "cadence_results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("saved cadence_results.json")

if __name__ == "__main__":
    main()
