#!/usr/bin/env python3
"""Assemble results.json for the holdings-blends count sweep from the
five per-blend cells files + confirmation files. Computes the
per-period (quarterly) distributions for the winning and native
counts (house form) from the saved equity curves."""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sweep_common as SC  # noqa: E402

COUNTS = ["1", "2", "3", "5", "8", "10", "15", "20", "30", "ALL"]
BLENDS = {
    "combo-vm-nf3": ("cells_nf3.json", "confirm_nf3.json", 3),
    "combo-three-way": ("cells_3way.json", "confirm_3way.json", 3),
    "combo-vm-lazyp": ("cells_lazyp.json", "confirm_lazyp.json", 3),
    "winners-blend": ("cells_winners.json", "confirm_winners.json", 2),
    "grand-combination": ("cells_grand.json", "confirm_grand.json", 2),
}


def _safe_dump(obj, path):
    last = None
    for _i in range(40):
        try:
            with open(path, "w") as _f:
                json.dump(obj, _f, indent=1)
            return
        except PermissionError as _e:
            last = _e
            time.sleep(10)
    raise last


def main():
    out = {"wing": "holdings-blends (v12 holdings-count sweep)",
           "convention": "at grid count N, every sleeve holds its own "
                         "top-N; equal weight inside each sleeve "
                         "(basket sleeve: the parent's own 1/N slot "
                         "rule); native count = 5 per sleeve",
           "counts_grid": COUNTS, "blends": {}}
    for name, (cells_f, conf_f, winner_n) in BLENDS.items():
        d = json.load(open(os.path.join(HERE, cells_f)))
        cells = d["cells"]
        sums = {}
        for n in COUNTS:
            sums[n] = round(sum(cells[f"{r}|house|{n}"]["final"]
                                for r in ("DECADE", "CONT", "VAL")), 2)
        beats = {n: sum(1 for r in ("DECADE", "CONT", "VAL")
                        if cells[f"{r}|house|{n}"]["final"]
                        > cells[f"{r}|house|5"]["final"])
                 for n in COUNTS}
        conf = None
        cp = os.path.join(HERE, conf_f)
        if os.path.exists(cp):
            conf = json.load(open(cp))
        dist = {}
        for road in ("DECADE", "CONT"):
            dist[road] = {}
            for n in {str(winner_n), "5"}:
                curve = d["curves"].get(f"{road}|house|{n}")
                if curve:
                    dist[road][n] = SC.period_distribution(
                        [(x[0], x[1]) for x in curve])
        out["blends"][name] = {
            "integrity": d["integrity"],
            "house_road_sums": sums,
            "roads_beating_native_house": beats,
            "grid_winner_house_sum": str(winner_n),
            "confirmation": conf,
            "cells": cells,
            "period_distributions_house": dist}
        print(name, "sums:", sums, "beats:", beats,
              "confirmed:", None if conf is None else conf["confirmed"],
              flush=True)
    _safe_dump(out, os.path.join(HERE, "results.json"))
    print("results.json written", flush=True)


if __name__ == "__main__":
    main()
