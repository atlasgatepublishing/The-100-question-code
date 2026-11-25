#!/usr/bin/env python3
"""Follow-up confirmation for count 3 (it also beat native count 5 on
4/4 roads under house rules, so Terry's CONFIRMATION RULE applies to
it too — same pre-registered confirmation as run_sweep.py used for
the overall winner count 2: fresh-$100 calendar-year folds 2017..2026
+ DECADE half-windows, fixed pond, house rules, head-to-head vs 5).
Appends its result into results.json under confirmation_count3."""
import json
import os

import run_sweep as R

HERE = os.path.dirname(os.path.abspath(__file__))

pb, pit_eq, pit_sh, universe = R.build_fixed_inputs()
all_sel = R.quarter_dates(pb, "2016-11-21", R.END)
dec = R.compute_decisions(pb, pit_eq, pit_sh, universe, all_sel)

cand = 3
folds = {}
for yr in range(2017, 2027):
    s = f"{yr}-01-01"
    e = R.END if yr == 2026 else f"{yr}-12-31"
    sel = R.quarter_dates(pb, s, e)
    rc = R.run_house(pb, dec, sel, s, e, cand)
    r5 = R.run_house(pb, dec, sel, s, e, 5)
    folds[str(yr)] = {"candidate_final": round(rc["final"], 2),
                      "native5_final": round(r5["final"], 2),
                      "candidate_wins": rc["final"] > r5["final"]}
halves = {}
for hn, (s, e) in {"H1_2016-2021": ("2016-11-21", "2021-12-31"),
                   "H2_2022-2026": ("2022-01-01", R.END)}.items():
    sel = R.quarter_dates(pb, s, e)
    rc = R.run_house(pb, dec, sel, s, e, cand)
    r5 = R.run_house(pb, dec, sel, s, e, 5)
    halves[hn] = {"candidate_final": round(rc["final"], 2),
                  "native5_final": round(r5["final"], 2),
                  "candidate_wins": rc["final"] > r5["final"]}
wins = sum(1 for v in folds.values() if v["candidate_wins"])
hwins = sum(1 for v in halves.values() if v["candidate_wins"])
out = {"candidate_count": cand, "year_folds": folds,
       "fold_wins": f"{wins}/10", "half_windows": halves,
       "confirmed": bool(wins >= 6 and hwins >= 1)}
print(json.dumps(out, indent=1), flush=True)

path = os.path.join(HERE, "results.json")
with open(path) as f:
    res = json.load(f)
res["confirmation_count3"] = out
with open(path, "w") as f:
    json.dump(res, f, indent=1)
print("saved into results.json", flush=True)
