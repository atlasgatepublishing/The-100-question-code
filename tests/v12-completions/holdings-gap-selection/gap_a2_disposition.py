#!/usr/bin/env python3
"""gap-a2-earnings-premium — holdings-count DISPOSITION evidence.
Computes the actual monthly cohort sizes the native engine holds
(FULL 2019-2026), from the v11 folder's own data (read-only), to ground
the NOT-APPLICABLE disposition: the count is set by the calendar (how
many of the 61 names announced in that month last year), every cohort
member is bought, nobody queues for a slot, and no ranking exists in
the published form (Frazzini & Lamont 2007) or the program engine.
"""
import glob, json, os, statistics

V11 = os.path.expanduser("~/workspace/stock-app/backtests/v11-native-rules/gap-a2-earnings-premium")
V3 = "/home/hatch/workspace/stock-app/backtests/v3/pead-cache"
V4 = "/home/hatch/workspace/stock-app/backtests/v4/pead-small-cache"
EPS = os.path.join(V11, "eps_cache")

tickers = sorted(({os.path.basename(f)[3:-5] for c in (V3, V4)
                   for f in glob.glob(os.path.join(c, "px_*.json"))} - {"SPY"}))
ann_months = {}
for t in tickers:
    fp = os.path.join(EPS, f"eps_{t}.json")
    if not os.path.exists(fp): continue
    ann_months[t] = {(int(f["filed"][:4]), int(f["filed"][5:7])) for f in json.load(open(fp))["facts"]}

cohorts = []
y, m = 2019, 1
while (y, m) <= (2026, 11):
    names = [t for t in tickers if (y - 1, m) in ann_months.get(t, set())]
    cohorts.append({"month": f"{y:04d}-{m:02d}", "cohort_n": len(names)})
    m += 1
    if m == 13: y, m = y + 1, 1
sizes = [c["cohort_n"] for c in cohorts]
out = {"family": "gap-a2-earnings-premium", "universe_n": len(tickers),
       "disposition": "NOT-APPLICABLE",
       "reason": "No ranked top-N selection and no slot queue: the published form holds "
                 "EVERY firm expected to announce that month, equal weight, fully "
                 "replaced monthly. The holdings count is an output of the calendar, "
                 "not an input a sweep can vary; cutting the cohort at N would require "
                 "inventing a ranking the record does not publish.",
       "cohort_stats_FULL_2019_2026": {
           "months": len(sizes), "min": min(sizes), "max": max(sizes),
           "median": statistics.median(sizes), "mean": round(statistics.mean(sizes), 1),
           "months_with_zero": sum(1 for s in sizes if s == 0)},
       "cohorts": cohorts,
       "native_reference_v11": {"FULL_final": 428.80, "DESIGN_final": 202.21, "VAL_final": 213.97,
                                "placebo_beaten_FULL": "6/20", "verdict": "STILL DEAD EVEN AT HOME"}}
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "results_gap_a2.json"), "w"), indent=1)
print(json.dumps(out["cohort_stats_FULL_2019_2026"], indent=1))
print("universe", len(tickers))
