#!/usr/bin/env python3
"""V13 best-rules: Ehlers MAMA/FAMA, published engine EXACTLY (v12 impl),
chassis = WEEKLY sampling of the daily crossover state (spec frozen first).
SPY only, all-in/cash, no floor. Costs 0.10%/side + $0.01 sell fee."""
import json, os, sys, random, statistics, importlib.util
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "v12mama", os.path.expanduser(
        "~/workspace/stock-app/backtests/v12-completions/hunt-ehlers-mama-fama/run_mama.py"))
M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)

START = 100.0
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
PUB = {"LONG": 268.05, "DECADE": 218.51, "CONT": 190.28, "VAL": 145.75}


def week_key(d):
    y, m, dd = map(int, d.split("-"))
    iso = date(y, m, dd).isocalendar()
    return (iso[0], iso[1])


def weekly_targets(bars, daily_targets):
    """Desired state updates only at the last trading bar of each ISO week,
    to the daily crossover state at that close."""
    n = len(bars)
    wk = [week_key(b["d"]) for b in bars]
    out = [False] * n
    state = False
    for i in range(n):
        if i == n - 1 or wk[i + 1] != wk[i]:
            state = daily_targets[i]
        out[i] = state
    return out


def weekly_placebo_targets(bars, daily_targets, road_idx, seed):
    """Circular shift of the weekly sampled states among the week's read
    points inside the road; daily targets rebuilt from shifted states."""
    wk = [week_key(b["d"]) for b in bars]
    reads = [i for i in road_idx if i == len(bars) - 1 or wk[i + 1] != wk[i]]
    states = []
    state = False
    pos_of = {}
    for i in range(len(bars)):
        if i == len(bars) - 1 or wk[i + 1] != wk[i]:
            state = daily_targets[i]
        pos_of[i] = state
    states = [pos_of[i] for i in reads]
    rng = random.Random(seed)
    if len(states) > 1:
        k = rng.randrange(1, len(states))
        states = states[k:] + states[:k]
    shifted = dict(zip(reads, states))
    out = [False] * len(bars)
    state = False
    for i in range(len(bars)):
        if i in shifted:
            state = shifted[i]
        out[i] = state
    return out


def main():
    spy = M.load_pxfull("SPY")
    daily = M.signal_fn(spy)
    wtgt = weekly_targets(spy, daily)
    out = {"family": "hunt-ehlers-mama-fama (Ehlers MAMA/FAMA) — v13 best rules",
           "form": "Published MAMA/FAMA engine untouched (FastLimit 0.5, SlowLimit 0.05, hl2); "
                   "chassis: weekly (last trading close of ISO week) sampling of the daily "
                   "crossover state, execute next open; SPY only, all-in/cash, NO floor",
           "costs": "stocks 0.10%/side + $0.01 sell fee",
           "data_range": f"{spy[0]['d']} -> {spy[-1]['d']}", "roads": {}}
    for name, (s, e) in ROADS.items():
        r = M.simulate(spy, wtgt, s, e, M.STK_COST, M.STK_SELL_FEE, chassis=False)
        bh = M.buy_hold(spy, s, e, M.STK_COST, M.STK_SELL_FEE)
        idx = [i for i, b in enumerate(spy) if s <= b["d"] <= e]
        finals = []
        for seed in range(1, 21):
            pt = weekly_placebo_targets(spy, daily, idx, seed)
            pr = M.simulate(spy, pt, s, e, M.STK_COST, M.STK_SELL_FEE, chassis=False)
            finals.append(pr["final"])
        rec = {"my_rules": {**r, "period_stats": M.period_stats(r["equity_curve"], "monthly")},
               "benchmark_hold": {"name": "SPY buy-and-hold (same plumbing)",
                                  "final": bh["final"], "max_dd_pct": bh["max_dd_pct"],
                                  "period_stats": M.period_stats(bh["equity_curve"], "monthly")},
               "placebo_weekly_shift": {
                   "seed_finals": finals,
                   "beaten_of_20": sum(1 for p in finals if r["final"] > p),
                   "median": round(statistics.median(finals), 2),
                   "design": "circular shift of weekly sampled states among week-read points in road (20 seeds)"},
               "published_native_final": PUB[name], "champion_vm": CHAMP[name],
               "spy_program_ref": SPYREF[name]}
        out["roads"][name] = rec
        print(f"{name}: mine ${r['final']} (DD {r['max_dd_pct']}%, orders {r['orders']}, "
              f"costs ${r['costs']}, inv {r['invested_pct']}%) | hold ${bh['final']} "
              f"| pub ${PUB[name]} | champ ${CHAMP[name]} | placebos {rec['placebo_weekly_shift']['beaten_of_20']}/20")
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE")


if __name__ == "__main__":
    main()
