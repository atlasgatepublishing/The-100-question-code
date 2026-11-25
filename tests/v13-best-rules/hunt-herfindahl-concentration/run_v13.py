#!/usr/bin/env python3
"""V13 best-rules run — Herfindahl concentration. Spec: BEST-RULES-SPEC.md
(frozen before this run). Annual formation (June 30, 6-mo lag), 12-month
hold, long-only lowest sales-HHI quintile, EW, ALL names, NO floor.
Signal: 3yr rolling mean sales HHI by 3-digit SIC from W04 EDGAR frames.
Placebos: HHI permuted across industries (sizes preserved), 20 seeds.
Simulation only."""
import json, os, sys, random, statistics, importlib.util
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from monthly_engine import run_monthly, month_list, period_stats_monthly

HERE = os.path.dirname(os.path.abspath(__file__))
ENG = os.path.expanduser("~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data/engine_w04.py")
spec = importlib.util.spec_from_file_location("engine_w04", ENG)
eng = importlib.util.module_from_spec(spec); spec.loader.exec_module(eng)
eng.D = eng.Data(); D = eng.D

EXCL3 = {401, 451, 481, 482, 483, 484}
def excluded(sic):
    if sic <= 0: return True
    if 490 <= sic // 10 <= 499: return True
    return (sic // 10) in EXCL3

SNAPS = {}
def snap(F):
    if F not in SNAPS: SNAPS[F] = eng.snapshot(F)
    return SNAPS[F]

def hhi_by_industry(F):
    s = snap(F); tot = {}; ssq = {}
    for cik, v in s.items():
        sic = v["sic"]
        if excluded(sic): continue
        x = v["rev"]
        if x is None or x <= 0: continue
        g = sic // 10
        tot[g] = tot.get(g, 0.0) + x; ssq[g] = ssq.get(g, 0.0) + x * x
    return {g: ssq[g] / (tot[g] ** 2) for g in tot if tot[g] > 0}

HHI3 = {}
def hhi3(F):
    if F not in HHI3:
        hs = [hhi_by_industry(f) for f in (F, F - 1, F - 2)]
        groups = set(hs[0]) & set(hs[1]) & set(hs[2])
        HHI3[F] = {g: sum(h[g] for h in hs) / 3 for g in groups}
    return HHI3[F]

def formation_for_month(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    return y if m >= 7 else y - 1

# Annual picks: formed once per formation year F using July-of-F price
# availability, then held unchanged Jul F -> Jun F+1.
PICKCACHE = {}
def annual_picks(F, perm=None):
    key = (F, id(perm) if perm else 0)
    if key in PICKCACHE: return PICKCACHE[key]
    if F < 2018 or F > 2026: return []
    s = snap(F); h = hhi3(F)
    ym0 = f"{F:04d}-07"
    firms = []
    for cik, v in s.items():
        g = v["sic"] // 10
        if excluded(v["sic"]) or g not in h: continue
        if not v["px_adj"] or not D.has_price_month(cik, ym0): continue
        hv = perm[g] if perm else h[g]
        firms.append((hv, cik))
    if len(firms) < 20:
        PICKCACHE[key] = []; return []
    firms.sort(key=lambda x: x[0])
    n5 = max(1, len(firms) // 5)
    out = [c for _, c in firms[:n5]]
    PICKCACHE[key] = out
    return out

ROADS = {  # habitat-truncated LONG/DECADE labeled; CONT/VAL as specified
 "LONG-habitat": ("2018-07", "2026-11"),
 "DECADE-habitat": ("2018-07", "2026-11"),
 "CONT": ("2019-01", "2026-11"),
 "VAL": ("2023-01", "2026-11"),
}
CAPCACHE = {}
for F in range(2018, 2027):
    for cik, v in snap(F).items(): CAPCACHE[cik] = v["cap"]
COSTF = lambda cik: eng.cost_rate(CAPCACHE.get(cik))

def spy_final(a, b):
    va = D.spy.get(a); vb = D.spy.get(b)
    return round(100 * vb / va, 2) if va and vb else None

def main():
    out = {"family": "hunt-herfindahl-concentration", "program": "v13-best-rules",
           "roads": {}}
    for road, (a, b) in ROADS.items():
        months = month_list(a, b)
        pf = lambda ym: annual_picks(formation_for_month(ym))
        r = run_monthly(months, pf, D, COSTF, "native")  # no floor in v13 form
        ent = {k: v for k, v in r.items() if k != "curve"}
        ent["period_stats_monthly"] = period_stats_monthly(r["monthly_returns"])
        ent["curve"] = r["curve"]
        ent["spy_buy_hold_same_window"] = spy_final(a, b)
        out["roads"][road] = ent
        print(road, "final", ent["final"], "max_dd", ent["max_dd"], "spy", ent["spy_buy_hold_same_window"], flush=True)
    out["placebos"] = {}
    for road in ("LONG-habitat", "VAL"):
        a, b = ROADS[road]; months = month_list(a, b)
        finals = []
        for seed in range(1, 21):
            perms = {}
            def pf(ym, seed=seed):
                F = formation_for_month(ym)
                if F not in perms:
                    if F < 2018: return []
                    h = hhi3(F)
                    groups = list(h); vals = list(h.values())
                    rng = random.Random(seed * 104729 + F); rng.shuffle(vals)
                    perms[F] = dict(zip(groups, vals))
                return annual_picks(F, perm=perms[F])
            r = run_monthly(months, pf, D, COSTF, "native")
            finals.append(r["final"])
        sysf = out["roads"][road]["final"]
        out["placebos"][road] = {"finals": finals,
                                 "median": round(statistics.median(finals), 2),
                                 "system_final": sysf,
                                 "beats": sum(1 for f in finals if sysf > f)}
        print("placebo", road, out["placebos"][road], flush=True)
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)

if __name__ == "__main__":
    main()
