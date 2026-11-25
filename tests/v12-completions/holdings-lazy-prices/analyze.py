#!/usr/bin/env python3
"""
Post-pass: (1) confirmation evidence — fresh-pot calendar-year folds
2020-2026 (different years than the road windows' judging use) for
counts 1, 5, 30 under the house form on the Nov-2016 pond;
(2) per-period (quarterly) distributions from the saved curves for
the native count 5 and for counts 1 and 30 (the road winners on VAL
and LONG), house form, all roads. Appends both to results.json.
"""
import json
import os
import sys
from datetime import date as _date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_sweep as RS  # noqa: E402

OUT_PATH = RS.OUT_PATH


def period_distribution(curve):
    qtrs = {}
    for d, v in curve:
        qtrs[(d[:4], (int(d[5:7]) - 1) // 3)] = v
    keys = sorted(qtrs)
    rets, prev = [], curve[0][1]
    for k in keys:
        v = qtrs[k]
        rets.append(v / prev - 1.0)
        prev = v
    srt = sorted(rets)
    m = len(srt)
    median = srt[m // 2] if m % 2 else 0.5 * (srt[m // 2 - 1] + srt[m // 2])
    longest_loss = run = 0
    for r in rets:
        run = run + 1 if r < 0 else 0
        longest_loss = max(longest_loss, run)
    peak, last_high_d, longest_gap = -1.0, None, 0
    for d, v in curve:
        if v >= peak:
            if last_high_d is not None:
                longest_gap = max(longest_gap, (_date.fromisoformat(d)
                                   - _date.fromisoformat(last_high_d)).days)
            peak, last_high_d = v, d
    if last_high_d:
        longest_gap = max(longest_gap, (_date.fromisoformat(curve[-1][0])
                          - _date.fromisoformat(last_high_d)).days)
    return {"periods": len(rets),
            "pct_periods_profitable": round(
                100.0 * sum(1 for r in rets if r > 0) / len(rets), 1),
            "median_period_pct": round(median * 100, 2),
            "best_period_pct": round(max(rets) * 100, 2),
            "worst_period_pct": round(min(rets) * 100, 2),
            "avg_period_pct_secondary": round(
                sum(rets) / len(rets) * 100, 2),
            "longest_losing_run_periods": longest_loss,
            "longest_stretch_between_new_highs_days": longest_gap}


def main():
    with open(OUT_PATH) as f:
        out = json.load(f)

    # ---- folds: fresh $100 pot per calendar year, house (v9) form,
    # plain run_pot_n episode mechanics via run_cell house wrapper
    book, sims, uni, _s, _e = RS.road_setup("CONT")
    folds = {}
    for n in (1, 5, 30):
        rows, comp = [], 100.0
        for y in range(2020, 2027):
            ws = f"{y}-01-02"
            we = "2026-11-20" if y == 2026 else f"{y}-12-31"
            r = RS.run_cell(book, sims, uni, ws, we, n, "house")
            rows.append({"year": y, "final": r["final"],
                         "halts": r["halts"]})
            comp *= r["final"] / 100.0
        folds[str(n)] = {"years": rows,
                         "fold_compounded_final": round(comp, 2),
                         "years_beating_native5": None}
    base = {r["year"]: r["final"] for r in folds["5"]["years"]}
    for n in ("1", "30"):
        folds[n]["years_beating_native5"] = sum(
            1 for r in folds[n]["years"] if r["final"] > base[r["year"]])
    out["confirmation_folds_house_2020_2026"] = folds
    print("folds:", json.dumps(folds), flush=True)

    # ---- period distributions from saved curves
    dists = {}
    for road in ("LONG", "DECADE", "CONT", "VAL"):
        for n in ("5", "1", "30"):
            key = f"{road}|house|{n}"
            curve = [(d, v) for d, v in out["curves"][key]]
            dists[key] = period_distribution(curve)
    out["period_distributions"] = dists
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, indent=1)
    print("distributions saved", flush=True)


if __name__ == "__main__":
    main()
