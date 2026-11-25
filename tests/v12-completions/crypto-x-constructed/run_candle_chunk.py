#!/usr/bin/env python3
"""Chunk driver for Form A (runtime kills long detached jobs): runs coins
[lo,hi) of the sorted registry, always including BTC for the benchmark,
saves chunk_<lo>_<hi>.json. Merge with merge_results.py."""
import json, os, sys
import run_all as R

HERE = os.path.dirname(os.path.abspath(__file__))

def main():
    lo, hi = int(sys.argv[1]), int(sys.argv[2])
    reg = R.load_registry_oc()
    cal = [r["d"] for r in reg[1]["rows"]]
    keys = sorted(reg.keys())
    sel = keys[lo:hi]
    sub = {1: reg[1]}
    for k in sel: sub[k] = reg[k]
    out = R.run_candle(sub, cal)
    with open(os.path.join(HERE, f"chunk_{lo}_{hi}.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("chunk saved", lo, hi, flush=True)

if __name__ == "__main__":
    main()
