#!/usr/bin/env python3
"""X4 confirmation: count 1 vs native 5, fresh-$100 calendar-year folds
2017..2026 + halves, house form (v10 driver run_v9)."""
import json, os
src = open(os.path.expanduser("~/workspace/stock-app/backtests/v10-retest/novel-x4-opex-release/driver.py")).read()
src = src.split("WINDOWS =")[0]
ns = {"__file__": os.path.expanduser("~/workspace/stock-app/backtests/v10-retest/novel-x4-opex-release/driver.py"),
      "__name__": "x4driver_head"}
exec(compile(src, "x4driver_head", "exec"), ns)
M = ns["M"]; build = ns["build"]; run_v9 = ns["run_v9"]
END = "2026-11-20"
folds = {}
for yr in range(2017, 2027):
    s = f"{yr}-01-01"; e = END if yr == 2026 else f"{yr}-12-31"
    row = {}
    for c in (1, 5):
        M.TOP_N = c
        r = run_v9(s, e, lambda s2, e2, af: build(3, s2, e2, af))
        row[str(c)] = round(r["final"], 2)
    row["win"] = row["1"] > row["5"]
    folds[str(yr)] = row
    print(yr, row, flush=True)
halves = {}
for hn, (s, e) in {"H1": ("2016-11-21", "2021-12-31"), "H2": ("2022-01-01", END)}.items():
    row = {}
    for c in (1, 5):
        M.TOP_N = c
        r = run_v9(s, e, lambda s2, e2, af: build(3, s2, e2, af))
        row[str(c)] = round(r["final"], 2)
    row["win"] = row["1"] > row["5"]
    halves[hn] = row
    print(hn, row, flush=True)
fw = sum(1 for v in folds.values() if v["win"])
hw = sum(1 for v in halves.values() if v["win"])
out = {"candidate": 1, "folds": folds, "fold_wins": fw, "halves": halves,
       "half_wins": hw, "confirmed": fw >= 6 and hw >= 1}
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "x4_confirmation.json"), "w"))
print("CONFIRM", out["fold_wins"], out["half_wins"], out["confirmed"])
