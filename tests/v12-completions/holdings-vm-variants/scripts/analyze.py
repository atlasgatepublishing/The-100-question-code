#!/usr/bin/env python3
"""Assemble results.json + verdicts + per-period distributions from
results_pond.json and results_broad.json. Reporting standard: periods at
the family's tempo; count, % profitable, MEDIAN, best, worst, longest
losing run, longest stretch between new highs; average secondary only.
"""
import json, os, statistics

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")

def period_stats(curve, start_value=100.0):
    """curve: [[label, value], ...] sampled at period ends (tempo tempo).
    Period 1 return is vs start_value."""
    vals = [start_value] + [v for _, v in curve]
    rets = []
    for a, b in zip(vals, vals[1:]):
        rets.append(b / a - 1.0 if a > 0 else 0.0)
    if not rets: return None
    n = len(rets)
    prof = sum(1 for r in rets if r > 0)
    longest_loss = 0; cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0
        longest_loss = max(longest_loss, cur)
    peak = vals[0]; stretch = 0; longest_stretch = 0
    for v in vals[1:]:
        if v > peak: peak = v; stretch = 0
        else: stretch += 1
        longest_stretch = max(longest_stretch, stretch)
    return {"periods": n, "pct_profitable": round(100.0 * prof / n, 1),
            "median_pct": round(statistics.median(rets) * 100, 2),
            "best_pct": round(max(rets) * 100, 2), "worst_pct": round(min(rets) * 100, 2),
            "longest_losing_run": longest_loss,
            "longest_stretch_between_new_highs_periods": longest_stretch,
            "average_pct_secondary": round(statistics.mean(rets) * 100, 2)}

def main():
    pond = json.load(open(os.path.join(ROOT, "results_pond.json")))
    broad = json.load(open(os.path.join(ROOT, "results_broad.json")))
    out = {"program": "v12 HOLDINGS-COUNT SWEEP — champion-variant shelf (holdings-vm-variants)",
           "spec": "SPEC.md", "counts_grid": [1, 2, 3, 5, 8, 10, 15, 20, 30, "ALL-ELIGIBLE"],
           "families": {}, "dispositions": {}}
    # ---- pond families: curves are quarterly samples (curve_q)
    for fam in ("vm-buffer", "vm-composite", "vm-twosleeve-house"):
        out["families"][fam] = pond[fam]
    # period stats for pond: native + best-by-sum cells per form/rules
    # ---- broad families: vm-broad curve is monthly marks; annual periods
    # derived from yearly rets in analyze step of RESULTS (yearly list saved)
    out["families"]["vm-broad"] = broad["vm-broad"]
    out["families"]["vm-twosleeve-constructed"] = broad["vm-twosleeve-constructed"]
    # period distributions
    dist = {}
    # vm-broad: annual periods from 'yearly' rets (native 30 + house 5 + winners filled by RESULTS pass)
    dist["vm-broad"] = {}
    for road, cells in broad["vm-broad"].items():
        dist["vm-broad"][road] = {}
        for key, cell in cells.items():
            rets = [y["ret"] for y in cell["yearly"]]
            curve = []
            v = 100.0
            for i, r in enumerate(rets):
                v = v * (1 + r); curve.append([str(i), round(v, 4)])
            dist["vm-broad"][road][key] = period_stats(curve)
    # twosleeve constructed: monthly curve
    dist["vm-twosleeve-constructed"] = {}
    for win, cells in broad["vm-twosleeve-constructed"].items():
        dist["vm-twosleeve-constructed"][win] = {}
        for key, cell in cells.items():
            dist["vm-twosleeve-constructed"][win][key] = period_stats(cell["curve"])
    # pond: quarterly curve_q
    dist["pond"] = {}
    for fam in ("vm-buffer", "vm-composite", "vm-twosleeve-house"):
        dist["pond"][fam] = {}
        src = pond[fam]
        roads = src if fam != "vm-buffer" else None
        if fam == "vm-buffer":
            for form, rmap in src.items():
                dist["pond"][fam][form] = {}
                for road, rd in rmap.items():
                    dist["pond"][fam][form][road] = {k: period_stats(c["curve_q"]) for k, c in rd["cells"].items()}
        else:
            for road, rd in src.items():
                dist["pond"][fam][road] = {k: period_stats(c["curve_q"]) for k, c in rd["cells"].items()}
    out["period_distributions"] = dist
    with open(os.path.join(ROOT, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("results.json assembled")

if __name__ == "__main__":
    main()
