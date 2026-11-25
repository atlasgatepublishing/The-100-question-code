#!/usr/bin/env python3
"""
INTEGRITY GATE — candlestick-patterns (v10 Great Retest).

Reproduces the ORIGINAL v2 tournament numbers for style A (candlestick:
bullish engulfing / hammer above the 50-day average; -5% stop, +10% target,
10-trading-day time exit) and its single-seed random-entry placebo, through
the ORIGINAL engine (tournament_original.py in this folder is a verbatim copy
of backtests/v2/tournament.py) under the ORIGINAL rules:
  - split-adjusted (NOT dividend-adjusted) Yahoo bars, cached read-only in
    backtests/v2/tournament-data/
  - costs 0.10%/side + $0.01 per sell order
  - ladder-era floor: $85, rising to $100 at a $125 close and $125 at a $150
    close; a close at/below the floor liquidates at the next open and ENDS
    the run (no restart — that was the era's rule)
  - window 2016-11-21 -> 2026-11-20, $100 pot

Published targets (backtests/v2/tournament.md):
  real style A : $122.94, halted 2021-05-19, 324 orders, costs $20.47
  A-placebo    : $165.09 (seed 42101) — BEAT the real style by $42.15
  SPY net (price-only, same bars): $314.10

Writes integrity.json next to this script. Simulation only.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import tournament_original as T

# Point the verbatim original engine at the original read-only bar cache.
T.CACHE_DIR = os.path.expanduser("~/workspace/stock-app/backtests/v2/tournament-data")


def main():
    raw = {sym: T.load_symbol(sym) for sym in T.ALL_SYMBOLS}
    frames = T.align_frames(raw)
    mkt = T.Market(frames)
    start_date = mkt.test_dates[0]

    pf = T.run_discrete(
        mkt, "a_candlestick", T.STOCK_UNIVERSE, signal_fn=T.sig_candlestick,
        entry_mode="next_open", stop_pct=0.05, target_pct=0.10,
        time_exit_days=10)
    real = T.score(pf, start_date)

    n_entries = sum(1 for tr in pf.trades if tr["side"] == "buy")
    schedule = T.make_placebo_schedule(mkt, T.STOCK_UNIVERSE, n_entries,
                                       T.PLACEBO_SEEDS["a_candlestick"])
    ppf = T.run_discrete(
        mkt, "a_candlestick_placebo", T.STOCK_UNIVERSE,
        placebo_schedule=schedule, stop_pct=0.05, target_pct=0.10,
        time_exit_days=10)
    plac = T.score(ppf, start_date)
    plac_entries = sum(1 for tr in ppf.trades if tr["side"] == "buy")

    spy_gross, spy_net = T.spy_benchmark(mkt)

    out = {
        "strategy": "a_candlestick",
        "conventions": ("ORIGINAL tournament rules: split-adjusted (not "
                        "dividend-adjusted) Yahoo bars; ladder-era floor "
                        "($85 -> $100 @ $125 close -> $125 @ $150 close, halt "
                        "ends the run, no restart); costs 0.10%/side + $0.01 "
                        "per sell; signals at close, entries next open, "
                        "stop-first intraday."),
        "published": {
            "real_final": 122.94, "halt_date": "2021-05-19",
            "orders": 324, "costs": 20.47,
            "placebo_final": 165.09, "placebo_seed": 42101,
            "placebo_margin_over_real": 42.15,
            "spy_net_price_only": 314.10,
        },
        "reproduced": {
            "real_final": round(real["final"], 2),
            "halt_date": real["halt_date"],
            "orders": real["orders"],
            "closed_trades": real["closed_trades"],
            "win_rate_pct": round(real["win_rate"], 1),
            "max_dd_pct": round(real["max_dd_pct"], 1),
            "costs": round(real["total_costs"], 2),
            "placebo_final": round(plac["final"], 2),
            "placebo_target_entries": n_entries,
            "placebo_actual_entries": plac_entries,
            "placebo_margin_over_real": round(plac["final"] - real["final"], 2),
            "spy_gross_price_only": round(spy_gross, 2),
            "spy_net_price_only": round(spy_net, 2),
        },
    }
    ok = (abs(out["reproduced"]["real_final"] - 122.94) < 0.005
          and out["reproduced"]["halt_date"] == "2021-05-19"
          and abs(out["reproduced"]["placebo_final"] - 165.09) < 0.005
          and abs(out["reproduced"]["spy_net_price_only"] - 314.10) < 0.005)
    out["status"] = "reproduced" if ok else "FAILED"
    with open(os.path.join(HERE, "integrity.json"), "w") as fh:
        json.dump(out, fh, indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
