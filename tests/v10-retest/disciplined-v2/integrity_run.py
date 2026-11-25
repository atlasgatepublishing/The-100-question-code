#!/usr/bin/env python3
"""INTEGRITY driver — disciplined-v2 v10 retest.
Reproduces the ORIGINAL published v2 finals through the ORIGINAL engine
(original_engine.py = byte copy of backtests/v2/disciplined-v2.py),
reading the v2 data cache READ-ONLY (DATA_DIR pointed at backtests/v2/data;
all 5 tickers are cached there as CSVs, so nothing is fetched or written).

Published targets (backtests/v2/disciplined-v2.md + disciplined-v2-results.json):
  Window A (2025-11-21 -> 2026-11-20) v2:      final $100.45, 35 trades,
                                               costs $1.29, max DD 11.11%
  Window A placebo (seed 42):                  final $100.96, 40 trades
  Window B (2016-11-21 -> 2026-11-20) decade:  final $194.28, 297 trades,
                                               costs $12.18, max DD 16.23%,
                                               no halt, single segment
  Window B SPY benchmark (price-only, engine): net $314.10
Cross-reference (v3 descendant anchors, task assignment): BASE decade
$194.28 / COMBO full $241.29 — the BASE anchor is the same $194.28.
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import original_engine as oe

oe.DATA_DIR = os.path.expanduser("~/workspace/stock-app/backtests/v2/data")

mkt = oe.Market()

a = oe.run_sim(mkt, "2025-11-21", "2026-11-20", mode="v2")
p = oe.run_sim(mkt, "2025-11-21", "2026-11-20", mode="placebo")
bench_a = oe.benchmark(mkt, "2025-11-21", "2026-11-20")

# Window B exactly as the original main(): chained segments with the
# original Jan-1 fresh-$100 restart convention (never invoked — no halt).
segments = []
seg_start = "2016-11-21"
while True:
    seg = oe.run_sim(mkt, seg_start, "2026-11-20", mode="v2")
    if seg is None:
        break
    segments.append(seg)
    if not seg["halted"]:
        break
    halt_year = int(seg["daily"][-1][0][:4])
    nxt = f"{halt_year + 1}-01-01"
    if nxt > "2026-11-20":
        break
    seg_start = nxt
bench_b = oe.benchmark(mkt, "2016-11-21", "2026-11-20")
chained = 100.0
for s in segments:
    chained *= s["final_balance"] / 100.0


def brief(r):
    return {"final": r["final_balance"], "trades": r["total_trades"],
            "costs": r["total_costs"], "max_dd_pct": r["max_drawdown_pct"],
            "halted": r["halted"]}


out = {
    "windowA_v2": brief(a),
    "windowA_placebo_seed42": brief(p),
    "windowA_benchmark_net": bench_a["net"],
    "windowB_segments": [brief(s) for s in segments],
    "windowB_n_segments": len(segments),
    "windowB_chained_final": round(chained, 2),
    "windowB_benchmark_net": bench_b["net"],
    "_targets": {
        "windowA_v2": {"final": 100.45, "trades": 35, "costs": 1.29,
                       "max_dd_pct": 11.11},
        "windowA_placebo_seed42": {"final": 100.96, "trades": 40},
        "windowB_decade": {"final": 194.28, "trades": 297, "costs": 12.18,
                           "max_dd_pct": 16.23, "halted": False},
        "windowB_benchmark_net": 314.10,
    },
}
out["_match"] = {
    "windowA_v2": out["windowA_v2"] == out["_targets"]["windowA_v2"] | {"halted": False},
    "windowA_placebo_final": out["windowA_placebo_seed42"]["final"] == 100.96,
    "windowB_decade": (len(segments) == 1
                       and out["windowB_segments"][0]["final"] == 194.28
                       and out["windowB_segments"][0]["trades"] == 297
                       and out["windowB_segments"][0]["costs"] == 12.18
                       and out["windowB_segments"][0]["max_dd_pct"] == 16.23
                       and out["windowB_segments"][0]["halted"] is False),
    "windowB_benchmark_net": out["windowB_benchmark_net"] == 314.10,
}
with open(os.path.join(HERE, "integrity.json"), "w") as f:
    json.dump(out, f, indent=2)
print(json.dumps(out, indent=2))
