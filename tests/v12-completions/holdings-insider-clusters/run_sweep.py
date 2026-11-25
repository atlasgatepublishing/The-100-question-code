"""Holdings-count sweep — insider-cluster: NOT-APPLICABLE determination + native-curve distribution.

The family is an event system, not a ranked top-N selection:
- Native (v11 NATIVE-SPEC): clusters fire when >=3 distinct insiders file code-P purchases
  within 30 calendar days; entry next open, hold 126 trading days; pot = slice equity/20,
  max 20 concurrent, taken in filing-completion (chronological) order; skipped clusters counted.
  No ranking score exists in Lakonishok & Lee / Seyhun / Jeng et al. / CMP.
- House (v3/v9/v10): identical chronological intake, max 4 positions, 60-day hold, -10% stop.
Changing 'count' here would only change a concurrency cap / slice divisor on a first-come
queue — it would not test 'hold top-N ranked names', which is what the sweep grid measures.
Per PROGRAM.md HOLDINGS-COUNT SWEEP: event systems get NOT-APPLICABLE with the reason.

This script therefore does NOT run the grid. It (a) records the determination, and
(b) computes the Reporting-Standard monthly per-period distribution from the SAVED
v11 native curve (slots=20) so the native count still gets its distribution treatment.
Read-only on all shared inputs.
"""
import json, os
import pandas as pd, numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
V11 = os.path.expanduser("~/workspace/stock-app/backtests/v11-native-rules/insider-cluster/results.json")

def period_distribution(curve):
    s = pd.Series({pd.Timestamp(d): v for d, v in curve}).sort_index()
    m = s.resample("M").last()
    rets = m.pct_change().dropna() * 100
    # longest losing run (consecutive negative months)
    longest = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0
        longest = max(longest, cur)
    # longest stretch between new highs (trading days on daily curve)
    peak_date = s.index[0]; peak = s.iloc[0]; longest_gap = 0; last_high = s.index[0]
    for d, v in s.items():
        if v >= peak:
            longest_gap = max(longest_gap, (d - last_high).days); peak = v; last_high = d
    longest_gap = max(longest_gap, (s.index[-1] - last_high).days)
    return {
        "tempo": "monthly (from saved daily equity curve)",
        "periods": int(len(rets)),
        "pct_periods_profitable": round(float((rets > 0).mean() * 100), 1),
        "median_period_pct": round(float(np.median(rets)), 3),
        "best_period_pct": round(float(rets.max()), 3),
        "worst_period_pct": round(float(rets.min()), 3),
        "longest_losing_run_periods": int(longest),
        "longest_stretch_between_new_highs_days": int(longest_gap),
        "average_period_pct_secondary_labeled": round(float(rets.mean()), 3),
    }

def main():
    v11 = json.load(open(V11))
    dist_native = period_distribution(v11["pot_curve"])
    out = {
        "family": "insider-cluster",
        "sweep_verdict": "NOT-APPLICABLE",
        "reason_one_line": "Event system, not a ranked top-N selection: clusters are taken first-come in filing-completion order up to a concurrency cap (native 20 slots, house 4 slots) with no ranking score in the published form, so varying a top-N count has no ranked list to vary.",
        "native_count_as_published": "20 concurrent slots (slice = equity/20) — a concurrency cap, not a top-N rank cut",
        "house_count_as_published": "4 concurrent positions (slice = equity/4) — same chronological intake",
        "grid_run": False,
        "grid_counts_not_run": [1, 2, 3, 5, 8, 10, 15, 20, 30, "ALL-ELIGIBLE"],
        "standing_fence": "Cluster origination FAILED its program test (v3 validation -14.41% at $100, lost to sales-cluster placebo by ~12.6 pts; v11 native: pot $177.23 vs SPY $308.98 on 2019-2026 road, event-study mean excess -3.46%, median -8.11%, 0/20 random-ticker placebos beaten, sales control $248.10 beats purchase signal). Radar-only in the app design. This sweep cannot promote anything.",
        "native_reference_from_v11": {
            "road": "2019-01-01 to 2026-11-20 (signals to 2026-03-31, SEC publication lag)",
            "final_usd_on_100": v11["pot_P"]["final"],
            "max_dd_pct": v11["pot_P"]["max_dd_pct"],
            "spy_final_same_road": v11["spy_final_same_road"],
            "taken": v11["pot_P"]["taken"], "skipped": v11["pot_P"]["skipped"],
            "event_study": v11["event_study_P"],
            "placebo_random_ticker_beaten": v11["placebo_random_ticker"]["beaten"],
        },
        "period_distribution_native_count_20_reference_only": dist_native,
        "curves": {"native_count_20": v11["pot_curve"]},
    }
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != "curves"}, indent=1))

if __name__ == "__main__":
    main()
