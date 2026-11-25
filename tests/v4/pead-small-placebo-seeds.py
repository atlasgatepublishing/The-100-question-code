#!/usr/bin/env python3
"""
Supplementary placebo robustness check for pead-small.py (simulation only).

The headline placebo (seed 42, same methodology as pead-lite) halted early
(2023-05-04) and so only filled 12 of the 26 target entries, which makes
the single-seed placebo gap hard to read. This script re-runs the SAME
validation placebo with several seeds and reports the distribution.
Everything comes from pead-small.py's local caches - no new data pulls
except re-attempts of previously failed price fetches.
"""
import importlib.util, json, os, random, sys
from datetime import date

BASE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("pead_small",
                                              os.path.join(BASE, "pead-small.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

SEEDS = [42, 7, 123, 2024, 555]
WS, WE = date(2023, 1, 1), date(2026, 11, 20)


def main():
    ciks = mod.get_ciks()
    earnings, nonearn, stats = mod.get_events(ciks)
    bars = {t: mod.get_bars(t) for t in mod.SEEDS + ["SPY"]}
    spy = bars["SPY"]
    mod.ALL_DAYS = sorted(spy.keys())
    mod.GLOBAL_IDX = {d: i for i, d in enumerate(mod.ALL_DAYS)}
    spy_close = {d: spy[d]["close"] for d in mod.ALL_DAYS}
    closes = [spy[d]["close"] for d in mod.ALL_DAYS]
    spy_ma = {d: (sum(closes[i - 199:i + 1]) / 200 if i >= 199 else None)
              for i, d in enumerate(mod.ALL_DAYS)}
    screener = mod.Screener(bars)
    cal = [d for d in mod.ALL_DAYS if WS <= d <= WE]
    pool = mod.build_placebo_pool(nonearn, bars, screener, WS, WE)
    print(f"placebo pool: {len(pool)}", file=sys.stderr)

    targets = {50: 26, 100: 26}  # real strategy's validation entries
    out = {}
    for seed in SEEDS:
        out[seed] = {}
        for pot, cfg in mod.POTS.items():
            target = targets[pot]
            rng = random.Random(seed)
            sampled = rng.sample(pool, min(len(pool), max(target * 6, target)))
            sampled.sort(key=lambda s: s["buy_date"])
            bench = mod.spy_benchmark(cal, spy, pot)
            sim = mod.Sim(cal, bars, spy_close, spy_ma, float(pot),
                          cfg["floor"], cfg["ladder"],
                          max_entries=target).run(sampled)
            out[seed][pot] = sim.summary(float(pot), bench)
            print(f"seed {seed} ${pot}: final ${sim.cash:.2f}, "
                  f"{sim.entries}/{target} entries, halted={sim.halted} "
                  f"({sim.halt_date})", file=sys.stderr)
    with open(os.path.join(BASE, "pead-small-placebo-seeds.json"), "w") as f:
        json.dump(out, f, indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
