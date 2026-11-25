#!/usr/bin/env python3
"""ENGINE VALIDATION ONLY — synthetic sentiment, NOT a result.
Generates a fake weekly II series in /tmp (deterministic sine + noise),
runs the frozen engine on real SPY bars to prove the plumbing works and
the SPY buy-hold comparator reproduces the settled record. Nothing here
is evidence about the II signal and nothing is written to results.json."""
import csv, math, os, random, sys
from datetime import date, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_best_rules as E

# synthetic prints: Wednesdays 2009-12-30 .. 2026-11-18
path = "/tmp/ii_synthetic.csv"
rng = random.Random(42)
d = date(2009, 12, 30); rows = []
while d <= date(2026, 11, 18):
    t = (d - date(2010, 1, 1)).days / 365.25
    bulls = 48 + 14 * math.sin(2 * math.pi * t / 3.7) + rng.uniform(-3, 3)
    bears = max(8.0, 62 - bulls + rng.uniform(-2, 2))
    rows.append({"publication_date": d.isoformat(), "bulls_pct": round(bulls, 1), "bears_pct": round(bears, 1)})
    d += timedelta(days=7)
with open(path, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["publication_date", "bulls_pct", "bears_pct"]); w.writeheader(); w.writerows(rows)

# dial unit checks against the frozen spec table
assert E.target_weight(61, 20) == 0.0 and E.target_weight(57, 20) == 0.25
assert E.target_weight(51, 20) == 0.50 and E.target_weight(45, 20) == 0.75
assert E.target_weight(35, 20) == 1.0 and E.target_weight(50, 56) == 1.0  # bears override
print("dial unit checks: PASS")

prints = E.load_ii(path); bars_all = E.load_spy()
for road, (s, e) in E.ROADS.items():
    bars = [b for b in bars_all if s <= b["d"] <= e]
    rp = [p for p in prints if p["pub"] < e and p["pub"] >= bars[0]["d"]]
    res = E.simulate(bars, E.build_weight_path(bars, rp))
    bh = E.buyhold(bars)
    print(f"{road}: synthetic-dial final ${res['final']:.2f} (maxDD {res['maxdd']}%, trades {res['trades']}, "
          f"costs ${res['costs']}) | SPY buy-hold same plumbing ${bh} vs settled ${E.SPYREF[road]}")
print("ENGINE VALIDATION COMPLETE — synthetic data only; no result recorded.")
