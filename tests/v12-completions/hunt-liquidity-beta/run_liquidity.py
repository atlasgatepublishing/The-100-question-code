#!/usr/bin/env python3
"""Liquidity Beta (hunt-liquidity-beta, v12) — SPEC-FROZEN leg 1:
Pastor-Stambaugh beta from the 60-month rolling regression of the
stock's monthly return on innovations in aggregate market liquidity,
using Pastor's published innovation series (liq_data_1962_2024,
Wharton/Chicago Booth author page; series ends Dec 2024 — stated).
Innovations 2015-2024 transcribed from the author's published file
into PS_INNOV below (the file's column 3, eq.8 innovations).
Formation monthly at month-end m (beta from the 60 months ending m,
>=48 valid months required), hold month m+1. Universe: price > $5.
Native long group: top decile of beta (program long-only adaptation
of the published long-short decile sort, labeled). First honest
formation Jan 2021 (60 monthly returns need the stack's prices from
Feb 2016); last formation Dec 2024 (innovation series end) -> holds
Feb 2021..Jan 2025. Roads: FULL = that whole span; VAL = holds from
Jan 2023; CONT is the same span as FULL (starts 2021, labeled).
Leg 2 (Acharya-Pedersen betas): documented-not-run per spec option —
in-sample-only published evidence plus a second full liquidity-series
construction; named in RESULTS as a gap, not silently dropped.
Placebos: random names, same count, same months. Grid in grid/."""
import json, os, sys, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from monthly_lib import *

HERE = os.path.dirname(os.path.abspath(__file__))
PS_INNOV = {
"2015-01": 0.02183311, "2015-02": 0.00119415, "2015-03": -0.02108124, "2015-04": 0.00619738,
"2015-05": 0.00422828, "2015-06": 0.00995177, "2015-07": 0.03323182, "2015-08": 0.07145377,
"2015-09": -0.07751100, "2015-10": 0.10663556, "2015-11": -0.03431734, "2015-12": -0.01288214,
"2016-01": -0.04542063, "2016-02": 0.02972618, "2016-03": 0.00364552, "2016-04": 0.09165088,
"2016-05": -0.05494044, "2016-06": -0.02670500, "2016-07": 0.01055463, "2016-08": -0.00382177,
"2016-09": -0.03142384, "2016-10": 0.08996467, "2016-11": -0.00358364, "2016-12": 0.04941367,
"2017-01": 0.06720165, "2017-02": -0.05258013, "2017-03": -0.06446981, "2017-04": 0.01001715,
"2017-05": 0.08911600, "2017-06": 0.02426171, "2017-07": 0.01387179, "2017-08": 0.06429244,
"2017-09": 0.05560052, "2017-10": 0.03140344, "2017-11": 0.01935147, "2017-12": 0.04636424,
"2018-01": -0.00970587, "2018-02": 0.02959768, "2018-03": 0.08568453, "2018-04": -0.01196645,
"2018-05": 0.08527741, "2018-06": 0.12575545, "2018-07": -0.02265213, "2018-08": 0.04554729,
"2018-09": 0.05793964, "2018-10": -0.03131035, "2018-11": 0.04117140, "2018-12": -0.03937019,
"2019-01": -0.02978301, "2019-02": 0.15376443, "2019-03": -0.00490047, "2019-04": 0.05791674,
"2019-05": -0.02062196, "2019-06": -0.06410421, "2019-07": 0.07291149, "2019-08": 0.02215737,
"2019-09": -0.02237908, "2019-10": 0.00200058, "2019-11": 0.03869783, "2019-12": 0.02122218,
"2020-01": -0.01470322, "2020-02": 0.02405276, "2020-03": -0.16401914, "2020-04": -0.02408057,
"2020-05": -0.06989159, "2020-06": 0.01935011, "2020-07": 0.07282782, "2020-08": -0.01228093,
"2020-09": -0.12009975, "2020-10": 0.03214371, "2020-11": 0.06539280, "2020-12": 0.01275480,
"2021-01": 0.06211251, "2021-02": -0.04761208, "2021-03": -0.00933628, "2021-04": -0.02828946,
"2021-05": -0.01047231, "2021-06": 0.00354027, "2021-07": 0.03830307, "2021-08": 0.03166787,
"2021-09": -0.00183064, "2021-10": -0.00837262, "2021-11": 0.02907322, "2021-12": 0.07439954,
"2022-01": -0.04622693, "2022-02": -0.07207870, "2022-03": -0.02466016, "2022-04": -0.13460513,
"2022-05": 0.02700270, "2022-06": 0.07943401, "2022-07": 0.07561750, "2022-08": 0.02243347,
"2022-09": -0.01592645, "2022-10": 0.00094557, "2022-11": 0.00802682, "2022-12": 0.03832234,
"2023-01": 0.04938161, "2023-02": 0.04054655, "2023-03": 0.00445632, "2023-04": -0.13255066,
"2023-05": -0.00106691, "2023-06": 0.01985003, "2023-07": 0.05309215, "2023-08": -0.01383397,
"2023-09": -0.03251257, "2023-10": 0.17552559, "2023-11": -0.10659695, "2023-12": -0.12649621,
"2024-01": 0.02461798, "2024-02": 0.01820823, "2024-03": -0.00255847, "2024-04": -0.10275165,
"2024-05": 0.00067461, "2024-06": -0.01665431, "2024-07": -0.01036066, "2024-08": 0.02292551,
"2024-09": -0.00892977, "2024-10": 0.17347056, "2024-11": -0.04141490, "2024-12": -0.02242166}

