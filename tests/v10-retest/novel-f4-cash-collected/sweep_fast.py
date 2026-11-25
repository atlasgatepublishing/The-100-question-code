#!/usr/bin/env python3
"""
Continuation of sweep.py for the remaining cadences (biweekly..annual).
Identical strategy math — the ONLY change is plumbing: a bisect-indexed
price book replaces the original engine's linear-scan close_on_or_before
(same returned values; the shared box was CPU-starved). Picks are loaded
from picks_by_date.json, written by sweep.py's scoring pass (frozen-spec
scores, unchanged). A daily-cadence cross-check against the already-saved
cells/daily.json runs first and must match to the cent before the
remaining cells are taken.
"""
import bisect, json, os, random, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import engine_original as eng
import sweep as sw

START, END, START_CASH = sw.START, sw.END, sw.START_CASH

class FastBook:
    """Same interface/semantics as eng.PriceBook (bar, close_on_or_before,
    dates) with indexed lookups."""
    def __init__(self, bars_by_ticker):
        self.bars = bars_by_ticker
        self.dates = sorted({b["d"] for bl in bars_by_ticker.values() for b in bl})
        self.idx = {t: {b["d"]: b for b in bl} for t, bl in bars_by_ticker.items()}
        self._dl = {t: [b["d"] for b in bl] for t, bl in bars_by_ticker.items()}
        self._cl = {t: [b["c"] for b in bl] for t, bl in bars_by_ticker.items()}

    def bar(self, t, d):
        return self.idx.get(t, {}).get(d)

    def close_on_or_before(self, t, d):
        dl = self._dl.get(t)
        if not dl:
            return None
        i = bisect.bisect_right(dl, d) - 1
        return self._cl[t][i] if i >= 0 else None

def run_cell(pb, picks_by_date, cad):
    sel = sw.cadence_dates(pb, cad, START, END)
    r = sw.run_pot_v9c(pb, picks_by_date, sel, START, END, START_CASH,
                       label=f"DECADE {cad}")
    m = sw.metrics(r, START, END)
    twins = []
    for seed in range(1, 21):
        rng = random.Random(seed)
        tw = sw.run_pot_v9c_placebo(pb, picks_by_date, sel, START, END,
                                    START_CASH, rng)
        twins.append({"seed": seed, "final": round(tw["final"], 2),
                      "halted_first": tw["halted"],
                      "second_halt": bool(tw["second_halt"])})
    beats = sum(1 for tw in twins if r["final"] > tw["final"])
    finals_sorted = sorted(tw["final"] for tw in twins)
    cell = {**m,
            "halts": (1 if r["halted"] else 0) + (1 if r["second_halt"] else 0),
            "first_halt": r["halted"],
            "restart": bool(r["restarts"]),
            "restarts": r["restarts"],
            "second_halt": bool(r["second_halt"]),
            "second_halt_detail": r["second_halt"],
            "placebo_beaten": beats,
            "placebo_median_twin_final": finals_sorted[9],
            "placebo_twin_finals": twins,
            "equity_curve": [[d, round(v, 2)] for d, v in r["curve"]],
            "n_selection_dates": len(sel)}
    return cell

def main():
    bars = {t: sw.get_prices_local(t) for t in eng.UNIVERSE + ["SPY"]}
    pb = FastBook(bars)
    with open(os.path.join(HERE, "picks_by_date.json")) as f:
        picks_by_date = json.load(f)
    print(f"book {pb.dates[0]}..{pb.dates[-1]}; picks for "
          f"{len(picks_by_date)} dates", flush=True)

    # cross-check: daily must reproduce the sweep.py cell to the cent
    saved = json.load(open(os.path.join(HERE, "cells", "daily.json")))
    chk = run_cell(pb, picks_by_date, "daily")
    assert chk["final"] == saved["final"] and \
        chk["placebo_median_twin_final"] == saved["placebo_median_twin_final"] and \
        chk["placebo_beaten"] == saved["placebo_beaten"], \
        (chk["final"], saved["final"])
    print(f"CROSS-CHECK daily: fast=${chk['final']} saved=${saved['final']} "
          f"median twin ${chk['placebo_median_twin_final']} — MATCH", flush=True)

    for cad in ["biweekly", "monthly", "quarterly", "semiannual", "annual"]:
        t0 = time.time()
        cell = run_cell(pb, picks_by_date, cad)
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump({"slug": "novel-f4-cash-collected", "cadence": cad,
                       "window": {"start": START, "end": END},
                       "start_cash": START_CASH, **cell}, f, indent=1)
        print(f"{cad}: final=${cell['final']:,.2f} CAGR={cell['cagr_pct']}% "
              f"maxDD={cell['max_dd_pct']}% costs=${cell['costs']} "
              f"orders={cell['orders']} halts={cell['halts']} "
              f"restart={cell['restart']} placebo {cell['placebo_beaten']}/20 "
              f"median twin ${cell['placebo_median_twin_final']:,.2f} "
              f"({time.time()-t0:.0f}s)", flush=True)
    print("FAST SWEEP DONE", flush=True)

if __name__ == "__main__":
    main()
