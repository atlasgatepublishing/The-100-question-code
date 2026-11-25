#!/usr/bin/env python3
"""Diagnostic + per-period stats for vm-twosleeve v12. Changes NO official
number. (1) Artifact diagnostic: identical frozen construction with the
single corrupt series (AMCCF, CIK 1748790) removed from the data, run
for the record and labeled DIAGNOSTIC. (2) Period-by-period stats at the
native monthly tempo from the saved equity curves. Writes
diagnostic.json and period_stats.json; appends a diagnostic block to
results.json."""
import importlib.util, os, json, math
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("rt", os.path.join(HERE, "run_twosleeve_constructed.py"))
R = importlib.util.module_from_spec(spec); spec.loader.exec_module(R)

BAD_CIK = 1748790  # AMCCF — corrupt Yahoo series in shared W04 cache

def period_stats(curve):
    """curve: [[ym, total, ...], ...] monthly marks incl. final liquidation."""
    pts = [(r[0], r[1]) for r in curve]
    rets = []
    for (d0, v0), (d1, v1) in zip(pts, pts[1:]):
        if v0 > 0: rets.append((d1, v1 / v0 - 1.0))
    vals = sorted(r for _, r in rets)
    n = len(vals)
    median = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
    mean = sum(vals) / n if n else 0.0
    # longest losing streak
    streak = longest = 0
    for _, r in rets:
        streak = streak + 1 if r < 0 else 0
        longest = max(longest, streak)
    # longest stretch between new highs (in months/periods)
    peak = -1.0; last_high = 0; longest_gap = 0
    for i, (_, v) in enumerate(pts):
        if v >= peak:
            peak = v; longest_gap = max(longest_gap, i - last_high); last_high = i
    trailing = len(pts) - 1 - last_high
    best = max(rets, key=lambda kv: kv[1]); worst = min(rets, key=lambda kv: kv[1])
    return {"periods": n,
            "pct_periods_positive": round(100.0 * sum(1 for _, r in rets if r > 0) / n, 1) if n else None,
            "median_period_pct": round(median * 100, 2),
            "mean_period_pct_secondary_average": round(mean * 100, 2),
            "best_period": [best[0], round(best[1] * 100, 2)],
            "worst_period": [worst[0], round(worst[1] * 100, 2)],
            "longest_losing_streak_periods": longest,
            "longest_stretch_between_new_highs_periods": longest_gap,
            "periods_since_last_new_high_at_end": trailing}

def main():
    R.D = R.Data()
    D = R.D
    res = json.load(open(os.path.join(HERE, "results.json")))
    stats = {}
    for name, w in res["windows"].items():
        stats[name + "_official"] = period_stats(w["curve"])
    # correlation excluding the two AMCCF-driven holding months
    rets = res["windows"]["FULL"]["sleeve_monthly_returns"]
    forms = []
    m = "2017-01"
    while m <= "2026-09":
        forms.append(m); m = R.ym_next(m)
    keep = [(a, b) for (a, b), f in zip(rets, forms) if f not in ("2021-03", "2021-05")]
    corr_ex = R.pearson([a for a, _ in keep], [b for _, b in keep])
    # diagnostic run: corrupt series removed from the data only
    del D.px[BAD_CIK]
    diag = {}
    for name, (s, e, f) in {"FULL": ("2017-01", "2026-09", "2026-10"),
                            "CONTs": ("2019-01", "2026-09", "2026-10"),
                            "VALs": ("2023-01", "2026-09", "2026-10")}.items():
        r = R.run_window(s, e, f, collect_corr=(name == "FULL"))
        diag[name] = r
        stats[name + "_diagnostic_no_AMCCF"] = period_stats(r["curve"])
        print("DIAG", name, r["final"], "spy", r["spy_final_same_window"], "dd", r["max_dd_pct"], flush=True)
    dr = diag["FULL"]["sleeve_monthly_returns"]
    dcorr = R.pearson([a for a, _ in dr], [b for _, b in dr])
    dv = R.stdev([a for a, _ in dr]); dm = R.stdev([b for _, b in dr])
    dcomb = R.stdev([(a + b) / 2 for a, b in dr])
    out = {"artifact": {"ticker": "AMCCF", "cik": BAD_CIK, "holder": "Amcor plc (OTC foreign ordinary)",
                        "defect": "Yahoo monthly adjusted series in the shared W04 cache is corrupt: negative adjusted prices through 2020, then alternating ~$0.004-0.09 penny prints and ~$34-57 prints in 2021 (ticker collision). No such returns ever existed."},
           "sleeve_corr_FULL_excluding_artifact_months_only": round(corr_ex, 3),
           "diagnostic_windows": {k: {kk: v[kk] for kk in ("final", "max_dd_pct", "costs", "orders", "spy_final_same_window", "curve")}
                                  for k, v in diag.items()},
           "diagnostic_sleeve_correlation_FULL": {"corr": round(dcorr, 3), "n_months": len(dr),
               "value_vol_pct": round(dv * 100, 2), "momentum_vol_pct": round(dm * 100, 2),
               "combined_50_50_vol_pct": round(dcomb * 100, 2)}}
    json.dump(out, open(os.path.join(HERE, "diagnostic.json"), "w"), indent=1)
    json.dump(stats, open(os.path.join(HERE, "period_stats.json"), "w"), indent=1)
    res["diagnostic_artifact_excluded"] = {"pointer": "diagnostic.json",
        "FULL_final": diag["FULL"]["final"], "CONTs_final": diag["CONTs"]["final"],
        "VALs_final": diag["VALs"]["final"], "sleeve_corr_FULL": round(dcorr, 3),
        "sleeve_corr_FULL_official_excl_artifact_months": round(corr_ex, 3)}
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("corr official excl artifact months:", round(corr_ex, 3))
    print("corr diagnostic:", round(dcorr, 3))
    print(json.dumps(stats, indent=1))

if __name__ == "__main__":
    main()
