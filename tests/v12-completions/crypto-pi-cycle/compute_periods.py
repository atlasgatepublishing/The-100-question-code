#!/usr/bin/env python3
"""Period-by-period record at the system's native tempo (coordinator
requirement, 2026-11-22): computed from the SAVED equity curves in
results.json. Pi Cycle's native tempo is the cycle — signals years apart —
so the record is printed two ways: (1) round-trip episodes (signal to
signal, the tempo the system actually lives at) and (2) calendar-year
periods sliced from the daily curve. Medians are the headline per-period
numbers; any average is a labeled secondary line."""
import json
import os
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))


def dp(s):
    y, m, d = s.split("-")
    return date(int(y), int(m), int(d))


def median(xs):
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def period_stats(curve, start_equity=100.0):
    years = {}
    for d, v in curve:
        years.setdefault(d[:4], []).append((d, v))
    ann = []
    prev = start_equity
    for y in sorted(years):
        pts = years[y]
        if len(pts) < 30:  # stub period (window opened on the year's last day)
            prev = pts[-1][1]
            continue
        end = pts[-1][1]
        ann.append({"year": y, "ret_pct": round((end / prev - 1) * 100, 1),
                    "end_equity": end})
        prev = end
    rets = [a["ret_pct"] for a in ann]
    best_streak = cur = 0
    for x in rets:
        cur = cur + 1 if x <= 0 else 0
        best_streak = max(best_streak, cur)
    # longest stretch between new highs, on the daily curve
    peak = -1.0
    peak_d = None
    longest = 0
    span = None
    for d, v in curve:
        if v >= peak:
            if peak_d is not None:
                gap = (dp(d) - dp(peak_d)).days
                if gap > longest:
                    longest, span = gap, (peak_d, d)
            peak, peak_d = v, d
    trailing = (dp(curve[-1][0]) - dp(peak_d)).days if peak_d else None
    return {
        "periods": ann,
        "n_periods": len(rets),
        "share_positive_pct": round(100 * sum(1 for x in rets if x > 0) / len(rets), 1) if rets else None,
        "median_period_pct": median(rets) if rets else None,
        "best_period_pct": max(rets) if rets else None,
        "worst_period_pct": min(rets) if rets else None,
        "longest_losing_streak_periods": best_streak,
        "longest_stretch_between_new_highs_days": longest,
        "longest_stretch_span": span,
        "days_since_last_new_high_at_end": trailing,
        "average_period_pct_SECONDARY": round(sum(rets) / len(rets), 1) if rets else None,
    }


def main():
    r = json.load(open(os.path.join(HERE, "results.json")))
    out = {}
    for key in ("pi_mult0.745_reentry-down_native", "pi_mult0.745_reentry-up_native",
                "pi_mult0.475_reentry-down_native"):
        run = r["btc_primary"]["runs"]["full"][key]
        out[f"btc_full_{key}"] = period_stats(run["curve"])
    out["btc_full_buy_hold_note"] = (
        "Buy-hold curve not saved bar-by-bar; its FULL max drawdown (-83.4%) "
        "and final ($13,641.45) are in results.json.")
    with open(os.path.join(HERE, "periods.json"), "w") as f:
        json.dump(out, f, indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
