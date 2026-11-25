#!/usr/bin/env python3
"""V13 BEST-RULES — F-9 Presidential cycle.
MY RULES (frozen in BEST-RULES-SPEC.md): long SPY unconditionally Oct 1 of midterm
year (Y+1) through Dec 31 of election year (Y+3); outside that window, long only
when prior close > 200-day SMA (daily gate, switch at next open). No floor.
Costs 0.10%/side + $0.01/sell. Placebos: 20 phase-shifted cycle calendars
(window mask circularly shifted, trend gate unchanged)."""
import json, os, sys, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine_shared import bars, run, spy_bh
from datetime import date

INAUG = [2009, 2013, 2017, 2021, 2025]

def in_window(d):
    for Y in INAUG:
        if date(Y + 1, 10, 1) <= d <= date(Y + 3, 12, 31):
            return True
    return False

# 200-day SMA of close, and trend-ok flag using only data up to prior bar
closes = [b["close"] for b in bars]
sma = [None] * len(bars)
s = 0.0
for i, c in enumerate(closes):
    s += c
    if i >= 200: s -= closes[i - 200]
    if i >= 199: sma[i] = s / 200
trend_ok = {}
for i, b in enumerate(bars):
    # decision for bar i uses close/SMA of bar i-1 (known before bar i opens)
    trend_ok[b["date"]] = (i >= 1 and sma[i - 1] is not None and closes[i - 1] > sma[i - 1])

window_mask = {b["date"]: in_window(date.fromisoformat(b["date"])) for b in bars}
desired = {d: (window_mask[d] or trend_ok[d]) for d in window_mask}

def shifted_desired(seed):
    dates = [b["date"] for b in bars]
    vals = [window_mask[d] for d in dates]
    n = len(vals)
    rng = random.Random(seed)
    sh = rng.randint(60, n - 60)
    rot = vals[-sh:] + vals[:-sh]
    wm = dict(zip(dates, rot))
    return {d: (wm[d] or trend_ok[d]) for d in dates}

WINDOWS = [("LONG", "2010-01-01", "2026-11-20"), ("CONT", "2019-01-01", "2026-11-20"),
           ("VAL", "2023-01-01", "2026-11-20"), ("DECADE", "2016-11-21", "2026-11-20")]

def distribution(curve, folds):
    yrs = sorted(folds)
    vals = [folds[y] for y in yrs]
    sv = sorted(vals)
    med = sv[len(sv) // 2] if len(sv) % 2 else (sv[len(sv)//2 - 1] + sv[len(sv)//2]) / 2
    pos = sum(1 for v in vals if v > 100.0)
    # longest losing streak of calendar years (final < 100)
    streak = cur = 0
    for v in vals:
        cur = cur + 1 if v < 100.0 else 0
        streak = max(streak, cur)
    # longest stretch between new highs on the LONG curve (trading days)
    peak = -1; last_high = 0; longest = 0
    for i, (_, e) in enumerate(curve):
        if e >= peak:
            peak = e; longest = max(longest, i - last_high); last_high = i
    longest = max(longest, len(curve) - 1 - last_high)
    return {"median_year_final": round(med, 2), "years": len(vals),
            "share_years_positive_pct": round(pos / len(vals) * 100, 1),
            "best_year": [yrs[vals.index(max(vals))], round(max(vals), 2)],
            "worst_year": [yrs[vals.index(min(vals))], round(min(vals), 2)],
            "longest_losing_year_streak": streak,
            "longest_days_between_new_highs_long_road": longest}

res = {"family": "folklore-f9-presidential", "program": "v13-best-rules",
       "rule": "unconditional Oct(Y+1)-Dec(Y+3) window; 200d trend gate outside; no floor",
       "windows": {}}
for w, s, e in WINDOWS:
    r = run(bars, desired, s, e)
    sp = spy_bh(bars, s, e)
    res["windows"][w] = {"strategy": r, "spy_final": sp["final"], "spy_max_dd_pct": sp["max_dd_pct"]}

# year folds on LONG span
folds = {}
for y in range(2010, 2027):
    s = f"{y}-01-01"; e = f"{y}-12-31" if y < 2026 else "2026-11-20"
    folds[str(y)] = run(bars, desired, s, e)["final"]
res["year_folds"] = folds
res["distribution"] = distribution(res["windows"]["LONG"]["strategy"]["curve"], folds)

# placebos: phase-shifted cycle calendars, LONG + DECADE
for road, s, e in [("LONG", "2010-01-01", "2026-11-20"), ("DECADE", "2016-11-21", "2026-11-20")]:
    finals = []
    for seed in range(1, 21):
        des = shifted_desired(seed)
        finals.append(run(bars, des, s, e)["final"])
    sf = sorted(finals)
    res[f"placebos_{road.lower()}"] = {"finals": finals, "median": sf[len(sf)//2],
                                       "p90": sf[int(len(sf)*0.9)-1], "max": max(finals),
                                       "true_final": res["windows"][road]["strategy"]["final"],
                                       "true_beats": sum(1 for f in finals if res["windows"][road]["strategy"]["final"] > f)}

json.dump(res, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.json"), "w"), indent=1)
for w, v in res["windows"].items():
    st = v["strategy"]
    print(w, "final", st["final"], "DD", st["max_dd_pct"], "in-mkt%", st["time_in_market_pct"],
          "orders", st["orders"], "costs", st["costs"], "| SPY", v["spy_final"], v["spy_max_dd_pct"])
print("dist", res["distribution"])
for road in ("long", "decade"):
    p = res[f"placebos_{road}"]
    print("placebo", road, "median", p["median"], "max", p["max"], "true", p["true_final"], "beats", p["true_beats"], "/20")
