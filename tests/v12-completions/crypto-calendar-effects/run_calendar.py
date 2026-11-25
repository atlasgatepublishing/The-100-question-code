#!/usr/bin/env python3
"""crypto-calendar-effects v12 — CONSTRUCTED calendar systems, per coin.
Spec frozen in CONSTRUCTION-SPEC.md before this run. Shared data read-only."""
import json, glob, os, math, random, statistics
from datetime import date

DATA = os.path.expanduser("~/workspace/stock-app/backtests/v4/crypto-basket-pit-data")
OUT = os.path.dirname(os.path.abspath(__file__))
COST = 0.006
POT = 100.0
END = "2026-11-20"
STABLE = {"USDT","USDC","DAI","BUSD","WBTC","USTC"}
WINDOWS = {"FULL": (None, END), "DESIGN": ("2017-01-01","2022-12-31"),
           "VALIDATION": ("2023-01-01", END)}

def load_series():
    out = {}
    for f in sorted(glob.glob(os.path.join(DATA, "y_*-USD.json"))):
        sym = os.path.basename(f)[2:-9]
        try: bars = json.load(open(f))
        except Exception: bars = []
        bars = [b for b in bars if b.get("c") and b.get("o") and b["c"] > 0 and b["o"] > 0]
        bars.sort(key=lambda b: b["d"])
        out[sym] = bars
    return out

def wd(datestr):
    y,m,d = map(int, datestr.split("-"))
    return date(y,m,d).weekday()  # Mon=0 .. Sun=6

def max_dd(curve):
    peak, dd = -1, 0.0
    for v in curve:
        peak = max(peak, v)
        if peak > 0: dd = min(dd, v/peak - 1)
    return dd

def period_stats(curve):
    """Period-by-period record at the system's native tempo (one round trip
    = one period, weekly here), computed from the equity curve."""
    vals = [v for _, v in curve]
    rets = [vals[i]/vals[i-1] - 1 for i in range(1, len(vals)) if vals[i-1] > 0]
    if not rets: return None
    wins = sum(1 for r in rets if r > 0)
    # longest losing streak
    streak = longest = 0
    for r in rets:
        streak = streak + 1 if r <= 0 else 0
        longest = max(longest, streak)
    # longest stretch (in periods) between new highs
    peak = vals[0]; since_high = 0; longest_gap = 0
    for v in vals[1:]:
        if v > peak: peak = v; since_high = 0
        else:
            since_high += 1; longest_gap = max(longest_gap, since_high)
    return {"periods": len(rets), "pct_periods_profitable": round(wins/len(rets)*100, 1),
            "median_period_pct": round(statistics.median(rets)*100, 3),
            "mean_period_pct_secondary": round(statistics.mean(rets)*100, 3),
            "best_period_pct": round(max(rets)*100, 2), "worst_period_pct": round(min(rets)*100, 2),
            "longest_losing_streak_periods": longest,
            "longest_stretch_between_new_highs_periods": longest_gap}

def simulate(bars, system, floor, label=None, wds=None):
    """Clean event simulation. label: None=native weekday; int=placebo weekday/window-start."""
    eq = POT; curve = [(bars[0]["d"], eq)]; trades = 0; cost_paid = 0.0
    n = len(bars)
    if wds is None: wds = [wd(b["d"]) for b in bars]
    pos = None  # (entry_price, entry_date)
    def buy(price):
        nonlocal eq, trades, cost_paid
        c = eq * COST; cost_paid += c; eq -= c; trades += 1
        return price
    def sell(price, entry):
        nonlocal eq, trades, cost_paid
        eq *= price / entry
        c = eq * COST; cost_paid += c; eq -= c; trades += 1
    i = 0
    while i < n:
        b = bars[i]; w = wds[i]
        if system == "MON":
            target = 0 if label is None else label
            if w == target:
                e = buy(b["o"]); sell(b["c"], e)
                curve.append((b["d"], eq))
                if floor and eq <= 85.0: break
        else:  # WKD: window = 2 consecutive days starting weekday s (native s=5 Sat)
            s = 5 if label is None else label
            # entry at close of day before window start; find that day
            if w == (s - 1) % 7:
                # need bars i (entry close), i+2 open as exit (open of day after window)
                if i + 2 < n:
                    e = buy(b["c"]); exitbar = bars[i+2]
                    # floor check on holding days' closes
                    sell(exitbar["o"], e)
                    curve.append((exitbar["d"], eq))
                    if floor and eq <= 85.0: break
                    i += 2
        i += 1
    return eq, curve, trades, round(cost_paid, 2)

def buyhold(bars):
    if len(bars) < 2: return None
    eq = POT * (1-COST) * (bars[-1]["c"] / bars[0]["o"]) * (1-COST)
    curve = [(b["d"], POT*(1-COST)*(b["c"]/bars[0]["o"])) for b in bars]
    return eq, curve

def window_bars(bars, wname):
    lo, hi = WINDOWS[wname]
    wb = [b for b in bars if b["d"] <= hi and (lo is None or b["d"] >= lo)]
    return wb

