#!/usr/bin/env python3
"""Intangibles / R&D (hunt-intangibles-rd, v12) — SPEC-FROZEN headline
leg 1 (Chan-Lakonishok-Sougiannis): R&D expense / market cap, annual
June formation (program 6-month lag), hold 12 months, long-only top
quintile among R&D REPORTERS (missing xrd is NOT zero-filled — the
sort lives among reporters, per spec). Sub-sleeves: advertising/cap
(same paper), leg 2 Li R&D capital stock / assets within small firms,
leg 4 Eberhart-Maxwell-Siddique unexpected-R&D-increase event basket.
Leg 3 (patent/citation efficiency) NOT RUN — named grid gap (free
assignee->ticker point-in-time concordance does not exist; see
RESULTS). Tiered habitat costs native; house = program costs + v9
floor. 20-seed placebos within the reporter universe. Holdings grid
in grid/ subfolder."""
import json, os, sys, math, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from annual_lib import *

HERE = os.path.dirname(os.path.abspath(__file__))
MF = load_my_frames(os.path.join(HERE, "data", "frames"))
RD = "ResearchAndDevelopmentExpense"; ADV = "AdvertisingExpense"; CAPX = "PaymentsToAcquirePropertyPlantAndEquipment"

SNAPS = {}
def snap(F):
    if F not in SNAPS: SNAPS[F] = E.snapshot(F)
    return SNAPS[F]

def ranked_leg1(F):
    s = snap(F); rd = MF.get((RD, F - 1), {})
    pool = {c: rd[c] / s[c]["cap"] for c in rd if rd[c] and rd[c] > 0 and s.get(c, {}).get("cap") and s[c]["px_adj"]}
    return sorted(pool, key=lambda c: -pool[c]), pool

def ranked_adv(F):
    s = snap(F); ad = MF.get((ADV, F - 1), {})
    pool = {c: ad[c] / s[c]["cap"] for c in ad if ad[c] and ad[c] > 0 and s.get(c, {}).get("cap") and s[c]["px_adj"]}
    return sorted(pool, key=lambda c: -pool[c]), pool

def ranked_leg2(F):
    s = snap(F)
    if F - 5 < 2013: return [], {}
    caps = MF.get((RD, F - 1), {})
    pool0 = {c: v for c, v in caps.items() if v and v > 0 and s.get(c, {}).get("cap") and s[c]["px_adj"] and s[c]["assets"]}
    if len(pool0) < 10: return [], {}
    medcap = statistics.median([s[c]["cap"] for c in pool0])
    pool = {}
    for c in pool0:
        if s[c]["cap"] >= medcap: continue
        stock = 0.0; ok = True
        for k, wgt in enumerate([1.0, 0.8, 0.6, 0.4, 0.2]):
            v = MF.get((RD, F - 1 - k), {}).get(c)
            if v is None: ok = False; break
            stock += wgt * v
        if ok: pool[c] = stock / s[c]["assets"]
    return sorted(pool, key=lambda c: -pool[c]), pool

def ranked_leg4(F):
    s = snap(F); rd1 = MF.get((RD, F - 1), {}); rd0 = MF.get((RD, F - 2), {})
    pool = {}
    for c in rd1:
        v = s.get(c)
        if not v or not v["px_adj"] or not v["assets"] or not v["assets0"] or not v["rev"] or not v["rev0"]: continue
        if c not in rd0 or not rd1[c] or not rd0[c]: continue
        a1 = rd1[c] / v["assets"]; a0 = rd0[c] / v["assets0"]
        s1 = rd1[c] / v["rev"]; s0 = rd0[c] / v["rev0"]
        if a0 > 0 and s0 > 0 and a1 > 1.05 * a0 and s1 > 1.05 * s0: pool[c] = a1
    return sorted(pool, key=lambda c: -pool[c]), pool

def quintile(ranked): return max(1, math.ceil(len(ranked) / 5))

def run_family(rankfn, native_count_fn, formations_by_road=ROADS_ANNUAL, do_grid=False):
    out = {"roads": {}}
    ranked_by_F = {}; pool_by_F = {}
    for F in range(2017, 2026):
        ranked_by_F[F], pool_by_F[F] = rankfn(F)
    for road, forms in formations_by_road.items():
        picks = {F: ranked_by_F[F][:native_count_fn(ranked_by_F[F])] for F in forms}
        rn = run_annual(picks, forms, "native")
        rh = run_annual(picks, forms, "house")
        out["roads"][road] = {"native": rn, "house": rh,
                              "period_stats_annual": period_stats_annual(rn["curve"]),
                              "n_picks_by_year": {F: len(picks[F]) for F in forms}}
    # placebos on FULL native
    forms = formations_by_road["FULL"]
    picks = {F: ranked_by_F[F][:native_count_fn(ranked_by_F[F])] for F in forms}
    twins = []
    for seed in range(1, 21):
        twins.append(run_annual(picks, forms, "native", pool_by_F=pool_by_F, placebo_seed=seed)["final"])
    out["placebo_FULL_native"] = {"finals": twins, "beaten_of_20": sum(1 for t in twins if out["roads"]["FULL"]["native"]["final"] > t)}
    if do_grid:
        grid = {}
        for cnt in COUNTS:
            cell = {}
            for road, forms in formations_by_road.items():
                n = (lambda r: native_count_fn(r)) if cnt == "ALL" else cnt
                picks = {F: ranked_by_F[F][:n(ranked_by_F[F]) if cnt == "ALL" else cnt] for F in forms}
                cell[road] = {"native": run_annual(picks, forms, "native")["final"],
                              "house": run_annual(picks, forms, "house")["final"]}
            grid[str(cnt)] = cell
            print("grid", cnt, cell["FULL"], flush=True)
        out["grid"] = grid
    return out

def main():
    res = {"family": "hunt-intangibles-rd"}
    print("leg1...", flush=True)
    res["leg1_rd_intensity"] = run_family(ranked_leg1, quintile, do_grid=True)
    print("leg1 FULL native", res["leg1_rd_intensity"]["roads"]["FULL"]["native"]["final"], flush=True)
    print("adv...", flush=True)
    res["sleeve_advertising"] = run_family(ranked_adv, quintile)
    print("leg2...", flush=True)
    roads2 = {"FULL": list(range(2018, 2026)), "CONT": list(range(2019, 2026)), "VAL": list(range(2023, 2026))}
    res["leg2_rd_capital_small"] = run_family(ranked_leg2, quintile, formations_by_road=roads2)
    print("leg4...", flush=True)
    res["leg4_unexpected_rd"] = run_family(ranked_leg4, len)
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    os.makedirs(os.path.join(HERE, "grid"), exist_ok=True)
    json.dump({"leg1_grid": res["leg1_rd_intensity"].pop("grid")}, open(os.path.join(HERE, "grid", "grid_results.json"), "w"), indent=1)
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("saved")

if __name__ == "__main__":
    main()
