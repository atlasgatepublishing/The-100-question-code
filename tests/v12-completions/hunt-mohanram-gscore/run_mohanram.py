#!/usr/bin/env python3
"""Mohanram G-Score (hunt-mohanram-gscore, v12) — SPEC-FROZEN.
Universe: lowest book-to-market quintile (glamour) at annual June
formation, program 6-month accounting lag. G-score 0-8 vs 2-digit SIC
industry medians (medians over the full snapshot cross-section):
G1 ROA>med, G2 cash-flow ROA>med, G3 CFO>NI, G4 earnings (ROA)
variance<med, G5 sales-growth variance<med, G6 R&D intensity>med,
G7 capex intensity>med, G8 advertising intensity>med. Variances over
up to 5 prior fiscal years (min 3 obs). Missing advertising (widely
undisclosed) scores 0 for G8 — stated convention, conservative (never
imputed as above-median). Native long group: G>=6, ranked by G desc
then ROA desc. Placebos: random names within the same low-BM universe.
Tiered costs native; house = program costs + v9 floor. Holdings grid
in grid/."""
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

def frame_series(concepts, years):
    out = {}
    for y in years:
        got = {}
        for c in concepts:
            d = D.F(c, y, "D")
            for cik, v in d.items():
                if cik not in got and v is not None: got[cik] = v
        for cik, v in got.items(): out.setdefault(cik, {})[y] = v
    return out

