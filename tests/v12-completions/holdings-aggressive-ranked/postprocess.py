#!/usr/bin/env python3
"""
Post-processing for the ranked-aggressive holdings sweep:
  1. CONFIRMATION (Terry's rule) for any non-native count that beat the
     native count on ALL roads under house rules — found mechanically
     from results.json. (Pre-analysis: only v0-aggressive house counts
     3, 5, 8, 10 qualify; ALL-ELIGIBLE is identical to count 10 by
     construction and inherits its confirmation.)
     Folds: fresh-$100 calendar years 2017-2026 + two half-windows,
     head-to-head vs native count 2, house (v9) protection.
  2. Per-period (daily) distributions for the winning count (highest
     summed finals across roads) and the native count, DECADE road,
     every protection form — from curves.pkl.
  3. Equity curves for winner/native DECADE cells are copied into
     results.json (all other curves stay in curves.pkl).
Simulation only.
"""
import json, os, pickle, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_sweep as R

res = json.load(open(os.path.join(HERE, "results.json")))
curves = pickle.load(open(os.path.join(HERE, "curves.pkl"), "rb"))

# ---------------- 1. v0 confirmation -----------------------------------
data = R.v0_load()
def v0_house(start, end, count):
    return R.v0_run(data, start, end, count, "house")["final"]

conf = {}
native_cache = {}
def native_v0(start, end):
    if (start, end) not in native_cache:
        native_cache[(start, end)] = v0_house(start, end, 2)
    return native_cache[(start, end)]

for cand in (3, 5, 8, 10):
    folds = {}
    for yr in range(2017, 2027):
        sd, ed = f"{yr}-01-01", f"{yr}-12-31"
        folds[str(yr)] = {"candidate": round(v0_house(sd, ed, cand), 2),
                          "native2": round(native_v0(sd, ed), 2)}
    halves = {}
    for lbl, (sd, ed) in {"H1": ("2016-11-21", "2021-12-31"),
                          "H2": ("2022-01-01", "2026-11-20")}.items():
        halves[lbl] = {"candidate": round(v0_house(sd, ed, cand), 2),
                       "native2": round(native_v0(sd, ed), 2)}
    wins = sum(1 for v in folds.values() if v["candidate"] > v["native2"])
    hwins = sum(1 for v in halves.values() if v["candidate"] > v["native2"])
    conf[str(cand)] = {"folds": folds, "fold_wins_of_10": wins,
                       "halves": halves,
                       "confirmed": bool(wins >= 6 and hwins == 2)}
    print(f"v0 confirmation count {cand}: folds {wins}/10 halves {halves} "
          f"confirmed={conf[str(cand)]['confirmed']}", flush=True)
conf["ALL"] = {"note": "ALL-ELIGIBLE is identical to count 10 by construction "
                       "(10-name universe); it inherits count 10's confirmation",
               "inherits_count": "10", "confirmed": conf["10"]["confirmed"]}
res["families"]["v0-aggressive"]["confirmation_house"] = conf

# ---------------- 2. distributions + winner curves ----------------------
def fam_winner(fam_name, key_prefix, roads):
    cells = res["families"][fam_name]["cells"]
    totals = {}
    for k, c in cells.items():
        if k.startswith(key_prefix) and str(c["count"]) in (
                "1", "2", "3", "5", "8", "10"):
            totals[str(c["count"])] = totals.get(str(c["count"]), 0) + c["final"]
    return max(totals, key=totals.get), {k: round(v, 2) for k, v in totals.items()}

SPECS = [
    # (family, key prefix builder, native count, roads)
    ("v0-aggressive", "era", 2), ("v0-aggressive", "house", 2),
    ("aggressive-v2", "original", 2), ("aggressive-v2", "house", 2),
    ("aggressive-v3", "house|combo", 2), ("aggressive-v3", "house|base", 2),
    ("aggressive-v3", "original|combo", 2), ("aggressive-v3", "original|base", 2),
    ("high-winrate-lab-H4", "house", 5),
]
dists = {}
saved_curves = {}
for fam_name, prefix, native in SPECS:
    if fam_name not in res["families"]:
        continue
    cells = res["families"][fam_name]["cells"]
    # roads for this prefix
    roads = sorted({c["road"] for k, c in cells.items() if k.startswith(prefix + "|")})
    totals = {}
    for k, c in cells.items():
        if k.startswith(prefix + "|") and str(c["count"]) in ("1", "2", "3", "5", "8", "10"):
            totals[str(c["count"])] = totals.get(str(c["count"]), 0) + c["final"]
    if not totals:
        continue
    winner = max(totals, key=totals.get)
    res["families"][fam_name].setdefault("house_totals_by_prefix", {})[prefix] = {
        "totals": {k: round(v, 2) for k, v in totals.items()}, "winner": winner}
    for cnt in {winner, str(native)}:
        ck = f"{fam_name}|{prefix}|DECADE|{cnt}"
        if ck in curves:
            dists[f"{prefix}|DECADE|{cnt}"] = R.period_distribution(curves[ck])
            saved_curves[ck] = curves[ck]
    print(f"{fam_name} {prefix}: totals={ {k: round(v,2) for k,v in totals.items()} } "
          f"winner={winner} native={native}", flush=True)

res.setdefault("period_distributions_DECADE", {}).update(
    {f"{fam}|{k}": v for fam in ("v0-aggressive", "aggressive-v2",
                                 "aggressive-v3", "high-winrate-lab-H4")
     for k, v in dists.items() if True})
# simpler: store flat with family prefix already in key construction above;
# rebuild cleanly:
res["period_distributions_DECADE"] = {}
for fam_name, prefix, native in SPECS:
    if fam_name not in res["families"]:
        continue
    cells = res["families"][fam_name]["cells"]
    totals = {}
    for k, c in cells.items():
        if k.startswith(prefix + "|") and str(c["count"]) in ("1", "2", "3", "5", "8", "10"):
            totals[str(c["count"])] = totals.get(str(c["count"]), 0) + c["final"]
    if not totals:
        continue
    winner = max(totals, key=totals.get)
    for cnt in {winner, str(native)}:
        ck = f"{fam_name}|{prefix}|DECADE|{cnt}"
        if ck in curves:
            res["period_distributions_DECADE"][f"{fam_name}|{prefix}|DECADE|{cnt}"] = \
                R.period_distribution(curves[ck])
            saved_curves[ck] = curves[ck]
res["curves_DECADE_winner_and_native"] = saved_curves

with open(os.path.join(HERE, "results.json"), "w") as f:
    json.dump(res, f, indent=1)
print("postprocess saved", flush=True)
