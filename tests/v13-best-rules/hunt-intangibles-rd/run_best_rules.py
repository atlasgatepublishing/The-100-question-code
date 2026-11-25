#!/usr/bin/env python3
"""V13 best-rules run — hunt-intangibles-rd. Rules per BEST-RULES-SPEC.md
(frozen before this run): Li-form depreciated R&D capital stock / assets,
reporters-only with 5 consecutive reported positive R&D years (missing
xrd is NEVER zero-filled), small half defined on the eligible pool,
top quintile equal-weight, annual June formation (6-month PIT lag),
12-month hold, NO floor, tiered habitat costs, 20-seed placebos within
the eligible small-half pool. Roads are the honest June-to-June roads
(FULL 2018-2025 formations, CONT 2019-, VAL 2023-) — the stack cannot
honestly support 2010/2016 formations for a 5-year R&D stock."""
import json, os, sys, math, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from annual_lib import *

HERE = os.path.dirname(os.path.abspath(__file__))
V12 = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/hunt-intangibles-rd")
MF = load_my_frames(os.path.join(V12, "data", "frames"))
RD = "ResearchAndDevelopmentExpense"

SNAPS = {}
def snap(F):
    if F not in SNAPS: SNAPS[F] = E.snapshot(F)
    return SNAPS[F]

def ranked_best(F):
    """Returns (ranked_small_half_ciks, pool_dict_of_small_half)."""
    s = snap(F)
    pool_all = {}
    for c, v in MF.get((RD, F - 1), {}).items():
        if not v or v <= 0: continue
        sv = s.get(c)
        if not sv or not sv.get("cap") or not sv.get("px_adj") or not sv.get("assets"): continue
        stock = 0.0; ok = True
        for k, wgt in enumerate([1.0, 0.8, 0.6, 0.4, 0.2]):
            vv = MF.get((RD, F - 1 - k), {}).get(c)
            if vv is None or vv <= 0: ok = False; break
            stock += wgt * vv
        if ok: pool_all[c] = stock / sv["assets"]
    if len(pool_all) < 10: return [], {}
    medcap = statistics.median([s[c]["cap"] for c in pool_all])
    small = {c: v for c, v in pool_all.items() if s[c]["cap"] < medcap}
    return sorted(small, key=lambda c: -small[c]), small

def quintile(ranked): return max(1, math.ceil(len(ranked) / 5))

ROADS = {"FULL": list(range(2018, 2026)), "CONT": list(range(2019, 2026)), "VAL": list(range(2023, 2026))}

def spy_june(forms):
    """SPY $100 bought at first formation June, marked to last hold-end June."""
    start = E.D.spy.get(ym(forms[0], 6)); end = E.D.spy.get(ym(forms[-1] + 1, 6))
    if not start or not end: return None
    return round(100.0 * end / start, 2)

def main():
    res = {"family": "hunt-intangibles-rd", "rules": "v13-best-rules (see BEST-RULES-SPEC.md)", "roads": {}}
    ranked_by_F, pool_by_F = {}, {}
    for F in range(2018, 2026):
        ranked_by_F[F], pool_by_F[F] = ranked_best(F)
        print("formation", F, "eligible-small pool", len(pool_by_F[F]), "quintile", quintile(ranked_by_F[F]), flush=True)
    for road, forms in ROADS.items():
        picks = {F: ranked_by_F[F][:quintile(ranked_by_F[F])] for F in forms}
        rn = run_annual(picks, forms, "native")
        res["roads"][road] = {"native": rn, "period_stats_annual": period_stats_annual(rn["curve"]),
                              "n_picks_by_year": {F: len(picks[F]) for F in forms},
                              "spy_june_window": spy_june(forms)}
        print(road, "final", rn["final"], "max_dd", rn["max_dd"], "spy", res["roads"][road]["spy_june_window"], flush=True)
    # 20-seed placebos on FULL, within eligible small-half pool
    forms = ROADS["FULL"]
    picks = {F: ranked_by_F[F][:quintile(ranked_by_F[F])] for F in forms}
    twins = []
    for seed in range(1, 21):
        t = run_annual(picks, forms, "native", pool_by_F=pool_by_F, placebo_seed=seed)["final"]
        twins.append(t); print("placebo", seed, t, flush=True)
    res["placebo_FULL"] = {"finals": twins, "median": round(statistics.median(twins), 2),
                           "beaten_of_20": sum(1 for t in twins if res["roads"]["FULL"]["native"]["final"] > t)}
    # Confirmation pack (frozen bars): yearly folds + half-windows, run unconditionally
    folds = {}
    for F in forms:
        p = {F: ranked_by_F[F][:quintile(ranked_by_F[F])]}
        folds[str(F)] = run_annual(p, [F], "native")["final"]
    halves = {}
    for name, fs in [("2018-2021", list(range(2018, 2022))), ("2022-2025", list(range(2022, 2026)))]:
        p = {F: ranked_by_F[F][:quintile(ranked_by_F[F])] for F in fs}
        halves[name] = run_annual(p, fs, "native")["final"]
    res["confirmation_FULL"] = {"yearly_folds_final_from_100": folds, "half_windows_final_from_100": halves}
    print("folds", folds, "halves", halves, flush=True)
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("saved")

if __name__ == "__main__":
    main()