def gscores(F):
    s = snap(F)
    uni = {c: v for c, v in s.items() if v["equity"] and v["equity"] > 0 and v["cap"] and v["px_adj"]}
    if len(uni) < 20: return [], {}, {}
    bm = {c: v["equity"] / v["cap"] for c, v in uni.items()}
    n5 = max(1, len(bm) // 5)
    lowbm = sorted(bm, key=lambda c: bm[c])[:n5]
    rd = MF.get((RD, F - 1), {}); ad = MF.get((ADV, F - 1), {}); cx = MF.get((CAPX, F - 1), {})
    ni_s = frame_series(["NetIncomeLoss"], range(F - 5, F))
    as_s = {}
    for y in range(F - 5, F):
        for cik, v in D.F("Assets", y, "I").items(): as_s.setdefault(cik, {})[y] = v
    rev_s = frame_series(["Revenues", "SalesRevenueNet", "RevenueFromContractWithCustomerExcludingAssessedTax"], range(F - 6, F))
    def feats(c):
        v = s[c]
        if not v["assets"] or v["ni"] is None or v["cfo"] is None: return None
        roa = v["ni"] / v["assets"]; cfroa = v["cfo"] / v["assets"]
        ev = None
        yrs = [y for y in range(F - 5, F) if c in ni_s.get(c, {}) and c in as_s.get(c, {}) and as_s[c][y]]
        if len(yrs) >= 3:
            series = [ni_s[c][y] / as_s[c][y] for y in yrs]
            ev = statistics.pvariance(series)
        sv = None
        ry = [y for y in range(F - 5, F) if c in rev_s.get(c, {}) and (y - 1) in rev_s.get(c, {}) and rev_s[c][y - 1]]
        if len(ry) >= 3:
            g = [rev_s[c][y] / rev_s[c][y - 1] - 1 for y in ry]
            sv = statistics.pvariance(g)
        rev = v["rev"]
        return {"roa": roa, "cfroa": cfroa, "accr": 1.0 if v["cfo"] > v["ni"] else 0.0,
                "evar": ev, "svar": sv,
                "rdint": (rd[c] / rev) if (c in rd and rev) else 0.0,
                "cxint": (cx[c] / rev) if (c in cx and rev) else 0.0,
                "adint": (ad[c] / rev) if (c in ad and rev) else None,
                "sic2": v["sic"] // 100}
    allf = {}
    for c in s:
        f = feats(c)
        if f: allf[c] = f
    med = {}
    keys = ["roa", "cfroa", "evar", "svar", "rdint", "cxint", "adint"]
    byind = {}
    for c, f in allf.items(): byind.setdefault(f["sic2"], []).append(f)
    for k in keys:
        med[k] = {}
        allv = [f[k] for f in allf.values() if f[k] is not None]
        gmed = statistics.median(allv) if allv else None
        for ind, fs in byind.items():
            vv = [f[k] for f in fs if f[k] is not None]
            med[k][ind] = statistics.median(vv) if len(vv) >= 5 else gmed
    scores = {}
    for c in lowbm:
        f = allf.get(c)
        if not f: continue
        ind = f["sic2"]; g = 0
        if med["roa"].get(ind) is not None and f["roa"] > med["roa"][ind]: g += 1
        if med["cfroa"].get(ind) is not None and f["cfroa"] > med["cfroa"][ind]: g += 1
        g += int(f["accr"])
        if f["evar"] is not None and med["evar"].get(ind) is not None and f["evar"] < med["evar"][ind]: g += 1
        if f["svar"] is not None and med["svar"].get(ind) is not None and f["svar"] < med["svar"][ind]: g += 1
        if med["rdint"].get(ind) is not None and f["rdint"] > med["rdint"][ind]: g += 1
        if med["cxint"].get(ind) is not None and f["cxint"] > med["cxint"][ind]: g += 1
        if f["adint"] is not None and med["adint"].get(ind) is not None and f["adint"] > med["adint"][ind]: g += 1
        scores[c] = (g, f["roa"])
    ranked = sorted(scores, key=lambda c: (-scores[c][0], -scores[c][1]))
    pool = {c: scores[c][0] for c in lowbm if c in allf}
    return ranked, pool, scores

def main():
    res = {"family": "hunt-mohanram-gscore", "roads": {}}
    ranked_by_F = {}; pool_by_F = {}; scores_by_F = {}
    for F in range(2017, 2026):
        ranked_by_F[F], pool_by_F[F], scores_by_F[F] = gscores(F)
        print(F, "lowBM pool", len(pool_by_F[F]), "G>=6", sum(1 for c in ranked_by_F[F] if scores_by_F[F][c][0] >= 6), flush=True)
    def native_picks(F): return [c for c in ranked_by_F[F] if scores_by_F[F][c][0] >= 6]
    for road, forms in ROADS_ANNUAL.items():
        picks = {F: native_picks(F) for F in forms}
        rn = run_annual(picks, forms, "native"); rh = run_annual(picks, forms, "house")
        res["roads"][road] = {"native": rn, "house": rh, "period_stats_annual": period_stats_annual(rn["curve"]),
                              "n_picks_by_year": {F: len(picks[F]) for F in forms}}
        print(road, "native", rn["final"], "house", rh["final"], flush=True)
    forms = ROADS_ANNUAL["FULL"]; picks = {F: native_picks(F) for F in forms}
    twins = [run_annual(picks, forms, "native", pool_by_F=pool_by_F, placebo_seed=sd)["final"] for sd in range(1, 21)]
    res["placebo_FULL_native"] = {"finals": twins, "beaten_of_20": sum(1 for t in twins if res["roads"]["FULL"]["native"]["final"] > t)}
    grid = {}
    for cnt in COUNTS:
        cell = {}
        for road, forms in ROADS_ANNUAL.items():
            pk = {F: (native_picks(F) if cnt == "ALL" else ranked_by_F[F][:cnt]) for F in forms}
            cell[road] = {"native": run_annual(pk, forms, "native")["final"], "house": run_annual(pk, forms, "house")["final"]}
        grid[str(cnt)] = cell; print("grid", cnt, cell["FULL"], flush=True)
    os.makedirs(os.path.join(HERE, "grid"), exist_ok=True)
    json.dump({"grid": grid}, open(os.path.join(HERE, "grid", "grid_results.json"), "w"), indent=1)
    res["grid_summary"] = grid
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("saved")

if __name__ == "__main__":
    main()
