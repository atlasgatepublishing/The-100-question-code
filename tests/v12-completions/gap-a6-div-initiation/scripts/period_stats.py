#!/usr/bin/env python3
"""Period-by-period record at the strategy's native reporting tempo.
MTW's own measurement tempo is the MONTH (their drift is computed from
monthly returns, event month excluded). Periods = calendar months of the
saved daily equity curve (month-end values), DECADE window, HOLD12 and
HOLD36. Averages are emitted only as a clearly-labeled secondary line.
"""
import json, os, statistics, datetime as dt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def monthly(curve):
    ends = {}
    for d, v in curve:
        ends[d[:7]] = v  # last day in month wins (curve is date-ordered)
    months = sorted(ends)
    rets = []
    prev = 100.0
    for m in months:
        rets.append((m, ends[m] / prev - 1))
        prev = ends[m]
    return months, rets, ends

def stats(curve):
    months, rets, ends = monthly(curve)
    vals = [r for _, r in rets]
    pos = sum(1 for r in vals if r > 0)
    # longest losing streak
    streak = mx = 0
    for r in vals:
        streak = streak + 1 if r <= 0 else 0
        mx = max(mx, streak)
    # longest stretch between new highs (in months, peak-to-recovery)
    peak = -1.0; peak_m = None; longest = 0; cur = 0
    for m in months:
        if ends[m] >= peak:
            peak = ends[m]; longest = max(longest, cur); cur = 0
        else:
            cur += 1
    longest = max(longest, cur)
    return {"period": "calendar month (MTW measurement tempo)",
            "n_periods": len(vals),
            "share_positive_pct": round(100 * pos / len(vals), 1) if vals else None,
            "median_period_pct": round(statistics.median(vals) * 100, 2) if vals else None,
            "best_period": {"month": max(rets, key=lambda x: x[1])[0],
                            "pct": round(max(vals) * 100, 2)} if vals else None,
            "worst_period": {"month": min(rets, key=lambda x: x[1])[0],
                             "pct": round(min(vals) * 100, 2)} if vals else None,
            "longest_losing_streak_months": mx,
            "longest_months_between_new_highs": longest,
            "secondary_average_month_pct": round(statistics.mean(vals) * 100, 2) if vals else None}

def main():
    res = json.load(open(os.path.join(ROOT, "results.json")))
    out = {}
    for hname in ("HOLD12", "HOLD36"):
        run = res["runs"][hname]["DECADE"]["run"]
        if run and run.get("curve"):
            out[hname] = stats(run["curve"])
    json.dump(out, open(os.path.join(ROOT, "period_stats.json"), "w"), indent=1)
    print(json.dumps(out, indent=1))

if __name__ == "__main__":
    main()
