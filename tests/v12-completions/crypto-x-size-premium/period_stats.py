#!/usr/bin/env python3
"""Period-by-period record at the family's native tempo (monthly), computed
from the saved equity curves in results.json. Periods = calendar months
(month-end equity). Median period is the headline; any average is labeled."""
import json, os, statistics
HERE = os.path.dirname(os.path.abspath(__file__))

def month_ends(curve):
    m = {}
    for d, e in curve: m[d[:7]] = e
    ks = sorted(m)
    return [m[k] for k in ks], ks

def stats(curve):
    eq, ks = month_ends(curve)
    rets = [eq[i+1]/eq[i]-1 for i in range(len(eq)-1) if eq[i] > 0]
    pos = sum(1 for r in rets if r > 0)
    run = best_run = 0
    for r in rets:
        run = run+1 if r < 0 else 0
        best_run = max(best_run, run)
    peak, since, worst_stretch = -1.0, 0, 0
    for e in eq:
        if e > peak: peak, since = e, 0
        else:
            since += 1; worst_stretch = max(worst_stretch, since)
    return {"periods": len(rets), "pct_positive": round(100*pos/len(rets), 1),
            "median_period_pct": round(statistics.median(rets)*100, 2),
            "best_period_pct": round(max(rets)*100, 2),
            "worst_period_pct": round(min(rets)*100, 2),
            "longest_losing_run_periods": best_run,
            "longest_stretch_between_new_highs_periods": worst_stretch,
            "average_period_pct_SECONDARY_LABELED_AVERAGE":
                round(statistics.mean(rets)*100, 2)}

def main():
    with open(os.path.join(HERE, "results.json")) as f: R = json.load(f)
    out = {}
    for key in ("monthly|n5|nofloor|full", "monthly|n5|v9|full",
                "monthly|n10|nofloor|full",
                "monthly|n5|nofloor|validation", "monthly|n5|v9|validation"):
        out[key] = stats(R["runs"][key]["curve"])
    out["btc_hold_full_c060"] = stats(R["btc_hold"]["c060"]["full"]["curve"])
    out["btc_hold_validation_c060"] = stats(
        R["btc_hold"]["c060"]["validation"]["curve"])
    print(json.dumps(out, indent=1))
    with open(os.path.join(HERE, "period_stats.json"), "w") as f:
        json.dump(out, f, indent=1)

if __name__ == "__main__":
    main()
