#!/usr/bin/env python3
"""Mohanram G-Score v13 BEST RULES — frozen spec in BEST-RULES-SPEC.md.
Universe: lowest book-to-market quintile of the W04 broad EDGAR stack,
June formation, 6-month program lag (via chassis snapshots).
Score: G-core = G1+G2+G3 only (ROA>industry median, cash-flow ROA>industry
median, CFO>NI), industry = 2-digit SIC medians over the full snapshot
cross-section (industry median used when >=5 firms, else global median —
same convention as v12). Rank by (G-core desc, CFROA desc), hold top 10
equal-weighted, annual hold, NO floor, habitat-tiered (native) costs.
Placebos: 20 seeds, random draws of 10 from the same scored low-BM pond.
Reads the v12 folder's chassis/data read-only; writes only here."""
import json, os, sys, statistics
V12 = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/hunt-mohanram-gscore")
sys.path.insert(0, V12)
import annual_lib as A
E, D = A.E, A.D
HERE = os.path.dirname(os.path.abspath(__file__))

SNAPS = {}
def snap(F):
    if F not in SNAPS: SNAPS[F] = E.snapshot(F)
    return SNAPS[F]

def core_scores(F):
    s = snap(F)
    uni = {c: v for c, v in s.items() if v["equity"] and v["equity"] > 0 and v["cap"] and v["px_adj"]}
    if len(uni) < 20: return [], {}, {}
    bm = {c: v["equity"] / v["cap"] for c, v in uni.items()}
    n5 = max(1, len(bm) // 5)
    lowbm = sorted(bm, key=lambda c: bm[c])[:n5]
    # features over the FULL cross-section (industry medians as published)
    allf = {}
    for c, v in s.items():
        if not v["assets"] or v["ni"] is None or v["cfo"] is None: continue
        allf[c] = {"roa": v["ni"] / v["assets"], "cfroa": v["cfo"] / v["assets"],
                   "accr": 1.0 if v["cfo"] > v["ni"] else 0.0, "sic2": v["sic"] // 100}
    med = {}
    for k in ["roa", "cfroa"]:
        allv = [f[k] for f in allf.values()]
        gmed = statistics.median(allv) if allv else None
        byind = {}
        for f in allf.values(): byind.setdefault(f["sic2"], []).append(f[k])
        med[k] = {ind: (statistics.median(vv) if len(vv) >= 5 else gmed) for ind, vv in byind.items()}
        med[k]["__global__"] = gmed
    scores = {}
    for c in lowbm:
        f = allf.get(c)
        if not f: continue
        ind = f["sic2"]
        g = 0
        if f["roa"] > med["roa"].get(ind, med["roa"]["__global__"]): g += 1
        if f["cfroa"] > med["cfroa"].get(ind, med["cfroa"]["__global__"]): g += 1
        g += int(f["accr"])
        scores[c] = (g, f["cfroa"])
    ranked = sorted(scores, key=lambda c: (-scores[c][0], -scores[c][1]))
    pool = {c: scores[c][0] for c in lowbm if c in allf}
    return ranked, pool, scores

ROADS = {"FULL": list(range(2017, 2026)), "CONT": list(range(2019, 2026)),
         "VAL": list(range(2023, 2026)), "FOLD-A": list(range(2017, 2021)),
         "FOLD-B": list(range(2021, 2026))}
TOPN = 10

def main():
    ranked_by_F, pool_by_F, scores_by_F = {}, {}, {}
    diag = {}
    for F in range(2017, 2026):
        ranked_by_F[F], pool_by_F[F], scores_by_F[F] = core_scores(F)
        dist = {}
        for g, _ in scores_by_F[F].values(): dist[g] = dist.get(g, 0) + 1
        diag[F] = {"pond_scored": len(scores_by_F[F]), "core_dist": dist,
                   "top10_core": [scores_by_F[F][c][0] for c in ranked_by_F[F][:TOPN]]}
        print(F, "pond", len(scores_by_F[F]), "dist", dist, flush=True)
    res = {"family": "hunt-mohanram-gscore", "variant": "v13-best-rules G-core top10 no-floor",
           "roads": {}, "diagnostics": diag}
    for road, forms in ROADS.items():
        picks = {F: ranked_by_F[F][:TOPN] for F in forms}
        r = A.run_annual(picks, forms, "native")
        res["roads"][road] = {"best": r, "period_stats_annual": A.period_stats_annual(r["curve"]),
                              "n_picks_by_year": {F: len(picks[F]) for F in forms}}
        print(road, "final", r["final"], "maxdd", r["max_dd"], flush=True)
    res["placebos"] = {}
    for road in ["FULL", "CONT", "VAL"]:
        forms = ROADS[road]
        picks = {F: ranked_by_F[F][:TOPN] for F in forms}
        twins = [A.run_annual(picks, forms, "native", pool_by_F=pool_by_F, placebo_seed=sd)["final"]
                 for sd in range(1, 21)]
        mine = res["roads"][road]["best"]["final"]
        res["placebos"][road] = {"finals": twins, "median": round(statistics.median(twins), 2),
                                 "beaten_of_20": sum(1 for t in twins if mine > t)}
        print(road, "placebo beaten", res["placebos"][road]["beaten_of_20"], "median", res["placebos"][road]["median"], flush=True)
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("saved")

if __name__ == "__main__":
    main()
