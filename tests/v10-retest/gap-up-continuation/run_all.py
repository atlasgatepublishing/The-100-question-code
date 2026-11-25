#!/usr/bin/env python3
"""
Driver for the gap-up-continuation v10 retest.

  1) INTEGRITY: style G under the ORIGINAL tournament rules (ladder floor,
     run ends at halt) + its original placebo twin (seed 42107).
     Targets: real $84.04 halted 2020-01-16; placebo $97.91.
  2) SWEEP: DECADE x 7 cadences under v9 protections, $100/cell.
  3) PLACEBOS: 20 seeds per cadence (random entries on cadence dates,
     identical exits/sizing/protections). Seeds 42107..42126.
  4) SPY benchmarks: price-only from the tournament cache (tournament
     convention); dividend-adjusted computed from Yahoo adjclose if the
     fetch works, else the SPEC/W6 verified reference $367.80 is used and
     labeled as such.

Writes cells/<cadence>.json (full equity curve + all placebo finals),
cells/integrity.json, and results.json. Simulation only.
"""

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gap_up_engine as E

HERE = os.path.dirname(os.path.abspath(__file__))
CELLS = os.path.join(HERE, "cells")
os.makedirs(CELLS, exist_ok=True)

PLACEBO_SEEDS = [42107 + i for i in range(20)]
ORIGINAL_PLACEBO_SEED = 42107


def curve_json(pf):
    return [[d.isoformat(), round(v, 4)] for d, v in pf.equity_curve]


def cell_record(pf, events, placebo_finals):
    s = E.score(pf, E.TEST_START)
    beaten = None
    if placebo_finals:
        beaten = sum(1 for f in placebo_finals if s["final"] > f)
    return s, {
        "final": round(s["final"], 2),
        "cagr_pct": round(s["cagr_pct"], 2),
        "max_dd_pct": round(s["max_dd_pct"], 2),
        "halts": len(events["halts"]),
        "halt_events": events["halts"],
        "restart": events["restart_date"] is not None,
        "restart_date": events["restart_date"],
        "second_halt": events["second_halt"],
        "costs": round(s["total_costs"], 2),
        "orders": s["orders"],
        "entries": s["entries"],
        "closed_trades": s["closed_trades"],
        "win_rate_pct": (round(s["win_rate"], 1)
                         if s["win_rate"] is not None else None),
        "end_date": s["end_date"],
        "open_positions": s["open_positions"],
        "placebo_beaten": (f"{beaten}/20" if beaten is not None else None),
        "placebo_finals": [round(f, 2) for f in placebo_finals],
    }


def spy_dividend_adjusted(mkt):
    """Total-return SPY buy-and-hold on the decade, tournament cost
    convention, from Yahoo adjclose. Returns None if the fetch fails."""
    try:
        import urllib.request
        p1 = int(datetime(2016, 11, 1, tzinfo=timezone.utc).timestamp())
        p2 = int(datetime(2026, 11, 22, tzinfo=timezone.utc).timestamp())
        url = ("https://query1.finance.yahoo.com/v8/finance/chart/SPY"
               f"?period1={p1}&period2={p2}&interval=1d&events=div,splits")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        result = payload["chart"]["result"][0]
        adj = result["indicators"]["adjclose"][0]["adjclose"]
        close = result["indicators"]["quote"][0]["close"]
        ts = result["timestamp"]
        rows = []
        for i, t in enumerate(ts):
            d = datetime.fromtimestamp(t, tz=timezone.utc).date()
            if adj[i] is None or close[i] is None:
                continue
            rows.append((d, adj[i], close[i]))
        rows = [r for r in rows if E.TEST_START <= r[0] <= E.TEST_END]
        first_adj, last_adj = rows[0][1], rows[-1][1]
        # buy at the first test close (adjclose is a close series), sell at
        # the last test close, tournament costs on both sides
        buy_value = E.START_CASH / (1 + E.COST_RATE)
        shares = buy_value / first_adj
        sell_value = shares * last_adj
        net = sell_value - (E.COST_RATE * sell_value + E.SELL_FEE)
        return round(net, 2)
    except Exception as exc:
        print(f"  dividend-adjusted SPY fetch failed: {exc}")
        return None