FORM_MONTHS = [m for m in MONTHS if "2021-01" <= m <= "2024-12"]
def hold_of(fm):
    i = MONTHS.index(fm); return MONTHS[i + 1]

RET = {}
def ret(c, m):
    if (c, m) not in RET: RET[(c, m)] = mret(c, m)
    return RET[(c, m)]

def betas(fm):
    i = MONTHS.index(fm)
    win = MONTHS[i - 59:i + 1]
    innov = [PS_INNOV.get(m) for m in win]
    if any(v is None for v in innov): return [], []
    mi = statistics.mean(innov); var = sum((v - mi) ** 2 for v in innov)
    out = {}
    elig = []
    for c in D.cand:
        praw = D.price(c, fm, adj=False)
        if not praw or praw <= 5: continue
        elig.append(c)
        pairs = []
        for m in win:
            r = ret(c, m)
            if r is not None: pairs.append((r, PS_INNOV[m]))
        if len(pairs) < 48: continue
        mr = statistics.mean([p[0] for p in pairs])
        cov = sum((r - mr) * (v - mi) for r, v in pairs)
        out[c] = cov / var
    ranked = sorted(out, key=lambda c: -out[c])
    return ranked, elig

def main():
    res = {"family": "hunt-liquidity-beta", "roads": {}}
    ranked_by_H = {}; pool_by_H = {}
    for fm in FORM_MONTHS:
        ranked, elig = betas(fm)
        ranked_by_H[hold_of(fm)] = ranked; pool_by_H[hold_of(fm)] = elig
        print("form", fm, "ranked", len(ranked), flush=True)
    holds = [hold_of(fm) for fm in FORM_MONTHS]
    def native_n(ranked): return max(1, len(ranked) // 10)
    picks = {hm: ranked_by_H[hm][:native_n(ranked_by_H[hm])] for hm in holds}
    roads = {"FULL": holds, "VAL": [m for m in holds if m >= "2023-01"]}
    for road, months in roads.items():
        rn = run_monthly(picks, months, "native"); rh = run_monthly(picks, months, "house")
        res["roads"][road] = {"native": rn, "house": rh, "period_stats_monthly": period_stats_monthly(rn["curve"])}
        print(road, "native", rn["final"], "house", rh["final"], flush=True)
    twins = [run_monthly(picks, holds, "native", pool_by_M=pool_by_H, placebo_seed=sd)["final"] for sd in range(1, 21)]
    res["placebo_FULL_native"] = {"finals": twins, "beaten_of_20": sum(1 for t in twins if res["roads"]["FULL"]["native"]["final"] > t)}
    grid = {}
    for cnt in COUNTS:
        cell = {}
        for road, months in roads.items():
            pk = {hm: (ranked_by_H[hm][:native_n(ranked_by_H[hm])] if cnt == "ALL" else ranked_by_H[hm][:cnt]) for hm in months}
            cell[road] = {"native": run_monthly(pk, months, "native")["final"], "house": run_monthly(pk, months, "house")["final"]}
        grid[str(cnt)] = cell; print("grid", cnt, cell["FULL"], flush=True)
    os.makedirs(os.path.join(HERE, "grid"), exist_ok=True)
    json.dump({"grid": grid}, open(os.path.join(HERE, "grid", "grid_results.json"), "w"), indent=1)
    res["grid_summary"] = grid
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("saved")

if __name__ == "__main__":
    main()
