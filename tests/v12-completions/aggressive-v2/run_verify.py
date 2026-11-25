#!/usr/bin/env python3
"""
V12 VERIFICATION — aggressive-v2 (program construction, §6 NO-NATIVE-FORM).

Runs the FROZEN v2 program spec exactly as published, using the original
v2 engine code UNCHANGED (imported read-only from backtests/v2/), on:
  - Window A  2025-11-21 -> 2026-11-20  (integrity vs the v2 report)
  - DECADE    2016-11-21 -> 2026-11-20  (integrity vs v2/v10/v11 record)
  - CONT      2019-01-02 -> 2026-11-20  (new road, same frozen spec)
  - VAL       2023-01-03 -> 2026-11-20  (new road, same frozen spec)
LONG 2010->2026 is NOT runnable: the family's own data cache begins
2015-06-01 (needed for the 200-day warmup); DECADE is the longest honest
road this family's record supports. Stated, not patched.

Protection is the ORIGINAL frozen form (plain $85 floor + $125/$150 profit
ladder, halt = liquidate at next open and end the run) — NOT the v10 sweep's
v9 substitution. The v10 RESULTS.md documents that the substitution never
bit on DECADE (no halts, ladder never engaged), so DECADE finals are
directly comparable across both protection forms.

Placebos: the engine's own placebo mode (random free name, random day,
entry_prob = real entries / road days, identical sizing/exits/costs/floor,
no entry filters, no cost gate), 20 seeds per road (seeds 1..20; DECADE and
Window A additionally carry the original single seed 20261121 where the
record used it).

Costs: the engine's own program costs — 0.10%/side + $0.01 sell fee.
Data: read-only v2 cache (Yahoo daily OHLCV, split-adjusted, NOT
dividend-adjusted). SPY benchmarks are therefore price-only, labeled as
such; dividend-adjusted program references are printed in RESULTS.md.
"""
import importlib.util, json, os, random, sys

HERE = os.path.dirname(os.path.abspath(__file__))
V2PY = os.path.expanduser("~/workspace/stock-app/backtests/v2/aggressive-v2.py")
spec = importlib.util.spec_from_file_location("aggv2_engine", V2PY)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)   # engine reads its own ./data cache (read-only)

D = m.load_data()

def run_road(start, end):
    cal = m.calendar(D, start, end)
    sim = m.Sim(D, cal, mode="v2").run()
    st = sim.stats()
    curve = [[d, round(e, 4)] for d, e in sim.equity_curve]
    entry_prob = st["counters"]["entries"] / len(cal) if cal else 0
    twins = []
    for seed in range(1, 21):
        rng = random.Random(seed)
        twin = m.Sim(D, cal, mode="placebo", rng=rng, entry_prob=entry_prob).run()
        twins.append(round(twin.stats()["final_balance"], 2))
    beaten = sum(1 for t in twins if st["final_balance"] > t)
    gross, net = m.benchmark(D, cal[0], cal[-1])
    return {
        "window": [cal[0], cal[-1]], "n_days": len(cal),
        "stats": st, "equity_curve": curve,
        "spy_price_only": {"gross": gross, "net": net},
        "placebo": {"entry_prob_per_day": round(entry_prob, 4),
                    "seeds": list(range(1, 21)), "finals": twins,
                    "beaten": beaten,
                    "median": sorted(twins)[10]},
    }

out = {"family": "aggressive-v2", "engine": "backtests/v2/aggressive-v2.py (unchanged, imported read-only)",
       "costs": "0.10%/side + $0.01 sell fee (engine's own)",
       "protection": "original frozen form: $85 floor + $125/$150 profit ladder",
       "roads": {}}
out["roads"]["windowA"] = run_road("2025-11-21", "2026-11-20")
# original single-seed placebo on Window A (seed 20261121), for the record check
calA = m.calendar(D, "2025-11-21", "2026-11-20")
stA = out["roads"]["windowA"]["stats"]
ep = stA["counters"]["entries"] / len(calA)
orig_twin = m.Sim(D, calA, mode="placebo", rng=random.Random(m.PLACEBO_SEED), entry_prob=ep).run()
out["roads"]["windowA"]["placebo_original_seed_20261121"] = round(orig_twin.stats()["final_balance"], 2)
out["roads"]["DECADE"] = run_road("2016-11-21", "2026-11-20")
out["roads"]["CONT"] = run_road("2019-01-02", "2026-11-20")
out["roads"]["VAL"] = run_road("2023-01-03", "2026-11-20")
out["roads"]["LONG"] = {"status": "NOT RUNNABLE on this family's data",
    "reason": "v2 cache begins 2015-06-01; the 200-day-MA warmup puts the earliest honest start in 2016. DECADE (2016-11-21) is the longest honest road. No substitute data was introduced — that would change the frozen record."}

with open(os.path.join(HERE, "results.json"), "w") as f:
    json.dump(out, f, indent=1)
for k, r in out["roads"].items():
    if "stats" in r:
        s = r["stats"]
        print(k, r["window"], "final", s["final_balance"], "DD", s["max_drawdown_pct"],
              "costs", s["total_costs"], "orders", s["total_orders"], "RT", s["round_trips"],
              "win%", s["win_rate"], "halted", s["halted"], "SPYnet", r["spy_price_only"]["net"],
              "placebo beaten", r["placebo"]["beaten"], "/20 median twin", r["placebo"]["median"])
print("windowA orig-seed placebo:", out["roads"]["windowA"]["placebo_original_seed_20261121"])
