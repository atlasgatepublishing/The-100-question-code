#!/usr/bin/env python3
"""Period-by-period record at the strategy's NATIVE TEMPO (monthly —
Barroso & Santa-Clara re-set the weight monthly), computed from the
saved constructed equity curves in results.json. A period is a calendar
month; its return is last-close / previous month's last-close - 1 (the
first period is measured from the $100 start). No averages are used as
headline numbers; the mean is printed only as a labeled secondary line.
"""
import json, os, statistics

HERE = os.path.dirname(os.path.abspath(__file__))

def monthly_stats(curve, start_cash=100.0):
    month_end = {}
    for d, v in curve:
        month_end[d[:7]] = v  # last close of the month wins
    months = sorted(month_end)
    rets = []
    prev = start_cash
    for m in months:
        rets.append((m, month_end[m] / prev - 1.0))
        prev = month_end[m]
    vals = [r for _, r in rets]
    # longest losing streak
    streak = longest = 0
    for r in vals:
        streak = streak + 1 if r < 0 else 0
        longest = max(longest, streak)
    # longest stretch between new highs (months, month-end closes)
    peak = start_cash
    since_high = longest_drought = 0
    for m in months:
        if month_end[m] >= peak:
            peak = month_end[m]
            since_high = 0
        else:
            since_high += 1
            longest_drought = max(longest_drought, since_high)
    best_m, best_r = max(rets, key=lambda kv: kv[1])
    worst_m, worst_r = min(rets, key=lambda kv: kv[1])
    return {"periods": len(vals),
            "pct_positive": round(100.0 * sum(1 for r in vals if r > 0) / len(vals), 1),
            "median_pct": round(statistics.median(vals) * 100, 2),
            "best": {"month": best_m, "pct": round(best_r * 100, 2)},
            "worst": {"month": worst_m, "pct": round(worst_r * 100, 2)},
            "longest_losing_streak_months": longest,
            "longest_between_new_highs_months": longest_drought,
            "mean_pct_secondary": round(sum(vals) / len(vals) * 100, 2)}

def main():
    with open(os.path.join(HERE, "results.json")) as f:
        res = json.load(f)
    out = {}
    for road, blk in res["roads"].items():
        out[road] = monthly_stats(blk["constructed_curve"])
        s = out[road]
        print(f"{road}: {s['periods']} months | positive {s['pct_positive']}% | "
              f"median {s['median_pct']:+.2f}% | best {s['best']['pct']:+.2f}% ({s['best']['month']}) | "
              f"worst {s['worst']['pct']:+.2f}% ({s['worst']['month']}) | "
              f"longest losing streak {s['longest_losing_streak_months']} mo | "
              f"longest between new highs {s['longest_between_new_highs_months']} mo | "
              f"(secondary, average month {s['mean_pct_secondary']:+.2f}%)")
    res["monthly_period_record_constructed"] = out
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(res, f, indent=1, default=str)
    print("saved into results.json")

if __name__ == "__main__":
    main()
