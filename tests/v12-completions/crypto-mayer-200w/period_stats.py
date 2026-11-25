#!/usr/bin/env python3
"""Period-by-period record at the family's native tempo (WEEKLY — the 200WMA
is a weekly gauge and Mayer is practitioner-checked weekly), computed from the
saved equity curves in results.json. Appends 'period_stats_weekly' per form."""
import json, os, statistics

HERE = os.path.dirname(os.path.abspath(__file__))

def period_stats(curve):
    # curve[0] is equity after day 1; prepend the $100 start as period anchor.
    pts = [100.0] + list(curve)
    rets = []
    for i in range(7, len(pts), 7):
        if pts[i - 7] <= 0:
            rets.append(0.0)   # pot already at zero (dead coin); stays zero
        else:
            rets.append(pts[i] / pts[i - 7] - 1.0)
    if not rets:
        return None
    # period-end equity series for high-water stats
    ends = [pts[i] for i in range(7, len(pts), 7)]
    longest_loss = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0
        longest_loss = max(longest_loss, cur)
    peak = 100.0; since_high = 0; longest_between = 0
    for e in ends:
        if e > peak:
            peak = e; since_high = 0
        else:
            since_high += 1
            longest_between = max(longest_between, since_high)
    return {
        "periods": len(rets),
        "pct_periods_profitable": round(100.0 * sum(1 for r in rets if r > 0) / len(rets), 1),
        "median_period_pct": round(statistics.median(rets) * 100, 2),
        "best_period_pct": round(max(rets) * 100, 1),
        "worst_period_pct": round(min(rets) * 100, 1),
        "longest_losing_streak_periods": longest_loss,
        "longest_stretch_between_new_highs_periods": longest_between,
        "average_period_pct_secondary": round(statistics.mean(rets) * 100, 2),
    }

def main():
    with open(os.path.join(HERE, "results.json")) as f:
        res = json.load(f)
    for sym, coin in res["coins"].items():
        for form, fd in coin["forms"].items():
            fd["period_stats_weekly"] = {
                "native": period_stats(fd["curves"]["native"]),
                "v9_house": period_stats(fd["curves"]["v9_house"]),
                "coin_hold": period_stats(fd["curves"]["coin_hold"]),
            }
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(res, f)
    # print BTC detail + medians across coins for RESULTS.md
    for form in ("W_200wma", "M_mayer24"):
        fd = res["coins"]["BTC"]["forms"][form]
        print(form, "BTC native weekly:", json.dumps(fd["period_stats_weekly"]["native"]))
        print(form, "BTC v9 weekly:    ", json.dumps(fd["period_stats_weekly"]["v9_house"]))
        print(form, "BTC hold weekly:  ", json.dumps(fd["period_stats_weekly"]["coin_hold"]))
    import collections
    for form in ("W_200wma", "M_mayer24"):
        med_nat = statistics.median(c["forms"][form]["period_stats_weekly"]["native"]["median_period_pct"] for c in res["coins"].values())
        med_pos = statistics.median(c["forms"][form]["period_stats_weekly"]["native"]["pct_periods_profitable"] for c in res["coins"].values())
        print(form, "cross-coin median of median-week %:", round(med_nat, 2), "| median % profitable weeks:", med_pos)

if __name__ == "__main__":
    main()