def main():
    series = load_series()
    results = {"family": "crypto-calendar-effects (CONSTRUCTED)", "cost_per_side": COST,
               "pot": POT, "bar_convention": "UTC calendar days; weekday = UTC weekday of bar date",
               "coins": {}, "closures": []}
    btc = series.get("BTC", [])
    for sym, bars in sorted(series.items()):
        if len(bars) < 750:
            results["closures"].append({"coin": sym, "bars": len(bars),
                "reason": f"insufficient honest history: {len(bars)} bars < 750 SUFFICIENT-HISTORY rule"})
            continue
        coin = {"bars": len(bars), "first": bars[0]["d"], "last": bars[-1]["d"],
                "stable_flag": sym in STABLE, "windows": {}, "weekday_means_gross": {}}
        # measurement annex: weekday means, FULL
        by_wd = {k: [] for k in range(7)}
        for j in range(1, len(bars)):
            by_wd[wd(bars[j]["d"])].append(bars[j]["c"]/bars[j-1]["c"] - 1)
        coin["weekday_means_gross"] = {["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][k]:
            (round(statistics.mean(v)*100, 3) if v else None) for k, v in by_wd.items()}
        wknd = by_wd[5]+by_wd[6]; wkdy = sum((by_wd[k] for k in range(5)), [])
        coin["weekend_vs_weekday_gross_pct"] = {
            "weekend_mean": round(statistics.mean(wknd)*100, 3),
            "weekday_mean": round(statistics.mean(wkdy)*100, 3)}
        for wname in WINDOWS:
            wb = window_bars(bars, wname)
            if len(wb) < 100:
                coin["windows"][wname] = None; continue
            btc_wb = window_bars(btc, wname)
            # for FULL, BTC bar = same calendar span as coin
            if wname == "FULL":
                btc_wb = [b for b in btc if wb[0]["d"] <= b["d"] <= wb[-1]["d"]]
            wb_wds = [wd(b["d"]) for b in wb]
            bh = buyhold(wb); btc_bh = buyhold(btc_wb)
            w = {"bars": len(wb), "coin_buyhold": round(bh[0], 2),
                 "coin_buyhold_maxdd_pct": round(max_dd([v for _, v in bh[1]])*100, 1),
                 "btc_buyhold_same_window": round(btc_bh[0], 2), "systems": {}}
            for system in ("MON", "WKD"):
                for ruleset, floor in (("NATIVE", False), ("V9", True)):
                    fin, curve, trades, cp = simulate(wb, system, floor, wds=wb_wds)
                    w["systems"][f"{system}_{ruleset}"] = {
                        "final": round(fin, 2), "trades": trades, "costs_paid": cp,
                        "maxdd_pct": round(max_dd([v for _, v in curve])*100, 1),
                        "period_stats_native_tempo": period_stats(curve),
                        "curve": [[d, round(v, 2)] for d, v in curve]}
            # placebos, FULL + VALIDATION only, NATIVE
            if wname in ("FULL", "VALIDATION"):
                for system in ("MON", "WKD"):
                    finals = []
                    for seed in range(20):
                        rng = random.Random(1000 + seed)
                        if system == "MON":
                            lab = rng.choice([1,2,3,4,5,6])  # any non-Monday weekday
                        else:
                            lab = rng.choice([0,1,2,3,4,6])  # any non-Sat window start
                        fin, _, _, _ = simulate(wb, system, False, label=lab, wds=wb_wds)
                        finals.append(fin)
                    sysfin = w["systems"][f"{system}_NATIVE"]["final"]
                    pct = sum(1 for f in finals if f < sysfin) / len(finals) * 100
                    w["systems"][f"{system}_NATIVE"]["placebo"] = {
                        "median": round(statistics.median(finals), 2),
                        "min": round(min(finals), 2), "max": round(max(finals), 2),
                        "system_percentile": round(pct, 1)}
            coin["windows"][wname] = w
        results["coins"][sym] = coin
    with open(os.path.join(OUT, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    # pooled summary printed for RESULTS.md
    for wname in WINDOWS:
        for syskey in ("MON_NATIVE","MON_V9","WKD_NATIVE","WKD_V9"):
            vals, bhs, btcs = [], [], []
            for sym, c in results["coins"].items():
                if c["stable_flag"]: continue
                w = c["windows"].get(wname)
                if not w: continue
                vals.append(w["systems"][syskey]["final"]); bhs.append(w["coin_buyhold"]); btcs.append(w["btc_buyhold_same_window"])
            if vals:
                print(wname, syskey, "n=", len(vals), "median $", round(statistics.median(vals),2),
                      "| coins>100:", sum(1 for v in vals if v>100), "| median coinBH $", round(statistics.median(bhs),2),
                      "| median BTC BH $", round(statistics.median(btcs),2))
    b = results["coins"].get("BTC")
    if b:
        for wname in WINDOWS:
            w = b["windows"].get(wname)
            if w: print("BTC", wname, "BH $", w["coin_buyhold"],
                         {k: v["final"] for k, v in w["systems"].items()},
                         {k: v.get("placebo") for k, v in w["systems"].items() if "placebo" in v})
        print("BTC weekday means", b["weekday_means_gross"], b["weekend_vs_weekday_gross_pct"])
    print("closures:", [(c["coin"], c["bars"]) for c in results["closures"]])

if __name__ == "__main__":
    main()
