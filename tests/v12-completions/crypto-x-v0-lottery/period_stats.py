#!/usr/bin/env python3
"""Per-period distribution at the family's native tempo (DAILY — the system
screens monthly but ranks and exits daily), computed from the saved curves
in results.json. Two views per cell: (a) the full saved curve, and (b) the
ACTIVE stretch only (through the run's halt / last trade day), because the
ladder and v9 runs that end early sit in flat cash for years and a flat-cash
day is not a period the system traded. Median is the headline; the average
appears only as a labeled secondary line."""
import json, os, statistics
HERE = os.path.dirname(os.path.abspath(__file__))

def stats(curve):
    eq = [e for _, e in curve]
    pnl = [eq[i + 1] - eq[i] for i in range(len(eq) - 1)]
    if not pnl: return None
    pos_n = sum(1 for x in pnl if x > 0)
    run = best_run = 0
    for x in pnl:
        run = run + 1 if x < 0 else 0
        best_run = max(best_run, run)
    peak, since, worst = -1.0, 0, 0
    for e in eq:
        if e > peak: peak, since = e, 0
        else:
            since += 1; worst = max(worst, since)
    return {"periods": len(pnl), "pct_profitable": round(100 * pos_n / len(pnl), 1),
            "median_period_usd": round(statistics.median(pnl), 4),
            "best_period_usd": round(max(pnl), 2), "worst_period_usd": round(min(pnl), 2),
            "longest_losing_run_periods": best_run,
            "longest_stretch_between_new_highs_periods": worst,
            "average_period_usd_SECONDARY_LABELED_AVERAGE": round(statistics.mean(pnl), 4)}

def active(curve, run):
    """Curve truncated at the halt date (or window end if the run never halted)."""
    if not run["halts"]: return curve
    hd = run["halts"][-1]["halt_date"]
    return [pt for pt in curve if pt[0] <= hd]

def main():
    with open(os.path.join(HERE, "results.json")) as f: R = json.load(f)
    out = {}
    for key in ("ladder|full|costed", "ladder|full|zerocost", "v9|full|costed",
                "ladder|validation|costed", "v9|validation|costed"):
        run = R["runs"][key]
        out[key] = {"full_curve": stats(run["curve"]),
                    "active_stretch": stats(active(run["curve"], run))}
    for w in ("full", "validation"):
        out[f"btc_hold|{w}"] = {"full_curve": stats(R["btc_hold"]["c060"][w]["curve"])}
    print(json.dumps(out, indent=1))
    with open(os.path.join(HERE, "period_stats.json"), "w") as f: json.dump(out, f, indent=1)

if __name__ == "__main__":
    main()