def main():
    print("Loading market (read-only tournament cache)...")
    mkt = E.build_market()
    print(f"Test window: {mkt.test_dates[0]} -> {mkt.test_dates[-1]} "
          f"({len(mkt.test_dates)} trading days)")

    spy_gross, spy_net = E.spy_benchmark_price_only(mkt)
    print(f"SPY price-only: gross ${spy_gross:.2f} / net ${spy_net:.2f}")
    spy_div = spy_dividend_adjusted(mkt)
    print(f"SPY dividend-adjusted (computed): {spy_div}")

    # ------------------------------------------------------------------
    # 1) INTEGRITY — original tournament form (ladder floor, ends at halt)
    # ------------------------------------------------------------------
    print("\n--- INTEGRITY (original ladder-era rules) ---")
    pf, _ = E.run_gap(mkt, "g_gap_up_integrity", cadence="daily",
                      protection="ladder")
    s = E.score(pf, mkt.test_dates[0])
    print(f"real:     final ${s['final']:.2f}  orders {s['orders']}  "
          f"closed {s['closed_trades']}  costs ${s['total_costs']:.2f}  "
          f"maxDD {s['max_dd_pct']:.1f}%  halt {s['halt_date']}")
    n_entries = s["entries"]
    sched = E.make_placebo_schedule(mkt.test_dates[:-1], E.STOCK_UNIVERSE,
                                    n_entries, ORIGINAL_PLACEBO_SEED)
    ppf, _ = E.run_gap(mkt, "g_gap_up_placebo_integrity", cadence="daily",
                       protection="ladder", placebo_schedule=sched)
    ps = E.score(ppf, mkt.test_dates[0])
    print(f"placebo:  final ${ps['final']:.2f}  entries {ps['entries']} "
          f"(target {n_entries})  seed {ORIGINAL_PLACEBO_SEED}")

    ok_real = abs(s["final"] - 84.04) < 0.02 and s["halt_date"] == "2020-01-16"
    ok_pl = abs(ps["final"] - 97.91) < 0.02
    integrity_status = "reproduced" if (ok_real and ok_pl) else "FAILED"
    print(f"integrity: {integrity_status}")
    with open(os.path.join(CELLS, "integrity.json"), "w") as f:
        json.dump({
            "mode": "original tournament form: ladder floor, run ends at "
                    "halt, daily cadence, split-adjusted bars, costs "
                    "0.10%/side + $0.01/sell",
            "real": {"final": round(s["final"], 2), "orders": s["orders"],
                     "closed_trades": s["closed_trades"],
                     "costs": round(s["total_costs"], 2),
                     "max_dd_pct": round(s["max_dd_pct"], 2),
                     "halt_date": s["halt_date"],
                     "equity_curve": curve_json(pf)},
            "placebo": {"seed": ORIGINAL_PLACEBO_SEED,
                        "target_entries": n_entries,
                        "actual_entries": ps["entries"],
                        "final": round(ps["final"], 2),
                        "equity_curve": curve_json(ppf)},
            "published": {"real_final": 84.04, "halt_date": "2020-01-16",
                          "placebo_final": 97.91, "placebo_margin": -13.87},
            "status": integrity_status,
        }, f, indent=1)

    # ------------------------------------------------------------------
    # 2) + 3) SWEEP with v9 protections + 20-seed placebos per cadence
    # ------------------------------------------------------------------
    cells = {}
    for cad in E.CADENCES:
        print(f"\n--- cadence: {cad} (v9 protections) ---")
        pf, events = E.run_gap(mkt, f"g_gap_up_{cad}", cadence=cad,
                               protection="v9")
        s = E.score(pf, mkt.test_dates[0])
        cad_dates = sorted(E.cadence_dates(mkt.test_dates, cad))
        pool = cad_dates[:-1] if len(cad_dates) > 1 else cad_dates
        placebo_finals = []
        for seed in PLACEBO_SEEDS:
            sched = E.make_placebo_schedule(pool, E.STOCK_UNIVERSE,
                                            s["entries"], seed)
            ppf, _ = E.run_gap(mkt, f"g_gap_up_{cad}_placebo", cadence=cad,
                               protection="v9", placebo_schedule=sched)
            placebo_finals.append(E.score(ppf, mkt.test_dates[0])["final"])
        _, rec = cell_record(pf, events, placebo_finals)
        rec["cadence"] = cad
        rec["n_cadence_dates"] = len(cad_dates)
        rec["equity_curve"] = curve_json(pf)
        rec["placebo_seeds"] = PLACEBO_SEEDS
        rec["placebo_note"] = (
            "20 seeds (42107..42126); random entries drawn from this "
            "cadence's dates (all but the last), random symbols, entry "
            "count matched to the real run's buys at this cadence; "
            "identical exits, sizing, costs and v9 protections.")
        cells[cad] = rec
        with open(os.path.join(CELLS, f"{cad}.json"), "w") as f:
            json.dump(rec, f, indent=1)
        print(f"final ${rec['final']:.2f}  CAGR {rec['cagr_pct']}%  "
              f"maxDD {rec['max_dd_pct']}%  orders {rec['orders']}  "
              f"costs ${rec['costs']:.2f}  halts {rec['halts']}  "
              f"restart {rec['restart']}  placebo beaten "
              f"{rec['placebo_beaten']}")

    # ------------------------------------------------------------------
    # results.json (SPEC sweep format)
    # ------------------------------------------------------------------
    spy_for_cells = spy_div if spy_div is not None else 367.80
    money = [c for c in E.CADENCES
             if cells[c]["final"] > spy_for_cells
             and cells[c]["placebo_beaten"] not in (None, "0/20")
             and int(cells[c]["placebo_beaten"].split("/")[0]) > 10]
    results = {
        "slug": "gap-up-continuation",
        "area": "SHORT-CYCLE daily price style (W9): overnight gap-up "
                "continuation with 3-day exits, cycled and compounded "
                "over the full DECADE road",
        "area_source": "SPEC W9 assignment + CADENCE GRID (gap-up-"
                       "continuation = daily)",
        "native_cadence": "daily",
        "cadence": "daily",
        "original_cadence_foreign": False,
        "original_cadence_note": "The v2 tournament ran this style daily, "
                                 "which IS its native cadence — not foreign.",
        "integrity": {
            "status": integrity_status,
            "original_finals": {"real": 84.04, "halt_date": "2020-01-16",
                                "orders": 96, "closed_trades": 48,
                                "costs": 5.11, "max_dd_pct": 23.1,
                                "placebo_seed": ORIGINAL_PLACEBO_SEED,
                                "placebo_final": 97.91,
                                "placebo_margin_real_minus_placebo": -13.87},
            "reproduced_finals": {"real": round(s["final"], 2),
                                  "halt_date": s["halt_date"],
                                  "orders": s["orders"],
                                  "closed_trades": s["closed_trades"],
                                  "costs": round(s["total_costs"], 2),
                                  "max_dd_pct": round(s["max_dd_pct"], 2),
                                  "placebo_final": round(ps["final"], 2),
                                  "placebo_actual_entries": ps["entries"]},
            "conventions": "split-adjusted Yahoo bars from the "
                           "tournament's own cache; ladder-era floor "
                           "($85, rising to $100 at a $125 close and $125 "
                           "at a $150 close; touch liquidates at next "
                           "open and ENDS the run); costs 0.10%/side + "
                           "$0.01 per sell order",
        },
        "decade_spy_final": spy_for_cells,
        "decade_spy": {
            "price_only_net": round(spy_net, 2),
            "price_only_gross": round(spy_gross, 2),
            "dividend_adjusted_net": spy_for_cells,
            "dividend_adjusted_source": (
                "computed in this run from Yahoo adjclose, tournament "
                "cost convention" if spy_div is not None else
                "SPEC reference $367.80 (W6 verified plumbing); local "
                "adjclose fetch failed, figure carried from the SPEC"),
        },
        "champion_decade_reference": {
            "final": 65.89,
            "caveat": "Champion (Value+Momentum) DECADE $65.89 after two "
                      "halts, per the SPEC/lazy-quarterly test; its crown "
                      "rests on the 2010 and 2019 roads, not the decade.",
        },
        "cells": {
            c: {k: cells[c][k] for k in
                ("final", "cagr_pct", "max_dd_pct", "halts", "restart",
                 "second_halt", "costs", "orders", "placebo_beaten",
                 "placebo_note")}
            for c in E.CADENCES
        },
        "money_cadences": money,
        "verdict_area": None,   # filled in RESULTS.md narrative; set below
        "verdict_change": None,
        "cadence_treatment": (
            "Gap gate evaluated only at cadence-date opens; stop/target "
            "and the 3-trading-day time exit reviewed only on cadence "
            "dates (SPEC uniform rule). At slower cadences a position is "
            "therefore held until the next cadence date — the published "
            "rule stays expressible at every cadence, so no cell is N/A; "
            "what changes is the holding period, which is the deformation "
            "the sweep exists to measure. v9 floor marked at every close "
            "and liquidated at the next open in all cells; restart waits "
            "for the next cadence date after the 90-day cash sit."),
    }
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("\nWrote cells/*.json and results.json")
    print("money cadences (beat div-adj SPY AND placebo majority):", money)


if __name__ == "__main__":
    main()
