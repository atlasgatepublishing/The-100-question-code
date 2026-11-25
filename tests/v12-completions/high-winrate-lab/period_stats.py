#!/usr/bin/env python3
"""
Period-by-period record at the lab's native tempo (DAILY), computed from
the saved equity curves in cells/<shape>/<road>.json.

Per Terry's reporting correction (2026-11-22): the headline per-period
numbers are the count of periods, the share of periods that made money,
the MEDIAN period, the best and worst periods, the longest run of
consecutive losing periods, and the longest stretch between new highs.
Averages appear only as a secondary, explicitly labeled line.

A "period" is one trading day: period return = equity[t]/equity[t-1] - 1.
A day at exactly 0.00% (flat, in cash, no mark change) counts as neither
a money-making nor a losing period; both shares are reported.
Output: period_stats.json in this folder.
"""
import json
import os
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
SHAPES = ["H1", "H2", "H3", "H4"]
ROADS = ["DECADE", "CONT", "VAL"]


def stats_for_curve(curve):
    eq = [v for _, v in curve]
    rets = []
    for i in range(1, len(eq)):
        if eq[i - 1] > 0:
            rets.append(eq[i] / eq[i - 1] - 1.0)
    n = len(rets)
    up = sum(1 for r in rets if r > 1e-12)
    down = sum(1 for r in rets if r < -1e-12)
    flat = n - up - down
    # longest run of consecutive losing periods
    longest_loss_run = 0
    cur = 0
    for r in rets:
        if r < -1e-12:
            cur += 1
            longest_loss_run = max(longest_loss_run, cur)
        else:
            cur = 0
    # longest stretch between new highs (in periods, peak to next new peak;
    # if the curve ends below its last peak, the open stretch to the end
    # is also measured and the larger is reported, flagged)
    peak = eq[0]
    peak_i = 0
    longest_gap = 0
    for i, v in enumerate(eq):
        if v > peak:
            longest_gap = max(longest_gap, i - peak_i)
            peak = v
            peak_i = i
    open_gap = len(eq) - 1 - peak_i
    longest_gap = max(longest_gap, open_gap)
    return {
        "periods": n,
        "pct_periods_up": round(100.0 * up / n, 1) if n else None,
        "pct_periods_down": round(100.0 * down / n, 1) if n else None,
        "pct_periods_flat": round(100.0 * flat / n, 1) if n else None,
        "median_period_pct": round(100.0 * statistics.median(rets), 4) if n else None,
        "best_period_pct": round(100.0 * max(rets), 2) if n else None,
        "worst_period_pct": round(100.0 * min(rets), 2) if n else None,
        "longest_losing_run_periods": longest_loss_run,
        "longest_stretch_between_new_highs_periods": longest_gap,
        "mean_period_pct_secondary_average": round(100.0 * statistics.mean(rets), 4) if n else None,
    }


def main():
    out = {}
    for shape in SHAPES:
        out[shape] = {}
        for road in ROADS:
            path = os.path.join(HERE, "cells", shape, f"{road}.json")
            with open(path) as fh:
                cell = json.load(fh)
            out[shape][road] = stats_for_curve(cell["equity_curve"])
            s = out[shape][road]
            print(f"{shape} {road:7s}: periods {s['periods']}  up "
                  f"{s['pct_periods_up']}%  median {s['median_period_pct']}%  "
                  f"best {s['best_period_pct']}%  worst {s['worst_period_pct']}%  "
                  f"loss-run {s['longest_losing_run_periods']}  "
                  f"high-gap {s['longest_stretch_between_new_highs_periods']}",
                  flush=True)
    with open(os.path.join(HERE, "period_stats.json"), "w") as fh:
        json.dump(out, fh, indent=2)
    print("Wrote period_stats.json", flush=True)


if __name__ == "__main__":
    main()
