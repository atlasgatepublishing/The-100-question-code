#!/usr/bin/env python3
"""Verify the speedups in sy_v10.py are result-identical: reproduce the
already-saved annual cell (ranked final, full curve, placebo seed 1),
the quarterly ranked final, and the semiannual ranked final (from the
slow-path log) using the fast plumbing."""
import importlib.util
import json
import os
import random
import time

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("sy_v10", os.path.join(HERE, "sy_v10.py"))
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
E, SY = M.E, M.SY

rows = M.build_rows()
bars, divs = {}, {}
for t in M.UNIVERSE:
    b, dv = M.raw_bars_divs_from_payload(M.load_payload_full(t))
    bars[t] = b
    divs[t] = dv
pb = M.FastPriceBook(bars)

ann = json.load(open(os.path.join(HERE, "cells", "annual.json")))
qrt = json.load(open(os.path.join(HERE, "cells", "quarterly.json")))

M.STATE["cadence"] = "annual"
t0 = time.time()
r = M.run_v9g(pb, divs, rows, *M.DECADE)
print(f"annual ranked fast: {r['final']:.2f} vs saved {ann['final']} "
      f"curve_equal={[[d, round(v,4)] for d, v in r['curve']] == ann['equity_curve']} ({time.time()-t0:.0f}s)", flush=True)
rp = M.run_v9g(pb, divs, rows, *M.DECADE, placebo_rng=random.Random(1))
print(f"annual placebo seed1 fast: {rp['final']:.2f} vs saved {ann['placebo_twin_finals'][0]}", flush=True)

M.STATE["cadence"] = "quarterly"
rq = M.run_v9g(pb, divs, rows, *M.DECADE)
print(f"quarterly ranked fast: {rq['final']:.2f} vs saved {qrt['final']}", flush=True)

M.STATE["cadence"] = "semiannual"
rs = M.run_v9g(pb, divs, rows, *M.DECADE)
print(f"semiannual ranked fast: {rs['final']:.2f} vs slow-path log 268.17", flush=True)
print("VERIFY DONE", flush=True)
