#!/usr/bin/env python3
"""v0-aggressive house-rule confirmation (Terry's rule) -> confirm_v0.json.
Counts 3, 5, 8, 10 each beat native count 2 on ALL four roads under house
(v9) rules in the sweep grid, so each is re-run on different years:
fresh-$100 calendar folds 2017-2026 + two half-windows, vs native 2.
ALL-ELIGIBLE = count 10 by construction (10-name universe) and inherits
count 10's result. Simulation only. Writes via tmp + atomic rename."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_sweep as R

data = R.v0_load()
def house(start, end, count):
    return R.v0_run(data, start, end, count, "house")["final"]

cache = {}
def native(start, end):
    if (start, end) not in cache:
        cache[(start, end)] = house(start, end, 2)
    return cache[(start, end)]

out = {}
for cand in (3, 5, 8, 10):
    folds = {}
    for yr in range(2017, 2027):
        sd, ed = f"{yr}-01-01", f"{yr}-12-31"
        folds[str(yr)] = {"candidate": round(house(sd, ed, cand), 2),
                          "native2": round(native(sd, ed), 2)}
    halves = {}
    for lbl, (sd, ed) in {"H1": ("2016-11-21", "2021-12-31"),
                          "H2": ("2022-01-01", "2026-11-20")}.items():
        halves[lbl] = {"candidate": round(house(sd, ed, cand), 2),
                       "native2": round(native(sd, ed), 2)}
    wins = sum(1 for v in folds.values() if v["candidate"] > v["native2"])
    hwins = sum(1 for v in halves.values() if v["candidate"] > v["native2"])
    out[str(cand)] = {"folds": folds, "fold_wins_of_10": wins, "halves": halves,
                      "confirmed": bool(wins >= 6 and hwins == 2)}
    print(f"count {cand}: folds {wins}/10 confirmed={out[str(cand)]['confirmed']}",
          flush=True)
    print("  folds:", json.dumps(folds), flush=True)
    print("  halves:", json.dumps(halves), flush=True)
out["ALL"] = {"note": "ALL-ELIGIBLE identical to count 10 by construction "
                      "(10-name universe); inherits count 10's confirmation",
              "inherits_count": "10", "confirmed": out["10"]["confirmed"]}
tmp = os.path.join(HERE, "confirm_v0.json.tmp")
with open(tmp, "w") as f:
    json.dump(out, f, indent=1)
os.replace(tmp, os.path.join(HERE, "confirm_v0.json"))
print("saved confirm_v0.json", flush=True)
