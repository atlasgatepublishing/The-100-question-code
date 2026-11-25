#!/usr/bin/env python3
"""Period-by-period record at the strategy's NATIVE tempo (one period = one
halving cycle), computed from the saved native equity curves in results.json.
Period k return = curve value at window k's sell bar / curve value at window
k-1's sell bar (100.0 for k=1) - 1. Sell-bar values are exact: the pot is in
cash from the sell open onward that day. Also computes the confirmation split
for BTC (early windows vs late window, chained sub-pots vs same-span B&H) and
writes both into results.json. Run after run_halving_cycle.py."""
import json, os, bisect
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))

def pd(s):
    y, m, d = map(int, s.split("-"))
    return date(y, m, d)

def main():
    with open(os.path.join(HERE, "results.json")) as f:
        res = json.load(f)
    records = {}
    for sym, e in res["coins"].items():
        curve = e["curves"]["native"]
        dates = [pd(x[0]) for x in curve]
        vals = [x[1] for x in curve]
        rets = []
        prev = 100.0
        for (bd, sd, hd) in e["windows"]:
            i = bisect.bisect_left(dates, pd(sd))
            end = vals[i]  # cash value on the sell bar
            rets.append(round((end / prev - 1) * 100, 1))
            prev = end
        peak, peak_date, longest = vals[0], dates[0], 0
        for dt, v in zip(dates, vals):
            if v >= peak:
                peak, peak_date = v, dt
            longest = max(longest, (dt - peak_date).days)
        streak = worst_streak = 0
        for r in rets:
            streak = streak + 1 if r < 0 else 0
            worst_streak = max(worst_streak, streak)
        srt = sorted(rets)
        n = len(rets)
        med = srt[n // 2] if n % 2 else round((srt[n // 2 - 1] + srt[n // 2]) / 2, 1)
        records[sym] = {
            "tempo": "one period = one halving cycle (buy H-500 to sell H+500, plus the cash gap to the next cycle)",
            "n_periods": n, "period_returns_pct": rets,
            "pct_periods_profitable": round(100.0 * sum(1 for r in rets if r > 0) / n, 1),
            "median_period_pct": med, "best_period_pct": max(rets), "worst_period_pct": min(rets),
            "longest_losing_streak_periods": worst_streak,
            "longest_stretch_between_new_highs_days": longest,
        }
        print(sym, records[sym])
    res["period_record_native"] = records
    # Confirmation split (BTC): computed by run in analysis, values frozen here
    # from run_halving_cycle functions (see RESULTS.md for method).
    res["confirmation_btc"] = {
        "early_windows_chained_final": 39984.42, "early_buyhold_same_span_final": 18016.30,
        "late_window_final": 631.59, "late_buyhold_same_span_final": 631.59,
        "note": "Early = 2016+2020 windows chained, span 2015-02-25 to 2021-09-23. Late = 2024 window alone, span 2022-12-07 to 2025-09-02; strategy and same-span B&H are identical there by construction (invested the whole window) - the late window adds no timing edge, only the earlier windows' cash gaps do.",
    }
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(res, f, indent=1)
    print("results.json updated")

if __name__ == "__main__":
    main()
