#!/usr/bin/env python3
"""Wrapper: runs run_judgment.main() with json.dump intercepted (exec-sandbox
byte-writes are blocked in this session), captures the results object, and
prints a compact JSON (summary + monthly curves + period stats + trades)
to stdout for assembly into results.json by the file tool."""
import json, sys, os, statistics
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
captured = {}
def fake_dump(obj, f, **kw):
    captured["obj"] = obj
json.dump = fake_dump
import run_judgment
try:
    run_judgment.main()
except Exception as e:
    print("main tail error (expected, dump intercepted):", e, flush=True)
obj = captured["obj"]
compact = {"label": obj["label"], "universe_size": obj["universe_size"],
           "failures": obj["failures"],
           "curve_note": "monthly curve (last equity value of each month); daily curve computed in-run for drawdown/stretch stats",
           "roads": {}}
for name, r in obj["roads"].items():
    curve = r["curve"]
    months = {}
    for d, v in curve:
        months[d[:7]] = v
    keys = sorted(months)
    rets = []; prev = 100.0
    for k in keys:
        rets.append(months[k] / prev - 1); prev = months[k]
    streak = mx = 0
    for x in rets:
        streak = streak + 1 if x <= 0 else 0; mx = max(mx, streak)
    peak = -1; since = mxs = 0
    for _d, v in curve:
        if v >= peak:
            peak = v; since = 0
        else:
            since += 1; mxs = max(mxs, since)
    compact["roads"][name] = {
        "start": r["start"], "end": r["end"], "final": r["final"],
        "costs": r["costs"], "orders": r["orders"], "halted": r["halted"],
        "max_dd_pct": r["max_dd_pct"], "n_entries": r["n_entries"],
        "placebo_beaten": r["placebo_beaten"], "placebo_finals": r["placebo_finals"],
        "monthly_curve": [[k, months[k]] for k in keys],
        "period_stats_monthly": {
            "n_months": len(rets),
            "pct_positive": round(100 * sum(1 for x in rets if x > 0) / len(rets), 1),
            "median_month_pct": round(100 * statistics.median(rets), 2),
            "mean_month_pct": round(100 * statistics.mean(rets), 2),
            "best_month_pct": round(100 * max(rets), 2),
            "worst_month_pct": round(100 * min(rets), 2),
            "longest_losing_streak_months": mx,
            "longest_days_between_highs": mxs},
        "trades": r["trades"]}
only = sys.argv[1] if len(sys.argv) > 1 else None
if only:
    compact["roads"] = {only: compact["roads"][only]}
print("COMPACT_JSON_BEGIN")
print(json.dumps(compact))
print("COMPACT_JSON_END")
